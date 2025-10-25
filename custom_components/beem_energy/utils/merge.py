# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
from typing import Dict, Any

# Clés de la batterie qui NE doivent PAS être écrasées par le live
PROTECTED_FIELDS = {
    "id",
    "serialNumber",
    "batteryId",
}

# Aliases possibles pour la date dans le live (selon payload)
DATE_ALIASES = ("lastKnownMeasureDate", "ts", "timestamp", "date")


def _first_present(d: Dict[str, Any], keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _flatten_live_payload(d: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(d, dict):
        return {}
    for inner_key in ("data", "result", "payload", "live", "live_data"):
        inner = d.get(inner_key)
        if isinstance(inner, dict) and inner:
            return inner
    return d


def merge_live_into_battery(
    battery: Dict[str, Any], live_raw: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge *direct* du live-data au niveau racine de la batterie.
    - aplati (data/result/payload/live)
    - écrase les clés existantes *sauf* PROTECTED_FIELDS
    - ignore les valeurs None
    - normalise lastKnownMeasureDate à partir d'aliases connus
    - conserve le live brut sous _live_raw (debug)
    """
    if not isinstance(battery, dict):
        battery = {}
    if not isinstance(live_raw, dict):
        battery.setdefault("_live_raw", live_raw)
        return battery

    flat_live = _flatten_live_payload(live_raw)

    # merge direct
    for k, v in flat_live.items():
        if v is None:
            continue
        if k in PROTECTED_FIELDS:
            continue
        battery[k] = v

    # lastKnownMeasureDate
    lkmd = _first_present({**battery, **flat_live}, DATE_ALIASES)
    if lkmd is not None:
        battery["lastKnownMeasureDate"] = lkmd

    # garder une trace du live brut
    battery["_live_raw"] = live_raw
    return battery
