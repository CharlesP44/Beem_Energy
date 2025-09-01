import pytest
from unittest.mock import patch, AsyncMock

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant

from custom_components.beem_energy.const import DOMAIN
from custom_components.beem_energy.exceptions import BeemAuthError, BeemConnectionError

@pytest.mark.asyncio
async def test_config_flow_success(hass: HomeAssistant):
    """Test d'un flow de config Beem réussi."""
    with patch(
        "custom_components.beem_energy.config_flow.try_login",
        return_value={"access_token": "fake_token", "user_id": "123"},
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "user"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"email": "test@beem.fr", "password": "ok"},
        )
        await hass.async_block_till_done()

        assert result2["type"] == "create_entry"
        assert result2["title"] == "Beem Energy (test@beem.fr)"
        assert result2["data"] == {"email": "test@beem.fr", "password": "ok"}

@pytest.mark.asyncio
async def test_config_flow_auth_error(hass: HomeAssistant):
    """Test une erreur d'authentification lors du flow."""
    with patch(
        "custom_components.beem_energy.config_flow.try_login",
        side_effect=BeemAuthError,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"email": "fail@beem.fr", "password": "bad"},
        )
        assert result2["type"] == "form"
        assert result2["errors"]["base"] == "invalid_auth"
