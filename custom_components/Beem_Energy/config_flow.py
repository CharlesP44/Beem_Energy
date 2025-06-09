from homeassistant import config_entries
import voluptuous as vol
from .const import DOMAIN
import logging
from .api import BeemApiClient
from homeassistant.core import callback
import re  # Pour valider l'email
from .storage import BeemSecureStorage  # Import du storage sécurisé

_LOGGER = logging.getLogger(__name__)

DASHBOARD_TEMPLATE = """
views:
  - title: Power Flow
    path: power-flow
    cards:
      - type: energy-distribution
        title: Flux d'énergie
        solar_power_entity: sensor.solar_power
        grid_power_entity: sensor.meter_power
        battery_power_entity: sensor.active_power
        battery_charge_entity: sensor.soc
"""

class BeemConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            email = user_input["email"].strip()
            password = user_input["password"].strip()

            if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                errors["email"] = "invalid_email"
            elif not password:
                errors["password"] = "empty_password"
            else:
                api_client = BeemApiClient(email=email, password=password, token=None)

                login_success = await api_client.login()
                if login_success:
                    try:
                        batteries = await api_client.get_batteries()
                        if batteries and isinstance(batteries, list) and "id" in batteries[0]:
                            battery_id = batteries[0]["id"]
                            token = api_client.token

                            # Stockage sécurisé du mot de passe
                            storage = BeemSecureStorage(self.hass)
                            await storage.save_password(email, password)

                            return self.async_create_entry(
                                title=email,
                                data={
                                    "email": email,
                                    "battery_id": battery_id
                                },
                                options={
                                    "token": token
                                }
                            )
                        else:
                            errors["base"] = "no_battery_found"
                    except Exception as e:
                        _LOGGER.exception("Erreur lors de la récupération des batteries : %s", e)
                        errors["base"] = "api_error"
                else:
                    errors["base"] = "auth_failed"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("email"): str,
                vol.Required("password"): str
            }),
            errors=errors
        )


class BeemOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=self.config_entry.options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
            description_placeholders={"info": "Générer le dashboard Power Flow"},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BeemOptionsFlowHandler(config_entry)
