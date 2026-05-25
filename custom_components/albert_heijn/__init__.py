"""Albert Heijn integration for Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .auth import PROXY_PATH, handle_login_fallback, handle_proxy_request
from .const import DOMAIN
from .coordinator import AlbertHeijnCoordinator
from .intents import async_setup_intents
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CARD_URL = "/local/community/albert_heijn/albert-heijn-orders-card.js"


class AlbertHeijnLoginProxyView(HomeAssistantView):
    """View to handle the login proxy requests."""

    url = PROXY_PATH + "/{session_id}/{path_info:.*}"
    name = "api:albert_heijn:login_proxy"
    requires_auth = False

    async def _handle(self, request, session_id, path_info):
        """Forward to the proxy handler."""
        return await handle_proxy_request(request)

    get = _handle
    post = _handle
    put = _handle
    delete = _handle
    patch = _handle
    head = _handle
    options = _handle


class AlbertHeijnLoginFallbackView(HomeAssistantView):
    """Catch-all for /login/... paths from AH's hardcoded JS URLs."""

    url = "/login/{path_info:.*}"
    name = "api:albert_heijn:login_fallback"
    requires_auth = False

    async def _handle(self, request, path_info):
        """Forward to the fallback handler."""
        return await handle_login_fallback(request)

    get = _handle
    post = _handle
    put = _handle
    delete = _handle
    patch = _handle
    head = _handle
    options = _handle


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Albert Heijn integration."""
    hass.data.setdefault(DOMAIN, {})

    # Register the login proxy views (must happen before router freezes)
    hass.http.register_view(AlbertHeijnLoginProxyView)
    hass.http.register_view(AlbertHeijnLoginFallbackView)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Albert Heijn from a config entry."""
    coordinator = AlbertHeijnCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up services and register card (only once for all entries)
    if len(hass.data[DOMAIN]) == 1:
        await async_setup_services(hass)
        await async_setup_intents(hass)

        # Register the custom card JS
        hass.http.register_static_path(
            "/local/community/albert_heijn/albert-heijn-orders-card.js",
            str(Path(__file__).parent / "www" / "albert-heijn-orders-card.js"),
            cache_headers=False,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    # Remove services if no entries remain
    if not hass.data[DOMAIN]:
        await async_unload_services(hass)

    return unload_ok
