"""Tests: exported files, imported files and diagnostics don't leak the account's data."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.beem_energy.const import DOMAIN
from custom_components.beem_energy.diagnostics import async_get_config_entry_diagnostics
from custom_components.beem_energy.services.export_csv import _export_filename
from custom_components.beem_energy.services.import_statistic import _internal_import_file


def test_export_names_cannot_be_guessed():
    """Files in www are public under /local/: their names hold a random part."""
    first = _export_filename("production_export", "2025-01-01", "2025-01-31")
    second = _export_filename("production_export", "2025-01-01", "2025-01-31")

    assert first != second
    assert first.startswith("production_export_2025-01-01_to_2025-01-31_")
    assert first.endswith(".csv")
    assert "@" not in first


@pytest.mark.parametrize("filename", ["../../etc/passwd", "/etc/passwd", "www/../../secrets.csv"])
async def test_import_refuses_files_outside_the_configuration(hass: HomeAssistant, filename):
    """The import service only reads files inside /config."""
    # The service reports its errors in a notification
    assert await async_setup_component(hass, "persistent_notification", {})
    with patch(
        "custom_components.beem_energy.services.import_statistic._prepare_data_to_import"
    ) as prepare, pytest.raises(ValueError, match="inside the configuration folder"):
        await _internal_import_file(hass, filename)

    prepare.assert_not_called()


async def test_diagnostics_are_redacted(hass: HomeAssistant, mock_config_entry):
    """Diagnostics go to public issues: no email, ids, serials or MAC addresses."""
    mock_config_entry.add_to_hass(hass)
    coordinator = SimpleNamespace(
        last_update_success=True,
        data={
            "main_battery_serial": "B123SECRET",
            "batteries_by_serial": {
                "B123SECRET": {"id": 42, "serialNumber": "B123SECRET", "soc": 88}
            },
            "beemboxes": [{"id": 7, "macAddress": "AA:BB:CC:DD:EE:FF", "power": 300}],
        },
    )
    hass.data[DOMAIN] = {
        mock_config_entry.entry_id: {
            "coordinator": coordinator,
            "user_id": "user-123456",
            "client_id": "beemapp-user-123456-1",
        }
    }

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    dump = json.dumps(diagnostics)

    for secret in ("test@beem.fr", "user-123456", "B123SECRET", "AA:BB:CC:DD:EE:FF"):
        assert secret not in dump
    assert diagnostics["devices"]["device_1"]["fields"]["soc"] == 88
