import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from custom_components.beem_energy.const import DOMAIN

@pytest.mark.asyncio
async def test_async_setup_entry(hass):
    """Test le setup complet de l'intégration."""
    # Patch les fonctions réseaux pour simuler API Beem
    with patch(
        "custom_components.beem_energy.beem_api.get_tokens",
        new=AsyncMock(return_value={
            "access_token": "token",
            "user_id": "123",
            "client_id": "client",
            "mqtt_token": "mqtt",
            "mqtt_server": "server",
            "mqtt_port": 8883,
        }),
    ), patch(
        "custom_components.beem_energy.beem_api.get_devices",
        new=AsyncMock(return_value=([{"serialNumber": "BEE123"}], "SWITCH123")),
    ), patch(
        "custom_components.beem_energy.__init__.Client",
        new=MagicMock()
    ):
        # Simule une entrée de config
        entry = hass.config_entries.async_create_mock_entry(
            domain=DOMAIN,
            data={"email": "test@beem.fr", "password": "ok"},
            unique_id="beem_123"
        )
        entry.add_to_hass(hass)

        # Appelle le setup_entry
        from custom_components.beem_energy import async_setup_entry
        result = await async_setup_entry(hass, entry)
        assert result is True
        # Vérifie que les données sont bien stockées dans hass.data
        assert DOMAIN in hass.data
        assert entry.entry_id in hass.data[DOMAIN]
