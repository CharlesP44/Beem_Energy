from __future__ import annotations
from typing import Any
import voluptuous as vol

from homeassistant import config_entries

CONF_ENABLE_LIVE_MQTT = "enable_live_mqtt"
CONF_BRAIN_SERIAL = "brain_serial"
CONF_REST_POLL_INTERVAL = "rest_poll_interval"

# Valeurs par défaut
DEFAULT_FRESHNESS_WINDOW = 120
DEFAULT_REST_POLL_INTERVAL = 120
DEFAULT_ENABLE_INTERNAL_ENERGY = True
DEFAULT_KEEPALIVE_ENABLED = True
DEFAULT_KEEPALIVE_INTERVAL = 240
DEFAULT_ENABLE_LIVE_MQTT = True


class BeemOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._entry.options

        schema = vol.Schema(
            {
                vol.Optional(
                    "freshness_window",
                    default=options.get("freshness_window", DEFAULT_FRESHNESS_WINDOW),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                vol.Optional(
                    CONF_REST_POLL_INTERVAL,
                    default=options.get(
                        CONF_REST_POLL_INTERVAL, DEFAULT_REST_POLL_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                vol.Optional(
                    "enable_internal_energy",
                    default=options.get(
                        "enable_internal_energy", DEFAULT_ENABLE_INTERNAL_ENERGY
                    ),
                ): bool,
                vol.Optional(
                    "enable_backend_keepalive",
                    default=options.get(
                        "enable_backend_keepalive", DEFAULT_KEEPALIVE_ENABLED
                    ),
                ): bool,
                vol.Optional(
                    "backend_keepalive_interval",
                    default=options.get(
                        "backend_keepalive_interval", DEFAULT_KEEPALIVE_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=120, max=1800)),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
