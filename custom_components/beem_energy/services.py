# Copyright (c) 2025 Charles P44
# SPDX-License-Identifier: MIT
import logging
import os
import csv
import aiohttp
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import partial

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# --- Définition des services ---
SERVICE_EXPORT_CSV = "export_to_csv"
SERVICE_EXPORT_FOR_IMPORT = "export_for_import"
SERVICE_EXPORT_FOR_HA_IMPORT = "export_for_ha_import"

BASE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("start_date"): cv.date,
        vol.Required("end_date"): cv.date,
    },
    extra=vol.ALLOW_EXTRA,
)

# --- Fonctions utilitaires ---
def _build_api_urls(battery_id: int | None) -> dict:
    urls = {
        "production": "https://api-x.beem.energy/beemapp/production/energy/intraday",
        "house_active": "https://api-x.beem.energy/beemapp/consumption/houses/active-energy/intraday",
        "house_returned": "https://api-x.beem.energy/beemapp/consumption/houses/active-returned-energy/intraday",
    }
    if battery_id:
        urls["battery_charged"] = f"https://api-x.beem.energy/beemapp/batteries/{battery_id}/energy-charged/intraday"
        urls["battery_discharged"] = f"https://api-x.beem.energy/beemapp/batteries/{battery_id}/energy-discharged/intraday"
    return urls

def _write_csv_sync(file_path: str, all_rows: list[dict], fieldnames: list[str]):
    _LOGGER.debug("Écriture de %d lignes dans %s", len(all_rows), file_path)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

# --- Logique des services ---

async def async_export_to_csv(hass: HomeAssistant, service_call: ServiceCall):
    """Service pour exporter les données historiques en CSV standard."""
    start_date = service_call.data["start_date"]
    end_date = service_call.data["end_date"]
    device_ids = service_call.data.get("device") or service_call.data.get("device_id") or []
    if not isinstance(device_ids, list): device_ids = [device_ids]
    if not device_ids:
        _LOGGER.error("Aucun appareil n'a été ciblé pour l'exportation.")
        return

    device_reg = dr.async_get(hass)
    for device_id in device_ids:
        device = device_reg.async_get(device_id)
        if not device or not device.config_entries: continue
        
        entry_id = list(device.config_entries)[0]
        _LOGGER.info("Exportation CSV pour le compte %s (appareil %s), de %s à %s", entry_id, device_id, start_date, end_date)
        
        entry_data = hass.data[DOMAIN][entry_id]
        coordinator = entry_data.get("coordinator")
        if not coordinator or not coordinator.data.get("battery"):
            _LOGGER.warning("Coordinateur non prêt ou pas de batterie pour le compte %s.", entry_id)

        token_rest = coordinator.token_rest
        battery_id = coordinator.data.get("battery", {}).get("id")
        
        API_URLS = _build_api_urls(battery_id)
        CSV_DIR = "/config/www/beem_exports"
        start_dt = dt_util.as_local(datetime.combine(start_date, datetime.min.time()))
        end_dt = dt_util.as_local(datetime.combine(end_date + timedelta(days=1), datetime.min.time()))

        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {token_rest}", "Accept": "application/json"}
            for api_name, api_url in API_URLS.items():
                _LOGGER.info(f"📡 Traitement de : {api_name} pour l'appareil {device_id}")
                cur_from, all_rows = start_dt, []
                while cur_from < end_dt:
                    cur_to = min(end_dt, cur_from + timedelta(days=7))
                    params = {"from": cur_from.isoformat(), "to": cur_to.isoformat(), "scale": "PT60M"}
                    try:
                        async with session.get(api_url, headers=headers, params=params, timeout=30) as resp:
                            resp.raise_for_status()
                            data = await resp.json()
                        devices = data.get("devices") or data.get("houses") or ([data] if "batteryId" in data else [])
                        for device_data in devices:
                            dev_id = device_data.get("deviceId") or device_data.get("houseId") or device_data.get("batteryId", "N/A")
                            for measure in device_data.get("measures", []):
                                start_iso, val = measure.get("startDate"), measure.get("value", 0)
                                if start_iso and val is not None:
                                    dt_utc = dt_util.parse_datetime(start_iso)
                                    dt_paris = dt_utc.astimezone(ZoneInfo("Europe/Paris"))
                                    all_rows.append({"startDate_utc": dt_utc.isoformat(), "datetime_paris": dt_paris.strftime("%Y-%m-%d %H:%M:%S"), "device_id": str(dev_id), "value_Wh": float(val)})
                    except Exception as e:
                        _LOGGER.error(f"   → Erreur lors de la récupération du chunk pour {api_name}: {e}")
                    cur_from = cur_to
                
                if all_rows:
                    entry_title = hass.config_entries.async_get_entry(entry_id).title.replace(" ", "_").lower()
                    filename = f"{api_name}_export_{entry_title}_{start_date}_to_{end_date}.csv"
                    file_path = os.path.join(CSV_DIR, filename)
                    fieldnames = ["startDate_utc", "datetime_paris", "device_id", "value_Wh"]
                    await hass.async_add_executor_job(_write_csv_sync, file_path, sorted(all_rows, key=lambda x: x["datetime_paris"]), fieldnames)
                    _LOGGER.info(f"✅ Fichier exporté : /local/beem_exports/{filename}")
                else:
                    _LOGGER.warning(f"Aucune donnée à exporter pour {api_name}")

    await hass.services.async_call("persistent_notification", "create", {"title": "Beem Energy Export", "message": "Exportation CSV terminée."})

async def async_export_for_import(hass: HomeAssistant, service_call: ServiceCall):
    """Service pour exporter les données dans un format cumulatif générique."""
    start_date, end_date = service_call.data["start_date"], service_call.data["end_date"]
    device_ids = service_call.data.get("device") or service_call.data.get("device_id") or []
    if not isinstance(device_ids, list): device_ids = [device_ids]
    if not device_ids:
        _LOGGER.error("Aucun appareil n'a été ciblé.")
        return

    device_reg = dr.async_get(hass)
    for device_id in device_ids:
        device = device_reg.async_get(device_id)
        if not device or not device.config_entries: continue
        
        entry_id = list(device.config_entries)[0]
        _LOGGER.info("Export (format import) pour le compte %s de %s à %s", entry_id, start_date, end_date)
        
        entry_data = hass.data[DOMAIN][entry_id]
        coordinator = entry_data.get("coordinator")
        if not coordinator or not coordinator.data: continue

        token_rest = coordinator.token_rest
        battery_id = coordinator.data.get("battery", {}).get("id")
        
        API_URLS = _build_api_urls(battery_id)
        CSV_DIR = "/config/www/beem_exports"
        start_dt = dt_util.as_local(datetime.combine(start_date, datetime.min.time()))
        end_dt = dt_util.as_local(datetime.combine(end_date + timedelta(days=1), datetime.min.time()))

        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {token_rest}", "Accept": "application/json"}
            for api_name, api_url in API_URLS.items():
                _LOGGER.info(f"Traitement (format import) de : {api_name} pour l'appareil {device_id}")
                cur_from, raw_measures = start_dt, []
                while cur_from < end_dt:
                    cur_to = min(end_dt, cur_from + timedelta(days=7))
                    params = {"from": cur_from.isoformat(), "to": cur_to.isoformat(), "scale": "PT60M"}
                    try:
                        async with session.get(api_url, headers=headers, params=params, timeout=30) as resp:
                            resp.raise_for_status(); data = await resp.json()
                        devices = data.get("devices") or data.get("houses") or ([data] if "batteryId" in data else [])
                        for device_data in devices:
                            for measure in device_data.get("measures", []):
                                start_iso, val = measure.get("startDate"), measure.get("value", 0)
                                if start_iso and val is not None:
                                    raw_measures.append({"start": dt_util.parse_datetime(start_iso), "value": float(val)})
                    except Exception as e: _LOGGER.error(f"Erreur de chunk pour {api_name}: {e}")
                    cur_from = cur_to
                if not raw_measures: continue
                
                if api_name == "production":
                    hourly_agg = {m["start"].strftime("%Y-%m-%d %H:00:00"): 0.0 for m in raw_measures}
                    for m in raw_measures: hourly_agg[m["start"].strftime("%Y-%m-%d %H:00:00")] += m["value"]
                    processed_measures = [{"start": datetime.fromisoformat(k).replace(tzinfo=timezone.utc), "value": v} for k, v in hourly_agg.items()]
                else:
                    processed_measures = raw_measures
                
                processed_measures.sort(key=lambda x: x["start"])
                all_rows_for_import, cumulative_sum_kwh = [], 0.0
                entry_title = hass.config_entries.async_get_entry(entry_id).title.replace(" ", "_").lower()
                statistic_id = f"beem_energy:{api_name}_{entry_title}"

                for measure in processed_measures:
                    cumulative_sum_kwh += measure["value"] / 1000.0
                    dt_paris = measure["start"].astimezone(ZoneInfo("Europe/Paris"))
                    all_rows_for_import.append({"statistic_id": statistic_id, "unit": "kWh", "start": dt_paris.strftime("%d.%m.%Y %H:%M"), "state": "", "sum": round(cumulative_sum_kwh, 6)})

                filename = f"{api_name}_import_format_{entry_title}_{start_date}_to_{end_date}.csv"
                file_path = os.path.join(CSV_DIR, filename)
                await hass.async_add_executor_job(_write_csv_sync, file_path, all_rows_for_import, ["statistic_id", "unit", "start", "state", "sum"])
                _LOGGER.info(f"✅ Fichier (format import) exporté : /local/beem_exports/{filename}")

    await hass.services.async_call("persistent_notification", "create", {"title": "Beem Energy Export", "message": "Exportation (format import) terminée."})

async def async_export_for_ha_import(hass: HomeAssistant, service_call: ServiceCall):
    """Exporte les données en utilisant les entity_id des capteurs existants."""
    start_date, end_date = service_call.data["start_date"], service_call.data["end_date"]
    device_ids = service_call.data.get("device") or service_call.data.get("device_id") or []
    if not isinstance(device_ids, list): device_ids = [device_ids]
    if not device_ids:
        _LOGGER.error("Aucun appareil n'a été ciblé.")
        return

    device_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    for device_id in device_ids:
        device = device_reg.async_get(device_id)
        if not device or not device.config_entries: continue
        
        entry_id = list(device.config_entries)[0]
        _LOGGER.info("Export (format HA) pour le compte %s de %s à %s", entry_id, start_date, end_date)
        
        entry_data = hass.data[DOMAIN][entry_id]
        coordinator = entry_data.get("coordinator")
        if not coordinator or not coordinator.data: continue

        token_rest = coordinator.token_rest
        battery_id = coordinator.data.get("battery", {}).get("id")
        main_serial_lower = coordinator.data.get("main_battery_serial", "").lower()
        if not main_serial_lower:
            _LOGGER.error("Impossible de trouver le numéro de série principal pour le compte %s.", entry_id)
            continue

        API_TO_SENSOR_MAP = {
            "production": ("solarPower", "production"),
            "house_returned": ("meterPower", "injection"),
            "house_active": ("meterPower", "consumption"),
            "battery_discharged": ("batteryPower", "discharging"),
            "battery_charged": ("batteryPower", "charging"),
        }
        API_URLS = _build_api_urls(battery_id)
        CSV_DIR = "/config/www/beem_exports"
        start_dt = dt_util.as_local(datetime.combine(start_date, datetime.min.time()))
        end_dt = dt_util.as_local(datetime.combine(end_date + timedelta(days=1), datetime.min.time()))
        
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {token_rest}", "Accept": "application/json"}
            for api_name, (source_key, mode) in API_TO_SENSOR_MAP.items():
                if api_name.startswith("battery_") and not battery_id: continue
                
                ckey = f"{source_key.lower()}_{mode}_kwh"
                unique_id = f"beem_{main_serial_lower}_{ckey}"
                entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
                if not entity_id:
                    _LOGGER.warning(f"Capteur avec unique_id '{unique_id}' non trouvé, export ignoré.")
                    continue
                
                statistic_id = entity_id
                _LOGGER.info(f"Traitement (format HA) de : {api_name} -> {statistic_id}")
                
                api_url = API_URLS[api_name]
                raw_measures, cur_from = [], start_dt
                while cur_from < end_dt:
                    cur_to = min(end_dt, cur_from + timedelta(days=7))
                    params = {"from": cur_from.isoformat(), "to": cur_to.isoformat(), "scale": "PT60M"}
                    try:
                        async with session.get(api_url, headers=headers, params=params, timeout=30) as resp:
                            resp.raise_for_status(); data = await resp.json()
                        devices = data.get("devices") or data.get("houses") or ([data] if "batteryId" in data else [])
                        for device_data in devices:
                            for measure in device_data.get("measures", []):
                                start_iso, val = measure.get("startDate"), measure.get("value", 0)
                                if start_iso and val is not None:
                                    raw_measures.append({"start": dt_util.parse_datetime(start_iso), "value": float(val)})
                    except Exception as e: _LOGGER.error(f"Erreur de chunk pour {api_name}: {e}")
                    cur_from = cur_to
                if not raw_measures: continue
                
                if api_name == "production":
                    hourly_agg = {m["start"].strftime("%Y-%m-%d %H:00:00"): 0.0 for m in raw_measures}
                    for m in raw_measures: hourly_agg[m["start"].strftime("%Y-%m-%d %H:00:00")] += m["value"]
                    processed_measures = [{"start": datetime.fromisoformat(k).replace(tzinfo=timezone.utc), "value": v} for k, v in hourly_agg.items()]
                else:
                    processed_measures = raw_measures
                
                processed_measures.sort(key=lambda x: x["start"])
                all_rows, cumulative_sum_kwh = [], 0.0
                for measure in processed_measures:
                    cumulative_sum_kwh += measure["value"] / 1000.0
                    dt_paris = measure["start"].astimezone(ZoneInfo("Europe/Paris"))
                    all_rows.append({"statistic_id": statistic_id, "unit": "kWh", "start": dt_paris.strftime("%d.%m.%Y %H:%M"), "state": "", "sum": round(cumulative_sum_kwh, 6)})
                
                filename = f"{statistic_id.replace('sensor.','')}_import_ha_{start_date}_to_{end_date}.csv"
                file_path = os.path.join(CSV_DIR, filename)
                await hass.async_add_executor_job(_write_csv_sync, file_path, all_rows, ["statistic_id", "unit", "start", "state", "sum"])
                _LOGGER.info(f"✅ Fichier (format HA) exporté : /local/beem_exports/{filename}")

    await hass.services.async_call("persistent_notification", "create", {"title": "Beem Energy Export", "message": "Exportation (format HA) terminée."})


# --- Fonctions d'enregistrement et de déchargement ---

def async_register_services(hass: HomeAssistant):
    """Enregistre tous les services de l'intégration."""
    hass.services.async_register(
        DOMAIN, 
        SERVICE_EXPORT_CSV, 
        partial(async_export_to_csv, hass), 
        schema=BASE_SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, 
        SERVICE_EXPORT_FOR_IMPORT, 
        partial(async_export_for_import, hass), 
        schema=BASE_SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, 
        SERVICE_EXPORT_FOR_HA_IMPORT, 
        partial(async_export_for_ha_import, hass), 
        schema=BASE_SERVICE_SCHEMA
    )

def async_unload_services(hass: HomeAssistant):
    """Supprime les services lors du déchargement de l'intégration."""
    hass.services.async_remove(DOMAIN, SERVICE_EXPORT_CSV)
    hass.services.async_remove(DOMAIN, SERVICE_EXPORT_FOR_IMPORT)
    hass.services.async_remove(DOMAIN, SERVICE_EXPORT_FOR_HA_IMPORT)
