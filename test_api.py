"""Test script for Albert Heijn API - order fetching.

Run: python test_api.py

Requires tokens from test_login.py (stored in .tokens.json),
or pass --login to authenticate first.
"""

import asyncio
import json
import sys
from pathlib import Path

import aiohttp


async def main() -> None:
    sys.path.insert(0, "custom_components/albert_heijn")

    from api import (
        AlbertHeijnApi,
        AlbertHeijnApiError,
        AlbertHeijnAuthError,
    )

    token_file = Path(".tokens.json")

    if "--login" in sys.argv:
        import getpass

        from auth import async_login

        email = input("Email: ").strip()
        password = getpass.getpass("Password: ")
        print("Logging in...")
        tokens = await async_login(email, password)
        with open(token_file, "w") as f:
            json.dump(tokens, f, indent=2)
        print("✓ Logged in and saved tokens\n")
    elif token_file.exists():
        with open(token_file) as f:
            tokens = json.load(f)
    else:
        print("No .tokens.json found. Run test_login.py first, or use --login flag.")
        sys.exit(1)

    async with aiohttp.ClientSession() as session:
        api = AlbertHeijnApi(
            session=session,
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
        )

        # --- Test 1: Get fulfillments (open orders) ---
        print("=== Fulfillments (Open Orders) ===\n")
        try:
            fulfillments = await api.get_fulfillments()
            if not fulfillments:
                print("  No open orders found.\n")
            else:
                for f in fulfillments:
                    print(f"  Order #{f.order_id}")
                    print(f"    Status:       {f.status_description}")
                    print(f"    Type:         {f.shopping_type}")
                    print(f"    Total:        €{f.total_price:.2f}")
                    print(f"    Modifiable:   {f.modifiable}")
                    print(f"    Delivery:     {f.delivery_slot.date_display}")
                    print(f"    Time:         {f.delivery_slot.time_display}")
                    print()
        except AlbertHeijnApiError as e:
            print(f"  ✗ Failed: {e}\n")

        # --- Test 2: Get order details for the first order ---
        if fulfillments:
            first_order = fulfillments[0]
            print(f"=== Order Details (#{first_order.order_id}) ===\n")
            try:
                details = await api.get_order_details(first_order.order_id)
                print(f"  State:          {details.state}")
                print(f"  Delivery date:  {details.delivery_date}")
                print(f"  Closing time:   {details.closing_time}")
                print(f"  Products close: {details.products_closing_time}")
                print(f"  Delivery:       {details.delivery_start} - {details.delivery_end}")
                print(f"  Total items:    {details.total_items}")
                print(f"  Reopenable:     {details.reopenable}")
                print(f"  Order method:   {details.order_method}")
                print()
            except AlbertHeijnApiError as e:
                print(f"  ✗ Failed: {e}\n")

            # --- Test 3: Get minimum order value ---
            if first_order.modifiable:
                print(f"=== Order Value Limits (#{first_order.order_id}) ===\n")
                try:
                    limits = await api.get_order_value_limits(first_order.order_id)
                    print(f"  Minimum value:  €{limits.minimum_order_value:.2f}")
                    print(f"  Submittable:    {limits.submittable}")
                    remaining = limits.minimum_order_value - first_order.total_price
                    if remaining > 0:
                        print(f"  Remaining:      €{remaining:.2f} needed")
                    else:
                        print(f"  Remaining:      ✓ minimum met")
                    print()
                except AlbertHeijnApiError as e:
                    print(f"  ✗ Failed: {e}\n")

        # --- Test 4: Search products ---
        print("=== Product Search: 'melk' ===\n")
        try:
            products = await api.search_products("melk", 5)
            for p in products:
                orderable = "✓" if p.is_orderable else "✗"
                price_str = f"€{p.price:.2f}" if p.price is not None else "N/A"
                print(f"  [{orderable}] {p.title} ({p.unit_size}) - {price_str}")
                print(f"      ID: {p.id} | Brand: {p.brand}")
            print()
        except AlbertHeijnApiError as e:
            print(f"  ✗ Failed: {e}\n")

        # --- Test 5: Get active order summary ---
        print("=== Active Order Summary ===\n")
        try:
            summary = await api.get_active_order_summary()
            if summary:
                print(f"  Order ID:    {summary.get('id')}")
                print(f"  State:       {summary.get('state')}")
                tp = summary.get("totalPrice", {})
                print(f"  Total:       €{tp.get('priceTotalPayable', 0):.2f}")
                print(f"  Discount:    €{tp.get('priceDiscount', 0):.2f}")
                di = summary.get("deliveryInformation", {})
                print(f"  Delivery:    {di.get('deliveryDate')} {di.get('deliveryStartTime')}-{di.get('deliveryEndTime')}")
                items = summary.get("orderedProducts", [])
                print(f"  Items:       {len(items)}")
            else:
                print("  No active order.")
            print()
        except AlbertHeijnApiError as e:
            print(f"  ✗ Failed: {e}\n")

        # Save updated tokens (may have been refreshed)
        updated_tokens = {
            "access_token": api.access_token,
            "refresh_token": api.refresh_token,
            "member_id": tokens.get("member_id", ""),
        }
        with open(token_file, "w") as f:
            json.dump(updated_tokens, f, indent=2)
        print("✓ Updated tokens saved to .tokens.json")


if __name__ == "__main__":
    asyncio.run(main())
