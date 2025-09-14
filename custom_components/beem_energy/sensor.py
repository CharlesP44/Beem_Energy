# Copyright (c) 2025 Charles P44
# SPDX-License-Identifier: MIT
import logging
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
import asyncio
import uuid
import functools

from homeassistant.components import mqtt as ha_mqtt
from homeassistant.core import CoreState

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import UnitOfPower, UnitOfEnergy, EVENT_HOMEASSISTANT_STARTED
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers import entity_registry as er
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from .const import (
    DOMAIN,
    SENSOR_DEFINITIONS,
    MQTT_ONLY_SENSORS,
    SOLAR_EQUIPMENT_SENSORS,
    ENERGYSWITCH_SENSORS,
    SENSOR_KEY_MAP,
    ENABLE_ES_POLLING,
    # BASE_URL,
)

_LOGGER = logging.getLogger(__name__)
SIGNAL_BEEM_BATTERY_UPDATE = "beem_battery_update"
SIGNAL_BEEM_ES_UPDATE = "beem_es_update"

DEFAULT_EM1DATA_KEYS = [
    "total_act_energy", "total_act_ret_energy",
    "lag_react_energy", "lead_react_energy",
    "max_act_power", "min_act_power",
    "max_aprt_power", "min_aprt_power",
    "max_voltage", "min_voltage", "avg_voltage",
    "max_current", "min_current", "avg_current",
]

REST_TO_SNAKE = {
    "solarPower": "solar_power",
    "inverterPower": "inverter_power",
    "batteryPower": "battery_power",
    "meterPower": "grid_power",
    "soc": "soc",
    "mppt1Power": "mppt1_power",
    "mppt2Power": "mppt2_power",
    "mppt3Power": "mppt3_power",
    "date": "date",
    "workingModeLabel": "working_mode_label",
    "workingModelabel": "working_mode_label",
    "numberOfCycles": "number_of_cycles",
    "numberOfModules": "number_of_modules",
    "isBatteryWorkingModeOk": "is_battery_working_mode_ok",
    "isBatteryInBackupMode": "is_battery_in_backup_mode",
}

def _serial_for_uid(s: Optional[str]) -> str:
    """Forme canonique pour unique_id / clés internes: minuscule."""
    return "" if s is None else str(s).strip().lower()

def _serial_for_topic(s: Optional[str]) -> str:
    """Forme exacte pour les topics Cloud Beem: MAJUSCULE."""
    return "" if s is None else str(s).strip().upper()

def _norm_serial(s: Optional[str]) -> str:
    return _serial_for_uid(s)

def _clean_key(serial, key):
    key = str(key).lower()
    serial = str(serial)
    while serial in key:
        key = key.replace(serial, "")
    return key.replace("__", "_").strip("_")

def _camel_to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", str(name))
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.replace("__", "_").lower()

def _snake_to_camel(s: str) -> str:
    parts = str(s).split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])

def _decode_payload_bytes(b):
    try:
        return json.loads(b)
    except Exception:
        try:
            return b.decode() if isinstance(b, (bytes, bytearray)) else str(b)
        except Exception:
            return repr(b)

def _to_float(x):
    try:
        v = float(x)
        if not (v == v):
            return None
        if v in (float("inf"), float("-inf")):
            return None
        return v
    except Exception:
        return None

def _parse_payload_dt(value):
    if value is None:
        return None, False
    try:
        s = str(value)
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc), True
        if "T" not in s and "." not in s and "+" not in s and "Z" not in s:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc)
        return dt, True
    except Exception:
        return None, False

class MqttBatteryBuffer:
    def __init__(self, availability_window: int = 120):
        self._data: Dict[str, tuple[Any, datetime]] = {}
        self._availability_window = int(availability_window)

    def update(self, key, value):
        self._data[str(key)] = (value, datetime.now(timezone.utc))

    def get(self, key):
        return self._data.get(str(key), (None, None))

    def last_ts(self):
        if not self._data:
            return None
        ts_vals = [ts for _, ts in self._data.values() if ts]
        return max(ts_vals) if ts_vals else None

    def is_fresh(self, now: datetime | None = None) -> bool:
        ts = self.last_ts()
        if not ts:
            return False
        now = now or datetime.now(timezone.utc)
        return (now - ts).total_seconds() <= self._availability_window

_CAMEL_SPECIAL = {
    "meterPower": "grid_power",
    "batteryPower": "battery_power",
    "solarPower": "solar_power",
    "inverterPower": "inverter_power",
    "mppt1Power": "mppt1_power",
    "mppt2Power": "mppt2_power",
    "mppt3Power": "mppt3_power",
    "soc": "soc",
}

def _candidate_keys_for_mqtt(logical_key: str):
    cands = []
    lk = str(logical_key)
    try:
        for mqtt_key, mapped in SENSOR_KEY_MAP.items():
            if mapped == lk and mqtt_key not in cands:
                cands.append(mqtt_key)
    except Exception:
        pass
    sp = _CAMEL_SPECIAL.get(lk)
    if sp and sp not in cands:
        cands.append(sp)
    for k in (lk, lk.lower()):
        if k not in cands:
            cands.append(k)
    snake = _camel_to_snake(lk)
    for k in (snake, snake.replace("_", "")):
        if k not in cands:
            cands.append(k)
    camel = _snake_to_camel(snake)
    for k in (camel, camel.lower()):
        if k not in cands:
            cands.append(k)
    alias = {
        "batteryPower": ["battery_power", "batterypower"],
        "solarPower": ["solar_power", "solarpower"],
        "inverterPower": ["inverter_power", "inverterpower"],
        "meterPower": ["meter_power", "meterpower", "grid_power", "gridpower"],
        "mppt1Power": ["mppt1_power", "mppt1power"],
        "mppt2Power": ["mppt2_power", "mppt2power"],
        "mppt3Power": ["mppt3_power", "mppt3power"],
        "soc": ["soc"],
    }.get(lk, [])
    for k in alias:
        if k not in cands:
            cands.append(k)
    return cands

def _is_mqtt_only_key(k: str) -> bool:
    variants = {k, k.lower(), _camel_to_snake(k), _camel_to_snake(k).replace("_", "")}
    return any(v in MQTT_ONLY_SENSORS for v in variants)

def _candidate_keys_for_rest(logical_key: str):
    lk = str(logical_key)
    cands: list[str] = []
    def add(x: str):
        if x and x not in cands:
            cands.append(x)
    add(lk)
    snake = _camel_to_snake(lk)
    camel = _snake_to_camel(snake)
    add(snake)
    add(camel)
    for rest_key, snake_key in REST_TO_SNAKE.items():
        if rest_key == lk or snake_key == snake:
            add(rest_key)
            add(snake_key)
    if lk.lower() == "workingmodelabel":
        add("workingModeLabel")
    return cands

_ES_ALIAS_MAP: Dict[str, str] = {}
def _init_es_alias_map():
    global _ES_ALIAS_MAP
    _ES_ALIAS_MAP = {}
    try:
        for key_canon, meta in ENERGYSWITCH_SENSORS.items():
            _ES_ALIAS_MAP[str(key_canon).lower()] = str(key_canon)
            for a in meta.get("aliases", []):
                _ES_ALIAS_MAP[str(a).lower()] = str(key_canon)
    except Exception:
        pass
_init_es_alias_map()

_ES_SYNONYMS_READ: Dict[str, list[str]] = {
    "power": ["power", "act_power"],
    "apparent_power": ["apparent_power", "aprt_power"],
    "voltage": ["voltage", "avg_voltage"],
    "current": ["current", "avg_current"],
    "freq": ["freq", "frequency"],
    "pf": ["pf", "powerfactor"],
    "energy_active_total": ["energy_active_total", "total_act_energy"],
    "energy_active_returned_total": ["energy_active_returned_total", "total_act_ret_energy"],
    "energy_reactive_lag": ["energy_reactive_lag", "lag_react_energy"],
    "energy_reactive_lead": ["energy_reactive_lead", "lead_react_energy"],
    "act_power_max": ["act_power_max", "max_act_power"],
    "act_power_min": ["act_power_min", "min_act_power"],
    "apparent_power_max": ["apparent_power_max", "max_aprt_power"],
    "apparent_power_min": ["apparent_power_min", "min_aprt_power"],
    "voltage_max": ["voltage_max", "max_voltage"],
    "voltage_min": ["voltage_min", "min_voltage"],
}

def _es_candidate_keys_for_read(logical_key: str) -> list[str]:
    """Retourne les clés possibles pour une entité ES donnée (canon + alias + synonymes)."""
    lk = str(logical_key).lower().replace("-", "_").strip("_")
    canon = _ES_ALIAS_MAP.get(lk, lk)
    cands: list[str] = []
    def add(k: str):
        k2 = str(k).lower().replace("-", "_").strip("_")
        if k2 not in cands:
            cands.append(k2)
    add(lk)
    add(canon)
    for k in _ES_SYNONYMS_READ.get(canon, []):
        add(k)
    return cands

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id].setdefault("brain_state", {})
    hass.data[DOMAIN][entry.entry_id].setdefault("mqtt_unsubs", [])
    hass.data[DOMAIN][entry.entry_id].setdefault("ha_mqtt_subscribed", set())
    hass.data[DOMAIN][entry.entry_id]["cloud_mqtt_connected"] = False

    avail_window = int(entry.options.get("freshness_window", 120))

    mqtt_client = hass.data[DOMAIN][entry.entry_id].get("mqtt_client")
    batteries = hass.data[DOMAIN][entry.entry_id].get("batteries", [])
    coordinator = hass.data[DOMAIN][entry.entry_id].get("coordinator")

    all_entities: list[SensorEntity] = []
    mqtt_buffers: dict[str, MqttBatteryBuffer] = {}
    mqtt_buffers_es: dict[str, MqttBatteryBuffer] = {}

    battery_serials = {
        _serial_for_uid(b.get("serialNumber"))
        for b in batteries
        if b.get("serialNumber")
    }

    energy_switch_serials = set()
    def _add_es(v):
        if isinstance(v, str) and v.strip():
            energy_switch_serials.add(_serial_for_uid(v))
        elif isinstance(v, (list, tuple, set)):
            for s in v:
                if isinstance(s, str) and s.strip():
                    energy_switch_serials.add(_serial_for_uid(s))

    for key in ("energyswitch_serial", "energy_switch_serial", "energyswitch_serials", "energyswitch", "brain_serial"):
        _add_es(hass.data[DOMAIN][entry.entry_id].get(key))
    for source in (entry.data, entry.options):
        for key in ("energyswitch_serial", "energy_switch_serial", "energyswitch_serials", "energyswitch", "brain_serial"):
            _add_es(source.get(key))

    rest_batteries = {}
    if coordinator and hasattr(coordinator, "data") and "batteries_by_serial" in coordinator.data:
        for serial, bat in coordinator.data["batteries_by_serial"].items():
            rest_batteries[_serial_for_uid(serial)] = bat

    for battery in batteries:
        serial = _serial_for_uid(battery.get("serialNumber"))
        if not serial: continue
        mqtt_buffers[serial] = MqttBatteryBuffer(availability_window=avail_window)
        rest_battery = rest_batteries.get(serial, {})
        for logical_key, meta in SENSOR_DEFINITIONS.items():
            if not isinstance(meta, (tuple, list)) or len(meta) < 2: continue
            unit, icon = meta[0], meta[1]
            is_mqtt = _is_mqtt_only_key(logical_key)
            all_entities.append(BeemMqttOrRestSensor(serial=serial, logical_key=logical_key, unit=unit, icon=icon, mqtt_buffer=mqtt_buffers[serial], rest_battery=rest_battery, prefer_mqtt=is_mqtt))
        all_entities.append(BeemDerivedSensor(serial, "batteryPower", "charging", mqtt_buffers[serial], rest_battery))
        all_entities.append(BeemDerivedSensor(serial, "batteryPower", "discharging", mqtt_buffers[serial], rest_battery))
        all_entities.append(BeemDerivedSensor(serial, "solarPower", "production", mqtt_buffers[serial], rest_battery))
        all_entities.append(BeemDerivedSensor(serial, "meterPower", "consumption", mqtt_buffers[serial], rest_battery))
        all_entities.append(BeemDerivedSensor(serial, "meterPower", "injection", mqtt_buffers[serial], rest_battery))
        all_entities.append(BeemEnergySensor(hass, serial, "batteryPower", "charging"))
        all_entities.append(BeemEnergySensor(hass, serial, "batteryPower", "discharging"))
        all_entities.append(BeemEnergySensor(hass, serial, "solarPower", "production"))
        all_entities.append(BeemEnergySensor(hass, serial, "meterPower", "consumption"))
        all_entities.append(BeemEnergySensor(hass, serial, "meterPower", "injection"))
        all_entities.append(BeemMqttLastUpdateSensor(serial, mqtt_buffers[serial]))
        all_entities.append(BeemMqttDebugSensor(serial, mqtt_buffers[serial]))
    solar_equipments = []
    main_battery_serial = None
    if coordinator and hasattr(coordinator, "data"):
        solar_equipments = coordinator.data.get("battery", {}).get("solarEquipments", [])
        main_battery_serial = _serial_for_uid(coordinator.data.get("main_battery_serial"))
    if not main_battery_serial: main_battery_serial = "unknown"
    for idx, equipment in enumerate(solar_equipments):
        equipment_id = str(equipment.get("mpptId", f"{idx+1}"))
        for key, (unit, icon) in SOLAR_EQUIPMENT_SENSORS.items():
            if key in equipment:
                all_entities.append(SolarEquipmentSensor(coordinator, equipment_id, key, unit, idx, icon, main_battery_serial))
    if coordinator and hasattr(coordinator, "data"):
        for box_id in coordinator.data.get("beemboxes_by_id", {}).keys():
            for sensor_type in BeemBoxSensor.SENSOR_TYPES.keys():
                all_entities.append(BeemBoxSensor(coordinator, box_id, sensor_type))
    created_es_uids: set[str] = set()
    for es_serial in sorted({s for s in energy_switch_serials if s}):
        es_serial = _serial_for_uid(es_serial)
        mqtt_buffers_es[es_serial] = MqttBatteryBuffer(availability_window=avail_window)
        for chan in [0, 1]:
            for logical_key, meta in ENERGYSWITCH_SENSORS.items():
                unit, icon = meta.get("unit"), meta.get("icon", "mdi:flash")
                friendly = f"Ch {chan} {meta.get('friendly_name', logical_key.replace('_', ' ').title())}"
                uid = f"beem_es_{es_serial}_ch{chan}_{_clean_key(es_serial, logical_key)}"
                if uid in created_es_uids: continue
                created_es_uids.add(uid)
                all_entities.append(BeemEnergySwitchSensor(serial=es_serial, channel=chan, logical_key=logical_key, unit=unit, icon=icon, friendly_name=friendly, mqtt_buffer=mqtt_buffers_es[es_serial], precision=meta.get("precision"), device_class=meta.get("device_class"), state_class=meta.get("state_class")))
    deduped_entities: list[SensorEntity] = []
    seen_uids: set[str] = set()
    for ent in all_entities:
        uid = getattr(ent, "_attr_unique_id", None)
        if not uid or uid not in seen_uids:
            if uid: seen_uids.add(uid)
            deduped_entities.append(ent)
    
    async_add_entities(deduped_entities)
    _LOGGER.info("🟢 Entités Beem Energy ajoutées (%d, après déduplication) pour entry %s", len(deduped_entities), entry.entry_id)

    def _resolve_energy_switch_serials() -> set[str]:
        if not hass.data.get(DOMAIN, {}).get(entry.entry_id): return set()
        serials_raw = set()
        def _add(v):
            if isinstance(v, str) and v.strip(): serials_raw.add(_serial_for_uid(v))
        for key in ("energyswitch", "energyswitch_serial", "energy_switch_serial", "energyswitch_serials", "brain_serial"):
            val = hass.data[DOMAIN][entry.entry_id].get(key)
            if isinstance(val, (list, tuple, set)):
                for s in val: _add(s)
            else: _add(val)
        for src in (entry.data, entry.options):
            for key in ("energyswitch", "energyswitch_serial", "energy_switch_serial", "energyswitch_serials", "brain_serial"):
                val = src.get(key)
                if isinstance(val, (list, tuple, set)):
                    for s in val: _add(s)
                else: _add(val)
        try:
            coordinator_local = hass.data[DOMAIN][entry.entry_id].get("coordinator")
            if coordinator_local and hasattr(coordinator_local, "data"):
                _add(coordinator_local.data.get("energyswitch_serial") or coordinator_local.data.get("energy_switch_serial"))
        except Exception: pass
        return { _serial_for_topic(s) for s in serials_raw if s }

    def _get_es_buf(es_serial: str) -> MqttBatteryBuffer:
        es_serial = _serial_for_uid(es_serial)
        buf = mqtt_buffers_es.get(es_serial)
        if buf is None:
            mqtt_buffers_es[es_serial] = MqttBatteryBuffer(availability_window=avail_window)
            buf = mqtt_buffers_es[es_serial]
        return buf

    _echo_seen_q: list[str] = []
    _echo_seen_set: set[str] = set()
    def _echo_seen(key: str) -> bool:
        if key in _echo_seen_set: return True
        _echo_seen_set.add(key)
        _echo_seen_q.append(key)
        if len(_echo_seen_q) > 256:
            old = _echo_seen_q.pop(0)
            _echo_seen_set.discard(old)
        return False

    def _es_put(es_serial: str, chan: int, key: str, value: Any):
        try:
            canon = _ES_ALIAS_MAP.get(str(key).lower().replace("-", "_").replace(" ", "_").strip("_"), key)
            meta = ENERGYSWITCH_SENSORS.get(canon, {})
            prec = meta.get("precision")
            if isinstance(value, (int, float)) and isinstance(prec, int):
                value = round(float(value), prec)
            buf = _get_es_buf(es_serial)
            buffer_key = f"ch{chan}_{canon}"
            buf.update(buffer_key, value)
        except Exception as e: _LOGGER.debug("[MQTT][brain] es_put ignore key=%s err=%s", key, e)
    def _publish_metrics(es_serial: str, chan: int, metrics: Dict[str, Any]):
        map_inst = {"act_power": "power", "aprt_power": "apparent_power", "avg_voltage": "voltage", "avg_current": "current", "frequency": "freq", "powerfactor": "pf", "pf": "pf", "voltage": "voltage", "current": "current", "freq": "freq"}
        map_cum = {"total_act_energy": "energy_active_total", "total_act_ret_energy": "energy_active_returned_total", "lag_react_energy": "energy_reactive_lag", "lead_react_energy": "energy_reactive_lead", "max_act_power": "act_power_max", "min_act_power": "act_power_min", "max_aprt_power": "apparent_power_max", "min_aprt_power": "apparent_power_min", "max_voltage": "voltage_max", "min_voltage": "voltage_min"}
        for k, v in (metrics or {}).items():
            if k in map_inst: _es_put(es_serial, chan, map_inst[k], v)
            elif k in map_cum: _es_put(es_serial, chan, map_cum[k], v)
        async_dispatcher_send(hass, f"{SIGNAL_BEEM_ES_UPDATE}_{es_serial}")

    def _process_notifystatus(es_serial: str, chan: int, data: Dict[str, Any]):
        if not isinstance(data, dict): return
        metrics = {"act_power": data.get("act_power") or data.get("power"), "aprt_power": data.get("aprt_power") or data.get("apparent_power"), "voltage": data.get("voltage") or data.get("avg_voltage"), "current": data.get("current") or data.get("avg_current"), "frequency": data.get("frequency") or data.get("freq"), "pf": data.get("pf") or data.get("powerfactor"), "powerfactor": data.get("powerfactor") or data.get("pf")}
        _publish_metrics(es_serial, chan, metrics)
    def _process_em1data_status(es_serial: str, chan: int, data: Dict[str, Any]):
        if not isinstance(data, dict): return
        metrics = {"total_act_energy": data.get("total_act_energy"), "total_act_ret_energy": data.get("total_act_ret_energy"), "lag_react_energy": data.get("lag_react_energy"), "lead_react_energy": data.get("lead_react_energy"), "max_act_power": data.get("max_act_power"), "min_act_power": data.get("min_act_power"), "max_aprt_power": data.get("max_aprt_power"), "min_aprt_power": data.get("min_aprt_power"), "max_voltage": data.get("max_voltage"), "min_voltage": data.get("min_voltage"), "avg_voltage": data.get("avg_voltage"), "max_current": data.get("max_current"), "min_current": data.get("min_current"), "avg_current": data.get("avg_current")}
        _publish_metrics(es_serial, chan, metrics)

    def _handle_rpc_component_result(es_serial: str, obj: dict) -> bool:
        if not isinstance(obj, dict): return False
        comp = str(obj.get("component") or obj.get("comp") or "")
        if not comp: return False
        if "values" in obj:
            vals = obj.get("values") or []
            keys = obj.get("keys") or obj.get("labels") or DEFAULT_EM1DATA_KEYS
            try: chan = int(comp.split(":")[1]) if ":" in comp else 0
            except Exception: chan = 0
            if isinstance(vals, list) and vals:
                last = vals[-1] if isinstance(vals[-1], list) else None
                if isinstance(last, list):
                    flat = {keys[i] if i < len(keys) else f"k{i}": last[i] for i in range(len(last))}
                    _process_em1data_status(es_serial, chan, flat)
                    return True
        data = obj.get("data")
        if isinstance(data, dict):
            try: chan = int(comp.split(":")[1]) if ":" in comp else 0
            except Exception: chan = 0
            if comp.startswith("em1data:"): _process_em1data_status(es_serial, chan, data); return True
            if comp.startswith("em1:"): _process_notifystatus(es_serial, chan, data); return True
            keys = set(data.keys())
            if keys & {"act_power", "aprt_power", "voltage", "avg_voltage", "current", "avg_current", "pf", "powerfactor", "frequency", "freq"}:
                _process_notifystatus(es_serial, chan, data)
                return True
        return False

    def _handle_result_payload(es_serial: str, payload: dict):
        result = payload.get("result", {})
        def _maybe_push_instant(comp_key: str, val: dict):
            if not isinstance(val, dict): return False
            keys = set(val.keys())
            if not keys & {"act_power", "aprt_power", "voltage", "avg_voltage", "current", "avg_current", "pf", "powerfactor", "frequency", "freq"}: return False
            chan = 0
            try:
                if ":" in comp_key:
                    tail = comp_key.split(":")[-1]
                    if tail.isdigit(): chan = int(tail)
            except Exception: pass
            _process_notifystatus(es_serial, chan, val)
            return True
        handled = False
        if isinstance(result, list):
            for obj in result:
                if isinstance(obj, dict): handled = _handle_rpc_component_result(es_serial, obj) or handled
        if isinstance(result, dict):
            handled = _handle_rpc_component_result(es_serial, result) or handled
            for comp_key, value in list(result.items()):
                if not isinstance(comp_key, str): continue
                if isinstance(value, dict) and comp_key.startswith("em1:"):
                    try: chan = int(comp_key.split(":")[1])
                    except Exception: chan = 0
                    _process_notifystatus(es_serial, chan, value); handled = True
                elif isinstance(value, dict) and comp_key.startswith("em1data:"):
                    try: chan = int(comp_key.split(":")[1])
                    except Exception: chan = 0
                    _process_em1data_status(es_serial, chan, value); handled = True
                else: handled = _maybe_push_instant(comp_key, value) or handled
        ts = (payload.get("ts") or payload.get("unixtime") or payload.get("params", {}).get("ts") or (isinstance(result, dict) and result.get("ts")))
        if ts: _get_es_buf(es_serial).update("__last_dt__", str(ts))
        if handled: async_dispatcher_send(hass, f"{SIGNAL_BEEM_ES_UPDATE}_{es_serial}")
    def _handle_events_rpc(es_serial: str, topic: str, msg: dict):
        if not isinstance(msg, dict): return
        if "result" in msg: _handle_result_payload(es_serial, msg); return
        method = msg.get("method")
        if method in ("getStatus", "EM1Data.GetData", "EM1.GetStatus", "Shelly.GetStatus") and "result" not in msg:
            ek = f"{topic}|{msg.get('id')}|{method}"
            if not _echo_seen(ek): _LOGGER.debug("[MQTT][brain] Echo %s ignoré sur %s : %s", method, topic, msg)
            return
        if method == "NotifyStatus":
            params = msg.get("params", {}) or {}
            if not isinstance(params, dict): return
            for key, val in params.items():
                if not isinstance(key, str): continue
                if key.startswith("em1:"):
                    try: chan = int(key.split(":")[1])
                    except Exception: continue
                    if isinstance(val, dict): _process_notifystatus(es_serial, chan, val)
                elif key.startswith("em1data:"):
                    try: chan = int(key.split(":")[1])
                    except Exception: continue
                    if isinstance(val, dict): _process_em1data_status(es_serial, chan, val)
            return
        if method == "NotifyEvent":
            events = msg.get("params", {}).get("events", []) or []
            for ev in events:
                comp = (ev or {}).get("component", "")
                if isinstance(comp, str) and comp.startswith("em1data:"):
                    try: chan = int(comp.split(":")[1])
                    except Exception: continue
                    data = (ev or {}).get("data", {})
                    if isinstance(data, dict) and "values" in data:
                        keys = DEFAULT_EM1DATA_KEYS
                        vals = data.get("values") or []
                        if isinstance(vals, list) and vals:
                            last = vals[-1] if isinstance(vals[-1], list) else None
                            if isinstance(last, list):
                                flat = {k: last[i] for i, k in enumerate(keys) if i < len(last)}
                                _publish_metrics(es_serial, chan, {"total_act_energy": flat.get("total_act_energy"), "total_act_ret_energy": flat.get("total_act_ret_energy"), "lag_react_energy": flat.get("lag_react_energy"), "lead_react_energy": flat.get("lead_react_energy"), "max_act_power": flat.get("max_act_power"), "min_act_power": flat.get("min_act_power"), "max_aprt_power": flat.get("max_aprt_power"), "min_aprt_power": flat.get("min_aprt_power"), "max_voltage": flat.get("max_voltage"), "min_voltage": flat.get("min_voltage"), "avg_voltage": flat.get("avg_voltage"), "max_current": flat.get("max_current"), "min_current": flat.get("min_current"), "avg_current": flat.get("avg_current")})
            return


    def _ingest_battery_payload(serial: str, topic: str, payload):
        serial = _serial_for_uid(serial)
        mbuf = mqtt_buffers.setdefault(serial, MqttBatteryBuffer(availability_window=avail_window))
        dt = None
        if isinstance(payload, dict):
            ts_str = payload.get("date") or payload.get("timestamp") or payload.get("ts")
            if ts_str:
                try:
                    dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                    dt = dt.astimezone(timezone.utc)
                except Exception: dt = None
        if dt is None: dt = datetime.now(timezone.utc)
        iso_str = dt.isoformat(timespec="seconds")
        mbuf.update("__last_dt__", iso_str)
        mbuf.update("mqtt_last_update", iso_str)
        wanted = ["solar_power", "inverter_power", "battery_power", "grid_power", "soc", "mppt1_power", "mppt2_power", "mppt3_power"]
        if isinstance(payload, dict):
            for k in wanted:
                if k in payload:
                    v = payload[k]
                    if k != "soc": v = _to_float(v)
                    if v is not None:
                        mbuf.update(k, v)
                        camel_map = {"solar_power": "solarPower", "inverter_power": "inverterPower", "battery_power": "batteryPower", "grid_power": "meterPower", "mppt1_power": "mppt1Power", "mppt2_power": "mppt2Power", "mppt3_power": "mppt3Power", "soc": "soc"}
                        alias = camel_map.get(k)
                        if alias: mbuf.update(alias, v)
        _LOGGER.info("[MQTT][battery] topic=%s serial=%s -> buffered keys=%s", topic, serial, list(mbuf._data.keys()))
        async_dispatcher_send(hass, f"{SIGNAL_BEEM_BATTERY_UPDATE}_{serial}")


    def _make_es_cb(es_serial_uid: str):
        async def _es_cb(msg):
            topic = str(msg.topic)
            payload = _decode_payload_bytes(msg.payload)
            if payload is None: _LOGGER.debug("[MQTT][brain] payload illisible sur %s", topic); return
            _LOGGER.debug("[MQTT][brain][HA] Reçu topic=%s payload=%s", topic, payload)
            try:
                if topic.endswith("/online"):
                    if hass.data.get(DOMAIN, {}).get(entry.entry_id):
                        hass.data[DOMAIN][entry.entry_id].setdefault("brain_state", {})[es_serial_uid] = payload
                        async_dispatcher_send(hass, f"{SIGNAL_BEEM_ES_UPDATE}_{es_serial_uid}")
                    return
                if isinstance(payload, dict):
                    if "result" in payload: _handle_result_payload(es_serial_uid, payload)
                    elif "method" in payload: _handle_events_rpc(es_serial_uid, topic, payload)
                    else: _LOGGER.debug("[MQTT][brain][HA] Payload dict non traité sur %s", topic)
                else:
                    _LOGGER.info("[MQTT][brain][HA] Payload non-dict (peut-être un écho de /command) sur %s: %s", topic, payload)
                    if hass.data.get(DOMAIN, {}).get(entry.entry_id):
                        hass.data[DOMAIN][entry.entry_id].setdefault("brain_state", {})[es_serial_uid] = payload
                        async_dispatcher_send(hass, f"{SIGNAL_BEEM_ES_UPDATE}_{es_serial_uid}")
            except KeyError as e: _LOGGER.debug("[MQTT][brain][HA] Entry dict manquant (%s), message ignoré.", e)
            except Exception as e: _LOGGER.warning("[MQTT][brain][HA] parsing error on %s: %s", topic, e)
        return _es_cb

    async def _subscribe_via_ha_mqtt():
        """S’abonne via le broker HA aux topics EnergySwitch nécessaires (lower + UPPER)."""
        serials_upper = sorted(_resolve_energy_switch_serials())
        if not serials_upper:
            _LOGGER.info("Aucun numéro de série EnergySwitch fourni → pas d’abonnement.")
            return

        unsubs = hass.data[DOMAIN][entry.entry_id]["mqtt_unsubs"]
        subs = []
        for es_u in serials_upper:
            es_l = _serial_for_uid(es_u)
            if not es_l:
                continue
            topics_ha = {
                f"brain/{es_l}", f"brain/{es_l}/online", f"brain/{es_l}/rpc", f"brain/{es_l}/events/#",
                f"brain/{es_l}/+/rpc", f"brain/{es_l}/+",
#                f"brain/{es_u}", f"brain/{es_u}/online", f"brain/{es_u}/rpc", f"brain/{es_u}/events/#",
#                f"brain/{es_u}/+/rpc", f"brain/{es_u}/+",
            }
            for t in topics_ha:
                seen = hass.data[DOMAIN][entry.entry_id]["ha_mqtt_subscribed"]
                if t in seen:
                    continue
                unsubs.append(await ha_mqtt.async_subscribe(hass, t, _make_es_cb(es_l), qos=0))
                seen.add(t)
                subs.append(t)
                _LOGGER.info("✅ Abonné MQTT EnergySwitch (HA) : %s", t)
        _LOGGER.info("📋 Topics MQTT (HA) effectivement abonnés : %s", subs)
        
    async def _start_beem_cloud_battery_listener():
        if not mqtt_client: _LOGGER.warning("[MQTT][battery][Cloud] Aucun mqtt_client Cloud Beem disponible."); return
        battery_topics = {f"battery/{_serial_for_topic(s)}/sys/streaming" for s in battery_serials if s}
        if not battery_topics: _LOGGER.info("[MQTT][battery][Cloud] Aucun topic batterie à écouter."); return
        while True:
            try:
                async with mqtt_client:
                    hass.data[DOMAIN][entry.entry_id]["cloud_mqtt_connected"] = True
                    _LOGGER.info("[MQTT][battery][Cloud] Connexion établie. Abonnement aux topics batterie...")
                    for t in sorted(list(battery_topics)):
                        await mqtt_client.subscribe(t)
                        _LOGGER.info("✅ Abonné Cloud : %s", t)
                    async for message in mqtt_client.messages:
                        # --- CORRECTION APPLIQUÉE ICI ---
                        # 1. On convertit le topic en chaîne de caractères
                        topic_str = str(message.topic)
                        # 2. On travaille ensuite avec cette chaîne
                        serial_uid = _serial_for_uid(topic_str.split('/')[1])
                        payload = _decode_payload_bytes(message.payload)
                        _ingest_battery_payload(serial_uid, topic_str, payload)

            except asyncio.CancelledError: _LOGGER.info("[MQTT][battery][Cloud] Listener batterie annulé (unload)."); break
            except Exception as e: _LOGGER.warning("[MQTT][battery][Cloud] Listener batterie interrompu (%s). Reconnexion dans 15s…", repr(e))
            finally:
                if hass.data.get(DOMAIN, {}).get(entry.entry_id):
                    hass.data[DOMAIN][entry.entry_id]["cloud_mqtt_connected"] = False
            if entry.entry_id not in hass.data.get(DOMAIN, {}): break
            await asyncio.sleep(15)

    async def _renew_battery_streaming(_now=None, entry=None):
        if not entry or not hass.data.get(DOMAIN, {}).get(entry.entry_id): return
        try:
            if not battery_serials or not coordinator: return
            candidates = []
            for attr in ("async_ensure_streaming", "async_keep_streaming", "ensure_streaming"):
                fn = getattr(coordinator, attr, None)
                if callable(fn): candidates.append(fn)
            api = getattr(coordinator, "api", None)
            if api:
                for attr in ("async_ensure_streaming", "async_keep_streaming", "ensure_streaming"):
                    fn = getattr(api, attr, None)
                    if callable(fn): candidates.append(fn)
            serials = [s for s in battery_serials if s]
            for fn in candidates:
                try:
                    ok_any = False
                    for s in serials:
                        res = fn(s)
                        if asyncio.iscoroutine(res): res = await res
                        ok_any = bool(res) or ok_any
                    if ok_any: _LOGGER.debug("[MQTT][battery] Renouvellement streaming OK via %s", getattr(fn, '__name__', fn)); return
                except Exception as e: _LOGGER.debug("[MQTT][battery] Hook %s a échoué: %s", getattr(fn, '__name__', fn), e)
            _LOGGER.warning("[MQTT][battery] Impossible de renouveler le streaming avec les hooks testés.")
        except Exception as e: _LOGGER.warning("[MQTT][battery] Erreur lors du renouvellement du streaming: %s", e)

    async def _tick_availability(_now=None, entry=None):
        if not entry or not hass.data.get(DOMAIN, {}).get(entry.entry_id): return
        for serial in list(mqtt_buffers.keys()): async_dispatcher_send(hass, f"{SIGNAL_BEEM_BATTERY_UPDATE}_{serial}")
        for es_serial in list(mqtt_buffers_es.keys()): async_dispatcher_send(hass, f"{SIGNAL_BEEM_ES_UPDATE}_{es_serial}")
        try:
            if not coordinator: return
            for serial, buf in list(mqtt_buffers.items()):
                if not buf.is_fresh():
                    for attr in ("async_ensure_streaming", "async_keep_streaming", "ensure_streaming"):
                        fn = getattr(coordinator, attr, None)
                        if callable(fn):
                            try:
                                res = fn(serial)
                                if asyncio.iscoroutine(res): await res
                                break
                            except Exception: pass
            stale_store = hass.data[DOMAIN][entry.entry_id].setdefault("stale_counts", {})
            for serial, buf in list(mqtt_buffers.items()):
                fresh = buf.is_fresh()
                stale_store[serial] = 0 if fresh else stale_store.get(serial, 0) + 1
                if not fresh and stale_store[serial] >= 4:
                    _LOGGER.info("[MQTT][battery] Flux figé pour %s → rafraîchissement REST global + relance streaming", serial)
                    try:
                        if hasattr(coordinator, "_async_update_data"): await coordinator._async_update_data()
                    except Exception as e: _LOGGER.debug("Échec refresh REST global: %s", e)
                    await _renew_battery_streaming()
                    stale_store[serial] = 0
        except Exception: pass

    async def _poll_es_once(_now=None, entry=None):
        if not entry or not hass.data.get(DOMAIN, {}).get(entry.entry_id):
            _LOGGER.debug("Polling ES ignoré : l'entrée a été déchargée.")
            return

        entry_hass_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        cloud_mqtt_connected = entry_hass_data.get("cloud_mqtt_connected", False)
        serials_upper = _resolve_energy_switch_serials()
        if not serials_upper: return

        for es_u in sorted(serials_upper):
            es_l = _serial_for_uid(es_u)
            if not es_l: continue

            src_topic = f"brain/{es_l}/ha_{entry.entry_id}"

            # On ajoute Shelly.GetStatus en premier, c'est notre "coup de pied"
            rpc_calls = [
                {"method": "Shelly.GetStatus", "params": {}},
                {"method": "EM1.GetStatus", "params": {}}
            ]
            for ch in (0, 1):
                rpc_calls.append({"method": "EM1Data.GetData", "params": {"id": ch}})

            for call in rpc_calls:
                body = {"id": str(uuid.uuid4()), "method": call["method"], "params": call["params"], "src": src_topic}
                payload_str = json.dumps(body)

                # Polling HA (local)
                try:
                    await ha_mqtt.async_publish(hass, f"brain/{es_l}/rpc", payload_str, qos=0, retain=False)
                    await ha_mqtt.async_publish(hass, f"brain/{es_l}/events/rpc", payload_str, qos=0, retain=False)
                    _LOGGER.debug("[MQTT][brain][HA] → Poll '%s' sur brain/%s/[events/]rpc", call["method"], es_l)
                except Exception as e:
                    _LOGGER.warning("[MQTT][brain][HA] Échec publish sur /rpc ou /events/rpc : %s", e)

                # Polling Cloud (par sécurité)
                if cloud_mqtt_connected:
                    try:
                        await mqtt_client.publish(f"brain/{es_u}/rpc", payload_str)
                        _LOGGER.debug("[MQTT][brain][Cloud] → Poll '%s' sur brain/%s/rpc", call["method"], es_u)
                    except Exception as e:
                        _LOGGER.debug("[MQTT][brain][Cloud] Échec publish sur /rpc : %s", e)

    async def _start_after_start(_: object = None) -> None:
        if hass.state != CoreState.running:
            for _ in range(50):
                await asyncio.sleep(0.1)
                if hass.state == CoreState.running: break
        try:
            await ha_mqtt.async_wait_for_mqtt_client(hass)
            _LOGGER.info("MQTT client prêt → abonnements MQTT (HA).")
        except Exception as e: _LOGGER.warning("Impossible d'attendre le client MQTT : %s. On tente quand même.", e)
        hass.data[DOMAIN][entry.entry_id]["timed_tasks"] = []
        await _subscribe_via_ha_mqtt()
        if mqtt_client:
            task_bat = hass.async_create_task(
                _start_beem_cloud_battery_listener(),
                name=f"{DOMAIN}_beem_cloud_battery_{entry.entry_id}",
            )
            hass.data[DOMAIN][entry.entry_id]["beem_cloud_task_battery"] = task_bat
        else: _LOGGER.warning("[MQTT][Cloud] mqtt_client Cloud Beem absent → pas d'écoute.")
        renew_streaming_for_entry = functools.partial(_renew_battery_streaming, entry=entry)
        tick_availability_for_entry = functools.partial(_tick_availability, entry=entry)
        await renew_streaming_for_entry()
        cancel_renew = async_track_time_interval(hass, renew_streaming_for_entry, timedelta(seconds=90))
        hass.data[DOMAIN][entry.entry_id]["timed_tasks"].append(cancel_renew)
        cancel_tick = async_track_time_interval(hass, tick_availability_for_entry, timedelta(seconds=30))
        hass.data[DOMAIN][entry.entry_id]["timed_tasks"].append(cancel_tick)
        if ENABLE_ES_POLLING:
            poll_es_for_entry = functools.partial(_poll_es_once, entry=entry)
            _LOGGER.info("Le polling de l'EnergySwitch est activé (via constante de développement).")
            await poll_es_for_entry()
            cancel_poll = async_track_time_interval(hass, poll_es_for_entry, timedelta(seconds=60))
            hass.data[DOMAIN][entry.entry_id]["timed_tasks"].append(cancel_poll)
        else: _LOGGER.info("Le polling de l'EnergySwitch est désactivé (via constante de développement).")
        coordinator = hass.data[DOMAIN][entry.entry_id].get("coordinator")
        if coordinator:
            cancel_keepalive = async_track_time_interval(hass, coordinator.async_keepalive, timedelta(minutes=5))
            hass.data[DOMAIN][entry.entry_id]["timed_tasks"].append(cancel_keepalive)
            
    # --- DÉMARRAGE DES TÂCHES ---
    if hass.state == CoreState.running:
        hass.async_create_task(_start_after_start())
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start_after_start)
    _LOGGER.info("🟢 [setup_entry] Terminé pour entry %s", entry.entry_id)
    return True

class BeemMqttOrRestSensor(SensorEntity):
    def __init__(self, serial, logical_key, unit, icon, mqtt_buffer, rest_battery, prefer_mqtt=True):
        self._serial = _serial_for_uid(serial)
        self._logical_key = logical_key
        self._unit = unit
        self._icon = icon
        self._mqtt_buffer = mqtt_buffer
        self._rest_battery = rest_battery
        self._prefer_mqtt = prefer_mqtt
        self._debug_last_mqtt_key = "INIT"
        self._debug_source = "init"
        self._debug_rest_key = None

        _ckey = _clean_key(self._serial, logical_key)
        self._attr_unique_id = f"beem_{self._serial}_{_ckey}"
        self._attr_name = f"{_ckey.replace('_', ' ').capitalize()}"
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_has_entity_name = True
        self._unsub_dispatcher = None
        self._unsub_timer = None

        try:
            meta = SENSOR_DEFINITIONS.get(logical_key)
            if isinstance(meta, tuple) and len(meta) >= 3 and meta[2]:
                self._attr_device_class = meta[2]
            if isinstance(meta, tuple) and len(meta) >= 4 and meta[3]:
                self._attr_state_class = meta[3]
        except Exception:
            pass

    async def async_added_to_hass(self):
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, f"{SIGNAL_BEEM_BATTERY_UPDATE}_{self._serial}", self.async_write_ha_state
        )
        async def _on_timer(now):
            self.async_write_ha_state()
        self._unsub_timer = async_track_time_interval(self.hass, _on_timer, timedelta(seconds=30))
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    def _value_from_mqtt(self):
        if not self._mqtt_buffer:
            self._debug_last_mqtt_key = "NO_BUFFER"
            return None
        for k in _candidate_keys_for_mqtt(self._logical_key):
            val, _ = self._mqtt_buffer.get(k)
            if val is not None:
                self._debug_last_mqtt_key = k
                self._debug_source = "mqtt"
                return val
        self._debug_last_mqtt_key = "NO_MATCH"
        return None

    def _value_from_rest(self):
        self._debug_rest_key = None
        if not isinstance(self._rest_battery, dict):
            return None
        for k in _candidate_keys_for_rest(self._logical_key):
            if k in self._rest_battery:
                self._debug_rest_key = k
                self._debug_source = "rest"
                return self._rest_battery[k]
        return None

    @property
    def native_value(self):
        if self._prefer_mqtt:
            v = self._value_from_mqtt()
            if v is not None:
                return v
            v = self._value_from_rest()
            if v is not None:
                return v
            return self._value_from_mqtt()

        v = self._value_from_rest()
        if v is not None:
            return v
        return self._value_from_mqtt()

    @property
    def available(self) -> bool:
        return True

    @property
    def extra_state_attributes(self):
        keys = []
        try:
            if getattr(self._mqtt_buffer, "_data", None):
                keys = list(self._mqtt_buffer._data.keys())
        except Exception:
            pass
        return {
            "prefer_mqtt": bool(self._prefer_mqtt),
            "debug_source": self._debug_source,
            "debug_mqtt_key": self._debug_last_mqtt_key,
            "debug_rest_key": self._debug_rest_key,
            "buffer_keys": keys,
        }

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
        self._serial = _serial_for_uid(serial)
        self._source_key = source_key
        self._mode = mode
        self._mqtt_buffer = mqtt_buffer
        self._rest_battery = rest_battery
        self._debug_last_mqtt_key = "INIT"

        _ckey = _clean_key(self._serial, f"{source_key}_{mode}")
        self._attr_unique_id = f"beem_{self._serial}_{_ckey}"
        self._attr_name = f"{_ckey.replace('_', ' ').capitalize()}"
        self._attr_native_unit_of_measurement = UnitOfPower.WATT
        self._attr_icon = (
            "mdi:transmission-tower-export" if mode in ("discharging", "injection") else "mdi:battery-charging-100"
        )
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self._unsub_dispatcher = None
        self._unsub_timer = None

    async def async_added_to_hass(self):
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, f"{SIGNAL_BEEM_BATTERY_UPDATE}_{self._serial}", self.async_write_ha_state
        )
        async def _on_timer(now):
            self.async_write_ha_state()
        self._unsub_timer = async_track_time_interval(self.hass, _on_timer, timedelta(seconds=60))

    async def async_will_remove_from_hass(self):
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    @property
    def available(self) -> bool:
        return True

    def _value_from_mqtt(self):
        if not self._mqtt_buffer:
            self._debug_last_mqtt_key = "NO_BUFFER"
            return None
        for k in _candidate_keys_for_mqtt(self._source_key):
            val, _ = self._mqtt_buffer.get(k)
            if val is not None:
                self._debug_last_mqtt_key = k
                return val
        self._debug_last_mqtt_key = "NO_MATCH"
        return None

    @property
    def native_value(self):
        value = self._value_from_mqtt()
        if value is None and isinstance(self._rest_battery, dict):
            for k in _candidate_keys_for_rest(self._source_key):
                if k in self._rest_battery:
                    value = self._rest_battery[k]
                    break
        if value is None:
            return None
        value = _to_float(value)
        if value is None:
            return None

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
        return result

    @property
    def extra_state_attributes(self):
        keys = []
        try:
            if getattr(self._mqtt_buffer, "_data", None):
                keys = list(self._mqtt_buffer._data.keys())
        except Exception:
            pass
        return {
            "prefer_mqtt": True,
            "debug_mqtt_key": self._debug_last_mqtt_key,
            "buffer_keys": keys,
        }

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
        self._serial = _serial_for_uid(serial)
        self._source_key = source_key
        self._mode = mode

        _ckey = _clean_key(self._serial, f"{source_key}_{mode}_kwh")
        self._attr_unique_id = f"beem_{self._serial}_{_ckey}"
        self._attr_name = f"{_ckey.replace('_', ' ').capitalize()}"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_icon = "mdi:counter"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

        self._last_updated = None
        self._integrated_value = 0.0
        self._unsub_timer = None
        self._power_entity_id = None

    async def async_added_to_hass(self):
        self._last_updated = datetime.now(timezone.utc)
        reg = er.async_get(self.hass)
        derived_uid = f"beem_{self._serial}_{_clean_key(self._serial, f'{self._source_key}_{self._mode}')}"
        power_entity = reg.async_get_entity_id("sensor", DOMAIN, derived_uid)
        if power_entity:
            self._power_entity_id = power_entity
        else:
            _LOGGER.debug("[BeemEnergySensor] Unresolved power entity for unique_id=%s", derived_uid)

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
        if not self._power_entity_id:
            reg = er.async_get(self.hass)
            derived_uid = f"beem_{self._serial}_{_clean_key(self._serial, f'{self._source_key}_{self._mode}')}"
            self._power_entity_id = reg.async_get_entity_id("sensor", DOMAIN, derived_uid)
            if not self._power_entity_id:
                return

        state = self.hass.states.get(self._power_entity_id)
        if state is None or state.state in (None, "unknown", "unavailable"):
            return
        try:
            power_watts = abs(float(state.state))
        except (ValueError, TypeError):
            return

        now_dt = datetime.now(timezone.utc)
        if self._last_updated is not None:
            elapsed = (now_dt - self._last_updated).total_seconds()
            if elapsed > 0:
                self._integrated_value += (power_watts * (elapsed / 3600.0)) / 1000.0
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
        self._serial = _serial_for_uid(serial)
        self._mqtt_buffer = mqtt_buffer
        self._attr_unique_id = f"beem_{self._serial}_mqtt_last_update"
        self._attr_name = "Mqtt last update"
        self._attr_icon = "mdi:clock-outline"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

    @property
    def native_value(self):
        if not getattr(self._mqtt_buffer, "_data", None):
            return None
        last_payload_dt_str, _ = self._mqtt_buffer.get("__last_dt__")
        if isinstance(last_payload_dt_str, (str, datetime)):
            dt, ok = _parse_payload_dt(last_payload_dt_str)
            if ok:
                return dt.isoformat(timespec="seconds")
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

class BeemMqttDebugSensor(SensorEntity):
    """Expose tout le contenu du buffer MQTT d'une batterie."""
    def __init__(self, serial, mqtt_buffer):
        self._serial = _serial_for_uid(serial)
        self._mqtt_buffer = mqtt_buffer
        self._attr_unique_id = f"beem_{self._serial}_mqtt_debug"
        self._attr_name = "MQTT debug"
        self._attr_icon = "mdi:bug"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

    @property
    def native_value(self):
        try:
            return len(getattr(self._mqtt_buffer, "_data", {}) or {})
        except Exception:
            return 0

    @property
    def extra_state_attributes(self):
        attrs = {}
        try:
            for k, (val, ts) in (getattr(self._mqtt_buffer, "_data", {}) or {}).items():
                safe_key = f"buf__{k}"
                attrs[safe_key] = val
                if isinstance(ts, datetime):
                    attrs[f"{safe_key}__ts"] = ts.isoformat()
        except Exception:
            pass
        return attrs

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
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._equipment_index = equipment_index
        self._main_battery_serial = _serial_for_uid(main_battery_serial)
        self._attr_unique_id = f"beem_solar_{self._main_battery_serial}_{self._equipment_id}_{sensor_key.lower()}"
        self._attr_name = f"{sensor_key.replace('_', ' ').capitalize()}"
        self._attr_has_entity_name = True
        self._via_device = (DOMAIN, self._main_battery_serial)

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
            "via_device": self._via_device,
        }

class BeemBoxSensor(SensorEntity):
    """Représente un capteur pour une BeemBox."""
    
    SENSOR_TYPES = {
        "power": {
            "key": "wattHour",
            "name": "Puissance",
            "unit": UnitOfPower.WATT,
            "icon": "mdi:solar-power",
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
        },
        "today": {
            "key": "totalDay",
            "name": "Production Aujourd'hui",
            "unit": UnitOfEnergy.WATT_HOUR,
            "icon": "mdi:counter",
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
        },
        "month": {
            "key": "totalMonth",
            "name": "Production du Mois",
            "unit": UnitOfEnergy.WATT_HOUR,
            "icon": "mdi:calendar-month",
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
        },
        "wifi": {
            "key": "lastDbm",
            "name": "Signal WiFi",
            "unit": "dBm",
            "icon": "mdi:wifi",
            "device_class": "signal_strength",
            "state_class": SensorStateClass.MEASUREMENT,
            "entity_category": EntityCategory.DIAGNOSTIC,
        },
        "last_production": {
            "key": "lastProduction",
            "name": "Dernière Production",
            "unit": None,
            "icon": "mdi:clock-outline",
            "device_class": "timestamp",
            "entity_category": EntityCategory.DIAGNOSTIC,
        },
    }

    def __init__(self, coordinator, box_id, sensor_type):
        self.coordinator = coordinator
        self._box_id = str(box_id)
        self._sensor_type = sensor_type
        
        meta = self.SENSOR_TYPES[sensor_type]
        self._key = meta["key"]

        self._attr_unique_id = f"beembox_{self._box_id}_{sensor_type}".lower()
        self._attr_name = meta["name"]
        self._attr_native_unit_of_measurement = meta.get("unit")
        self._attr_icon = meta.get("icon")
        self._attr_device_class = meta.get("device_class")
        self._attr_state_class = meta.get("state_class")
        self._attr_entity_category = meta.get("entity_category")
        self._attr_has_entity_name = True

    @property
    def native_value(self):
        """Retourne la valeur du capteur."""
        summary_data = self.coordinator.data.get("beemboxes_summary_by_id", {}).get(self._box_id)
        if not summary_data:
            return None

        value = summary_data.get(self._key)
        
        if self._attr_device_class == "timestamp" and isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None
        
        return value

    @property
    def available(self) -> bool:
        """Retourne True si le summary est disponible pour cette box."""
        return self.coordinator.data.get("beemboxes_summary_by_id", {}).get(self._box_id) is not None

    @property
    def device_info(self):
        """Retourne les informations de l'appareil."""
        box_info = self.coordinator.data.get("beemboxes_by_id", {}).get(self._box_id)
        device_name = f"BeemBox {self._box_id}"
        if box_info and box_info.get("name"):
            device_name = box_info["name"]

        return {
            "identifiers": {(DOMAIN, f"beembox_{self._box_id}")},
            "name": device_name,
            "manufacturer": "Beem Energy",
            "model": "BeemOn / PnP",
        }

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info(">>> Déchargement des entités Beem (sensor) pour l'entrée: %s", entry.entry_id)
    unload_ok = True
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})

    timed_tasks = entry_data.get("timed_tasks", [])
    _LOGGER.info("Annulation de %d tâches périodiques (timers).", len(timed_tasks))
    for cancel_task in timed_tasks:
        try:
            cancel_task()
        except Exception as e:
            _LOGGER.warning("Erreur lors de l'annulation d'une tâche périodique : %s", e)
            unload_ok = False
            
    unsubs = entry_data.get("mqtt_unsubs", [])
    _LOGGER.info("Désabonnement de %d topics MQTT (broker HA).", len(unsubs))
    for u in unsubs:
        try:
            u()
        except Exception:
            pass

    task_bat = entry_data.get("beem_cloud_task_battery")
    if task_bat:
        task_bat.cancel()
        _LOGGER.info("Tâche MQTT Cloud Beem (battery) annulée pour l'entrée: %s", entry.entry_id)
    
    _LOGGER.info("<<< Déchargement des entités Beem (sensor) terminé (OK=%s)", unload_ok)
    return unload_ok

class BeemEnergySwitchSensor(RestoreEntity, SensorEntity):
    def __init__(
        self,
        serial,
        channel,
        logical_key,
        unit,
        icon,
        friendly_name,
        mqtt_buffer,
        precision=None,
        device_class=None,
        state_class=None,
    ):
        self._serial = _serial_for_uid(serial)
        self._channel = channel
        self._logical_key = logical_key
        self._unit = unit
        self._icon = icon
        self._friendly = friendly_name
        self._mqtt_buffer = mqtt_buffer
        self._precision = precision
        self._device_class = device_class
        self._state_class = state_class

        _ckey = _clean_key(self._serial, logical_key)
        self._attr_unique_id = f"beem_es_{self._serial}_ch{self._channel}_{_ckey}"
        self._attr_name = f"ES {self._serial} {friendly_name}"
        self._attr_icon = icon
        if unit:
            self._attr_native_unit_of_measurement = unit
        if device_class:
            self._attr_device_class = device_class
        if state_class:
            self._attr_state_class = state_class
        self._attr_should_poll = False

        self._unsub_dispatcher = None

    async def async_added_to_hass(self):
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._attr_native_value = float(last_state.state)
            except Exception:
                self._attr_native_value = last_state.state
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, f"{SIGNAL_BEEM_ES_UPDATE}_{self._serial}", self.async_write_ha_state
        )
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self):
        for k in _es_candidate_keys_for_read(self._logical_key):
            buffer_key = f"ch{self._channel}_{_clean_key(self._serial, k)}"
            raw, _ = self._mqtt_buffer.get(buffer_key)
            if raw is None:
                continue
            try:
                if isinstance(self._precision, int):
                    return round(float(raw), self._precision)
            except Exception:
                return raw
            return raw
        return None

    async def async_update(self):
        return

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"energyswitch_{self._serial}")},
            "name": f"Beem EnergySwitch {self._serial}",
            "manufacturer": "Beem Energy",
            "model": "EnergySwitch",
        }
