import pytest
from unittest.mock import patch, AsyncMock

from homeassistant.core import HomeAssistant
from tests.common import MockConfigEntry

from custom_components.beem_energy.const import DOMAIN

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Permet les intégrations custom automatiquement."""
    yield

# Créez une fixture qui met en place l'intégration pour vos tests
@pytest.fixture
async def setup_integration(hass: HomeAssistant):
    """Met en place l'intégration Beem Energy avec des données mockées."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "test@beem.fr", "password": "ok"},
        unique_id="beem_123"
    )
    entry.add_to_hass(hass)

    # Payload de mock complet et réaliste
    mock_devices_payload = {
        "batteries": [
            {
                "serialNumber": "B123",
                "id": 42,
                "soc": 88,
                "solarPower": 1200,
                # ... autres données de capteurs
                "control_parameters": {
                    "mode": "advanced",
                    "canChangeMode": True,
                    "minSoc": 15,
                    "allowChargeFromGrid": False
                }
            }
        ],
        "energySwitches": []
    }

    with patch(
        "custom_components.beem_energy.get_tokens",
        new=AsyncMock(return_value={
            "access_token": "token", "user_id": "123", "client_id": "client",
            "mqtt_token": "mqtt", "mqtt_server": "server", "mqtt_port": 8883,
        }),
    ), patch(
        "custom_components.beem_energy.BeemCoordinator._fetch_data_with_token",
        new=AsyncMock(return_value=mock_devices_payload),
    ), patch(
        "custom_components.beem_energy.Client", new_callable=AsyncMock
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry
