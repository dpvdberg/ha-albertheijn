"""Intent handlers for Albert Heijn Assist integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .const import DOMAIN
from .coordinator import AlbertHeijnCoordinator

_LOGGER = logging.getLogger(__name__)

INTENT_ORDER_STATUS = "AlbertHeijnOrderStatus"


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Set up intent handlers for Albert Heijn."""
    intent.async_register(hass, OrderStatusIntentHandler())


def _get_coordinator(hass: HomeAssistant) -> AlbertHeijnCoordinator:
    """Get the first available coordinator."""
    if DOMAIN not in hass.data or not hass.data[DOMAIN]:
        raise intent.IntentHandleError("Albert Heijn integration not configured")
    return next(iter(hass.data[DOMAIN].values()))


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
