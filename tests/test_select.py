from unittest.mock import patch, AsyncMock

from homeassistant.core import HomeAssistant

async def test_selects_state_and_actions(hass: HomeAssistant, setup_integration):
    """Test l'état initial des entités select et leurs actions."""
    mode_select_id = "select.batterie_beem_b123_mode_de_la_batterie" # Note: l'ID peut varier si vous ajoutez un object_id
    power_select_id = "select.b123_charge_power"

    # Vérifie l'état initial
    assert hass.states.get(mode_select_id).state == "advanced"
    assert hass.states.get(power_select_id).state == "1000"

    # Test de l'action 'select_option'
    with patch("custom_components.beem_energy.select.set_battery_control_parameters", new=AsyncMock()) as mock_api_call:
        await hass.services.async_call(
            "select", "select_option", {"entity_id": mode_select_id, "option": "auto"}, blocking=True
        )
        mock_api_call.assert_called_once_with("fake_token", 42, {"mode": "auto"})
