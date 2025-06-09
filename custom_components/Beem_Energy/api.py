import aiohttp
import logging
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

BEEM_API_BASE = "https://api-x.beem.energy/beemapp"

class BeemApiClient:
    def __init__(self, email: str, password: str = None, token: str = None, hass=None, entry=None):
        self.email = email
        self.password = password
        self.token = token
        self.hass = hass
        self.entry = entry
        self._timeout = aiohttp.ClientTimeout(total=10)

    def set_password(self, password: str):
        self.password = password

    async def login(self) -> bool:
        if not self.password:
            _LOGGER.error("Mot de passe manquant pour %s", self.email)
            return False

        url = f"{BEEM_API_BASE}/user/login"
        payload = {"email": self.email, "password": self.password}
        headers = {"Content-Type": "application/json"}

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    text = await resp.text()

                    if resp.status not in (200, 201):
                        _LOGGER.error("Échec de la connexion à Beem (%s): %s", resp.status, text)
                        return False

                    try:
                        data = await resp.json()
                    except Exception:
                        _LOGGER.error("Réponse non JSON: %s", text)
                        return False

                    token = data.get("accessToken")
                    if token:
                        self.token = token
                        _LOGGER.info("Token récupéré avec succès pour %s", self.email)

                        if self.hass and self.entry:
                            new_options = {**self.entry.options, "token": token}
                            await self.hass.config_entries.async_update_entry(self.entry, options=new_options)

                        return True
                    else:
                        _LOGGER.error("Token absent dans la réponse: %s", data)
                        return False
        except aiohttp.ClientError as e:
            _LOGGER.exception("Erreur de connexion à l'API Beem : %s", e)
            return False
        except Exception as e:
            _LOGGER.exception("Erreur inattendue lors du login Beem : %s", e)
            return False

    async def _ensure_token(self):
        if not self.token:
            _LOGGER.warning("Token manquant, tentative de reconnexion...")
            return await self.login()
        return True

    async def get_live_data(self, battery_id: int) -> dict | None:
        if not await self._ensure_token():
            return None

        url = f"{BEEM_API_BASE}/batteries/{battery_id}/live-data"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    text = await resp.text()

                    if resp.status == 401:
                        _LOGGER.warning("Token expiré, tentative de reconnexion...")
                        if await self.login():
                            return await self.get_live_data(battery_id)
                        return None

                    if resp.status != 200:
                        _LOGGER.error("Erreur API Beem (%s): %s", resp.status, text)
                        return None

                    try:
                        return await resp.json()
                    except Exception:
                        _LOGGER.error("Réponse non JSON: %s", text)
                        return None
        except aiohttp.ClientError as e:
            _LOGGER.exception("Erreur HTTP lors de la récupération des données : %s", e)
        except Exception as e:
            _LOGGER.exception("Erreur inattendue dans get_live_data : %s", e)

        return None

    async def get_batteries(self) -> list | None:
        if not await self._ensure_token():
            return None

        url = f"{BEEM_API_BASE}/devices"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 401:
                        _LOGGER.warning("Token expiré, tentative de reconnexion...")
                        if await self.login():
                            return await self.get_batteries()
                        return None

                    if resp.status != 200:
                        text = await resp.text()
                        _LOGGER.error("Erreur API lors de get_batteries (%s): %s", resp.status, text)
                        return None

                    data = await resp.json()
                    _LOGGER.debug("Réponse batteries: %s", data)

                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "batteries" in data:
                        return data["batteries"]
                    else:
                        _LOGGER.warning("Structure inattendue dans get_batteries: %s", data)
                        return None
        except Exception as e:
            _LOGGER.exception("Erreur lors de la récupération des batteries: %s", e)
            return None

    async def get_beemboxes(self) -> list[dict]:
        """Récupère les panneaux PnP (beemboxes)."""
        if not await self._ensure_token():
            return []

        url = f"{BEEM_API_BASE}/devices"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status == 401:
                        _LOGGER.warning("Token expiré, tentative de reconnexion...")
                        if await self.login():
                            return await self.get_beemboxes()
                        return []

                    if resp.status != 200:
                        _LOGGER.error("Erreur API dans get_beemboxes (%s): %s", resp.status, text)
                        return []

                    data = await resp.json()
                    return data.get("beemboxes", [])
        except Exception as e:
            _LOGGER.exception("Erreur dans get_beemboxes: %s", e)
            return []

    async def get_beembox_summary(self, month=None, year=None) -> list[dict]:
        """Récupère les données mensuelles (Wh, totalDay, totalMonth) des beemboxes."""
        if not await self._ensure_token():
            return []

        if not month or not year:
            now = datetime.now()
            month = now.month
            year = now.year

        url = f"{BEEM_API_BASE}/box/summary"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        payload = {"month": month, "year": year}

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    text = await resp.text()
                    if resp.status == 401:
                        _LOGGER.warning("Token expiré, tentative de reconnexion...")
                        if await self.login():
                            return await self.get_beembox_summary(month, year)
                        return []

                    if resp.status != 200:
                        _LOGGER.error("Erreur API dans get_beembox_summary (%s): %s", resp.status, text)
                        return []

                    try:
                        return await resp.json()
                    except Exception:
                        _LOGGER.error("Réponse non JSON: %s", text)
                        return []
        except Exception as e:
            _LOGGER.exception("Erreur dans get_beembox_summary: %s", e)
            return []
