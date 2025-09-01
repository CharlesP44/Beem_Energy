from unittest.mock import patch, AsyncMock
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.const import ConfigEntryState

from custom_components.beem_energy.exceptions import BeemConnectionError

async def test_setup_and_unload_entry(hass: HomeAssistant, setup_integration):
    """Test le chargement et le déchargement de l'intégration."""
    entry = setup_integration
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED

async def test_setup_fails_on_connection_error(hass: HomeAssistant, mock_config_entry):
    """Test que le setup passe en mode 'retry' si l'API est injoignable."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.beem_energy.get_tokens", side_effect=BeemConnectionError
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
