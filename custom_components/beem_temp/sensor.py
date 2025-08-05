# Copyright (c) 2025 CharlesP44 
# SPDX-License-Identifier: MIT
import logging
import json
from datetime import datetime, timezone, timedelta
import asyncio
import async_timeout

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send

from .const import (
    DOMAIN, SENSOR_KEY_MAP, SENSOR_DEFINITIONS, MQTT_ONLY_SENSORS,
    SOLAR_EQUIPMENT_SENSORS, BEEMBOX_SENSORS
)

_LOGGER = logging.getLogger(__name__)
SIGNAL_BEEM_BATTERY_UPDATE = "beem_battery_update"

class MqttBatteryBuffer:
    """Buffer circulaire pour chaque batterie, clé = snake_case."""
    def __init__(self):
        self._data = {}

    def update(self, key, value):
        self._data[key] = (value, datetime.now(timezone.utc))

    def get(self, key):
        return self._data.get(key, (None, None))

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    mqtt_client = hass.data[DOMAIN][entry.entry_id]["mqtt_client"]
    batteries = hass.data[DOMAIN][entry.entry_id].get("batteries", [])
    coordinator = hass.data[DOMAIN][entry.entry_id].get("coordinator")

    # --- REST battery dict {serial: battery_dict} fusionné live+config ---
    rest_batteries = {}
    if coordinator and hasattr(coordinator, "data") and "batteries_by_serial" in coordinator.data:
        for serial, bat in coordinator.data["batteries_by_serial"].items():
            rest_batteries[str(serial)] = bat
    if rest_batteries:
        _LOGGER.debug("[sensor.py] REST batteries (live+config): %s", rest_batteries)

    all_entities = []
    mqtt_buffers = {}

    for battery in batteries:
        serial = str(battery.get("serialNumber")).strip()
        mqtt_buffers[serial] = MqttBatteryBuffer()
        rest_battery = rest_batteries.get(serial, {})
        _LOGGER.debug("[sensor.py] REST DATA pour serial %s : %s", serial, rest_battery)

        # --- Capteurs MQTT only (toujours live) ou REST only ---
        for logical_key, (unit, icon) in SENSOR_DEFINITIONS.items():
            is_mqtt = logical_key in MQTT_ONLY_SENSORS
            entity = BeemMqttOrRestSensor(
                serial=serial,
                logical_key=logical_key,
                unit=unit,
                icon=icon,
                mqtt_buffer=mqtt_buffers[serial] if is_mqtt else None,
                rest_battery=rest_battery if not is_mqtt else None,
                prefer_mqtt=is_mqtt
            )
            all_entities.append(entity)

        # --- Sensors dérivés (puissances W) ---
        all_entities.append(BeemDerivedSensor(serial, "batteryPower", "charging", mqtt_buffers[serial], rest_battery))
        all_entities.append(BeemDerivedSensor(serial, "batteryPower", "discharging", mqtt_buffers[serial], rest_battery))
        all_entities.append(BeemDerivedSensor(serial, "solarPower", "production", mqtt_buffers[serial], rest_battery))
        all_entities.append(BeemDerivedSensor(serial, "meterPower", "consumption", mqtt_buffers[serial], rest_battery))
        all_entities.append(BeemDerivedSensor(serial, "meterPower", "injection", mqtt_buffers[serial], rest_battery))

        # --- Capteurs kWh auto-intégrés (basés sur derived) ---
        all_entities.append(BeemEnergySensor(hass, serial, "batteryPower", "charging"))
        all_entities.append(BeemEnergySensor(hass, serial, "batteryPower", "discharging"))
        all_entities.append(BeemEnergySensor(hass, serial, "solarPower", "production"))
        all_entities.append(BeemEnergySensor(hass, serial, "meterPower", "consumption"))
        all_entities.append(BeemEnergySensor(hass, serial, "meterPower", "injection"))

        # --- Sensor technique : mqtt_last_update (une seule entité par batterie !) ---
        all_entities.append(BeemMqttLastUpdateSensor(serial, mqtt_buffers[serial]))

    # --- Solar Equipment (REST) ---
    solar_equipments = []
    main_battery_serial = None
    if coordinator and hasattr(coordinator, "data"):
        solar_equipments = coordinator.data.get("battery", {}).get("solarEquipments", [])
        main_battery_serial = coordinator.data.get("main_battery_serial")
    if not main_battery_serial:
        main_battery_serial = "unknown"

    for idx, equipment in enumerate(solar_equipments):
        equipment_id = str(equipment.get("mpptId", f"{idx+1}"))
        for key, (unit, icon) in SOLAR_EQUIPMENT_SENSORS.items():
            if key in equipment:
                _LOGGER.debug(f"[SolarSensor] Ajout sensor: equipment_id={equipment_id} key={key}")
                all_entities.append(SolarEquipmentSensor(
                    coordinator, equipment_id, key, unit, idx, icon, main_battery_serial
                ))

    # --- BeemBox (REST) ---
    if coordinator and hasattr(coordinator, "beemboxes"):
        for box in coordinator.beemboxes:
            box_id = str(box.get("macAddress") or box.get("id") or "unknown")
            for key, (unit, icon) in BEEMBOX_SENSORS.items():
                if key in box:
                    all_entities.append(BeemBoxSensor(coordinator, box_id, key, unit, icon))

    async_add_entities(all_entities)
    _LOGGER.info("🟢 Entités Beem Energy ajoutées pour entry %s", entry.entry_id)

    # --- Superviseur pour la boucle MQTT ---
    async def supervised_mqtt_loop():
        async def subscribe_topics():
            subscribed_topics = []
            for battery in batteries:
                serial = str(battery.get("serialNumber")).strip()
                topic = f"battery/{serial}/sys/streaming"
                try:
                    async with async_timeout.timeout(10):
                        result = await mqtt_client.subscribe(topic)
                    subscribed_topics.append(topic)
                    _LOGGER.info(f"✅ Abonné MQTT battery streaming : {topic} (result={result})")
                except asyncio.TimeoutError:
                    _LOGGER.error(f"⏰ Timeout lors du subscribe MQTT pour le topic {topic}")
                except Exception as e:
                    _LOGGER.error(f"❌ Échec de subscribe MQTT pour le topic {topic} : {e}")
            _LOGGER.info(f"📋 Topics MQTT effectivement abonnés : {subscribed_topics}")

        async def handle_message(message):
            topic = str(message.topic)
            try:
                payload = json.loads(message.payload)
            except Exception:
                _LOGGER.error("Erreur de décodage JSON sur le topic %s: %s", topic, message.payload)
                return
            _LOGGER.debug("[MQTT] Reçu topic=%s payload=%s", topic, payload)
            if topic.startswith("battery/"):
                serial = str(topic.split("/")[1])
                if serial not in mqtt_buffers:
                    mqtt_buffers[serial] = MqttBatteryBuffer()
                for key, value in payload.items():
                    mqtt_buffers[serial].update(key, value)
                async_dispatcher_send(hass, f"{SIGNAL_BEEM_BATTERY_UPDATE}_{serial}")

        while True:
            try:
                await subscribe_topics()
                _LOGGER.info("Lancement de la boucle MQTT Beem.")
                messages = mqtt_client.messages
                async for message in messages:
                    try:
                        await handle_message(message)
                    except Exception as e:
                        _LOGGER.error("Exception in handle_message: %s", e)
            except asyncio.CancelledError:
                _LOGGER.info("MQTT loop cancelled proprement (unload/reload).")
                break
            except Exception as exc:
                _LOGGER.error("MQTT déconnecté ou erreur boucle (hors CancelledError): %s. Nouvelle tentative dans 10s.", exc)
                await asyncio.sleep(10)

    mqtt_task = hass.data[DOMAIN][entry.entry_id].get("mqtt_task")
    if not mqtt_task or mqtt_task.done():
        task = hass.async_create_task(supervised_mqtt_loop())
        hass.data[DOMAIN][entry.entry_id]["mqtt_task"] = task
    _LOGGER.info("MQTT loop lancé pour l'entry %s", entry.entry_id)

    _LOGGER.info("🟢 [setup_entry] Terminé pour entry %s", entry.entry_id)
    return True

def _clean_key(serial, key):
    key = key.lower()
    serial = str(serial)
    while serial in key:
        key = key.replace(serial, "")
    key = key.replace("__", "_").strip("_")
    return key

class BeemMqttOrRestSensor(SensorEntity):
    def __init__(self, serial, logical_key, unit, icon, mqtt_buffer, rest_battery, prefer_mqtt=True):
        self._serial = str(serial).strip()
        self._logical_key = logical_key
        self._unit = unit
        self._icon = icon
        self._mqtt_buffer = mqtt_buffer
        self._rest_battery = rest_battery
        self._prefer_mqtt = prefer_mqtt

        _ckey = _clean_key(self._serial, logical_key)
        self._attr_unique_id = f"beem_{self._serial}_{_ckey}"
        self._attr_name = f"{_ckey.replace('_', ' ').capitalize()}"
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_has_entity_name = True

    @property
    def native_value(self):
        if self._prefer_mqtt and self._mqtt_buffer:
            mqtt_key = None
            for k, v in SENSOR_KEY_MAP.items():
                if v == self._logical_key:
                    mqtt_key = k
                    break
            if mqtt_key:
                value, _ = self._mqtt_buffer.get(mqtt_key)
                if value is not None:
                    return value
        if self._rest_battery:
            return self._rest_battery.get(self._logical_key)
        return None

    @property
    def device_info(self):
        serial = str(self._serial).strip()
        return {
            "identifiers": {(DOMAIN, serial)},
            "name": f"Batterie Beem {serial}",
            "manufacturer": "Beem Energy",
            "model": "Beem Battery",
        }

class BeemDerivedSensor(SensorEntity):
    def __init__(self, serial, source_key, mode, mqtt_buffer, rest_battery):
        self._serial = str(serial).strip()
        self._source_key = source_key
        self._mode = mode
        self._mqtt_buffer = mqtt_buffer
        self._rest_battery = rest_battery

        _ckey = _clean_key(self._serial, f"{source_key}_{mode}")
        self._attr_unique_id = f"beem_{self._serial}_{_ckey}"
        self._attr_name = f"{_ckey.replace('_', ' ').capitalize()}"
        self._attr_native_unit_of_measurement = "W"
        self._attr_icon = "mdi:transmission-tower-export" if mode in ("discharging", "injection") else "mdi:battery-charging-100"
        self._attr_device_class = "power"
        self._attr_state_class = "measurement"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self._unsub_dispatcher = None
        self._unsub_timer = None

    async def async_added_to_hass(self):
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass,
            f"{SIGNAL_BEEM_BATTERY_UPDATE}_{self._serial}",
            self.async_write_ha_state
        )
        async def _on_timer(now):
            self.async_write_ha_state()
        self._unsub_timer = async_track_time_interval(
            self.hass,
            _on_timer,
            timedelta(seconds=60)
        )

    async def async_will_remove_from_hass(self):
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    @property
    def native_value(self):
        mqtt_key = None
        for k, v in SENSOR_KEY_MAP.items():
            if v == self._source_key:
                mqtt_key = k
                break
        if mqtt_key:
            mqtt_value, _ = self._mqtt_buffer.get(mqtt_key)
        else:
            mqtt_value, _ = self._mqtt_buffer.get(self._source_key.lower())
        value = mqtt_value
        if value is None and self._rest_battery:
            value = self._rest_battery.get(self._source_key)
        if value is None:
            _LOGGER.debug("[BeemDerivedSensor] %s (%s): Aucune valeur reçue, on retourne 0", self._mode, self._serial)
            return None

        try:
            value = float(value)
        except Exception:
            _LOGGER.warning("[BeemDerivedSensor] %s (%s): Conversion en float impossible pour %s", self._mode, self._serial, value)
            return None

        _LOGGER.debug("[BeemDerivedSensor] %s (%s): valeur brute=%s", self._mode, self._serial, value)

        if self._mode == "charging":
            result = value if value > 0 else 0.0
        elif self._mode == "discharging":
            result = abs(value) if value < 0 else 0.0
        elif self._mode == "production":
            result = value if value > 0 else 0.0
        elif self._mode == "consumption":
            result = abs(value) if value < 0 else 0.0
        elif self._mode == "injection":
            result = value if value > 0 else 0.0
        else:
            result = 0.0

        _LOGGER.debug("[BeemDerivedSensor] %s (%s): résultat sensor=%s", self._mode, self._serial, result)
        return result

    @property
    def device_info(self):
        serial = str(self._serial).strip()
        return {
            "identifiers": {(DOMAIN, serial)},
            "name": f"Batterie Beem {serial}",
            "manufacturer": "Beem Energy",
            "model": "Beem Battery",
        }

class BeemEnergySensor(SensorEntity, RestoreEntity):
    def __init__(self, hass, serial, source_key, mode):
        self.hass = hass
        self._serial = str(serial).strip()
        self._source_key = source_key
        self._mode = mode

        _ckey = _clean_key(self._serial, f"{source_key}_{mode}_kwh")
        self._attr_unique_id = f"beem_{self._serial}_{_ckey}"
        self._attr_name = f"{_ckey.replace('_', ' ').capitalize()}"
        self._attr_native_unit_of_measurement = "kWh"
        self._attr_icon = "mdi:counter"
        self._attr_device_class = "energy"
        self._attr_state_class = "total_increasing"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

        self._last_updated = None
        self._integrated_value = 0.0
        self._unsub_timer = None

    async def async_added_to_hass(self):
        self._last_updated = datetime.now(timezone.utc)
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._integrated_value = float(last_state.state)
            except Exception:
                self._integrated_value = 0.0

        self._unsub_timer = async_track_time_interval(self.hass, self._handle_update, timedelta(seconds=60))

    async def async_will_remove_from_hass(self):
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    async def _handle_update(self, now):
        power_entity_id = f"sensor.batterie_beem_{self._serial.lower()}_{_clean_key(self._serial, f'{self._source_key}_{self._mode}')}"
        entity_ids = self.hass.states.async_entity_ids("sensor")
        _LOGGER.debug(f"[BeemEnergySensor] Intégration via {power_entity_id} ; sensors connus: {list(entity_ids)}")
        state = self.hass.states.get(power_entity_id)
        if state is None or state.state in (None, "unknown", "unavailable"):
            return
        try:
            power_watts = abs(float(state.state))
        except (ValueError, TypeError):
            return
        now_dt = datetime.now(timezone.utc)
        if self._last_updated is not None:
            elapsed_hours = (now_dt - self._last_updated).total_seconds() / 3600
            self._integrated_value += (power_watts * elapsed_hours) / 1000.0
        self._last_updated = now_dt
        self.async_write_ha_state()

    @property
    def native_value(self):
        return round(self._integrated_value, 3)

    @property
    def device_info(self):
        serial = str(self._serial).strip()
        return {
            "identifiers": {(DOMAIN, serial)},
            "name": f"Batterie Beem {serial}",
            "manufacturer": "Beem Energy",
            "model": "Beem Battery",
        }

class BeemMqttLastUpdateSensor(SensorEntity):
    def __init__(self, serial, mqtt_buffer):
        self._serial = str(serial).strip()
        self._mqtt_buffer = mqtt_buffer
        self._attr_unique_id = f"beem_{self._serial}_mqtt_last_update"
        self._attr_name = f"Mqtt last update"
        self._attr_native_unit_of_measurement = None
        self._attr_icon = "mdi:clock-outline"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

    @property
    def native_value(self):
        if not self._mqtt_buffer._data:
            return None
        last_ts = max(ts for val, ts in self._mqtt_buffer._data.values() if ts)
        return last_ts.isoformat()

    @property
    def device_info(self):
        serial = str(self._serial).strip()
        return {
            "identifiers": {(DOMAIN, serial)},
            "name": f"Batterie Beem {serial}",
            "manufacturer": "Beem Energy",
            "model": "Beem Battery",
        }

class SolarEquipmentSensor(SensorEntity):
    def __init__(self, coordinator, equipment_id, sensor_key, unit, equipment_index, icon, main_battery_serial):
        self.coordinator = coordinator
        self._equipment_id = str(equipment_id)
        self._sensor_key = sensor_key
        self._unit = unit
        self._equipment_index = equipment_index
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._main_battery_serial = str(main_battery_serial).strip()

        self._attr_unique_id = f"beem_solar_{self._main_battery_serial}_{self._equipment_id}_{sensor_key.lower()}"
        self._attr_name = f"{sensor_key.replace('_', ' ').capitalize()}"
        self._attr_has_entity_name = True

    @property
    def native_value(self):
        try:
            equipment = None
            if hasattr(self.coordinator, "data"):
                equipments = self.coordinator.data.get("battery", {}).get("solarEquipments", [])
                if len(equipments) > self._equipment_index:
                    equipment = equipments[self._equipment_index]
            if equipment is None:
                return None
            return equipment.get(self._sensor_key)
        except Exception:
            return None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"solar_{self._main_battery_serial}_{self._equipment_id}")},
            "name": f"Beem Solar Equipment {self._main_battery_serial} - {self._equipment_id}",
            "manufacturer": "Beem Energy",
            "model": "MPPT / Solar Equipment",
            "via_device": (DOMAIN, self._main_battery_serial),
        }

class BeemBoxSensor(SensorEntity):
    def __init__(self, coordinator, box_id, sensor_key, unit, icon):
        self.coordinator = coordinator
        self._box_id = str(box_id)
        self._sensor_key = sensor_key
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_unique_id = f"beembox_{self._box_id}_{sensor_key}".lower()
        self._attr_name = f"{sensor_key.replace('_', ' ').capitalize()}"
        self._attr_has_entity_name = True

    @property
    def native_value(self):
        for box in self.coordinator.beemboxes:
            if str(box.get("macAddress") or box.get("id")) == self._box_id:
                return box.get(self._sensor_key)
        return None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"beembox_{self._box_id}")},
            "name": f"BeemBox {self._box_id}",
            "manufacturer": "Beem",
            "model": "BeemOn / PnP",
        }

# --- Gérer le stop proprement pour la tâche MQTT ---
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info(">>> async_unload_entry called for entry: %s", entry.entry_id)

    unload_ok = True

    # Arrêt de la tâche MQTT si elle existe
    try:
        task = hass.data[DOMAIN][entry.entry_id].get("mqtt_task")
        if task:
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5)
                _LOGGER.info("Tâche MQTT arrêtée proprement pour entry: %s", entry.entry_id)
            except asyncio.TimeoutError:
                _LOGGER.warning("Timeout lors de l'arrêt de la tâche MQTT pour entry: %s", entry.entry_id)
            except asyncio.CancelledError:
                _LOGGER.info("Tâche MQTT annulée pour entry: %s", entry.entry_id)
            except Exception as exc:
                _LOGGER.error("Erreur inattendue lors du cancel de la tâche MQTT: %s", exc)
                unload_ok = False
    except Exception as exc:
        _LOGGER.error("Erreur lors du déchargement de la tâche MQTT: %s", exc)
        unload_ok = False

    try:
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN].pop(entry.entry_id)
            _LOGGER.info("Entrée %s supprimée de hass.data[%s]", entry.entry_id, DOMAIN)
    except Exception as exc:
        _LOGGER.error("Erreur lors de la suppression de hass.data: %s", exc)
        unload_ok = False

    _LOGGER.info("<<< async_unload_entry terminé pour entry: %s (OK=%s)", entry.entry_id, unload_ok)
    return unload_ok
