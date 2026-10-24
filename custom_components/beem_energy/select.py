# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BeemCoordinator
from .beem_api import set_battery_control_parameters, set_battery_led_brightness
from .exceptions import BeemAuthError, BeemConnectionError

_LOGGER = logging.getLogger(__name__)

BATTERY_MODES = ["auto", "pause", "advanced"]

LED_BRIGHTNESS_FEATURE = "led_brightness_control"
LED_BRIGHTNESS_OPTIONS = ["default", "low"]


def _battery_supports_led_brightness(battery_data: dict) -> bool:
    """True si l'API déclare la fonctionnalité de contrôle de luminosité LED."""
    features = battery_data.get("features") or []
    return any(
        isinstance(feature, dict) and feature.get("name") == LED_BRIGHTNESS_FEATURE
        for feature in features
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les entités select à partir d'une entrée de configuration."""
    coordinator: BeemCoordinator = hass.data[DOMAIN][entry.entry_id].get("coordinator")

    if not coordinator or not coordinator.data:
        _LOGGER.warning(
            "Coordinateur Beem non prêt, les entités select ne peuvent être ajoutées."
        )
        return

    entities = []
    for serial, battery_data in coordinator.data.get("batteries_by_serial", {}).items():
        if battery_id := battery_data.get("id"):
            entities.append(BeemBatteryModeSelect(coordinator, serial, battery_id))

            entities.append(BeemChargePowerSelect(coordinator, serial, battery_id))

            # La luminosité LED n'existe que sur certaines batteries/firmwares :
            # l'entité n'est créée que si l'API annonce la fonctionnalité.
            if _battery_supports_led_brightness(battery_data):
                entities.append(
                    BeemLedBrightnessSelect(coordinator, serial, battery_id)
                )
            else:
                _LOGGER.debug(
                    "Batterie %s : fonctionnalité '%s' absente, select LED non créé.",
                    serial,
                    LED_BRIGHTNESS_FEATURE,
                )

    async_add_entities(entities)


class BeemBatteryModeSelect(CoordinatorEntity[BeemCoordinator], SelectEntity):
    """Représente l'entité pour changer le mode de la batterie Beem."""

    _attr_has_entity_name = True
    translation_key = "battery_mode"

    def __init__(self, coordinator: BeemCoordinator, serial: str, battery_id: int):
        """Initialise l'entité select."""
        super().__init__(coordinator)
        self._serial = serial.lower()
        self._battery_id = battery_id

        self._attr_unique_id = f"beem_{self._serial}_mode"
        self._attr_icon = "mdi:cog-transfer-outline"
        self._attr_options = BATTERY_MODES
        self._attr_has_entity_name = True

    @property
    def _battery_data(self) -> dict | None:
        """Raccourci pour accéder aux données de cette batterie."""
        return self.coordinator.data.get("batteries_by_serial", {}).get(
            self._serial.upper()
        )

    @property
    def available(self) -> bool:
        """
        L'entité est disponible uniquement si le coordinateur est disponible
        ET si l'API nous autorise à changer le mode.
        """
        if not super().available or not self._battery_data:
            return False

        control_params = self._battery_data.get("control_parameters", {})
        return control_params.get("canChangeMode", False)

    @property
    def current_option(self) -> str | None:
        """Retourne l'option actuellement sélectionnée depuis les control_parameters."""
        if not self._battery_data:
            return None

        control_params = self._battery_data.get("control_parameters", {})
        mode = str(control_params.get("mode", "")).lower()

        return mode if mode in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Appelé lorsque l'utilisateur sélectionne une nouvelle option."""
        _LOGGER.info(
            "Demande de changement de mode pour la batterie %s vers '%s'",
            self._serial,
            option,
        )

        token_rest = self.coordinator.token_rest

        try:
            await set_battery_control_parameters(
                token_rest, self._battery_id, {"mode": option}
            )
        except (BeemAuthError, BeemConnectionError) as e:
            _LOGGER.error(
                "Erreur de connexion ou d'authentification lors du changement de mode : %s",
                e,
            )
        except Exception as e:
            _LOGGER.error("Erreur inattendue lors du changement de mode : %s", e)

        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        """Associe cette entité à l'appareil batterie EXISTANT."""
        return {
            "identifiers": {(DOMAIN, self._serial)},
        }


class BeemChargePowerSelect(CoordinatorEntity[BeemCoordinator], SelectEntity):
    translation_key = "charge_power"
    _attr_options = ["500", "1000", "2500", "5000"]

    def __init__(self, coordinator: BeemCoordinator, serial: str, battery_id: int):
        super().__init__(coordinator)
        self._serial = serial.lower()
        self._battery_id = battery_id
        self.object_id = f"{serial.lower()}_charge_power"
        self._attr_unique_id = f"beem_{self._serial}_charge_power"
        self._attr_has_entity_name = True

    @property
    def _control_params(self) -> dict:
        return (
            self.coordinator.data.get("batteries_by_serial", {})
            .get(self._serial.upper(), {})
            .get("control_parameters", {})
        )

    @property
    def available(self) -> bool:
        return super().available and self._control_params.get("mode") == "advanced"

    @property
    def current_option(self) -> str | None:
        power = self._control_params.get("chargeFromGridMaxPower")
        return str(power) if power is not None else None

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._serial)}}

    async def async_select_option(self, option: str) -> None:
        try:
            await set_battery_control_parameters(
                self.coordinator.token_rest,
                self._battery_id,
                {"chargeFromGridMaxPower": int(option)},
            )
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Erreur lors du changement de la puissance de charge : %s", e)


class BeemLedBrightnessSelect(CoordinatorEntity[BeemCoordinator], SelectEntity):
    """Luminosité des LED de la batterie (default / low).

    Créée uniquement pour les batteries exposant la feature 'led_brightness_control'.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "led_brightness"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:led-on"
    _attr_options = LED_BRIGHTNESS_OPTIONS

    def __init__(self, coordinator: BeemCoordinator, serial: str, battery_id: int):
        super().__init__(coordinator)
        self._serial = serial.lower()
        self._battery_id = battery_id
        self._attr_unique_id = f"beem_{self._serial}_led_brightness"

    @property
    def _battery_data(self) -> dict | None:
        return self.coordinator.data.get("batteries_by_serial", {}).get(
            self._serial.upper()
        )

    @property
    def available(self) -> bool:
        """Disponible si le coordinateur répond et si la feature est toujours annoncée."""
        data = self._battery_data
        return (
            super().available
            and data is not None
            and _battery_supports_led_brightness(data)
        )

    @property
    def current_option(self) -> str | None:
        if not self._battery_data:
            return None
        value = str(self._battery_data.get("ledBrightness") or "").lower()
        return value if value in self.options else None

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._serial)}}

    async def async_select_option(self, option: str) -> None:
        """Envoie la nouvelle luminosité (l'API met ~3 s à répondre)."""
        _LOGGER.info(
            "Demande de changement de luminosité LED pour la batterie %s vers '%s'",
            self._serial,
            option,
        )
        try:
            await set_battery_led_brightness(
                self.coordinator.token_rest, self._battery_id, option
            )
        except (BeemAuthError, BeemConnectionError) as e:
            raise HomeAssistantError(
                f"Impossible de changer la luminosité LED : {e}"
            ) from e
        except Exception as e:
            raise HomeAssistantError(
                f"Erreur lors du changement de la luminosité LED : {e}"
            ) from e

        # Mise à jour optimiste, puis rafraîchissement réel depuis l'API.
        if self._battery_data is not None:
            self._battery_data["ledBrightness"] = option
            self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
