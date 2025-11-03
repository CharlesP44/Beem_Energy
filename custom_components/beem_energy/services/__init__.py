# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .export_csv import async_register_export_services, async_unload_export_services
from .import_statistic import (
    async_register_import_services,
    async_unload_import_services,
)


def async_register_services(hass: HomeAssistant, entry: ConfigEntry):
    async_register_export_services(hass, entry)
    async_register_import_services(hass)


def async_unload_services(hass: HomeAssistant):
    async_unload_export_services(hass)
    async_unload_import_services(hass)
