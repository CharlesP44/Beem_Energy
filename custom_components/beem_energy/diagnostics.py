# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
from typing import Any, Dict

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> Dict[str, Any]:
    """Return diagnostics for a config entry."""

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.get("coordinator")
    mqtt_client = data.get("mqtt_client")
    energyswitch_topic = data.get("energyswitch_topic")
    mqtt_task = data.get("mqtt_task")

    diagnostics = {
        "entry_info": {
            "entry_id": entry.entry_id,
            "email": entry.data.get("email"),
            "user_id": data.get("user_id"),
            "client_id": data.get("client_id"),
        },
        "mqtt": {
            "server": getattr(mqtt_client, "hostname", None),
            "port": getattr(mqtt_client, "port", None),
            "status": (
                "running" if mqtt_task and not mqtt_task.done() else "stopped/cancelled"
            ),
            "energyswitch_topic": energyswitch_topic,
        },
        "rest_status": {
            "last_poll": getattr(coordinator, "last_update_success", None),
            "last_data_brief": None,
            "poll_ok": getattr(coordinator, "last_update_success", None),
        },
        "devices": {},
        "solar_equipments": [],
        "beemboxes": [],
        "active_sensors": [],
        "errors": [],
    }

    if hasattr(coordinator, "data"):
        last_data = coordinator.data or {}
        diagnostics["rest_status"]["last_data_brief"] = {
            k: (str(v)[:80] + "..." if len(str(v)) > 80 else v)
            for k, v in last_data.items()
            if not isinstance(v, (list, dict))
        }

        batteries_by_serial = last_data.get("batteries_by_serial", {})
        for serial, battery in batteries_by_serial.items():
            dev_info = {
                "serial": serial,
                "id": battery.get("id"),
                "firmware": battery.get("firmwareVersion"),
                "rest_lastKnownMeasureDate": battery.get("lastKnownMeasureDate"),
                "fields": {k: battery.get(k) for k in battery.keys()},
            }

            mqtt_buffers = hass.data[DOMAIN][entry.entry_id].get("mqtt_buffers", {})
            current_buffer = mqtt_buffers.get(serial.lower())
            if current_buffer and hasattr(current_buffer, "_data"):
                buffer_diag = {k: v[0] for k, v in current_buffer._data.items()}
            else:
                buffer_diag = {}
            dev_info["mqtt_buffer"] = buffer_diag
            diagnostics["devices"][serial] = dev_info

        if "solar_equipments" in last_data:
            for idx, eq in enumerate(last_data["solar_equipments"]):
                diagnostics["solar_equipments"].append(
                    {
                        "mpptId": eq.get("mpptId"),
                        "orientation": eq.get("orientation"),
                        "tilt": eq.get("tilt"),
                        "peakPower": eq.get("peakPower"),
                        "serialNumber": eq.get("serialNumber", ""),
                        "equip_raw": eq,
                    }
                )

        if "beemboxes" in last_data:
            for box in last_data["beemboxes"]:
                diagnostics["beemboxes"].append(
                    {
                        "id": box.get("macAddress") or box.get("id"),
                        "serialNumber": box.get("serialNumber"),
                        "power": box.get("power"),
                        "lastAlive": box.get("lastAlive"),
                        "raw": box,
                    }
                )

    sensors = data.get("active_sensors")
    if sensors:
        for ent in sensors:
            diagnostics["active_sensors"].append(
                {
                    "unique_id": getattr(ent, "unique_id", None),
                    "name": getattr(ent, "name", None),
                    "source": (
                        getattr(ent, "_prefer_mqtt", None) and "MQTT" or "REST"
                        if hasattr(ent, "_prefer_mqtt")
                        else None
                    ),
                    "type": type(ent).__name__,
                }
            )

    errors = data.get("errors")
    if errors:
        diagnostics["errors"].extend(errors)

    diagnostics["integration_status"] = "OK"
    if mqtt_task and mqtt_task.done():
        diagnostics["integration_status"] = "MQTT stopped or error"
    if not getattr(coordinator, "last_update_success", True):
        diagnostics["integration_status"] = "REST unavailable"

    return diagnostics
