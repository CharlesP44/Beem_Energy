# ... (imports inchangés)
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import EntityCategory  # ✅ Correction ici

from .const import DOMAIN

# Capteurs classiques sur la batterie avec icônes
SENSOR_DEFINITIONS = {
    "batteryPower": ("W", "mdi:home-battery-outline"),
    "meterPower": ("W", "mdi:flash"),
    "solarPower": ("W", "mdi:solar-power"),
    "activePower": ("W", "mdi:power"),
    "soc": ("%", "mdi:battery-charging-60"),
    "workingModeLabel": (None, "mdi:cog-outline"),
    "lastKnownMeasureDate": (None, "mdi:calendar-clock"),
    "numberOfCycles": (None, "mdi:cog-clockwise"),
    "numberOfModules": (None, "mdi:battery-high"),
    "globalSoh": ("%", "mdi:battery-heart-outline"),
    "capacityInKwh": ("kWh", "mdi:home-battery-outline"),
    "maxPower": ("W", "mdi:speedometer"),
    "isBatteryWorkingModeOk": (None, "mdi:check-circle"),
}

# Clés attendues dans solarEquipments
SOLAR_EQUIPMENT_SENSORS = {
    "mpptId": (None, "mdi:identifier"),
    "orientation": ("°", "mdi:compass-outline"),
    "tilt": ("°", "mdi:sun-angle-outline"),
    "peakPower": ("W", "mdi:solar-power"),
    "solarPanelsInParallel": (None, "mdi:equal"),
    "solarPanelsInSeries": (None, "mdi:align-vertical-bottom"),
}

# Capteurs pour les BeemBox (PnP)
BEEMBOX_SENSORS = {
    "name": (None, "mdi:label"),
    "serialNumber": (None, "mdi:barcode"),
    "power": ("W", "mdi:solar-power"),
    "wattHour": ("Wh", "mdi:counter"),
    "totalDay": ("Wh", "mdi:calendar-today"),
    "totalMonth": ("Wh", "mdi:calendar-month"),
    "lastDbm": ("dBm", "mdi:wifi"),
    "lastAlive": (None, "mdi:clock-check"),
    "lastProduction": (None, "mdi:clock-outline"),
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    battery_id = entry.data.get("battery_id")  # peut être None si uniquement beembox

    sensors = []

    # Capteurs batterie standards
    if battery_id and coordinator.data.get("battery"):
        for sensor_key, (unit, icon) in SENSOR_DEFINITIONS.items():
            sensors.append(BeemSensor(coordinator, sensor_key, battery_id, unit, icon))

        # 🔧 Capteurs dérivés pour l'intégration Energy
        sensors.append(BeemDerivedSensor(coordinator, battery_id, "batteryPower", "charging"))
        sensors.append(BeemDerivedSensor(coordinator, battery_id, "batteryPower", "discharging"))
        sensors.append(BeemDerivedSensor(coordinator, battery_id, "meterPower", "meter_pos"))
        sensors.append(BeemDerivedSensor(coordinator, battery_id, "meterPower", "meter_neg"))

        # Capteurs intégrés d'énergie (kWh) - remplacement de platform: integration
        sensors.append(BeemEnergySensor(hass, coordinator, battery_id, "batteryPower", "Battery Energy Charging (kWh)"))
        sensors.append(BeemEnergySensor(hass, coordinator, battery_id, "batteryPower", "Battery Energy Discharging (kWh)"))
        sensors.append(BeemEnergySensor(hass, coordinator, battery_id, "solarPower", "Battery Solar Energy (kWh)"))
        sensors.append(BeemEnergySensor(hass, coordinator, battery_id, "meterPower", "Meter Power Positive (kWh)"))
        sensors.append(BeemEnergySensor(hass, coordinator, battery_id, "meterPower", "Meter Power Negative (kWh)"))

        # Capteurs pour chaque équipement solaire
        for idx, equipment in enumerate(coordinator.solar_equipments):
            equipment_id = equipment.get("mpptId", f"solar_{idx}")
            for key, (unit, icon) in SOLAR_EQUIPMENT_SENSORS.items():
                if key in equipment:
                    sensors.append(SolarEquipmentSensor(coordinator, equipment_id, key, unit, idx, icon))

    # Capteurs BeemBox (PnP)
    for box in coordinator.beemboxes:
        box_id = box.get("macAddress") or box.get("id") or "unknown"
        for key, (unit, icon) in BEEMBOX_SENSORS.items():
            if key in box:
                sensors.append(BeemBoxSensor(coordinator, box_id, key, unit, icon))

    async_add_entities(sensors)


class BeemSensor(SensorEntity):
    def __init__(self, coordinator, sensor_key, battery_id, unit, icon):
        self.coordinator = coordinator
        self._sensor_key = sensor_key
        self._battery_id = battery_id
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

        self._attr_unique_id = f"{battery_id}_{sensor_key}"
        self._attr_name = sensor_key
        self._attr_has_entity_name = True

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def native_value(self):
        battery_data = self.coordinator.data.get("battery", {})
        return battery_data.get(self._sensor_key)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self._battery_id))},
            "name": "Beem Battery",
            "manufacturer": "Beem",
            "model": "Beem Battery",
            "configuration_url": "https://beem.energy/",
        }

    async def async_added_to_hass(self):
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))


class SolarEquipmentSensor(SensorEntity):
    def __init__(self, coordinator, equipment_id, sensor_key, unit, equipment_index, icon):
        self.coordinator = coordinator
        self._equipment_id = equipment_id
        self._sensor_key = sensor_key
        self._unit = unit
        self._equipment_index = equipment_index
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

        self._attr_unique_id = f"solar_{equipment_id}_{sensor_key}"
        self._attr_name = f"Solar Equipment {equipment_id} {sensor_key}"
        self._attr_has_entity_name = True

    @property
    def available(self):
        return (
            self.coordinator.last_update_success
            and len(self.coordinator.solar_equipments) > self._equipment_index
        )

    @property
    def native_value(self):
        try:
            equipment = self.coordinator.solar_equipments[self._equipment_index]
            return equipment.get(self._sensor_key)
        except IndexError:
            return None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"solar_{self._equipment_id}")},
            "name": f"Beem Solar Equipment {self._equipment_id}",
            "manufacturer": "Beem",
            "model": "Solar Equipment",
            "configuration_url": "https://beem.energy/",
        }

    async def async_added_to_hass(self):
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))


class BeemBoxSensor(SensorEntity):
    def __init__(self, coordinator, box_id, sensor_key, unit, icon):
        self.coordinator = coordinator
        self._box_id = box_id
        self._sensor_key = sensor_key
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

        self._attr_unique_id = f"beembox_{box_id}_{sensor_key}"
        self._attr_name = f"BeemBox {box_id} {sensor_key}"
        self._attr_has_entity_name = True

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def native_value(self):
        for box in self.coordinator.beemboxes:
            if (box.get("macAddress") or box.get("id")) == self._box_id:
                return box.get(self._sensor_key)
        return None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"beembox_{self._box_id}")},
            "name": f"BeemBox {self._box_id}",
            "manufacturer": "Beem",
            "model": "BeemOn / PnP",
            "configuration_url": "https://beem.energy/",
        }

    async def async_added_to_hass(self):
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))


class BeemDerivedSensor(SensorEntity):
    """Sensor dérivé basé sur une autre valeur de capteur."""

    def __init__(self, coordinator, battery_id, source_key, mode):
        self.coordinator = coordinator
        self._battery_id = battery_id
        self._source_key = source_key
        self._mode = mode  # "charging", "discharging", "meter_pos", "meter_neg"

        self._attr_device_class = "power"
        self._attr_state_class = "measurement"
        self._attr_native_unit_of_measurement = "W"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC  # ✅ Correction ici

        self._attr_unique_id = f"{battery_id}_{source_key}_{mode}"
        self._attr_name = f"{source_key}_{mode}"

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def native_value(self):
        value = self.coordinator.data.get("battery", {}).get(self._source_key)
        if value is None:
            return None

        try:
            val = float(value)
        except (ValueError, TypeError):
            return None

        if self._mode == "charging":
            return val if val > 0 else 0
        elif self._mode == "discharging":
            return -val if val < 0 else 0
        elif self._mode == "meter_pos":
            return -val if val < 0 else 0
        elif self._mode == "meter_neg":
            return val if val >= 0 else 0
        return None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self._battery_id))},
            "name": "Beem Battery",
            "manufacturer": "Beem",
            "model": "Beem Battery",
            "configuration_url": "https://beem.energy/",
        }

    async def async_added_to_hass(self):
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

import voluptuous as vol
from datetime import timedelta

class BeemEnergySensor(SensorEntity):
    """Capteur d'énergie basé sur une source de puissance intégrée."""

    def __init__(self, hass, coordinator, battery_id, source_entity_id, name):
        self.hass = hass
        self.coordinator = coordinator
        self._battery_id = battery_id
        self._source_entity_id = source_entity_id
        self._attr_name = name
        self._attr_unique_id = f"{battery_id}_{name.lower().replace(' ', '_')}"
        self._attr_native_unit_of_measurement = "kWh"
        self._attr_state_class = "total_increasing"
        self._attr_device_class = "energy"

        self._last_value = None
        self._last_updated = None
        self._integrated_value = 0

    async def async_added_to_hass(self):
        self._last_updated = self.coordinator.last_update_success_time or self.hass.helpers.event.dt_util.utcnow()
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    def _handle_coordinator_update(self):
        power_watts = self.coordinator.data.get("battery", {}).get(self._source_entity_id)
        if power_watts is None:
            return

        now = self.hass.helpers.event.dt_util.utcnow()
        if self._last_updated is not None:
            elapsed_hours = (now - self._last_updated).total_seconds() / 3600
            try:
                power_float = float(power_watts)
                # Intégration (Wh -> kWh)
                self._integrated_value += (power_float * elapsed_hours) / 1000
            except Exception:
                pass

        self._last_updated = now
        self.async_write_ha_state()

    @property
    def native_value(self):
        return round(self._integrated_value, 2)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self._battery_id))},
            "name": "Beem Battery",
            "manufacturer": "Beem",
            "model": "Beem Battery",
            "configuration_url": "https://beem.energy/",
        }
