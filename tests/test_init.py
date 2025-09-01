import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.beem_energy.const import DOMAIN

# Créez une fausse entrée de config réutilisable
from tests.common import MockConfigEntry

@pytest.mark.asyncio
async def test_async_setup_entry(hass: HomeAssistant):
    """Test le setup complet de l'intégration."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "test@beem.fr", "password": "ok"},
        unique_id="beem_123"
    )
    entry.add_to_hass(hass)

    # Mock réaliste pour get_devices
    mock_devices_payload = {
        "batteries": [{"serialNumber": "BEE123", "id": 42}],
        "energySwitches": [{"serialNumber": "SWITCH123"}]
    }

    with patch(
        "custom_components.beem_energy.get_tokens",
        new=AsyncMock(return_value={
            "access_token": "token", "user_id": "123", "client_id": "client",
            "mqtt_token": "mqtt", "mqtt_server": "server", "mqtt_port": 8883,
        }),
    ), patch(
        "custom_components.beem_energy.get_devices",
        new=AsyncMock(return_value=mock_devices_payload),
    ), patch(
        "custom_components.beem_energy.Client", new_callable=AsyncMock
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Vérifie que l'entrée est bien chargée et non en erreur
        assert entry.state is ConfigEntryState.LOADED
        # Vérifie que les données sont bien stockées
        assert DOMAIN in hass.data
        assert entry.entry_id in hass.data[DOMAIN]
        assert hass.data[DOMAIN][entry.entry_id]["user_id"] == "123"
