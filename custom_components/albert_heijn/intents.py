"""Intent handlers for Albert Heijn Assist integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .api import AlbertHeijnApiError
from .const import DOMAIN
from .coordinator import AlbertHeijnCoordinator

_LOGGER = logging.getLogger(__name__)

INTENT_ORDER_STATUS = "AlbertHeijnOrderStatus"
INTENT_SEARCH_PRODUCTS = "AlbertHeijnSearchProducts"
INTENT_ADD_TO_ORDER = "AlbertHeijnAddToOrder"
INTENT_LIST_ORDER_ITEMS = "AlbertHeijnListOrderItems"
INTENT_REMOVE_FROM_ORDER = "AlbertHeijnRemoveFromOrder"


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Set up intent handlers for Albert Heijn."""
    intent.async_register(hass, OrderStatusIntentHandler())
    intent.async_register(hass, SearchProductsIntentHandler())
    intent.async_register(hass, AddToOrderIntentHandler())
    intent.async_register(hass, ListOrderItemsIntentHandler())
    intent.async_register(hass, RemoveFromOrderIntentHandler())


def _get_coordinator(hass: HomeAssistant) -> AlbertHeijnCoordinator:
    """Get the first available coordinator."""
    if DOMAIN not in hass.data or not hass.data[DOMAIN]:
        raise intent.IntentHandleError("Albert Heijn integration not configured")
    return next(iter(hass.data[DOMAIN].values()))


class SearchProductsIntentHandler(intent.IntentHandler):
    """Search for products and return IDs + names for the AI to pick from."""

    intent_type = INTENT_SEARCH_PRODUCTS
    slot_schema = {
        "query": intent.non_empty_string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        slots = self.async_validate_slots(intent_obj.slots)
        query = slots["query"]["value"]

        coordinator = _get_coordinator(intent_obj.hass)

        try:
            products = await coordinator.api.search_products(query, 10)
        except AlbertHeijnApiError as err:
            raise intent.IntentHandleError(
                f"Kon niet zoeken naar '{query}': {err}"
            ) from err

        if not products:
            response = intent_obj.create_response()
            response.async_set_speech(f"Geen producten gevonden voor '{query}'.")
            return response

        lines = []
        for p in products:
            orderable = "✓" if p.is_orderable else "✗"
            lines.append(f"- [{orderable}] {p.title} ({p.brand}, {p.unit_size}) €{p.price:.2f} → id:{p.id}")

        response = intent_obj.create_response()
        response.async_set_speech(
            f"Zoekresultaten voor '{query}':\n" + "\n".join(lines)
        )
        return response


class AddToOrderIntentHandler(intent.IntentHandler):
    """Add a product to the order by product ID."""

    intent_type = INTENT_ADD_TO_ORDER
    slot_schema = {
        "product_id": intent.non_empty_string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        slots = self.async_validate_slots(intent_obj.slots)
        try:
            product_id = int(slots["product_id"]["value"])
        except (ValueError, TypeError):
            raise intent.IntentHandleError("Ongeldig product ID.")

        quantity_str = intent_obj.slots.get("quantity", {}).get("value", "1")
        try:
            quantity = int(quantity_str)
        except (ValueError, TypeError):
            quantity = 1

        coordinator = _get_coordinator(intent_obj.hass)

        try:
            summary = await coordinator.api.get_active_order_summary()
            order_id = summary["id"] if summary else None
            await coordinator.api.add_to_order(
                [{"productId": product_id, "quantity": quantity}],
                order_id=order_id,
            )
        except AlbertHeijnApiError as err:
            raise intent.IntentHandleError(
                f"Kon product {product_id} niet toevoegen: {err}"
            ) from err

        await coordinator.async_request_refresh()

        response = intent_obj.create_response()
        response.async_set_speech(
            f"{quantity}x product {product_id} toegevoegd aan je bestelling."
        )
        return response


class ListOrderItemsIntentHandler(intent.IntentHandler):
    """List items currently in the order."""

    intent_type = INTENT_LIST_ORDER_ITEMS

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        coordinator = _get_coordinator(intent_obj.hass)
        data = coordinator.data

        if not data or not data.next_order:
            response = intent_obj.create_response()
            response.async_set_speech("Geen actieve bestelling gevonden.")
            return response

        # Find the first modifiable order
        order_id = None
        for f in sorted(data.fulfillments, key=lambda f: f.delivery_slot.date):
            if f.modifiable:
                order_id = f.order_id
                break

        if not order_id:
            order_id = data.next_order.order_id

        try:
            items = await coordinator.api.get_order_items(order_id)
        except AlbertHeijnApiError as err:
            raise intent.IntentHandleError(
                f"Kon bestelling niet ophalen: {err}"
            ) from err

        if not items:
            response = intent_obj.create_response()
            response.async_set_speech("Je bestelling is leeg.")
            return response

        lines = []
        for item in items:
            lines.append(f"- {item.quantity}x {item.title} ({item.unit_size}) €{item.price:.2f} → id:{item.product_id}")

        response = intent_obj.create_response()
        response.async_set_speech(
            f"Er zitten {len(items)} producten in je bestelling:\n" + "\n".join(lines)
        )
        return response


class RemoveFromOrderIntentHandler(intent.IntentHandler):
    """Remove a product from the order by product ID."""

    intent_type = INTENT_REMOVE_FROM_ORDER
    slot_schema = {
        "product_id": intent.non_empty_string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        slots = self.async_validate_slots(intent_obj.slots)
        try:
            product_id = int(slots["product_id"]["value"])
        except (ValueError, TypeError):
            raise intent.IntentHandleError("Ongeldig product ID.")

        coordinator = _get_coordinator(intent_obj.hass)

        try:
            summary = await coordinator.api.get_active_order_summary()
            order_id = summary["id"] if summary else None
            await coordinator.api.add_to_order(
                [{"productId": product_id, "quantity": 0}],
                order_id=order_id,
            )
        except AlbertHeijnApiError as err:
            raise intent.IntentHandleError(
                f"Kon product {product_id} niet verwijderen: {err}"
            ) from err

        await coordinator.async_request_refresh()

        response = intent_obj.create_response()
        response.async_set_speech(
            f"Product {product_id} is verwijderd uit je bestelling."
        )
        return response


class OrderStatusIntentHandler(intent.IntentHandler):
    """Handle order status queries via Assist."""

    intent_type = INTENT_ORDER_STATUS

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        coordinator = _get_coordinator(intent_obj.hass)
        data = coordinator.data

        response = intent_obj.create_response()

        if not data or not data.next_order:
            response.async_set_speech(
                "Je hebt geen openstaande bestellingen bij Albert Heijn."
            )
            return response

        order = data.next_order
        parts = []
        parts.append(
            f"Je volgende bestelling wordt bezorgd op {order.delivery_slot.date_display} "
            f"tussen {order.delivery_slot.time_display}."
        )
        parts.append(f"Het totaalbedrag is €{order.total_price:.2f}.")

        if data.order_details and data.order_details.total_items:
            parts.append(
                f"Er zitten {data.order_details.total_items} producten in je bestelling."
            )

        if order.modifiable:
            parts.append("Je kunt nog producten toevoegen of wijzigen.")
        else:
            parts.append("De bestelling kan niet meer worden gewijzigd.")

        response.async_set_speech(" ".join(parts))
        return response
