from unittest.mock import patch, AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.const import PERCENTAGE

async def test_numbers_state_and_actions(hass: HomeAssistant, setup_integration):
    """Test l'état initial des entités number et leurs actions."""
    min_soc_id = "number.b123_min_soc"
    max_soc_id = "number.b123_max_soc"

    # Vérifie l'état initial
    min_soc_state = hass.states.get(min_soc_id)
    assert min_soc_state.state == "15.0"
    assert min_soc_state.attributes["unit_of_measurement"] == PERCENTAGE

    assert hass.states.get(max_soc_id).state == "95.0"

    # Test de l'action 'set_value'
    with patch("custom_components.beem_energy.number.set_battery_control_parameters", new=AsyncMock()) as mock_api_call:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": min_soc_id, "value": 20}, blocking=True
        )
        mock_api_call.assert_called_once_with("fake_token", 42, {"minSoc": 20})
