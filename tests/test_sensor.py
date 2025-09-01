from homeassistant.core import HomeAssistant
from homeassistant.const import PERCENTAGE, UnitOfPower

async def test_battery_sensors_state(hass: HomeAssistant, setup_integration):
    """Test l'état initial des capteurs de la batterie."""
    # Test un capteur principal
    soc_sensor = hass.states.get("sensor.batterie_beem_b123_soc")
    assert soc_sensor is not None
    assert soc_sensor.state == "88"
    assert soc_sensor.attributes["unit_of_measurement"] == PERCENTAGE

    # Test un capteur de puissance
    solar_power_sensor = hass.states.get("sensor.batterie_beem_b123_solarpower")
    assert solar_power_sensor is not None
    assert solar_power_sensor.state == "1200"
    assert solar_power_sensor.attributes["unit_of_measurement"] == UnitOfPower.WATT
