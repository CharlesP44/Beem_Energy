# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
import logging
from datetime import timedelta
from typing import Any, Dict
import aiohttp
import asyncio
import time

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, BASE_URL
from .exceptions import BeemAuthError, BeemConnectionError
from .utils.merge import merge_live_into_battery
from datetime import datetime, timezone
from .beem_api import (
    get_devices,
    get_tokens,
    get_battery_live_data,
    get_box_summary,
    get_battery_control_parameters,
)


_LOGGER = logging.getLogger(__name__)

# Backoff constants
BACKOFF_429_DELAY = 15 * 60  # 15 minutes for rate limit
BACKOFF_5XX_BASE = 5  # Base delay for 5xx errors (seconds)
BACKOFF_5XX_MAX = 300  # Max backoff (5 minutes)
WARNING_THROTTLE_SECONDS = 60  # Throttle "cannot find serial" warning


class BackoffState:
    """Tracks backoff state for a specific resource (battery serial, energy switch ID, etc.)."""

    def __init__(self):
        self.retry_count = 0
        self.next_allowed_time = 0.0
        self.last_warning_time = 0.0

    def is_allowed(self, now: float) -> bool:
        """Check if operation is allowed (backoff expired)."""
        return now >= self.next_allowed_time

    def can_warn(self, now: float) -> bool:
        """Check if warning should be logged (throttled)."""
        if now - self.last_warning_time >= WARNING_THROTTLE_SECONDS:
            self.last_warning_time = now
            return True
        return False

    def handle_429(self, now: float):
        """Handle 429 (rate limit) error."""
        self.retry_count += 1
        self.next_allowed_time = now + BACKOFF_429_DELAY
        _LOGGER.warning(
            "Rate limit (429) hit. Backing off for %d seconds until %.1f",
            BACKOFF_429_DELAY,
            self.next_allowed_time,
        )

    def handle_5xx(self, now: float):
        """Handle 5xx server errors with exponential backoff."""
        delay = min(BACKOFF_5XX_BASE * (2 ** self.retry_count), BACKOFF_5XX_MAX)
        self.next_allowed_time = now + delay
        self.retry_count += 1
        _LOGGER.warning(
            "Server error (5xx). Exponential backoff: attempt %d, waiting %d seconds",
            self.retry_count,
            delay,
        )

    def reset(self):
        """Reset backoff state on success."""
        self.retry_count = 0
        self.next_allowed_time = 0.0



class BeemCoordinator(DataUpdateCoordinator):
    """Coordonne le polling REST pour les appareils Beem (batteries, etc.)."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry,
        token_rest: str,
        email: str,
        password: str,
    ):
        poll_seconds = int(config_entry.options.get("rest_poll_interval", 120))
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{email}",
            update_interval=timedelta(seconds=poll_seconds),
        )
        self.hass = hass
        self.config_entry = config_entry
        self.token_rest = token_rest
        self.email = email
        self.password = password
        self.es_id: int | None = None

        # Créé le clientId de session de data-stream, une seule fois au démarrage
        # de HA. Il identifie le client (cette instance HA) et est partagé entre
        # batteries et EnergySwitch. Une session Beem dure 30 minutes et est
        # prolongée de 30 minutes à chaque appel POST data-stream portant le
        # même clientId.
        startup_ts = int(datetime.now(timezone.utc).timestamp())
        self._stream_client_id = f"ha-stream-{config_entry.entry_id}-{startup_ts}"

        self.data: Dict[str, Any] = {}
        self.batteries_by_serial: Dict[str, Dict[str, Any]] = {}
        self.solar_equipments_by_mppt: Dict[str, Dict[str, Any]] = {}
        self.solar_equipments_by_serial: Dict[str, list[Dict[str, Any]]] = {}
        self.beemboxes_by_id: Dict[str, Dict[str, Any]] = {}
        self.energyswitch_by_serial: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.es_serial: str | None = None

        # Backoff state management
        self._backoff_streaming_by_serial: Dict[str, BackoffState] = {}
        self._backoff_keepalive_es = BackoffState()
        self._backoff_serial_warning = BackoffState()

    async def _async_update_data(self):
        """
        Récupère les données REST périodiques.
        En cas d'erreur 401 (token expiré), tente de rafraîchir les tokens et de réessayer.
        """
        try:
            return await self._fetch_data_with_token(self.token_rest)
        except BeemAuthError:
            _LOGGER.info(
                "Token REST expiré pour %s. Tentative de rafraîchissement.", self.email
            )
            try:
                new_tokens = await get_tokens(
                    self.hass, self.config_entry, self.email, self.password
                )
                self.token_rest = new_tokens["access_token"]

                entry_data = dict(self.config_entry.data)
                entry_data["access_token"] = self.token_rest
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=entry_data
                )

                _LOGGER.info(
                    "Tokens rafraîchis avec succès pour %s. Nouvelle tentative de récupération des données.",
                    self.email,
                )

                return await self._fetch_data_with_token(self.token_rest)
            except (BeemAuthError, BeemConnectionError) as err:
                raise UpdateFailed(
                    f"Impossible de rafraîchir les tokens ou de se connecter après expiration: {err}"
                )
        except (BeemConnectionError, Exception) as err:
            raise UpdateFailed(
                f"Erreur inattendue lors de la mise à jour des données REST Beem : {err}"
            )

    async def _fetch_data_with_token(self, token: str):
        """Logique de récupération et de normalisation des données."""
        _LOGGER.debug("Début du rafraîchissement des données REST.")

        try:
            _LOGGER.debug("Appel à get_devices et get_box_summary en parallèle.")
            devices_payload, box_summary_data = await asyncio.gather(
                get_devices(token), get_box_summary(token)
            )
            _LOGGER.debug(
                "Données brutes reçues. devices_payload: %s, box_summary_data: %s",
                bool(devices_payload),
                bool(box_summary_data),
            )

            self.batteries_by_serial = {}
            self.solar_equipments_by_mppt = {}
            self.solar_equipments_by_serial = {}
            self.beemboxes_by_id = {}
            self.beemboxes_summary_by_id = {}

            beemboxes_list = []
            solar_equipments_list = []
            main_battery_serial = None
            main_battery = {}

            if box_summary_data:
                self.beemboxes_summary_by_id = {
                    str(summary.get("boxId")): summary
                    for summary in box_summary_data
                    if summary.get("boxId")
                }
                _LOGGER.debug(
                    "%d résumés de BeemBox traités.", len(self.beemboxes_summary_by_id)
                )

            if devices_payload:
                batteries = devices_payload.get("batteries", []) or []
                energyswitches = devices_payload.get("energySwitches", []) or []
                energyswitch_serial = (
                    energyswitches[0].get("serialNumber") if energyswitches else None
                )
                # Stocker l'ID de l'EnergySwitch pour le keep-alive
                if energyswitches and energyswitches[0].get("id"):
                    self.es_id = energyswitches[0].get("id")

                if isinstance(energyswitch_serial, str) and energyswitch_serial.strip():
                    self.es_serial = energyswitch_serial.strip().upper()

                if batteries:
                    _LOGGER.debug("Traitement de %d batterie(s).", len(batteries))
                    for bat in batteries:
                        serial_orig = str(bat.get("serialNumber") or "").strip()
                        serial = serial_orig.upper()
                        if not serial:
                            continue

                        bat_data = dict(bat)
                        battery_id = bat.get("id")
                        if battery_id:
                            live_raw, control_params = await asyncio.gather(
                                get_battery_live_data(token, battery_id),
                                get_battery_control_parameters(token, battery_id),
                            )
                            if live_raw:
                                bat_data = merge_live_into_battery(bat_data, live_raw)
                            bat_data["control_parameters"] = control_params

                        self.batteries_by_serial[serial] = bat_data
                        if main_battery_serial is None:
                            main_battery_serial = serial
                            main_battery = bat_data

                        for equip in bat.get("solarEquipments", []) or []:
                            equip_dict = dict(equip)
                            mppt_id = equip_dict.get("mpptId")
                            if mppt_id:
                                self.solar_equipments_by_mppt[f"{serial}_{mppt_id}"] = (
                                    equip_dict
                                )
                            solar_equipments_list.append(equip_dict)
                        self.solar_equipments_by_serial[serial] = solar_equipments_list

                        for box in bat.get("beemboxes", []) or []:
                            box_dict = dict(box)
                            box_id = box_dict.get("id")
                            if box_id and str(box_id) not in self.beemboxes_by_id:
                                self.beemboxes_by_id[str(box_id)] = box_dict
                                beemboxes_list.append(box_dict)

                top_level_beemboxes = devices_payload.get("beemboxes", []) or []
                if top_level_beemboxes:
                    _LOGGER.debug(
                        "Traitement de %d BeemBox de haut niveau.",
                        len(top_level_beemboxes),
                    )
                    for box in top_level_beemboxes:
                        box_dict = dict(box)
                        box_id = box_dict.get("id")
                        if box_id and str(box_id) not in self.beemboxes_by_id:
                            self.beemboxes_by_id[str(box_id)] = box_dict
                            beemboxes_list.append(box_dict)

            self.data = {
                "battery": main_battery,
                "main_battery_serial": main_battery_serial,
                "batteries": batteries or [],
                "batteries_by_serial": self.batteries_by_serial,
                "energyswitch_serial": self.es_serial or energyswitch_serial,
                "energyswitch_by_serial": self.energyswitch_by_serial,
                "solar_equipments": solar_equipments_list,
                "solar_equipments_by_serial": self.solar_equipments_by_serial,
                "solar_equipments_by_mppt": self.solar_equipments_by_mppt,
                "beemboxes": beemboxes_list,
                "beemboxes_by_id": self.beemboxes_by_id,
                "beemboxes_summary_by_id": self.beemboxes_summary_by_id,
            }

            _LOGGER.debug(
                "Données REST normalisées (main=%s), batteries=%d, beemboxes=%d, summaries=%d",
                main_battery_serial,
                len(self.batteries_by_serial),
                len(self.beemboxes_by_id),
                len(self.beemboxes_summary_by_id),
            )
            return self.data

        except Exception as err:
            _LOGGER.error(
                "Erreur critique inattendue dans _fetch_data_with_token: %s",
                err,
                exc_info=True,
            )
            raise

    async def async_keepalive(self, now=None):
        """Keepalive REST qui imite la séquence de l'app Beem pour maintenir le flux de données actif."""
        _LOGGER.debug("[REST][keepalive] Démarrage du keep-alive...")

        if not self.token_rest:
            _LOGGER.warning("[REST][keepalive] Token REST non disponible, abandon.")
            return

        all_battery_ids: set[str] = set()
        coordinator_data = self.data or {}

        if coordinator_data.get("batteries_by_serial"):
            for bat_data in coordinator_data["batteries_by_serial"].values():
                if isinstance(bat_data, dict) and bat_data.get("id"):
                    all_battery_ids.add(str(bat_data["id"]))

        if not all_battery_ids:
            _LOGGER.debug(
                "[REST][keepalive] Aucun ID de batterie trouvé. Tentative de rafraîchissement global."
            )
            try:
                await self.async_request_refresh()
            except Exception as e:
                _LOGGER.warning(
                    "[REST][keepalive] Échec du rafraîchissement global de secours: %s",
                    e,
                )
            return

        headers = {
            "Authorization": f"Bearer {self.token_rest}",
            "Accept": "application/json",
        }
        client_id = self._stream_client_id

        _LOGGER.debug(
            "[REST][keepalive] IDs à maintenir actifs : %s", list(all_battery_ids)
        )

        async with aiohttp.ClientSession(headers=headers) as session:
            for battery_id in sorted(all_battery_ids):
                try:
                    live_data_url = f"{BASE_URL}/batteries/{battery_id}/live-data"
                    async with session.get(live_data_url) as resp:
                        _LOGGER.debug(
                            "[REST][keepalive] Appel GET %s/live-data -> Status %d",
                            battery_id,
                            resp.status,
                        )
                        await resp.text()

                    data_stream_url = f"{BASE_URL}/batteries/{battery_id}/data-stream"
                    params = {"clientId": client_id}
                    async with session.post(data_stream_url, params=params) as resp:
                        _LOGGER.debug(
                            "[REST][keepalive] Appel POST %s/data-stream -> Status %d",
                            battery_id,
                            resp.status,
                        )
                        await resp.text()

                except aiohttp.ClientError as e:
                    _LOGGER.warning(
                        "[REST][keepalive] Erreur réseau lors du maintien de la session pour l'ID %s: %s",
                        battery_id,
                        e,
                    )
                except Exception as e:
                    _LOGGER.error(
                        "[REST][keepalive] Erreur inattendue pour l'ID %s: %s",
                        battery_id,
                        e,
                        exc_info=True,
                    )

        _LOGGER.debug("[REST][keepalive] Cycle de maintien de session terminé.")

    async def async_ensure_streaming(self, serial: str) -> bool:
        """S'assure que le flux de données MQTT est actif pour une batterie spécifique."""
        _LOGGER.debug(
            "[STREAMING] Demande de maintien du flux pour le serial %s", serial
        )
        if not self.token_rest or not serial:
            return False

        battery_data = self.batteries_by_serial.get(serial.upper())
        if not battery_data or not battery_data.get("id"):
            _LOGGER.warning(
                "[STREAMING] Impossible de trouver l'ID pour le serial %s", serial
            )
            return False

        battery_id = battery_data["id"]

        client_id = self._stream_client_id
        headers = {
            "Authorization": f"Bearer {self.token_rest}",
            "Accept": "application/json",
        }
        data_stream_url = f"{BASE_URL}/batteries/{battery_id}/data-stream"
        params = {"clientId": client_id}

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(data_stream_url, params=params) as resp:
                    if resp.status in (200, 201):
                        _LOGGER.debug(
                            "[STREAMING] Maintien du flux OK pour %s (status %d)",
                            serial,
                            resp.status,
                        )
                        return True
                    else:
                        _LOGGER.warning(
                            "[STREAMING] Échec du maintien du flux pour %s (status %d)",
                            serial,
                            resp.status,
                        )
                        return False
        except Exception as e:
            _LOGGER.error(
                "[STREAMING] Erreur lors du maintien du flux pour %s: %s", serial, e
            )
            return False

    async def async_ensure_streaming(self, serial: str) -> bool:
        """S'assure que le flux de données MQTT est actif pour une batterie spécifique."""
        _LOGGER.debug(
            "[STREAMING] Demande de maintien du flux pour le serial %s", serial
        )
        
        # Get or create backoff state for this serial
        if serial not in self._backoff_streaming_by_serial:
            self._backoff_streaming_by_serial[serial] = BackoffState()
        
        backoff = self._backoff_streaming_by_serial[serial]
        now = time.time()
        
        # Check if backoff period is still active
        if not backoff.is_allowed(now):
            _LOGGER.debug(
                "[STREAMING] Backoff actif pour %s, réessai en %.1f secondes",
                serial,
                backoff.next_allowed_time - now,
            )
            return False
        
        if not self.token_rest or not serial:
            return False

        battery_data = self.batteries_by_serial.get(serial.upper())
        if not battery_data or not battery_data.get("id"):
            if self._backoff_serial_warning.can_warn(now):
                _LOGGER.warning(
                    "[STREAMING] Impossible de trouver l'ID pour le serial %s", serial
                )
            return False

        battery_id = battery_data["id"]

        client_id = self._stream_client_id
        headers = {
            "Authorization": f"******",
            "Accept": "application/json",
        }
        data_stream_url = f"{BASE_URL}/batteries/{battery_id}/data-stream"
        params = {"clientId": client_id}

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(data_stream_url, params=params) as resp:
                    if resp.status in (200, 201):
                        _LOGGER.debug(
                            "[STREAMING] Maintien du flux OK pour %s (status %d)",
                            serial,
                            resp.status,
                        )
                        backoff.reset()
                        return True
                    elif resp.status == 429:
                        backoff.handle_429(now)
                        return False
                    elif resp.status >= 500:
                        backoff.handle_5xx(now)
                        return False
                    else:
                        _LOGGER.warning(
                            "[STREAMING] Échec du maintien du flux pour %s (status %d)",
                            serial,
                            resp.status,
                        )
                        return False
        except Exception as e:
            _LOGGER.error(
                "[STREAMING] Erreur lors du maintien du flux pour %s: %s", serial, e
            )
            return False

    async def async_keepalive_es(self, now=None):
        """Initie ou maintient le flux de données MQTT pour l'EnergySwitch via l'endpoint data-stream."""
        if not self.es_id or not self.token_rest:
            _LOGGER.debug(
                "[KEEP-ALIVE ES] Annulé (ID de l'EnergySwitch ou token REST manquant)."
            )
            return

        # Backoff check
        now_ts = time.time()
        if not self._backoff_keepalive_es.is_allowed(now_ts):
            _LOGGER.debug(
                "[KEEP-ALIVE ES] Backoff actif, réessai en %.1f secondes",
                self._backoff_keepalive_es.next_allowed_time - now_ts,
            )
            return

        _LOGGER.debug(
            "[KEEP-ALIVE ES] Maintien du flux de données pour l'ID %s.", self.es_id
        )

        url = f"{BASE_URL}/energy-switches/{self.es_id}/data-stream"
        headers = {
            "Authorization": f"******",
            "Accept": "application/json",
        }
        client_id = self._stream_client_id
        params = {"clientId": client_id}

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(url, params=params) as resp:
                    if resp.status in (200, 201):
                        _LOGGER.debug(
                            "[KEEP-ALIVE ES] Maintien du flux réussi (status %d) pour l'ID %s.",
                            resp.status,
                            self.es_id,
                        )
                        self._backoff_keepalive_es.reset()
                    elif resp.status == 429:
                        self._backoff_keepalive_es.handle_429(now_ts)
                    elif resp.status >= 500:
                        self._backoff_keepalive_es.handle_5xx(now_ts)
                    else:
                        _LOGGER.warning(
                            "[KEEP-ALIVE ES] Échec du maintien du flux (status %d) pour l'ID %s.",
                            resp.status,
                            self.es_id,
                        )
                    await resp.text()
        except Exception as e:
            _LOGGER.error(
                "[KEEP-ALIVE ES] Erreur inattendue lors du maintien du flux pour l'ID %s: %s",
                self.es_id,
                e,
                exc_info=True,
            )


def _coordinator_key(entry_id: str) -> str:
    return f"beem_coordinator_{entry_id}"


async def get_beem_coordinator(hass, config_entry, token_rest, email, password):
    key = _coordinator_key(config_entry.entry_id)
    if key not in hass.data:
        hass.data[key] = BeemCoordinator(
            hass, config_entry, token_rest, email, password
        )
        await hass.data[key].async_config_entry_first_refresh()
    return hass.data[key]


def async_remove_beem_coordinator(hass, entry_id: str) -> None:
    """Retire le coordinator mis en cache pour éviter une instance fantôme après reload."""
    hass.data.pop(_coordinator_key(entry_id), None)
