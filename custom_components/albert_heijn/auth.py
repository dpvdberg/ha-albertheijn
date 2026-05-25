"""Authentication handler for Albert Heijn.

Handles the full login flow and token lifecycle:
1. Browser-based login via standalone reverse proxy (user completes captcha)
2. Token storage and reuse
3. Token refresh when expired

The proxy runs as a standalone aiohttp server on a random port, bound to 0.0.0.0.
It uses the HA host's IP/hostname so the login URL is reachable from the user's browser.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from urllib.parse import urlparse

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
    """Standalone reverse proxy server for AH browser login.

    Starts its own aiohttp server on a random port, bound to 0.0.0.0.
    Uses the provided hostname (from HA's external URL) so the login link
    is reachable from the user's browser.
    """

    def __init__(self, hostname: str = "127.0.0.1") -> None:
        """Initialize the login proxy.

        Args:
            hostname: The hostname/IP to use in the login URL (e.g. '192.168.1.4').
                      The server always binds to 0.0.0.0 but the URL uses this hostname.
        """
        self._hostname = hostname
        self._session_id = secrets.token_hex(16)
        self._code_future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._port: int = 0

    @property
    def port(self) -> int:
        """Return the port the server is listening on."""
        return self._port

    @property
    def base_url(self) -> str:
        """Return the base URL of the proxy server."""
        return f"http://{self._hostname}:{self._port}"

    @property
    def login_url(self) -> str:
        """Return the URL to open in the browser."""
        params = "&".join(f"{k}={v}" for k, v in LOGIN_PARAMS.items())
        return f"{self.base_url}/login?{params}"

    async def start(self) -> str:
        """Start the proxy server. Returns the login URL."""
        app = web.Application()
        app.router.add_route("GET", "/callback", self._handle_callback)
        app.router.add_route("*", "/login/{path_info:.*}", self._handle_login_path)
        app.router.add_route("*", "/{path_info:.*}", self._handle_proxy)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", 0)
        await self._site.start()

        self._port = self._site._server.sockets[0].getsockname()[1]
        _LOGGER.debug(
            "Login proxy started on port %d (hostname=%s, session=%s)",
            self._port, self._hostname, self._session_id,
        )
        return self.login_url

    async def wait_for_code(self, timeout: float = 300) -> str:
        """Wait for the user to complete login. Returns the auth code."""
        return await asyncio.wait_for(self._code_future, timeout=timeout)

    async def stop(self) -> None:
        """Stop the proxy server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        _LOGGER.debug("Login proxy stopped")

    async def _handle_callback(self, request: web.Request) -> web.Response:
        """Handle the callback with the auth code."""
        code = request.query.get("code", "")
        if code and not self._code_future.done():
            self._code_future.set_result(code)
            _LOGGER.debug("Auth code received (length=%d)", len(code))
        return web.Response(text=LOGIN_SUCCESS_HTML, content_type="text/html")

    async def _handle_login_path(self, request: web.Request) -> web.Response:
        """Handle /login/... paths (the main login page and its sub-resources)."""
        path_info = "login/" + request.match_info.get("path_info", "")
        return await self._proxy_request(request, path_info)

    async def _handle_proxy(self, request: web.Request) -> web.Response:
        """Handle all other proxy paths."""
        path_info = request.match_info.get("path_info", "")
        if path_info == "callback":
            return await self._handle_callback(request)
        return await self._proxy_request(request, path_info)

    async def _proxy_request(self, request: web.Request, path_info: str) -> web.Response:
        """Proxy a request to login.ah.nl."""
        target_url = f"{LOGIN_BASE_URL}/{path_info}"
        if request.query_string:
            target_url += f"?{request.query_string}"

        body = await request.read() if request.can_read_body else None

        # Forward headers, rewriting origin/referer to match login.ah.nl
        headers = {}
        for key, value in request.headers.items():
            lower = key.lower()
            if lower in ("host", "transfer-encoding"):
                continue
            if lower == "origin":
                headers[key] = LOGIN_BASE_URL
                continue
            if lower == "referer":
                headers[key] = value.replace(self.base_url, LOGIN_BASE_URL)
                continue
            headers[key] = value
        headers["Host"] = LOGIN_HOST
        headers["Accept-Encoding"] = "gzip, deflate"

        async with aiohttp.ClientSession() as client:
            async with client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=body,
                allow_redirects=False,
                ssl=True,
            ) as resp:
                resp_body = await resp.read()
                resp_headers = dict(resp.headers)

        # Rewrite Location header
        location = resp_headers.get("Location", "")
        if location.startswith("appie://"):
            parsed = urlparse(location)
            resp_headers["Location"] = f"{self.base_url}/callback?{parsed.query}"
        elif LOGIN_HOST in location:
            resp_headers["Location"] = location.replace(
                f"https://{LOGIN_HOST}", self.base_url
            )

        # Strip security headers that block the proxy
        for hdr in ("Content-Security-Policy", "Strict-Transport-Security",
                    "X-Frame-Options", "Content-Encoding"):
            resp_headers.pop(hdr, None)

        # Rewrite body content
        content_type = resp_headers.get("Content-Type", "")
        if any(ct in content_type for ct in ("text/html", "javascript", "json", "text/css")):
            text = resp_body.decode("utf-8", errors="replace")
            text = text.replace("appie://login-exit", f"{self.base_url}/callback")
            text = text.replace(f"https://{LOGIN_HOST}", self.base_url)
            # Rewrite absolute paths (Next.js assets referenced from HTML/JS)
            text = text.replace('"/login/', f'"{self.base_url}/login/')
            text = text.replace("'/login/", f"'{self.base_url}/login/")
            text = text.replace('`/login/', f'`{self.base_url}/login/')
            text = text.replace('"/_next/', f'"{self.base_url}/_next/')
            text = text.replace("'/_next/", f"'{self.base_url}/_next/")
            text = text.replace('`/_next/', f'`{self.base_url}/_next/')
            text = text.replace('url(/login/', f'url({self.base_url}/login/')
            resp_body = text.encode("utf-8")
            resp_headers["Content-Length"] = str(len(resp_body))

        # Build response
        response = web.Response(status=resp.status, body=resp_body)
        for key, value in resp_headers.items():
            lower = key.lower()
            if lower in ("transfer-encoding", "content-length", "content-encoding"):
                continue
            if lower == "set-cookie":
                response.headers.add(key, _sanitize_cookie(value))
            else:
                response.headers[key] = value

        return response


async def exchange_code(code: str) -> dict[str, str]:
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


def _sanitize_cookie(cookie: str) -> str:
    """Strip Secure, SameSite, and Domain from Set-Cookie for proxy use."""
    parts = cookie.split(";")
    out = parts[:1]
    for part in parts[1:]:
        attr = part.strip().lower()
        if attr in ("secure", "") or attr.startswith(("samesite", "domain")):
            continue
        out.append(part)
    return ";".join(out)


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
