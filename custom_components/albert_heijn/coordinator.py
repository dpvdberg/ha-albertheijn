"""Data update coordinator for Albert Heijn."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AlbertHeijnApi,
    AlbertHeijnApiError,
    AlbertHeijnAuthError,
    AlbertHeijnData,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class AlbertHeijnCoordinator(DataUpdateCoordinator[AlbertHeijnData]):
    """Coordinator to manage fetching Albert Heijn data."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.config_entry = entry
        session = async_get_clientsession(hass)
        self.api = AlbertHeijnApi(
            session=session,
            access_token=entry.data[CONF_ACCESS_TOKEN],
            refresh_token=entry.data[CONF_REFRESH_TOKEN],
        )

    async def _async_update_data(self) -> AlbertHeijnData:
        """Fetch data from the API."""
        try:
            return await self._fetch_data()
        except AlbertHeijnAuthError as err:
            # Token refresh failed, trigger reauth flow
            raise ConfigEntryAuthFailed from err
        except AlbertHeijnApiError as err:
            raise UpdateFailed(
                f"Error communicating with Albert Heijn API: {err}"
            ) from err

    async def _fetch_data(self) -> AlbertHeijnData:
        """Fetch all data from the API."""
        fulfillments = await self.api.get_fulfillments()

        data = AlbertHeijnData(fulfillments=fulfillments)

        # Find the next upcoming order
        if fulfillments:
            sorted_fulfillments = sorted(
                fulfillments, key=lambda f: f.delivery_slot.date
            )
            data.next_order = sorted_fulfillments[0]

            # Get details for all orders (needed for card badges/deadlines)
            for f in sorted_fulfillments:
                try:
                    details = await self.api.get_order_details(f.order_id)
                    data.all_order_details[f.order_id] = details
                except AlbertHeijnApiError as err:
                    _LOGGER.debug(
                        "Could not fetch details for order %d: %s",
                        f.order_id, err,
                    )

            # Set the next order's details for backward compat
            next_order = data.next_order
            data.order_details = data.all_order_details.get(next_order.order_id)

            # Get minimum value limits if order is modifiable
            if next_order.modifiable:
                try:
                    data.order_value_limits = (
                        await self.api.get_order_value_limits(
                            next_order.order_id
                        )
                    )
                except AlbertHeijnApiError as err:
                    _LOGGER.debug(
                        "Could not fetch order value limits: %s", err
                    )

        # Persist refreshed tokens
        self._update_tokens()

        return data

    def _update_tokens(self) -> None:
        """Update stored tokens if they changed."""
        new_data = {
            **self.config_entry.data,
            CONF_ACCESS_TOKEN: self.api.access_token,
            CONF_REFRESH_TOKEN: self.api.refresh_token,
        }
        if new_data != self.config_entry.data:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
