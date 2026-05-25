"""Sensor platform for Albert Heijn."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AlbertHeijnData
from .const import DOMAIN
from .coordinator import AlbertHeijnCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Albert Heijn sensors from a config entry."""
    coordinator: AlbertHeijnCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        AHNextDeliveryDateSensor(coordinator),
        AHNextDeliveryTimeSensor(coordinator),
        AHNextOrderTotalSensor(coordinator),
        AHNextOrderStatusSensor(coordinator),
        AHNextOrderEditDeadlineSensor(coordinator),
        AHNextOrderModifiableSensor(coordinator),
        AHNextOrderItemCountSensor(coordinator),
        AHMinimumOrderValueSensor(coordinator),
        AHOrderSubmittableSensor(coordinator),
        AHOpenOrderCountSensor(coordinator),
        AHOrderSpendingSensor(coordinator),
    ]

    async_add_entities(entities)


class AHBaseSensor(CoordinatorEntity[AlbertHeijnCoordinator], SensorEntity):
    """Base class for Albert Heijn sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AlbertHeijnCoordinator,
        key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": "Albert Heijn",
            "manufacturer": "Albert Heijn",
            "model": "Grocery Delivery",
        }


class AHNextDeliveryDateSensor(AHBaseSensor):
    """Sensor for the next delivery date."""

    _attr_name = "Next delivery date"
    _attr_icon = "mdi:truck-delivery"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator: AlbertHeijnCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "next_delivery_date")

    @property
    def native_value(self) -> datetime | None:
        """Return the delivery date."""
        data: AlbertHeijnData = self.coordinator.data
        if data.next_order and data.next_order.delivery_slot.date:
            try:
                return datetime.strptime(
                    data.next_order.delivery_slot.date, "%Y-%m-%d"
                ).date()
            except ValueError:
                return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        data: AlbertHeijnData = self.coordinator.data
        if data.next_order:
            return {
                "date_display": data.next_order.delivery_slot.date_display,
                "shopping_type": data.next_order.shopping_type,
            }
        return {}


class AHNextDeliveryTimeSensor(AHBaseSensor):
    """Sensor for the next delivery time window."""

    _attr_name = "Next delivery time"
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: AlbertHeijnCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "next_delivery_time")

    @property
    def native_value(self) -> str | None:
        """Return the delivery time window."""
        data: AlbertHeijnData = self.coordinator.data
        if data.next_order:
            return data.next_order.delivery_slot.time_display
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        data: AlbertHeijnData = self.coordinator.data
        if data.next_order:
            return {
                "start_time": data.next_order.delivery_slot.start_time,
                "end_time": data.next_order.delivery_slot.end_time,
            }
        return {}


class AHNextOrderTotalSensor(AHBaseSensor):
    """Sensor for the next order total price."""

    _attr_name = "Next order total"
    _attr_icon = "mdi:currency-eur"
    _attr_native_unit_of_measurement = "€"
    _attr_suggested_display_precision = 2
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: AlbertHeijnCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "next_order_total")

    @property
    def native_value(self) -> float | None:
        """Return the order total."""
        data: AlbertHeijnData = self.coordinator.data
        if data.next_order:
            return data.next_order.total_price
        return None


class AHNextOrderStatusSensor(AHBaseSensor):
    """Sensor for the next order status."""

    _attr_name = "Next order status"
    _attr_icon = "mdi:package-variant"

    def __init__(self, coordinator: AlbertHeijnCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "next_order_status")

    @property
    def native_value(self) -> str | None:
        """Return the order status."""
        data: AlbertHeijnData = self.coordinator.data
        if data.next_order:
            return data.next_order.status_description
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        data: AlbertHeijnData = self.coordinator.data
        if data.next_order:
            return {
                "order_id": data.next_order.order_id,
                "status": data.next_order.status,
                "transaction_completed": data.next_order.transaction_completed,
            }
        return {}


class AHNextOrderEditDeadlineSensor(AHBaseSensor):
    """Sensor for the deadline to edit the next order."""

    _attr_name = "Next order edit deadline"
    _attr_icon = "mdi:timer-alert"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: AlbertHeijnCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "next_order_edit_deadline")

    @property
    def native_value(self) -> datetime | None:
        """Return the closing time as a timestamp."""
        data: AlbertHeijnData = self.coordinator.data
        if data.order_details and data.order_details.closing_time:
            try:
                return datetime.fromisoformat(
                    data.order_details.closing_time.replace("Z", "+00:00")
                )
            except ValueError:
                return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        data: AlbertHeijnData = self.coordinator.data
        attrs: dict[str, Any] = {}
        if data.order_details:
            attrs["reopenable"] = data.order_details.reopenable
            attrs["order_method"] = data.order_details.order_method
            if data.order_details.products_closing_time:
                attrs["products_closing_time"] = (
                    data.order_details.products_closing_time
                )
        return attrs


class AHNextOrderModifiableSensor(AHBaseSensor):
    """Sensor indicating if the next order can still be modified."""

    _attr_name = "Next order modifiable"
    _attr_icon = "mdi:pencil-lock"

    def __init__(self, coordinator: AlbertHeijnCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "next_order_modifiable")

    @property
    def native_value(self) -> str | None:
        """Return whether the order is modifiable."""
        data: AlbertHeijnData = self.coordinator.data
        if data.next_order:
            return "Yes" if data.next_order.modifiable else "No"
        return None


class AHNextOrderItemCountSensor(AHBaseSensor):
    """Sensor for the number of items in the next order."""

    _attr_name = "Next order items"
    _attr_icon = "mdi:cart"
    _attr_native_unit_of_measurement = "items"

    def __init__(self, coordinator: AlbertHeijnCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "next_order_item_count")

    @property
    def native_value(self) -> int | None:
        """Return the item count."""
        data: AlbertHeijnData = self.coordinator.data
        if data.order_details:
            return data.order_details.total_items
        return None


class AHMinimumOrderValueSensor(AHBaseSensor):
    """Sensor for the minimum order value (subscription requirement)."""

    _attr_name = "Minimum order value"
    _attr_icon = "mdi:cash-check"
    _attr_native_unit_of_measurement = "€"

    def __init__(self, coordinator: AlbertHeijnCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "minimum_order_value")

    @property
    def native_value(self) -> float | None:
        """Return the minimum order value."""
        data: AlbertHeijnData = self.coordinator.data
        if data.order_value_limits:
            return data.order_value_limits.minimum_order_value
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        data: AlbertHeijnData = self.coordinator.data
        attrs: dict[str, Any] = {}
        if data.order_value_limits and data.next_order:
            attrs["current_total"] = data.next_order.total_price
            remaining = (
                data.order_value_limits.minimum_order_value
                - data.next_order.total_price
            )
            attrs["remaining_to_minimum"] = max(0, remaining)
        return attrs


class AHOrderSubmittableSensor(AHBaseSensor):
    """Sensor indicating if the order meets the minimum value."""

    _attr_name = "Order submittable"
    _attr_icon = "mdi:check-circle"

    def __init__(self, coordinator: AlbertHeijnCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "order_submittable")

    @property
    def native_value(self) -> str | None:
        """Return whether the order is submittable."""
        data: AlbertHeijnData = self.coordinator.data
        if data.order_value_limits:
            return "Yes" if data.order_value_limits.submittable else "No"
        return None


class AHOpenOrderCountSensor(AHBaseSensor):
    """Sensor for the total number of open orders."""

    _attr_name = "Open orders"
    _attr_icon = "mdi:package-variant-closed"

    def __init__(self, coordinator: AlbertHeijnCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "open_order_count")

    @property
    def native_value(self) -> int | None:
        """Return the number of open orders."""
        data: AlbertHeijnData = self.coordinator.data
        return len(data.fulfillments)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes with summary of all open orders."""
        data: AlbertHeijnData = self.coordinator.data
        orders = []
        for f in data.fulfillments:
            details = data.all_order_details.get(f.order_id)
            orders.append(
                {
                    "order_id": f.order_id,
                    "delivery_date": f.delivery_slot.date,
                    "delivery_date_display": f.delivery_slot.date_display,
                    "time": f.delivery_slot.time_display,
                    "total": f.total_price,
                    "modifiable": f.modifiable,
                    "status": f.status_description,
                    "state": details.state if details else None,
                    "items": details.total_items if details else None,
                    "closing_time": details.closing_time if details else None,
                }
            )
        return {"orders": orders}


class AHOrderSpendingSensor(AHBaseSensor):
    """Sensor tracking order spending for history/statistics."""

    _attr_name = "Order spending"
    _attr_icon = "mdi:chart-line"
    _attr_native_unit_of_measurement = "€"
    _attr_suggested_display_precision = 2
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: AlbertHeijnCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "order_spending")

    @property
    def native_value(self) -> float | None:
        """Return the total of the most recent non-empty order.

        This tracks the latest order total as a measurement, allowing
        HA's recorder to build spending history over time.
        """
        data: AlbertHeijnData = self.coordinator.data
        if not data.fulfillments:
            return None

        # Find the most recent order with items (the one being/about to be delivered)
        sorted_orders = sorted(
            data.fulfillments, key=lambda f: f.delivery_slot.date
        )
        for order in sorted_orders:
            if order.total_price > 0:
                return order.total_price
        return 0.0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return spending breakdown."""
        data: AlbertHeijnData = self.coordinator.data
        attrs: dict[str, Any] = {}
        total_spending = sum(f.total_price for f in data.fulfillments)
        attrs["total_upcoming"] = round(total_spending, 2)
        attrs["order_count"] = len(
            [f for f in data.fulfillments if f.total_price > 0]
        )
        return attrs
