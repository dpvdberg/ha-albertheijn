"""Services for Albert Heijn integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError

from .api import AlbertHeijnApiError
from .const import DOMAIN
from .coordinator import AlbertHeijnCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_SEARCH_PRODUCTS = "search_products"
SERVICE_ADD_TO_ORDER = "add_to_order"
SERVICE_ADD_PRODUCT_BY_NAME = "add_product_by_name"
SERVICE_REOPEN_ORDER = "reopen_order"
SERVICE_REVERT_ORDER = "revert_order"

ATTR_QUERY = "query"
ATTR_PRODUCT_ID = "product_id"
ATTR_QUANTITY = "quantity"
ATTR_ORDER_ID = "order_id"
ATTR_LIMIT = "limit"
ATTR_PRODUCT_NAME = "product_name"


SEARCH_PRODUCTS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_QUERY): str,
        vol.Optional(ATTR_LIMIT, default=5): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=30)
        ),
    }
)

ADD_TO_ORDER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PRODUCT_ID): vol.Coerce(int),
        vol.Optional(ATTR_QUANTITY, default=1): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=99)
        ),
    }
)

ADD_PRODUCT_BY_NAME_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PRODUCT_NAME): str,
        vol.Optional(ATTR_QUANTITY, default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=99)
        ),
    }
)

ORDER_ID_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ORDER_ID): vol.Coerce(int),
    }
)


def _get_coordinator(hass: HomeAssistant) -> AlbertHeijnCoordinator:
    """Get the first available coordinator."""
    if DOMAIN not in hass.data:
        raise HomeAssistantError("Albert Heijn integration not configured")
    coordinators = hass.data[DOMAIN]
    if not coordinators:
        raise HomeAssistantError("No Albert Heijn accounts configured")
    # Return the first coordinator
    return next(iter(coordinators.values()))


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for the Albert Heijn integration."""

    async def handle_search_products(call: ServiceCall) -> ServiceResponse:
        """Handle search products service call."""
        coordinator = _get_coordinator(hass)
        query = call.data[ATTR_QUERY]
        limit = call.data.get(ATTR_LIMIT, 5)

        try:
            products = await coordinator.api.search_products(query, limit)
        except AlbertHeijnApiError as err:
            raise HomeAssistantError(f"Failed to search products: {err}") from err

        return {
            "products": [
                {
                    "id": p.id,
                    "title": p.title,
                    "brand": p.brand,
                    "price": p.price,
                    "unit_size": p.unit_size,
                    "is_orderable": p.is_orderable,
                    "image_url": p.image_url,
                }
                for p in products
            ]
        }

    async def handle_add_to_order(call: ServiceCall) -> None:
        """Handle add to order service call."""
        coordinator = _get_coordinator(hass)
        product_id = call.data[ATTR_PRODUCT_ID]
        quantity = call.data.get(ATTR_QUANTITY, 1)

        try:
            summary = await coordinator.api.get_active_order_summary()
            order_id = summary["id"] if summary else None
            await coordinator.api.add_to_order(
                [{"productId": product_id, "quantity": quantity}],
                order_id=order_id,
            )
        except AlbertHeijnApiError as err:
            raise HomeAssistantError(f"Failed to add to order: {err}") from err

        # Refresh data after modification
        await coordinator.async_request_refresh()

    async def handle_add_product_by_name(call: ServiceCall) -> ServiceResponse:
        """Handle adding a product by name - searches and adds the first match."""
        coordinator = _get_coordinator(hass)
        product_name = call.data[ATTR_PRODUCT_NAME]
        quantity = call.data.get(ATTR_QUANTITY, 1)

        try:
            # Search for the product
            products = await coordinator.api.search_products(product_name, 5)
        except AlbertHeijnApiError as err:
            raise HomeAssistantError(
                f"Failed to search for '{product_name}': {err}"
            ) from err

        if not products:
            raise HomeAssistantError(f"No products found for '{product_name}'")

        # Find first orderable product
        orderable = [p for p in products if p.is_orderable]
        if not orderable:
            raise HomeAssistantError(
                f"No orderable products found for '{product_name}'"
            )

        product = orderable[0]

        try:
            summary = await coordinator.api.get_active_order_summary()
            order_id = summary["id"] if summary else None
            await coordinator.api.add_to_order(
                [{"productId": product.id, "quantity": quantity}],
                order_id=order_id,
            )
        except AlbertHeijnApiError as err:
            raise HomeAssistantError(
                f"Failed to add '{product.title}' to order: {err}"
            ) from err

        # Refresh data after modification
        await coordinator.async_request_refresh()

        return {
            "added_product": {
                "id": product.id,
                "title": product.title,
                "brand": product.brand,
                "price": product.price,
                "quantity": quantity,
            }
        }

    async def handle_reopen_order(call: ServiceCall) -> None:
        """Handle reopen order service call."""
        coordinator = _get_coordinator(hass)
        order_id = call.data[ATTR_ORDER_ID]

        try:
            await coordinator.api.reopen_order(order_id)
        except AlbertHeijnApiError as err:
            raise HomeAssistantError(f"Failed to reopen order: {err}") from err

        await coordinator.async_request_refresh()

    async def handle_revert_order(call: ServiceCall) -> None:
        """Handle revert order service call."""
        coordinator = _get_coordinator(hass)
        order_id = call.data[ATTR_ORDER_ID]

        try:
            await coordinator.api.revert_order(order_id)
        except AlbertHeijnApiError as err:
            raise HomeAssistantError(f"Failed to revert order: {err}") from err

        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH_PRODUCTS,
        handle_search_products,
        schema=SEARCH_PRODUCTS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_TO_ORDER,
        handle_add_to_order,
        schema=ADD_TO_ORDER_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_PRODUCT_BY_NAME,
        handle_add_product_by_name,
        schema=ADD_PRODUCT_BY_NAME_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REOPEN_ORDER,
        handle_reopen_order,
        schema=ORDER_ID_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REVERT_ORDER,
        handle_revert_order,
        schema=ORDER_ID_SCHEMA,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services."""
    hass.services.async_remove(DOMAIN, SERVICE_SEARCH_PRODUCTS)
    hass.services.async_remove(DOMAIN, SERVICE_ADD_TO_ORDER)
    hass.services.async_remove(DOMAIN, SERVICE_ADD_PRODUCT_BY_NAME)
    hass.services.async_remove(DOMAIN, SERVICE_REOPEN_ORDER)
    hass.services.async_remove(DOMAIN, SERVICE_REVERT_ORDER)
