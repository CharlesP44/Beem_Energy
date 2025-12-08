# Copyright (c) 2025 Charles P44
# SPDX-License-Identifier: MIT
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

from .beem_api import try_login, get_devices
from .exceptions import BeemAuthError, BeemConnectionError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)


class BeemEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Flux de configuration de l'intégration Beem Energy."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Premier écran: saisie des identifiants."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = (user_input.get("email") or "").strip()
            password = user_input.get("password")
            try:
                # 1. Connexion / Récupération des tokens
                tokens = await try_login(email, password)

                # 2. Vérification des équipements (pour éviter l'erreur no_battery_found)
                # On récupère la liste des appareils
                devices = await get_devices(tokens["access_token"])

                batteries = devices.get("batteries", []) or []
                energy_switches = devices.get("energySwitches", []) or []
                beemboxes = devices.get("beemboxes", []) or []

                if not batteries and not energy_switches and not beemboxes:
                    errors["base"] = "no_devices_found"
                else:
                    await self.async_set_unique_id(f"beem_{tokens['user_id']}")
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"Beem Energy ({email})",
                        data={"email": email, "password": password},
                    )

            except BeemAuthError:
                errors["base"] = "invalid_auth"
            except BeemConnectionError:
                errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.exception("Erreur inattendue Beem ConfigFlow: %s", e)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
