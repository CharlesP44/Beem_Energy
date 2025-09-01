from unittest.mock import patch, AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_ON, STATE_OFF

async def test_switches_state_and_actions(hass: HomeAssistant, setup_integration):
    """Test l'état initial des switchs et leurs actions."""
    charge_switch_id = "switch.b123_allow_charge_from_grid"
    prevent_switch_id = "switch.b123_prevent_discharge"

    # Vérifie l'état initial basé sur le mock de conftest.py
    assert hass.states.get(charge_switch_id).state == STATE_OFF
    assert hass.states.get(prevent_switch_id).state == STATE_ON

    # Test de l'action 'turn_on'
    with patch("custom_components.beem_energy.switch.set_battery_control_parameters", new=AsyncMock()) as mock_api_call:
        await hass.services.async_call("switch", "turn_on", {"entity_id": charge_switch_id}, blocking=True)
        # Vérifie que l'API a été appelée avec les bons arguments
        mock_api_call.assert_called_once_with(
            "fake_token", 42, {"allowChargeFromGrid": True}
        )

    # Test de l'action 'turn_off'
    with patch("custom_components.beem_energy.switch.set_battery_control_parameters", new=AsyncMock()) as mock_api_call:
        await hass.services.async_call("switch", "turn_off", {"entity_id": prevent_switch_id}, blocking=True)
        mock_api_call.assert_called_once_with(
            "fake_token", 42, {"preventDischarge": False}
        )
