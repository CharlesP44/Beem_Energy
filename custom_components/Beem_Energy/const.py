# Domaine d'intégration Home Assistant
DOMAIN = "beem_energy"

# Plateformes supportées
PLATFORMS = ["sensor"]  # Ajoute "switch", "binary_sensor" si besoin plus tard

# === API Beem ===
BASE_URL = "https://api-x.beem.energy/beemapp"
MQTT_SERVER = "mqtt.beem.energy"
MQTT_PORT = 8084

REST_TOKEN_LIFETIME = 3500  # 58 minutes
MQTT_TOKEN_LIFETIME = 3500

MQTT_BATTERY_TOPIC = "battery/{serial}/sys/streaming"
MQTT_ENERGYSWITCH_TOPIC = "brain/{serial}"

UNIT_WATT = "W"
UNIT_KILOWATT_HOUR = "kWh"
UNIT_WATT_HOUR = "Wh"
UNIT_PERCENT = "%"
UNIT_DBM = "dBm"
UNIT_DEGREE = "°"

DEVICE_CLASS_POWER = "power"
DEVICE_CLASS_ENERGY = "energy"
STATE_CLASS_MEASUREMENT = "measurement"
STATE_CLASS_TOTAL_INCREASING = "total_increasing"

ICON_BATTERY = "mdi:home-battery-outline"
ICON_POWER = "mdi:flash"
ICON_SOLAR = "mdi:solar-power"
ICON_CHARGE = "mdi:battery-charging-60"
ICON_CLOCK = "mdi:calendar-clock"
ICON_SOH = "mdi:battery-heart-outline"
ICON_COUNTER = "mdi:counter"
ICON_SPEEDOMETER = "mdi:speedometer"
ICON_CHECK = "mdi:check-circle"

SENSOR_KEY_MAP = {
    "battery_power": "batteryPower",
    "grid_power": "meterPower",
    "solar_power": "solarPower",
    "soc": "soc",
    "working_mode_label": "workingModeLabel",
    "last_known_measure_date": "lastKnownMeasureDate",
    "number_of_cycles": "numberOfCycles",
    "number_of_modules": "numberOfModules",
    "global_soh": "globalSoh",
    "capacity_in_kwh": "capacityInKwh",
    "max_power": "maxPower",
    "is_battery_working_mode_ok": "isBatteryWorkingModeOk",
    "mppt1_power": "mppt1Power",
    "mppt2_power": "mppt2Power",
    "mppt3_power": "mppt3Power",
    "date": "lastKnownMeasureDate",
}

MQTT_ONLY_SENSORS = [
    "batteryPower", "meterPower", "solarPower", "soc",
    "mppt1Power", "mppt2Power", "mppt3Power",
]

SENSOR_DEFINITIONS = {
    "batteryPower": (UNIT_WATT, ICON_BATTERY),
    "meterPower": (UNIT_WATT, ICON_POWER),
    "solarPower": (UNIT_WATT, ICON_SOLAR),
    "soc": (UNIT_PERCENT, ICON_CHARGE),
    "workingModeLabel": (None, "mdi:cog-outline"),
    "numberOfCycles": (None, "mdi:cog-clockwise"),
    "numberOfModules": (None, "mdi:battery-high"),
    "globalSoh": (UNIT_PERCENT, ICON_SOH),
    "capacityInKwh": (UNIT_KILOWATT_HOUR, ICON_BATTERY),
    "maxPower": (UNIT_WATT, ICON_SPEEDOMETER),
    "isBatteryWorkingModeOk": (None, ICON_CHECK),
    "mppt1Power": (UNIT_WATT, ICON_SOLAR),
    "mppt2Power": (UNIT_WATT, ICON_SOLAR),
    "mppt3Power": (UNIT_WATT, ICON_SOLAR),
}

SOLAR_EQUIPMENT_SENSORS = {
    "mpptId": (None, "mdi:identifier"),
    "orientation": (UNIT_DEGREE, "mdi:compass-outline"),
    "tilt": (UNIT_DEGREE, "mdi:sun-angle-outline"),
    "peakPower": (UNIT_WATT, ICON_SOLAR),
    "solarPanelsInParallel": (None, "mdi:equal"),
    "solarPanelsInSeries": (None, "mdi:align-vertical-bottom"),
}

BEEMBOX_SENSORS = {
    "name": (None, "mdi:label"),
    "serialNumber": (None, "mdi:barcode"),
    "power": (UNIT_WATT, ICON_SOLAR),
    "wattHour": (UNIT_WATT_HOUR, ICON_COUNTER),
    "totalDay": (UNIT_WATT_HOUR, "mdi:calendar-today"),
    "totalMonth": (UNIT_WATT_HOUR, "mdi:calendar-month"),
    "lastDbm": (UNIT_DBM, "mdi:wifi"),
    "lastAlive": (None, ICON_CLOCK),
    "lastProduction": (None, "mdi:clock-outline"),
}
