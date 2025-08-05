# Copyright (c) 2025 CharlesP44 
# SPDX-License-Identifier: MIT
from homeassistant.helpers.storage import Store
import logging

_LOGGER = logging.getLogger(__name__)

class BeemSecureStorage:
    def __init__(self, hass):
        self._hass = hass
        self._store = Store(hass, 1, "Beem_Energy_passwords")

    async def save_password(self, email: str, password: str):
        data = await self._store.async_load() or {}
        data[email] = password
        await self._store.async_save(data)
        _LOGGER.debug("Mot de passe enregistré de façon sécurisée pour %s", email)

    async def get_password(self, email: str) -> str | None:
        data = await self._store.async_load()
        if data:
            return data.get(email)
        return None

    async def clear_password(self, email: str):
        data = await self._store.async_load() or {}
        if email in data:
            del data[email]
            await self._store.async_save(data)
            _LOGGER.debug("Mot de passe supprimé du stockage sécurisé pour %s", email)
