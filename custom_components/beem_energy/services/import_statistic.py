# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
import logging
import os
from functools import partial
import zoneinfo
from pathlib import Path
from enum import Enum
from datetime import datetime

import pandas as pd
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, valid_entity_id
from homeassistant.helpers import config_validation as cv
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    async_import_statistics,
    valid_statistic_id,
)

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# --- Constantes et Enum ---
class UnitFrom(Enum):
    TABLE = 1
    ENTITY = 2


DATETIME_DEFAULT_FORMAT = "%d.%m.%Y %H:%M"

# --- Définition des services ---
SERVICE_IMPORT_STATISTIC = "import_statistic"
SERVICE_IMPORT_HA_FILES = "import_ha_statistics_files"

IMPORT_SCHEMA = vol.Schema(
    {
        vol.Required("filename"): cv.string,
    }
)


# --- Fonctions Helpers ---
def _handle_error(error_string: str):
    _LOGGER.warning(error_string)


def _is_valid_float(value: str) -> bool:
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def _are_columns_valid(df: pd.DataFrame, unit_from_where: UnitFrom) -> bool:
    columns = df.columns
    if not (
        "statistic_id" in columns
        and "start" in columns
        and ("unit" in columns or unit_from_where == UnitFrom.ENTITY)
    ):
        _handle_error(
            "File must contain 'statistic_id', 'start', and 'unit' columns (unless unit_from_entity is true). Check delimiter."
        )
        return False
    if not (
        ("mean" in columns and "min" in columns and "max" in columns)
        or ("sum" in columns)
    ):
        _handle_error(
            "File must contain either ('mean', 'min', 'max') columns or a 'sum' column. Check delimiter."
        )
        return False
    return True


def _get_source(statistic_id: str) -> str:
    if valid_entity_id(statistic_id):
        return "recorder"
    if valid_statistic_id(statistic_id):
        source = statistic_id.split(":")[0]
        if source == "recorder":
            _handle_error(
                f"Invalid statistic_id {statistic_id}. DOMAIN 'recorder' is not allowed."
            )
        return source
    _handle_error(f"Statistic_id {statistic_id} is invalid.")
    return "unknown"


def _add_unit_to_dataframe(
    source: str, unit_from_where: UnitFrom, unit_from_row: str, statistic_id: str
) -> str:
    if source == "recorder":
        if unit_from_where == UnitFrom.ENTITY:
            return ""
        if unit_from_row:
            return unit_from_row
        _handle_error(f"Unit missing for statistic_id: {statistic_id}.")
    if unit_from_where == UnitFrom.ENTITY:
        _handle_error(
            f"unit_from_entity cannot be true for external statistics (like {statistic_id})."
        )
    if not unit_from_row:
        _handle_error(f"Unit missing for external statistic_id: {statistic_id}.")
    return unit_from_row


def _get_sum_stat(
    row: pd.Series, timezone: zoneinfo.ZoneInfo, datetime_format: str
) -> dict:
    if not _is_valid_float(row.get("sum")):
        _handle_error(f"Invalid or missing 'sum' value in row: {row.to_dict()}")
        return {}
    try:
        dt_from_file = datetime.strptime(str(row["start"]), datetime_format)
        start_time_with_tz = dt_from_file.replace(tzinfo=timezone)
        stat = {"start": start_time_with_tz, "sum": float(row["sum"])}
        if "state" in row.index and str(row["state"]) and _is_valid_float(row["state"]):
            stat["state"] = float(row["state"])
        return stat
    except (ValueError, TypeError):
        _handle_error(
            f"Invalid timestamp format for value '{row.get('start', 'N/A')}'. Expected '{datetime_format}'."
        )
        return {}


def _handle_dataframe(
    df: pd.DataFrame,
    timezone_identifier: str,
    datetime_format: str,
    unit_from_where: UnitFrom,
) -> dict:
    if not _are_columns_valid(df, unit_from_where):
        return {}
    stats = {}
    timezone = zoneinfo.ZoneInfo(timezone_identifier)
    has_sum = "sum" in df.columns
    for _index, row in df.iterrows():
        statistic_id = row.get("statistic_id")
        if not statistic_id:
            continue
        if statistic_id not in stats:
            source = _get_source(statistic_id)
            metadata = {
                "has_mean": False,
                "has_sum": has_sum,
                "source": source,
                "statistic_id": statistic_id,
                "name": None,
                "unit_of_measurement": _add_unit_to_dataframe(
                    source, unit_from_where, row.get("unit", ""), statistic_id
                ),
            }
            stats[statistic_id] = (metadata, [])
        if has_sum:
            new_stat = _get_sum_stat(row, timezone, datetime_format)
            if new_stat:
                stats[statistic_id][1].append(new_stat)
    return stats


def _prepare_data_to_import(file_path: str) -> tuple:
    decimal = "."
    timezone_identifier = "Europe/Paris"
    delimiter = ","
    datetime_format = "%d.%m.%Y %H:%M"
    unit_from_entity = UnitFrom.ENTITY

    _LOGGER.info("Importing statistics from file: %s", file_path)
    if not Path(file_path).exists():
        _handle_error(f"File not found: {file_path}")
        return {}, unit_from_entity
    my_df = pd.read_csv(
        file_path,
        sep=delimiter,
        decimal=decimal,
        engine="python",
        skipinitialspace=True,
        dtype=str,
    ).dropna(subset=["statistic_id", "start", "sum"])
    stats = _handle_dataframe(
        my_df, timezone_identifier, datetime_format, unit_from_entity
    )
    return stats, unit_from_entity


def _import_stats_sync(hass: HomeAssistant, stats: dict, unit_from_entity: UnitFrom):
    _LOGGER.info("Validating entities and units...")
    for stat in stats.values():
        metadata = stat[0]
        if metadata["source"] == "recorder":
            entity_id = metadata["statistic_id"]
            entity_state = hass.states.get(entity_id)
            if not entity_state:
                _handle_error(f"Entity does not exist: '{entity_id}'")
            if (
                unit_from_entity == UnitFrom.ENTITY
                and not metadata["unit_of_measurement"]
            ):
                metadata["unit_of_measurement"] = entity_state.attributes.get(
                    "unit_of_measurement"
                )
    return stats


async def _internal_import_file(hass: HomeAssistant, filename: str):
    _LOGGER.info("Starting internal import for file: %s", filename)
    try:
        if not filename:
            _handle_error("Filename cannot be empty.")
            return
        file_path = f"{hass.config.config_dir}/{filename}"
        stats, unit_from_entity = await hass.async_add_executor_job(
            _prepare_data_to_import, file_path
        )
        validated_stats = await hass.async_add_executor_job(
            _import_stats_sync, hass, stats, unit_from_entity
        )
        _LOGGER.info("Importing data into Home Assistant for %s...", filename)
        for stat in validated_stats.values():
            metadata, statistics_data = stat[0], stat[1]
            if not statistics_data:
                _LOGGER.warning(
                    "No valid data points found for statistic_id '%s' in file %s. Skipping.",
                    metadata["statistic_id"],
                    filename,
                )
                continue

            if metadata["source"] == "recorder":
                async_import_statistics(hass, metadata, statistics_data)
            else:
                async_add_external_statistics(hass, metadata, statistics_data)

        basename = os.path.basename(file_path)
        _LOGGER.info("Statistics import task scheduled for file %s.", basename)
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Import Scheduled",
                "message": f"Statistics import for {basename} has been scheduled.",
            },
        )
    except Exception as e:
        _LOGGER.error("Error during import of file %s: %s", filename, e, exc_info=False)
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Import Error",
                "message": f"An error occurred while importing {filename}: {e}",
            },
        )
        raise e


async def async_service_import_statistic(
    hass: HomeAssistant, service_call: ServiceCall
):
    """Service to import statistics from a single file."""
    filename = service_call.data.get("filename")
    await _internal_import_file(hass, filename)


async def async_import_ha_statistics_files(
    hass: HomeAssistant, service_call: ServiceCall
):
    _LOGGER.info("Mass import service for HA history files called.")
    export_dir = Path(f"{hass.config.config_dir}/www/beem_exports")
    if not export_dir.is_dir():
        _LOGGER.warning("Export directory '/config/www/beem_exports' does not exist.")
        return
    files_to_import = list(export_dir.glob("*_import_ha_*.csv"))
    if not files_to_import:
        _LOGGER.info("No HA export files to import were found in %s.", export_dir)
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {"title": "Beem Import", "message": "No files to import were found."},
        )
        return
    _LOGGER.info("%d files found for import. Starting process...", len(files_to_import))
    success_count = 0
    error_count = 0
    for file_path in files_to_import:
        try:
            relative_path = f"www/beem_exports/{file_path.name}"
            await _internal_import_file(hass, relative_path)
            success_count += 1
        except Exception:
            error_count += 1
    message = f"Mass import finished. {success_count} file(s) processed, {error_count} had errors."
    _LOGGER.info(message)
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {"title": "Beem Mass Import", "message": message},
    )


def async_register_import_services(hass: HomeAssistant):
    """Registers the import services."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_STATISTIC,
        partial(async_service_import_statistic, hass),
        schema=IMPORT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_IMPORT_HA_FILES, partial(async_import_ha_statistics_files, hass)
    )


def async_unload_import_services(hass: HomeAssistant):
    """Removes the import services."""
    hass.services.async_remove(DOMAIN, SERVICE_IMPORT_STATISTIC)
    hass.services.async_remove(DOMAIN, SERVICE_IMPORT_HA_FILES)
