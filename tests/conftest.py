import pytest
from unittest.mock import patch, AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.const import ConfigEntryState

from tests.common import MockConfigEntry

from custom_components.beem_energy.const import DOMAIN

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Permet les intégrations custom automatiquement."""
    yield

@pytest.fixture
def mock_config_entry():
    """Crée une fausse entrée de configuration."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={"email": "test@beem.fr", "password": "ok"},
        unique_id="beem_123",
    )

@pytest.fixture
def mock_beem_api():
    """Mock complet de l'API Beem et des dépendances externes."""
    
    # Payload de mock complet et réaliste pour le coordinateur
    mock_coordinator_data = {
        "batteries_by_serial": {
            "B123": {
                "serialNumber": "B123",
                "id": 42,
                "soc": 88,
                "solarPower": 1200,
                "batteryPower": -500, # Décharge
                "meterPower": 200, # Consommation
                "inverterPower": 700,
                "control_parameters": {
                    "mode": "advanced",
                    "canChangeMode": True,
                    "minSoc": 15,
                    "maxSoc": 95,
                    "allowChargeFromGrid": False,
                    "preventDischarge": True,
                    "chargeFromGridMaxPower": 1000,
                }
            }
        }
    }

    with patch(
        "custom_components.beem_energy.get_tokens",
        new=AsyncMock(return_value={
            "access_token": "fake_token", "user_id": "123", "client_id": "fake_client",
            "mqtt_token": "fake_mqtt_token", "mqtt_server": "fake_server", "mqtt_port": 8883,
        }),
    ), patch(
        "custom_components.beem_energy.BeemCoordinator._fetch_data_with_token",
        return_value=mock_coordinator_data,
    ), patch(
        "custom_components.beem_energy.Client", new_callable=AsyncMock
    ) as mock_mqtt_client:
        yield mock_mqtt_client


@pytest.fixture
async def setup_integration(hass: HomeAssistant, mock_config_entry, mock_beem_api):
    """Met en place l'intégration Beem Energy et retourne l'entrée de config."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    return mock_config_entry
