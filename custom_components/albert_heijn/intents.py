"""Intent handlers for Albert Heijn Assist integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .api import AlbertHeijnApiError
from .const import DOMAIN
from .coordinator import AlbertHeijnCoordinator

_LOGGER = logging.getLogger(__name__)

INTENT_ADD_TO_ORDER = "AlbertHeijnAddToOrder"
INTENT_ORDER_STATUS = "AlbertHeijnOrderStatus"


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Set up intent handlers for Albert Heijn."""
    intent.async_register(hass, AddToOrderIntentHandler())
    intent.async_register(hass, OrderStatusIntentHandler())


def _get_coordinator(hass: HomeAssistant) -> AlbertHeijnCoordinator:
    """Get the first available coordinator."""
    if DOMAIN not in hass.data or not hass.data[DOMAIN]:
        raise intent.IntentHandleError("Albert Heijn integration not configured")
    return next(iter(hass.data[DOMAIN].values()))


class AddToOrderIntentHandler(intent.IntentHandler):
    """Handle adding items to the Albert Heijn order via Assist."""

    intent_type = INTENT_ADD_TO_ORDER
    slot_schema = {
        "product_name": intent.non_empty_string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        slots = self.async_validate_slots(intent_obj.slots)
        product_name = slots["product_name"]["value"]

        # Extract quantity from slots if present
        quantity_str = intent_obj.slots.get("quantity", {}).get("value", "1")
        try:
            quantity = int(quantity_str)
        except (ValueError, TypeError):
            quantity = 1

        coordinator = _get_coordinator(intent_obj.hass)

        try:
            products = await coordinator.api.search_products(product_name, 5)
        except AlbertHeijnApiError as err:
            raise intent.IntentHandleError(
                f"Kon niet zoeken naar '{product_name}': {err}"
            ) from err

        if not products:
            raise intent.IntentHandleError(
                f"Geen producten gevonden voor '{product_name}'"
            )

        orderable = [p for p in products if p.is_orderable]
        if not orderable:
            raise intent.IntentHandleError(
                f"Geen bestelbare producten gevonden voor '{product_name}'"
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
            raise intent.IntentHandleError(
                f"Kon '{product.title}' niet toevoegen: {err}"
            ) from err

        await coordinator.async_request_refresh()

        response = intent_obj.create_response()
        response.async_set_speech(
            f"{quantity}x {product.title} ({product.unit_size}) toegevoegd aan je bestelling."
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
