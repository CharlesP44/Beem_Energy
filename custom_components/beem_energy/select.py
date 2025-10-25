# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BeemCoordinator
from .beem_api import set_battery_control_parameters
from .exceptions import BeemAuthError, BeemConnectionError

_LOGGER = logging.getLogger(__name__)

BATTERY_MODES = ["auto", "pause", "advanced"]


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
