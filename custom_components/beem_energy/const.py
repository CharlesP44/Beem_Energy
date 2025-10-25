# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
DOMAIN = "beem_energy"

PLATFORMS = ["sensor", "select", "switch", "number"]

# === API Beem ===
BASE_URL = "https://api-x.beem.energy/beemapp"
MQTT_SERVER = "mqtt.beem.energy"
MQTT_PORT = 8084

REST_TOKEN_LIFETIME = 3500  # 58 minutes
MQTT_TOKEN_LIFETIME = 3500

MQTT_BATTERY_TOPIC = "battery/{serial}/sys/streaming"
MQTT_ENERGYSWITCH_TOPIC = "brain/{serial}"

# --- Unités ---
UNIT_WATT = "W"
UNIT_KILOWATT_HOUR = "kWh"
UNIT_WATT_HOUR = "Wh"
UNIT_VOLT = "V"
UNIT_AMPERE = "A"
UNIT_HZ = "Hz"
UNIT_PERCENT = "%"
UNIT_DBM = "dBm"
UNIT_DEGREE = "°"
UNIT_VA = "VA"

# --- Device/State classes (chaînes acceptées par HA) ---
DEVICE_CLASS_POWER = "power"
DEVICE_CLASS_ENERGY = "energy"
DEVICE_CLASS_VOLTAGE = "voltage"
DEVICE_CLASS_CURRENT = "current"
DEVICE_CLASS_FREQUENCY = "frequency"
DEVICE_CLASS_POWER_FACTOR = "power_factor"
DEVICE_CLASS_BATTERY = "battery"

STATE_CLASS_MEASUREMENT = "measurement"
STATE_CLASS_TOTAL_INCREASING = "total_increasing"

# --- Icônes ---
ICON_BATTERY = "mdi:home-battery-outline"
ICON_POWER = "mdi:flash"
ICON_SOLAR = "mdi:solar-power"
ICON_CHARGE = "mdi:battery-charging-60"
ICON_CLOCK = "mdi:calendar-clock"
ICON_SOH = "mdi:battery-heart-outline"
ICON_COUNTER = "mdi:counter"
ICON_SPEEDOMETER = "mdi:speedometer"
ICON_CHECK = "mdi:check-circle"
ICON_INVERTER = "mdi:swap-horizontal"
ICON_MPPT = "mdi:solar-panel-large"


SENSOR_KEY_MAP = {
    # Instantanés principaux
    "battery_power": "batteryPower",
    "grid_power": "meterPower",  # "grid" côté payload -> "meter" côté logique
    "solar_power": "solarPower",
    "inverter_power": "inverterPower",
    # État batterie
    "soc": "soc",
    "working_mode_label": "workingModeLabel",
    "global_soh": "globalSoh",
    "number_of_cycles": "numberOfCycles",
    "number_of_modules": "numberOfModules",
    "capacity_in_kwh": "capacityInKwh",
    "max_power": "maxPower",
    "is_battery_working_mode_ok": "isBatteryWorkingModeOk",
    # MPPT
    "mppt1_power": "mppt1Power",
    "mppt2_power": "mppt2Power",
    "mppt3_power": "mppt3Power",
    # Date/horodatage connus dans certains payloads
    "date": "lastKnownMeasureDate",
    "timestamp": "lastKnownMeasureDate",
    "ts": "lastKnownMeasureDate",
    "last_known_measure_date": "lastKnownMeasureDate",
}

# Liste des capteurs qui n'existent qu'en MQTT
MQTT_ONLY_SENSORS = [
    "batteryPower",
    "meterPower",
    "solarPower",
    "inverterPower",
    "soc",
    "mppt1Power",
    "mppt2Power",
    "mppt3Power",
]

# -------------------------------------------------------------------
# Définition des capteurs logiques : unit, icon, device_class, state_class
# (Les 3e et 4e éléments du tuple sont optionnels, mais utilisés par sensor.py)
# -------------------------------------------------------------------

SENSOR_DEFINITIONS = {
    "batteryPower": (UNIT_WATT, ICON_BATTERY),
    "meterPower": (UNIT_WATT, ICON_POWER),
    "solarPower": (UNIT_WATT, ICON_SOLAR),
    "inverterPower": (UNIT_WATT, ICON_INVERTER),
    "soc": (UNIT_PERCENT, ICON_CHARGE),
    "workingModeLabel": (None, "mdi:cog-outline"),
    "numberOfCycles": (None, "mdi:cog-clockwise"),
    "numberOfModules": (None, "mdi:battery-high"),
    "globalSoh": (UNIT_PERCENT, ICON_SOH),
    "capacityInKwh": (UNIT_KILOWATT_HOUR, ICON_BATTERY),
    "maxPower": (UNIT_WATT, ICON_SPEEDOMETER),
    "isBatteryWorkingModeOk": (None, ICON_CHECK),
    "lastKnownMeasureDate": (None, "mdi:clock-outline"),
    "isBatteryInBackupMode": (None, "mdi:backup-restore"),
    "mppt1Power": (UNIT_WATT, ICON_SOLAR),
    "mppt2Power": (UNIT_WATT, ICON_SOLAR),
    "mppt3Power": (UNIT_WATT, ICON_SOLAR),
}

# -------------------------------------------------------------------
# Solar Equipment (extrait REST "battery.solarEquipments[]")
# -------------------------------------------------------------------
SOLAR_EQUIPMENT_SENSORS = {
    "mpptId": (None, "mdi:identifier"),
    "orientation": (UNIT_DEGREE, "mdi:compass-outline"),
    "tilt": (UNIT_DEGREE, "mdi:sun-angle-outline"),
    "peakPower": (UNIT_WATT, ICON_SOLAR),
    "solarPanelsInParallel": (None, "mdi:equal"),
    "solarPanelsInSeries": (None, "mdi:align-vertical-bottom"),
}

# -------------------------------------------------------------------
# EnergySwitch (MQTT brain/*)
# -------------------------------------------------------------------
ENERGYSWITCH_SENSORS = {
    "power": {
        "friendly_name": "Power",
        "unit": UNIT_WATT,
        "device_class": DEVICE_CLASS_POWER,
        "state_class": STATE_CLASS_MEASUREMENT,
        "aliases": ["act_power"],
        "precision": 1,
        "icon": "mdi:flash",
    },
    "apparent_power": {
        "friendly_name": "Apparent Power",
        "unit": UNIT_VA,
        "device_class": "apparent_power",
        "state_class": STATE_CLASS_MEASUREMENT,
        "aliases": ["aprt_power"],
        "precision": 1,
        "icon": "mdi:flash-outline",
    },
    "voltage": {
        "friendly_name": "Voltage",
        "unit": UNIT_VOLT,
        "device_class": DEVICE_CLASS_VOLTAGE,
        "state_class": STATE_CLASS_MEASUREMENT,
        "aliases": ["avg_voltage"],
        "precision": 2,
        "icon": "mdi:alpha-v-circle",
    },
    "current": {
        "friendly_name": "Current",
        "unit": UNIT_AMPERE,
        "device_class": DEVICE_CLASS_CURRENT,
        "state_class": STATE_CLASS_MEASUREMENT,
        "aliases": ["avg_current"],
        "precision": 3,
        "icon": "mdi:sine-wave",
    },
    "freq": {
        "friendly_name": "Frequency",
        "unit": UNIT_HZ,
        "device_class": DEVICE_CLASS_FREQUENCY,
        "state_class": STATE_CLASS_MEASUREMENT,
        "aliases": ["frequency"],
        "precision": 2,
        "icon": "mdi:sine-wave",
    },
    "pf": {
        "friendly_name": "Power Factor",
        "device_class": DEVICE_CLASS_POWER_FACTOR,
        "state_class": STATE_CLASS_MEASUREMENT,
        "aliases": ["powerfactor"],
        "precision": 2,
        "icon": "mdi:cosine-wave",
    },
    "energy_active_total": {
        "friendly_name": "Energy Active Total",
        "unit": UNIT_WATT_HOUR,
        "device_class": DEVICE_CLASS_ENERGY,
        "state_class": STATE_CLASS_TOTAL_INCREASING,
        "aliases": ["total_act_energy"],
        "precision": 2,
        "icon": "mdi:counter",
    },
    "energy_active_returned_total": {
        "friendly_name": "Energy Active Returned Total",
        "unit": UNIT_WATT_HOUR,
        "device_class": DEVICE_CLASS_ENERGY,
        "state_class": STATE_CLASS_TOTAL_INCREASING,
        "aliases": ["total_act_ret_energy"],
        "precision": 2,
        "icon": "mdi:counter",
    },
}

# --- EnergySwitch (RPC polling) ---

ENABLE_ES_POLLING = True
DISPATCH_ENERGY_SWITCH_UPDATE = "beem_energy_energyswitch_update"
DEFAULT_ENERGY_SWITCH_POLL_INTERVAL = 30
ENERGYSWITCH_RPC_REQUEST_TOPIC = "brain/{serial}/events/rpc"
ENERGYSWITCH_RPC_REPLY_TOPICS = [
    "brain/{serial}/events/rpc/reply",
    "brain/{serial}/events/+/reply",
    "brain/{serial}/+/rpc/reply",
]
