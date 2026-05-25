"""Test script for Albert Heijn authentication.

Run: python test_login.py
Tests the browser-based login flow via local reverse proxy.
Opens your browser to the AH login page, captures the auth code.
"""

import asyncio
import sys
import webbrowser


async def main() -> None:
    # Import auth module directly (avoids homeassistant dependency)
    sys.path.insert(0, "custom_components/albert_heijn")

    import logging
    logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")

    from auth import AuthenticationError, LoginProxy, async_refresh_token

    print("=== Albert Heijn Login Test (Browser-based) ===\n")
    print("Starting local login proxy...")

    proxy = LoginProxy()
    login_url = await proxy.start()

    print(f"\nProxy running on port {proxy.port}")
    print(f"Opening browser to: {login_url}\n")
    print("Please log in to Albert Heijn in your browser.")
    print("Waiting for login callback (timeout: 5 minutes)...\n")

    webbrowser.open(login_url)

    try:
        code = await proxy.wait_for_code(timeout=300)
        print(f"✓ Auth code received (length={len(code)})")
    except asyncio.TimeoutError:
        print("✗ Login timed out (5 minutes)")
        await proxy.stop()
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error waiting for code: {e}")
        await proxy.stop()
        sys.exit(1)

    print("\nExchanging code for tokens...")
    try:
        tokens = await proxy.exchange_code(code)
    except AuthenticationError as e:
        print(f"✗ Token exchange failed: {e}")
        await proxy.stop()
        sys.exit(1)
    finally:
        await proxy.stop()

    print("\n✓ Login successful!")
    print(f"  Access token:  {tokens['access_token'][:40]}...")
    print(f"  Refresh token: {tokens['refresh_token'][:20]}...")
    print(f"  Member ID:     {tokens.get('member_id', 'N/A')}")

    # Test token refresh
    print("\nTesting token refresh...")
    try:
        new_tokens = await async_refresh_token(tokens["refresh_token"])
        print("✓ Token refresh successful!")
        print(f"  New access token: {new_tokens['access_token'][:40]}...")
    except AuthenticationError as e:
        print(f"✗ Token refresh failed: {e}")
        new_tokens = tokens

    # Save tokens to file for test_api.py
    import json

    token_file = ".tokens.json"
    save_data = {
        "access_token": new_tokens.get("access_token", tokens["access_token"]),
        "refresh_token": new_tokens.get("refresh_token", tokens["refresh_token"]),
        "member_id": tokens.get("member_id", ""),
    }
    with open(token_file, "w") as f:
        json.dump(save_data, f, indent=2)
    print(f"\n✓ Tokens saved to {token_file} (for use with test_api.py)")


if __name__ == "__main__":
    asyncio.run(main())
