"""Config flow for Albert Heijn."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url

from .api import AlbertHeijnApi, AlbertHeijnAuthError
from .auth import (
    AuthenticationError,
    async_refresh_token,
    create_login_session,
    exchange_code,
    remove_login_session,
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
        self._session_id: str | None = None
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
        ha_base_url = get_url(self.hass)
        session = create_login_session(ha_base_url)
        self._session_id = session.session_id
        login_url = session.login_url

        # Start background task to wait for the auth code
        self._login_task = asyncio.ensure_future(self._wait_for_login(session))

        return self.async_external_step(step_id="login", url=login_url)

    async def _wait_for_login(self, session) -> None:
        """Wait for the user to complete login in the browser."""
        try:
            code = await asyncio.wait_for(
                session.code_future, timeout=LOGIN_TIMEOUT
            )
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
            if self._session_id:
                remove_login_session(self._session_id)

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
