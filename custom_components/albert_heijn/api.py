"""Albert Heijn API client."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp

try:
    from .const import (
        API_BASE_URL,
        AUTH_REFRESH_URL,
        CLIENT_ID,
        CLIENT_VERSION,
        GRAPHQL_URL,
        USER_AGENT,
    )
except ImportError:
    # Allow standalone import for testing without homeassistant
    from const import (  # type: ignore[no-redef]
        API_BASE_URL,
        AUTH_REFRESH_URL,
        CLIENT_ID,
        CLIENT_VERSION,
        GRAPHQL_URL,
        USER_AGENT,
    )

_LOGGER = logging.getLogger(__name__)


@dataclass
class DeliverySlot:
    """Delivery time window."""

    date: str
    date_display: str
    time_display: str
    start_time: str
    end_time: str


@dataclass
class Fulfillment:
    """A scheduled order with delivery information."""

    order_id: int
    status: str
    status_description: str
    shopping_type: str
    total_price: float
    transaction_completed: bool
    modifiable: bool
    delivery_slot: DeliverySlot
    delivery_address: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderDetails:
    """Detailed order information including closing time."""

    order_id: int
    state: str
    delivery_date: str
    closing_time: str | None
    products_closing_time: str | None
    delivery_start: str | None
    delivery_end: str | None
    total_items: int
    reopenable: bool
    order_method: str | None


@dataclass
class OrderValueLimits:
    """Minimum order value information."""

    minimum_order_value: float
    submittable: bool
    deadline: str | None = None


@dataclass
class Product:
    """A product from the AH webshop."""

    id: int
    title: str
    brand: str
    price: float
    unit_size: str
    is_orderable: bool
    image_url: str | None = None


@dataclass
class OrderItem:
    """An item in an order."""

    product_id: int
    title: str
    brand: str
    quantity: int
    price: float
    unit_size: str


@dataclass
class AlbertHeijnData:
    """Container for all data fetched from the API."""

    fulfillments: list[Fulfillment] = field(default_factory=list)
    next_order: Fulfillment | None = None
    order_details: OrderDetails | None = None
    order_value_limits: OrderValueLimits | None = None
    all_order_details: dict[int, OrderDetails] = field(default_factory=dict)


class AlbertHeijnApiError(Exception):
    """Base exception for API errors."""


class AlbertHeijnAuthError(AlbertHeijnApiError):
    """Authentication error."""


class AlbertHeijnApi:
    """Client for the Albert Heijn API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_token: str,
        refresh_token: str,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._access_token = access_token
        self._refresh_token = refresh_token

    @property
    def access_token(self) -> str:
        """Return the current access token."""
        return self._access_token

    @property
    def refresh_token(self) -> str:
        """Return the current refresh token."""
        return self._refresh_token

    def _headers(self) -> dict[str, str]:
        """Return default request headers."""
        return {
            "User-Agent": USER_AGENT,
            "x-clientname": "ipad",
            "x-clientversion": CLIENT_VERSION,
            "x-application": "AHWEBSHOP",
            "x-accept-language": "nl-NL",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

    async def _request(
        self,
        method: str,
        path: str,
        json_data: Any = None,
        retry_auth: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """Make an authenticated API request."""
        url = f"{API_BASE_URL}{path}"
        headers = self._headers()
        if extra_headers:
            headers.update(extra_headers)

        async with self._session.request(
            method, url, headers=headers, json=json_data
        ) as resp:
            if resp.status == 401 and retry_auth:
                await self.refresh_access_token()
                return await self._request(method, path, json_data, retry_auth=False)
            if resp.status == 401:
                raise AlbertHeijnAuthError("Authentication failed after token refresh")
            if resp.status >= 400:
                text = await resp.text()
                raise AlbertHeijnApiError(
                    f"API request failed: {resp.status} - {text}"
                )
            if resp.content_type == "application/json":
                return await resp.json()
            return None

    async def _graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> Any:
        """Make a GraphQL request."""
        headers = self._headers()
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        async with self._session.post(
            GRAPHQL_URL, headers=headers, json=payload
        ) as resp:
            if resp.status == 401 and retry_auth:
                await self.refresh_access_token()
                return await self._graphql(query, variables, retry_auth=False)
            if resp.status == 401:
                raise AlbertHeijnAuthError("Authentication failed after token refresh")
            if resp.status >= 400:
                text = await resp.text()
                raise AlbertHeijnApiError(
                    f"GraphQL request failed: {resp.status} - {text}"
                )

            data = await resp.json()
            if errors := data.get("errors"):
                raise AlbertHeijnApiError(f"GraphQL errors: {errors}")
            return data.get("data")

    async def refresh_access_token(self) -> None:
        """Refresh the access token."""
        payload = {
            "clientId": CLIENT_ID,
            "refreshToken": self._refresh_token,
        }
        headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        }

        async with self._session.post(
            AUTH_REFRESH_URL, headers=headers, json=payload
        ) as resp:
            if resp.status >= 400:
                raise AlbertHeijnAuthError("Failed to refresh access token")
            data = await resp.json()

        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]

    async def get_fulfillments(self) -> list[Fulfillment]:
        """Get all open order fulfillments."""
        query = """query OrderFulfillments {
  orderFulfillments(status: OPEN) {
    result {
      orderId
      statusCode
      statusDescription
      shoppingType
      transactionCompleted
      modifiable
      totalPrice {
        totalPrice { amount }
      }
      delivery {
        status
        method
        slot {
          date
          dateDisplay
          timeDisplay
          startTime
          endTime
        }
        address {
          street
          houseNumber
          houseNumberExtra
          city
          postalCode
        }
      }
    }
  }
}"""

        data = await self._graphql(query)
        results = data.get("orderFulfillments", {}).get("result", [])

        fulfillments = []
        for r in results:
            slot = r.get("delivery", {}).get("slot", {})
            address = r.get("delivery", {}).get("address", {})
            fulfillments.append(
                Fulfillment(
                    order_id=r["orderId"],
                    status=r.get("delivery", {}).get("status", ""),
                    status_description=r.get("statusDescription", ""),
                    shopping_type=r.get("shoppingType", ""),
                    total_price=r.get("totalPrice", {})
                    .get("totalPrice", {})
                    .get("amount", 0),
                    transaction_completed=r.get("transactionCompleted", False),
                    modifiable=r.get("modifiable", False),
                    delivery_slot=DeliverySlot(
                        date=slot.get("date", ""),
                        date_display=slot.get("dateDisplay", ""),
                        time_display=slot.get("timeDisplay", ""),
                        start_time=slot.get("startTime", ""),
                        end_time=slot.get("endTime", ""),
                    ),
                    delivery_address=address,
                )
            )

        return fulfillments

    async def get_order_details(self, order_id: int) -> OrderDetails:
        """Get detailed order information including closing time."""
        data = await self._request(
            "GET",
            f"/mobile-services/order/v1/{order_id}/details-grouped-by-taxonomy",
        )

        total_items = 0
        for group in data.get("groupedProductsInTaxonomy", []):
            total_items += len(group.get("orderedProducts", []))

        delivery_period = data.get("deliveryTimePeriod", {})

        return OrderDetails(
            order_id=data.get("orderId", order_id),
            state=data.get("orderState", ""),
            delivery_date=data.get("deliveryDate", ""),
            closing_time=data.get("closingTime"),
            products_closing_time=data.get("productsClosingTime"),
            delivery_start=delivery_period.get("startDateTime"),
            delivery_end=delivery_period.get("endDateTime"),
            total_items=total_items,
            reopenable=data.get("reopenable", False),
            order_method=data.get("orderMethod"),
        )

    async def get_order_items(self, order_id: int) -> list[OrderItem]:
        """Get the list of items in an order."""
        data = await self._request(
            "GET",
            f"/mobile-services/order/v1/{order_id}/details-grouped-by-taxonomy",
        )

        items: list[OrderItem] = []
        for group in data.get("groupedProductsInTaxonomy", []):
            for op in group.get("orderedProducts", []):
                product = op.get("product", {})
                items.append(
                    OrderItem(
                        product_id=product.get("webshopId", 0),
                        title=product.get("title", ""),
                        brand=product.get("brand", ""),
                        quantity=op.get("quantity", 1),
                        price=product.get("currentPrice") or product.get("priceBeforeBonus", 0),
                        unit_size=product.get("salesUnitSize", ""),
                    )
                )
        return items

    async def get_order_value_limits(self, order_id: int) -> OrderValueLimits:
        """Get minimum order value limits for an order."""
        query = """query FetchOrderMinimumValueLimits($orderId: Int!) {
  orderValueLimits(orderId: $orderId) {
    minimumOrderValue { amount }
    submittable
  }
}"""
        data = await self._graphql(query, {"orderId": order_id})
        limits = data.get("orderValueLimits", {})
        min_value = limits.get("minimumOrderValue", {})

        return OrderValueLimits(
            minimum_order_value=min_value.get("amount", 0),
            submittable=limits.get("submittable", True),
        )

    async def search_products(self, query: str, limit: int = 10) -> list[Product]:
        """Search for products."""
        data = await self._request(
            "GET",
            f"/mobile-services/product/search/v2?query={query}&page=0&size={limit}&sortOn=RELEVANCE",
        )

        products = []
        for p in data.get("products", []):
            image_url = None
            images = p.get("images", [])
            if images:
                image_url = images[0].get("url")

            products.append(
                Product(
                    id=p["webshopId"],
                    title=p.get("title", ""),
                    brand=p.get("brand", ""),
                    price=p.get("currentPrice", 0),
                    unit_size=p.get("salesUnitSize", ""),
                    is_orderable=p.get("isOrderable", False),
                    image_url=image_url,
                )
            )

        return products

    async def add_to_order(self, items: list[dict[str, Any]], order_id: int | None = None) -> None:
        """Add items to an order.

        Items should be a list of dicts with 'productId' and 'quantity'.
        If order_id is provided, adds to that specific order.
        Otherwise uses the current active order.
        """
        request_items = [
            {
                "productId": item["productId"],
                "quantity": item["quantity"],
                "originCode": "PRD",
                "description": "",
                "strikethrough": False,
            }
            for item in items
        ]

        extra_headers = {}
        if order_id:
            extra_headers["Appie-Current-Order-Id"] = str(order_id)

        await self._request(
            "PUT",
            "/mobile-services/order/v1/items?sortBy=DEFAULT",
            json_data={"items": request_items},
            extra_headers=extra_headers or None,
        )

    async def reopen_order(self, order_id: int) -> None:
        """Reopen a submitted order to allow modifications."""
        query = """mutation OrderReopen($id: Int!) {
  orderReopen(id: $id) {
    status
    errorMessage
  }
}"""
        data = await self._graphql(query, {"id": order_id})
        result = data.get("orderReopen", {})
        if result.get("status") != "SUCCESS":
            raise AlbertHeijnApiError(
                f"Failed to reopen order: {result.get('errorMessage', 'unknown error')}"
            )

    async def revert_order(self, order_id: int) -> None:
        """Revert a reopened order back to submitted state."""
        query = """mutation OrderRevert($id: Int!) {
  orderRevert(id: $id) {
    status
    errorMessage
  }
}"""
        data = await self._graphql(query, {"id": order_id})
        result = data.get("orderRevert", {})
        if result.get("status") != "SUCCESS":
            raise AlbertHeijnApiError(
                f"Failed to revert order: {result.get('errorMessage', 'unknown error')}"
            )

    async def get_active_order_summary(self) -> dict[str, Any] | None:
        """Get the active order summary."""
        try:
            data = await self._request(
                "GET",
                "/mobile-services/order/v1/summaries/active?sortBy=DEFAULT",
            )
            return data
        except AlbertHeijnApiError:
            return None
