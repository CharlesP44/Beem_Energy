import pytest
from unittest.mock import patch, AsyncMock

from custom_components.beem_energy.const import DOMAIN

@pytest.mark.asyncio
async def test_config_flow_success(hass):
    """Test d'un flow de config Beem réussi."""
    # Patch try_login pour retourner un user_id et un token fictif
    with patch(
        "custom_components.beem_energy.beem_api.try_login",
        new=AsyncMock(return_value={"access_token": "token", "user_id": "123"}),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == "form"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"email": "test@beem.fr", "password": "ok"},
        )
        assert result["type"] == "create_entry"
        assert result["data"]["email"] == "test@beem.fr"
        assert result["title"].startswith("Beem Energy")

@pytest.mark.asyncio
async def test_config_flow_auth_error(hass):
    """Test une erreur d'auth lors du flow."""
    with patch(
        "custom_components.beem_energy.beem_api.try_login",
        new=AsyncMock(side_effect=Exception("Identifiants invalides")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"email": "fail@beem.fr", "password": "bad"},
        )
        assert result["type"] == "form"
        assert result["errors"]["base"] in ["invalid_auth", "unknown"]
