# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BeemCoordinator
from .beem_api import set_battery_control_parameters

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    coordinator: BeemCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    entities = []
    for serial, battery_data in coordinator.data.get("batteries_by_serial", {}).items():
        if battery_id := battery_data.get("id"):
            entities.append(BeemMinSocNumber(coordinator, serial, battery_id))
            entities.append(BeemMaxSocNumber(coordinator, serial, battery_id))
            
    async_add_entities(entities)

class BaseBeemAdvancedNumber(CoordinatorEntity[BeemCoordinator], NumberEntity):
    """Classe de base pour les nombres du mode avancé."""
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: BeemCoordinator, serial: str, battery_id: int):
        super().__init__(coordinator)
        self._serial = serial.lower()
        self._battery_id = battery_id
        self._attr_has_entity_name = True

    @property
    def _control_params(self) -> dict:
        return self.coordinator.data.get("batteries_by_serial", {}).get(self._serial.upper(), {}).get("control_parameters", {})

    @property
    def available(self) -> bool:
        return super().available and self._control_params.get("mode") == "advanced"

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._serial)}}
        
    async def async_set_native_value(self, value: float) -> None:
        """Met à jour la valeur."""
        try:
            await set_battery_control_parameters(
                self.coordinator.token_rest, self._battery_id, {self._api_key: int(value)}
            )
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Erreur lors de la mise à jour du paramètre %s: %s", self._api_key, e)

class BeemMinSocNumber(BaseBeemAdvancedNumber):
    translation_key = "min_soc"
    _attr_native_min_value = 10
    _attr_native_max_value = 50
    _attr_native_step = 1

    def __init__(self, coordinator, serial, battery_id):
        super().__init__(coordinator, serial, battery_id)
        self.object_id = f"{serial.lower()}_min_soc"
        self._attr_unique_id = f"beem_{self._serial}_min_soc"
        self._api_key = "minSoc"

    @property
    def native_value(self) -> float | None:
        return self._control_params.get(self._api_key)

    # @property
    # def available(self) -> bool:
    #     """
    #     Disponible si le mode est avancé ET si le blocage de décharge est activé.
    #     """
    #     return (
    #         super().available 
    #         and self._control_params.get("mode") == "advanced"
    #         and self._control_params.get("preventDischarge", False)
    #     )

class BeemMaxSocNumber(BaseBeemAdvancedNumber):
    translation_key = "max_soc"
    _attr_native_min_value = 50
    _attr_native_max_value = 100
    _attr_native_step = 1

    def __init__(self, coordinator, serial, battery_id):
        super().__init__(coordinator, serial, battery_id)
        self.object_id = f"{serial.lower()}_max_soc"
        self._attr_unique_id = f"beem_{self._serial}_max_soc"
        self._api_key = "maxSoc"

    @property
    def native_value(self) -> float | None:
        return self._control_params.get(self._api_key)

    # @property
    # def available(self) -> bool:
    #     """Disponible si le mode est avancé ET si la charge depuis le réseau est activée."""
    #     return (
    #         super().available
    #         and self._control_params.get("mode") == "advanced"
    #         and self._control_params.get("allowChargeFromGrid", False)
    #     )
