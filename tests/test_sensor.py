import pytest
from unittest.mock import patch, AsyncMock

from homeassistant.core import HomeAssistant
from tests.common import MockConfigEntry

from custom_components.beem_energy.const import DOMAIN

# Importez vos helpers de test (voir ci-dessous)
from .conftest import setup_integration

async def test_battery_sensors_created(hass: HomeAssistant):
    """Test que les capteurs de la batterie sont créés avec les bonnes valeurs."""
    # Le setup de l'intégration est géré par la fixture
    await setup_integration(hass)

    # Vérifiez qu'un capteur a été créé et a le bon état
    soc_sensor = hass.states.get("sensor.batterie_beem_b123_soc")
    assert soc_sensor is not None
    assert soc_sensor.state == "88" # La valeur vient du mock dans conftest.py

    solar_power_sensor = hass.states.get("sensor.batterie_beem_b123_solarpower")
    assert solar_power_sensor is not None
    assert solar_power_sensor.state == "1200"
