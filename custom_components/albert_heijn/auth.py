"""Authentication handler for Albert Heijn.

Handles the full login flow and token lifecycle:
1. Browser-based login via local reverse proxy (user completes captcha in browser)
2. Token storage and reuse
3. Token refresh when expired
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp
from aiohttp import web

_LOGGER = logging.getLogger(__name__)

# Inline constants so this module can be imported standalone (without homeassistant)
_API_BASE_URL = "https://api.ah.nl"
_CLIENT_ID = "appie-ios"
_USER_AGENT = "Appie/9.28 (iPhone17,3; iPhone; CPU OS 26_1 like Mac OS X)"

LOGIN_HOST = "login.ah.nl"
LOGIN_BASE_URL = f"https://{LOGIN_HOST}"
LOGIN_PARAMS = {
    "client_id": _CLIENT_ID,
    "response_type": "code",
    "redirect_uri": "appie://login-exit",
}
TOKEN_EXCHANGE_URL = f"{_API_BASE_URL}/mobile-auth/v1/auth/token"
TOKEN_REFRESH_URL = f"{_API_BASE_URL}/mobile-auth/v1/auth/token/refresh"

LOGIN_SUCCESS_HTML = """\
<!DOCTYPE html>
<html><head><title>Login Successful</title></head>
<body style="font-family:system-ui;max-width:500px;margin:80px auto;text-align:center">
<h1>&#10003; Login successful!</h1>
<p>You can close this tab and return to Home Assistant.</p>
<script>setTimeout(function(){window.close()},1000)</script>
</body></html>"""


class AuthenticationError(Exception):
    """Raised when authentication fails."""


class LoginProxy:
    """Local reverse proxy for browser-based AH login.

    Starts an HTTP server on localhost that proxies requests to login.ah.nl.
    Rewrites appie:// redirects to a local /callback endpoint, then exchanges
    the auth code for tokens.
    """

    def __init__(self, port: int = 0) -> None:
        """Initialize the login proxy."""
        self._port = port
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._code_future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._local_origin: str = ""

    @property
    def login_url(self) -> str:
        """Return the URL to open in the browser."""
        params = "&".join(f"{k}={v}" for k, v in LOGIN_PARAMS.items())
        return f"{self._local_origin}/login?{params}"

    @property
    def port(self) -> int:
        """Return the port the proxy is listening on."""
        return self._port

    async def start(self) -> str:
        """Start the proxy server. Returns the login URL."""
        self._app = web.Application()
        self._app.router.add_route("GET", "/callback", self._handle_callback)
        self._app.router.add_route("*", "/{path_info:.*}", self._handle_proxy)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", self._port)
        await self._site.start()

        # Get the actual port if 0 was specified
        sockets = self._site._server.sockets  # type: ignore[attr-defined]
        if sockets:
            self._port = sockets[0].getsockname()[1]
        self._local_origin = f"http://127.0.0.1:{self._port}"

        _LOGGER.debug("Login proxy started at %s", self._local_origin)
        return self.login_url

    async def wait_for_code(self, timeout: float = 300) -> str:
        """Wait for the user to complete login. Returns the auth code."""
        return await asyncio.wait_for(self._code_future, timeout=timeout)

    async def stop(self) -> None:
        """Stop the proxy server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def exchange_code(self, code: str) -> dict[str, str]:
        """Exchange the authorization code for tokens."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TOKEN_EXCHANGE_URL,
                json={"clientId": _CLIENT_ID, "code": code},
                headers={
                    "User-Agent": _USER_AGENT,
                    "Content-Type": "application/json",
                },
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise AuthenticationError(
                        f"Token exchange failed ({resp.status}): {body[:200]}"
                    )
                data = await resp.json()

        return {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "member_id": data.get("member_id", ""),
        }

    async def _handle_callback(self, request: web.Request) -> web.Response:
        """Handle the callback with the auth code."""
        code = request.query.get("code", "")
        if code and not self._code_future.done():
            self._code_future.set_result(code)
            _LOGGER.debug("Auth code received (length=%d)", len(code))
        return web.Response(
            text=LOGIN_SUCCESS_HTML,
            content_type="text/html",
        )

    async def _handle_proxy(self, request: web.Request) -> web.Response:
        """Proxy requests to login.ah.nl, rewriting redirects."""
        target_url = f"{LOGIN_BASE_URL}/{request.match_info['path_info']}"
        if request.query_string:
            target_url += f"?{request.query_string}"

        # Read request body
        body = await request.read() if request.can_read_body else None

        # Forward headers, adjusting Host
        headers = dict(request.headers)
        headers["Host"] = LOGIN_HOST
        headers.pop("Transfer-Encoding", None)
        # Don't request brotli - aiohttp can't decode it without Brotli lib
        headers["Accept-Encoding"] = "gzip, deflate"

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=body,
                allow_redirects=False,
                ssl=True,
            ) as resp:
                resp_body = await resp.read()
                resp_headers = dict(resp.headers)

        # Check for appie:// redirect in Location header
        location = resp_headers.get("Location", "")
        if location.startswith("appie://"):
            parsed = urlparse(location)
            resp_headers["Location"] = (
                f"{self._local_origin}/callback?{parsed.query}"
            )
        elif LOGIN_HOST in location:
            resp_headers["Location"] = location.replace(
                f"https://{LOGIN_HOST}", self._local_origin
            )

        # Strip security headers that block the proxy
        for hdr in ("Content-Security-Policy", "Strict-Transport-Security",
                    "X-Frame-Options", "Content-Encoding"):
            resp_headers.pop(hdr, None)

        # Rewrite cookies for localhost (strip Secure/Domain/SameSite)
        if "Set-Cookie" in resp_headers:
            # aiohttp collapses multi-value headers; handle raw
            pass  # we'll handle below

        # Rewrite body content
        content_type = resp_headers.get("Content-Type", "")
        if any(ct in content_type for ct in ("text/html", "javascript", "json")):
            text = resp_body.decode("utf-8", errors="replace")
            text = text.replace("appie://login-exit", f"{self._local_origin}/callback")
            text = text.replace(f"https://{LOGIN_HOST}", self._local_origin)
            resp_body = text.encode("utf-8")
            resp_headers["Content-Length"] = str(len(resp_body))

        # Build response, sanitizing cookies
        response = web.Response(
            status=resp.status,
            body=resp_body,
        )
        # Copy headers except problematic ones
        for key, value in resp_headers.items():
            lower = key.lower()
            if lower in ("transfer-encoding", "content-length", "content-encoding"):
                continue
            if lower == "set-cookie":
                response.headers.add(key, _sanitize_cookie(value))
            else:
                response.headers[key] = value

        return response


def _sanitize_cookie(cookie: str) -> str:
    """Strip Secure, SameSite, and Domain from Set-Cookie for localhost use."""
    parts = cookie.split(";")
    out = parts[:1]
    for part in parts[1:]:
        attr = part.strip().lower()
        if attr in ("secure", "") or attr.startswith(("samesite", "domain")):
            continue
        out.append(part)
    return ";".join(out)


async def async_login_browser(timeout: float = 300) -> tuple[LoginProxy, str]:
    """Start the login proxy and return (proxy, login_url).

    The caller should:
    1. Present login_url to the user
    2. await proxy.wait_for_code(timeout)
    3. await proxy.exchange_code(code)
    4. await proxy.stop()
    """
    proxy = LoginProxy()
    login_url = await proxy.start()
    return proxy, login_url


async def async_refresh_token(refresh_token: str) -> dict[str, str]:
    """Refresh the access token using aiohttp (no captcha needed)."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            TOKEN_REFRESH_URL,
            json={"clientId": _CLIENT_ID, "refreshToken": refresh_token},
            headers={
                "User-Agent": _USER_AGENT,
                "Content-Type": "application/json",
            },
        ) as resp:
            if resp.status >= 400:
                raise AuthenticationError(
                    f"Token refresh failed with status {resp.status}"
                )
            data = await resp.json()

    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
    }
