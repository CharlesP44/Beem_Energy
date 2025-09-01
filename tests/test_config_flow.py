import pytest
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.beem_energy.const import DOMAIN
from custom_components.beem_energy.exceptions import BeemAuthError, BeemConnectionError

async def test_config_flow_success(hass: HomeAssistant):
    """Test un flow de configuration réussi."""
    with patch(
        "custom_components.beem_energy.config_flow.try_login",
        return_value={"access_token": "fake_token", "user_id": "123"},
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"email": "test@beem.fr", "password": "ok"}
        )
        await hass.async_block_till_done()

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["title"] == "Beem Energy (test@beem.fr)"
        assert result2["data"] == {"email": "test@beem.fr", "password": "ok"}

@pytest.mark.parametrize(
    ("side_effect", "error_base"),
    [
        (BeemAuthError, "invalid_auth"),
        (BeemConnectionError, "cannot_connect"),
        (Exception, "unknown"),
    ],
)
async def test_config_flow_failures(hass: HomeAssistant, side_effect, error_base):
    """Test les différents cas d'échec du flow de configuration."""
    with patch("custom_components.beem_energy.config_flow.try_login", side_effect=side_effect):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"email": "fail@beem.fr", "password": "bad"}
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == error_base
