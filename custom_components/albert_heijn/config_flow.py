"""Config flow for Albert Heijn."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url

from .api import AlbertHeijnApi, AlbertHeijnAuthError
from .auth import (
    AuthenticationError,
    LoginProxy,
    async_refresh_token,
    exchange_code,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_MEMBER_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Timeout for waiting for user to complete browser login (5 minutes)
LOGIN_TIMEOUT = 300


class AlbertHeijnConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Albert Heijn."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._proxy: LoginProxy | None = None
        self._tokens: dict[str, str] | None = None
        self._login_task: asyncio.Task | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - start browser login."""
        if user_input is not None:
            # User clicked submit, start the proxy and move to external step
            return await self.async_step_login()

        return self.async_show_form(
            step_id="user",
            description_placeholders={},
            data_schema=vol.Schema({}),
        )

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start the login proxy and show the external auth step."""
        if self._proxy is not None:
            # Called again after login completed - advance to done step
            return self.async_external_step_done(next_step_id="login_done")

        # Extract the hostname from HA's URL to use for the proxy
        ha_url = get_url(self.hass)
        hostname = urlparse(ha_url).hostname or "127.0.0.1"

        self._proxy = LoginProxy(hostname=hostname)
        login_url = await self._proxy.start()

        # Start background task to wait for the auth code
        self._login_task = self.hass.async_create_task(self._wait_for_login())

        return self.async_external_step(step_id="login", url=login_url)

    async def _wait_for_login(self) -> None:
        """Wait for the user to complete login in the browser."""
        try:
            code = await self._proxy.wait_for_code(timeout=LOGIN_TIMEOUT)
            self._tokens = await exchange_code(code)
        except asyncio.TimeoutError:
            _LOGGER.warning("Login timed out waiting for user")
            self._tokens = None
        except AuthenticationError as err:
            _LOGGER.error("Token exchange failed: %s", err)
            self._tokens = None
        except Exception:
            _LOGGER.exception("Unexpected error during login")
            self._tokens = None
        finally:
            if self._proxy:
                await self._proxy.stop()
            # Signal the config flow to advance
            self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)

    async def async_step_login_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle completion of the external login step."""
        if self._login_task and not self._login_task.done():
            # Wait a bit for the task to finish
            try:
                await asyncio.wait_for(self._login_task, timeout=10)
            except asyncio.TimeoutError:
                pass

        if not self._tokens:
            return self.async_abort(reason="login_failed")

        # Validate tokens
        session = async_get_clientsession(self.hass)
        api = AlbertHeijnApi(
            session,
            self._tokens["access_token"],
            self._tokens["refresh_token"],
        )
        try:
            await api.get_fulfillments()
        except AlbertHeijnAuthError:
            return self.async_abort(reason="invalid_auth")
        except Exception:
            _LOGGER.exception("Token validation failed")
            return self.async_abort(reason="cannot_connect")

        member_id = self._tokens.get("member_id", "")
        unique_id = member_id or "albert_heijn_user"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title="Albert Heijn",
            data={
                CONF_ACCESS_TOKEN: self._tokens["access_token"],
                CONF_REFRESH_TOKEN: self._tokens["refresh_token"],
                CONF_MEMBER_ID: member_id,
            },
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth when tokens expire and refresh fails."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauth - try refresh first, then browser login."""
        if user_input is not None:
            # Start the browser login flow
            return await self.async_step_login()

        # Try refreshing first
        entry = self.hass.config_entries.async_get_entry(
            self.context.get("entry_id", "")
        )
        if entry and entry.data.get(CONF_REFRESH_TOKEN):
            try:
                tokens = await async_refresh_token(
                    entry.data[CONF_REFRESH_TOKEN]
                )
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_ACCESS_TOKEN: tokens["access_token"],
                        CONF_REFRESH_TOKEN: tokens["refresh_token"],
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            except AuthenticationError:
                _LOGGER.debug("Token refresh failed, requiring browser login")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({}),
        )
