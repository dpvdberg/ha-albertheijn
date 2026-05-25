"""Authentication handler for Albert Heijn.

Handles the full login flow and token lifecycle:
1. Browser-based login via reverse proxy on HA's web server (user completes captcha)
2. Token storage and reuse
3. Token refresh when expired
"""

from __future__ import annotations

import asyncio
import logging
import secrets
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

# Base path for proxy routes registered on HA's web server
PROXY_PATH = "/auth/external/albert_heijn"

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


class LoginSession:
    """An active login session waiting for a browser callback."""

    def __init__(self, session_id: str, proxy_base_url: str) -> None:
        self.session_id = session_id
        self.proxy_base_url = proxy_base_url
        self.code_future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

    @property
    def login_url(self) -> str:
        """URL to open in the user's browser."""
        params = "&".join(f"{k}={v}" for k, v in LOGIN_PARAMS.items())
        return f"{self.proxy_base_url}/{self.session_id}/login?{params}"


# Global registry of active login sessions (keyed by session_id)
_active_sessions: dict[str, LoginSession] = {}


def create_login_session(ha_base_url: str) -> LoginSession:
    """Create a new login session and return it."""
    session_id = secrets.token_hex(16)
    proxy_base_url = f"{ha_base_url.rstrip('/')}{PROXY_PATH}"
    session = LoginSession(session_id, proxy_base_url)
    _active_sessions[session_id] = session
    _LOGGER.debug("Login session created: %s", session_id)
    return session


def remove_login_session(session_id: str) -> None:
    """Remove a login session."""
    _active_sessions.pop(session_id, None)


async def handle_login_fallback(request: web.Request) -> web.Response:
    """Catch-all for /login/... paths that bypass the session prefix.

    The AH login JS constructs some URLs (like /login/api/login) with hardcoded
    absolute paths that can't be rewritten. This handler finds the active session
    and proxies through it.
    """
    if not _active_sessions:
        return web.Response(status=404, text="No active login session")

    # Use the most recent (typically only) session
    session = next(iter(_active_sessions.values()))
    proxy_base = f"{session.proxy_base_url}/{session.session_id}"

    # Get the full path after /login/ (the match_info key from the route)
    path_info = "login/" + request.match_info.get("path_info", "")

    return await _do_proxy(request, path_info, proxy_base, session)


async def handle_proxy_request(request: web.Request) -> web.Response:
    """Handle all proxy requests (registered as a HA view)."""
    session_id = request.match_info.get("session_id", "")
    path_info = request.match_info.get("path_info", "")

    session = _active_sessions.get(session_id)
    if not session:
        return web.Response(status=404, text="Invalid or expired login session")

    proxy_base = f"{session.proxy_base_url}/{session_id}"

    # Handle callback
    if path_info == "callback":
        code = request.query.get("code", "")
        if code and not session.code_future.done():
            session.code_future.set_result(code)
            _LOGGER.debug("Auth code received for session %s", session_id)
        return web.Response(text=LOGIN_SUCCESS_HTML, content_type="text/html")

    return await _do_proxy(request, path_info, proxy_base, session)


async def _do_proxy(
    request: web.Request, path_info: str, proxy_base: str, session: LoginSession
) -> web.Response:
    """Proxy a request to login.ah.nl."""
    # Proxy to login.ah.nl
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
            # Rewrite referer: replace proxy base with login.ah.nl
            headers[key] = value.replace(proxy_base, LOGIN_BASE_URL)
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
        resp_headers["Location"] = f"{proxy_base}/callback?{parsed.query}"
    elif LOGIN_HOST in location:
        resp_headers["Location"] = location.replace(
            f"https://{LOGIN_HOST}", proxy_base
        )

    # Strip security headers
    for hdr in ("Content-Security-Policy", "Strict-Transport-Security",
                "X-Frame-Options", "Content-Encoding"):
        resp_headers.pop(hdr, None)

    # Rewrite body content
    content_type = resp_headers.get("Content-Type", "")
    if any(ct in content_type for ct in ("text/html", "javascript", "json", "text/css")):
        text = resp_body.decode("utf-8", errors="replace")
        text = text.replace("appie://login-exit", f"{proxy_base}/callback")
        text = text.replace(f"https://{LOGIN_HOST}", proxy_base)
        # Rewrite absolute paths (Next.js assets) to go through proxy
        # The AH login page uses paths like /login/_next/static/...
        text = text.replace('"/_next/', f'"{proxy_base}/_next/')
        text = text.replace("'/_next/", f"'{proxy_base}/_next/")
        text = text.replace('`/_next/', f'`{proxy_base}/_next/')
        text = text.replace('"/login/_next/', f'"{proxy_base}/login/_next/')
        text = text.replace("'/login/_next/", f"'{proxy_base}/login/_next/")
        text = text.replace('`/login/_next/', f'`{proxy_base}/login/_next/')
        text = text.replace('"/login/api/', f'"{proxy_base}/login/api/')
        text = text.replace("'/login/api/", f"'{proxy_base}/login/api/")
        text = text.replace('`/login/api/', f'`{proxy_base}/login/api/')
        text = text.replace('"/login/static/', f'"{proxy_base}/login/static/')
        text = text.replace("'/login/static/", f"'{proxy_base}/login/static/")
        text = text.replace('url(/login/static/', f'url({proxy_base}/login/static/')
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
