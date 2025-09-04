# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
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
            entities.append(BeemAllowChargeFromGridSwitch(coordinator, serial, battery_id))
            entities.append(BeemPreventDischargeSwitch(coordinator, serial, battery_id))
            
    async_add_entities(entities)

class BaseBeemAdvancedSwitch(CoordinatorEntity[BeemCoordinator], SwitchEntity):
    """Classe de base pour les switchs du mode avancé."""

    def __init__(self, coordinator: BeemCoordinator, serial: str, battery_id: int):
        super().__init__(coordinator)
        self._serial = serial.lower()
        self._battery_id = battery_id
        self._attr_has_entity_name = True

    @property
    def _control_params(self) -> dict:
        """Raccourci pour accéder aux paramètres de contrôle."""
        battery_data = self.coordinator.data.get("batteries_by_serial", {}).get(self._serial.upper(), {})
        return battery_data.get("control_parameters", {})

    @property
    def available(self) -> bool:
        """Disponible uniquement si le coordinateur est prêt et le mode est 'avancé'."""
        return super().available and self._control_params.get("mode") == "advanced"

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._serial)}}

    async def _set_param(self, value: bool):
        """Envoie la mise à jour à l'API."""
        try:
            await set_battery_control_parameters(
                self.coordinator.token_rest, self._battery_id, {self._api_key: value}
            )
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Erreur lors de la mise à jour du paramètre %s: %s", self.entity_description.key, e)

class BeemAllowChargeFromGridSwitch(BaseBeemAdvancedSwitch):
    translation_key = "allow_charge_from_grid"
    
    def __init__(self, coordinator, serial, battery_id):
        super().__init__(coordinator, serial, battery_id)
        self.object_id = f"{serial.lower()}_allow_charge_from_grid"
        self._attr_unique_id = f"beem_{self._serial}_allow_charge_from_grid"
        self._api_key = "allowChargeFromGrid"

    @property
    def is_on(self) -> bool | None:
        return self._control_params.get(self._api_key)

    async def async_turn_on(self, **kwargs):
        await self._set_param(True)

    async def async_turn_off(self, **kwargs):
        await self._set_param(False)

class BeemPreventDischargeSwitch(BaseBeemAdvancedSwitch):
    translation_key = "prevent_discharge"

    def __init__(self, coordinator, serial, battery_id):
        super().__init__(coordinator, serial, battery_id)
        self.object_id = f"{serial.lower()}_prevent_discharge"
        self._attr_unique_id = f"beem_{self._serial}_prevent_discharge"
        self._api_key = "preventDischarge"

    @property
    def is_on(self) -> bool | None:
        return self._control_params.get(self._api_key)

    async def async_turn_on(self, **kwargs):
        await self._set_param(True)

    async def async_turn_off(self, **kwargs):
        await self._set_param(False)
