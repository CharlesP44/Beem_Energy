"""Tests du coordinateur REST face aux erreurs de l'API Beem (issue #96)."""

import time
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.beem_energy.beem_api import get_devices
from custom_components.beem_energy.coordinator import BeemCoordinator
from custom_components.beem_energy.exceptions import BeemAuthError, BeemConnectionError

COORDINATOR = "custom_components.beem_energy.coordinator"
DEVICES = {"batteries": [], "energySwitches": [], "beemboxes": []}


@pytest.fixture
def coordinator(hass: HomeAssistant, mock_config_entry):
    """Coordinateur dont le token n'a pas encore atteint sa date d'expiration locale."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **mock_config_entry.data,
            "access_token": "old_token",
            "user_id": "123",
            "rest_expires_at": time.time() + 3000,
        },
    )
    return BeemCoordinator(hass, mock_config_entry, "old_token", "test@beem.fr", "ok")


async def test_unreachable_api_fails_the_update_cleanly(coordinator):
    """Une API injoignable fait échouer la mise à jour, sans UnboundLocalError."""
    with patch(
        f"{COORDINATOR}.get_devices",
        new=AsyncMock(side_effect=BeemConnectionError("Erreur réseau Beem")),
    ), patch(f"{COORDINATOR}.get_box_summary", new=AsyncMock(return_value=[])):
        with pytest.raises(UpdateFailed, match="Erreur réseau Beem"):
            await coordinator._async_update_data()


async def test_refused_token_is_renewed(hass: HomeAssistant, coordinator, mock_config_entry):
    """Un 401 force un nouveau token, même avant sa date d'expiration locale."""
    seen_expiry = []

    async def fake_get_tokens(hass, entry, email, password):
        seen_expiry.append(entry.data["rest_expires_at"])
        return {"access_token": "new_token"}

    get_devices_mock = AsyncMock(side_effect=[BeemAuthError("401"), DEVICES])
    with patch(f"{COORDINATOR}.get_devices", new=get_devices_mock), patch(
        f"{COORDINATOR}.get_box_summary", new=AsyncMock(return_value=[])
    ), patch(f"{COORDINATOR}.get_tokens", new=fake_get_tokens):
        data = await coordinator._async_update_data()

    assert seen_expiry == [0]
    assert get_devices_mock.await_args_list[-1].args == ("new_token",)
    assert coordinator.token_rest == "new_token"
    assert data["batteries"] == []


async def test_get_devices_raises_on_network_error():
    """get_devices ne renvoie plus {} sur une erreur réseau : elle la signale."""
    with patch(
        "custom_components.beem_energy.beem_api.aiohttp.ClientSession",
        side_effect=aiohttp.ClientConnectionError("DNS server returned general failure"),
    ):
        with pytest.raises(BeemConnectionError):
            await get_devices("token")
