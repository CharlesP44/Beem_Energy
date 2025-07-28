import pytest

from custom_components.beem_energy.sensor import BeemSensor, BATTERY_SENSOR_META

def test_sensor_creation_and_native_value():
    """Test création d'un capteur BeemSensor et gestion d'une valeur."""
    sensor = BeemSensor(serial="123456", key="solar_power", meta_source=BATTERY_SENSOR_META, device_type="battery")
    assert sensor._attr_name.startswith("Beem 123456")
    assert sensor._attr_device_class == "power"
    assert sensor._attr_unit_of_measurement == "W"

    # Test d'une valeur
    sensor.set_native_value(200)
    assert sensor.native_value == 200
