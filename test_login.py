"""Test script for Albert Heijn authentication.

Run: python test_login.py
Tests the browser-based login flow via local reverse proxy.
Opens your browser to the AH login page, captures the auth code.
"""

import asyncio
import sys
import webbrowser


async def main() -> None:
    sys.path.insert(0, "custom_components/albert_heijn")

    import logging
    logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")

    from aiohttp import web
    from auth import (
        PROXY_PATH,
        AuthenticationError,
        async_refresh_token,
        create_login_session,
        exchange_code,
        handle_login_fallback,
        handle_proxy_request,
        remove_login_session,
    )

    print("=== Albert Heijn Login Test (Browser-based) ===\n")
    print("Starting local login proxy...")

    # For standalone testing, create a local aiohttp app
    app = web.Application()
    app.router.add_route("*", PROXY_PATH + "/{session_id}/{path_info:.*}", handle_proxy_request)
    app.router.add_route("*", "/login/{path_info:.*}", handle_login_fallback)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    port = site._server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    session = create_login_session(base_url)
    login_url = session.login_url

    print(f"\nProxy running at {base_url}")
    print(f"Opening browser to: {login_url}\n")
    print("Please log in to Albert Heijn in your browser.")
    print("Waiting for login callback (timeout: 5 minutes)...\n")

    webbrowser.open(login_url)

    try:
        code = await asyncio.wait_for(session.code_future, timeout=300)
        print(f"Auth code received (length={len(code)})")
    except asyncio.TimeoutError:
        print("Login timed out (5 minutes)")
        remove_login_session(session.session_id)
        await runner.cleanup()
        sys.exit(1)
    except Exception as e:
        print(f"Error waiting for code: {e}")
        remove_login_session(session.session_id)
        await runner.cleanup()
        sys.exit(1)

    print("\nExchanging code for tokens...")
    try:
        tokens = await exchange_code(code)
    except AuthenticationError as e:
        print(f"Token exchange failed: {e}")
        remove_login_session(session.session_id)
        await runner.cleanup()
        sys.exit(1)

    remove_login_session(session.session_id)
    await runner.cleanup()

    print("\nLogin successful!")
    print(f"  Access token:  {tokens['access_token'][:40]}...")
    print(f"  Refresh token: {tokens['refresh_token'][:20]}...")
    print(f"  Member ID:     {tokens.get('member_id', 'N/A')}")

    # Test token refresh
    print("\nTesting token refresh...")
    try:
        new_tokens = await async_refresh_token(tokens["refresh_token"])
        print("Token refresh successful!")
        print(f"  New access token: {new_tokens['access_token'][:40]}...")
    except AuthenticationError as e:
        print(f"Token refresh failed: {e}")
        new_tokens = tokens

    # Save tokens
    import json
    token_file = ".tokens.json"
    save_data = {
        "access_token": new_tokens.get("access_token", tokens["access_token"]),
        "refresh_token": new_tokens.get("refresh_token", tokens["refresh_token"]),
        "member_id": tokens.get("member_id", ""),
    }
    with open(token_file, "w") as f:
        json.dump(save_data, f, indent=2)
    print(f"\nTokens saved to {token_file}")


if __name__ == "__main__":
    asyncio.run(main())
