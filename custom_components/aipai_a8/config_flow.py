"""Config flow: add a fixture by IP address."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import A8Client, A8ConnectionError, A8ProtocolError, pretty_model
from .const import CONF_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class A8ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            client = A8Client(host, async_get_clientsession(self.hass))
            try:
                _, serial = await client.get_identity()
                cfg = await client.get_config()
            except A8ConnectionError:
                errors["base"] = "cannot_connect"
            except A8ProtocolError:
                errors["base"] = "not_a8"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error probing %s", host)
                errors["base"] = "unknown"
            else:
                serial = serial or cfg.serial or host
                await self.async_set_unique_id(str(serial))
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                title = f"{pretty_model(cfg.model)} ({host})"
                return self.async_create_entry(title=title, data={CONF_HOST: host})

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={"example": "192.168.1.208"},
        )
