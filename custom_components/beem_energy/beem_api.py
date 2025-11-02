# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
import aiohttp
import time
import logging
from homeassistant.config_entries import ConfigEntry

from datetime import datetime
from .exceptions import BeemAuthError, BeemConnectionError
from .const import (
    BASE_URL,
    MQTT_SERVER,
    MQTT_PORT,
    REST_TOKEN_LIFETIME,
    MQTT_TOKEN_LIFETIME,
)

_LOGGER = logging.getLogger(__name__)

BEEM_429_DELAY = 20 * 60  # 20 min en secondes
BEEM_429_MEMKEY = "beem_429_lock_ts"
BEEM_429_LAST_NOTIF = "beem_429_last_notif_ts"


def _beem429_set_lock(hass, email: str) -> None:
    """Active le blocage anti-429 pour un utilisateur."""
    hass.data.setdefault(BEEM_429_MEMKEY, {})
    hass.data[BEEM_429_MEMKEY][email] = time.time()


def _beem429_clear_lock(hass, email: str) -> None:
    """Supprime le blocage anti-429 pour un utilisateur."""
    if BEEM_429_MEMKEY in hass.data:
        hass.data[BEEM_429_MEMKEY].pop(email, None)


def _beem429_locked(hass, email: str) -> bool:
    """True si un blocage 429 est actif pour l'email."""
    ts = hass.data.get(BEEM_429_MEMKEY, {}).get(email)
    if ts is None:
        return False
    return (time.time() - ts) < BEEM_429_DELAY


def _beem429_next_try(hass, email: str) -> float | None:
    ts = hass.data.get(BEEM_429_MEMKEY, {}).get(email)
    if ts is None:
        return None
    return ts + BEEM_429_DELAY


async def _notify_rate_limit(hass, title: str, message: str) -> None:
    """Crée une notification persistante (dédupliquée ~5 min)."""
    now = time.time()
    last = hass.data.setdefault(BEEM_429_LAST_NOTIF, 0)
    if now - last < 300:
        return
    hass.data[BEEM_429_LAST_NOTIF] = now
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {"title": title, "message": message},
            blocking=True,
        )
    except Exception as e:
        _LOGGER.warning(
            "Impossible de créer la notification persistante '%s'. Erreur: %s", title, e
        )


async def try_login(email: str, password: str) -> dict:
    """Test de login simple (non utilisé par l’intégration en routine)."""
    login_url = f"{BASE_URL}/user/login"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                login_url,
                json={"email": email, "password": password},
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "Accept": "application/json",
                },
            ) as resp:
                text = await resp.text()
                if resp.status == 401:
                    raise BeemAuthError("Identifiants invalides")
                if resp.status == 429:
                    _LOGGER.error(
                        "Erreur Beem : trop de requêtes (429) ! Attendez quelques minutes avant de réessayer."
                    )
                    raise BeemConnectionError(
                        "Trop de tentatives, limite API atteinte. Réessayez dans 5-30 minutes."
                    )
                if resp.status >= 500:
                    raise BeemConnectionError("Serveur Beem indisponible")
                if resp.status not in (200, 201):
                    _LOGGER.error("Erreur Beem login (%s) : %s", resp.status, text)
                    raise Exception("Erreur Beem : " + text)

                data = await resp.json()
                token_rest = data.get("accessToken")
                user_id = data.get("userId")
                if not token_rest or not user_id:
                    raise Exception("AccessToken ou userId manquant")
                return {"access_token": token_rest, "user_id": user_id}
    except aiohttp.ClientError as e:
        raise BeemConnectionError("Erreur réseau Beem") from e


async def get_tokens(
    hass, config_entry: ConfigEntry, email: str, password: str
) -> dict:
    """Récupère/rafraîchit les tokens REST & MQTT avec anti-429 par utilisateur."""
    if _beem429_locked(hass, email):
        next_try = _beem429_next_try(hass, email)
        wait_minutes = (
            max(1, int((next_try - time.time()) // 60) + 1) if next_try else 20
        )
        msg = (
            f"L'API Beem bloque temporairement les connexions (429) pour {email}. "
            f"Attendez ~{wait_minutes} min avant de réessayer."
        )
        _LOGGER.error(
            "⛔ Auth Beem bloquée pour %s suite à un 429. Prochain essai ~%s min.",
            email,
            wait_minutes,
        )
        await _notify_rate_limit(hass, "Beem Energy - Limite API atteinte", msg)
        raise BeemConnectionError(msg)

    data = dict(config_entry.data)
    now = time.time()

    token_rest = data.get("access_token")
    rest_expires_at = data.get("rest_expires_at", 0)
    user_id = data.get("user_id")
    rest_ok = token_rest and user_id and (now < rest_expires_at)

    if not rest_ok:
        try:
            token_rest, user_id, rest_expires_at = await _refresh_rest_token(
                hass, email, password
            )
            data["access_token"] = token_rest
            data["user_id"] = user_id
            data["rest_expires_at"] = rest_expires_at
            _beem429_clear_lock(hass, email)
        except BeemConnectionError as exc:
            # Si c'est un 429, verrouille et notifie, puis propage
            if "429" in str(exc).lower() or "limite api" in str(exc).lower():
                _beem429_set_lock(hass, email)
                _LOGGER.error(
                    "🔒 Blocage 429 détecté pour %s. Auth désactivée temporairement.",
                    email,
                )
                await _notify_rate_limit(
                    hass,
                    "Beem Energy - Blocage API",
                    f"Trop de tentatives (429) pour {email}, Home Assistant attend ~20 min avant un nouvel essai.",
                )
            raise

    client_id = data.get("client_id")
    user_id_str = str(user_id)
    if not client_id or not user_id or user_id_str not in client_id:
        client_id = f"beemapp-{user_id_str}-{round(now * 1000)}"
        data["client_id"] = client_id

    mqtt_token = data.get("mqtt_token")
    mqtt_expires_at = data.get("mqtt_expires_at", 0)
    mqtt_ok = mqtt_token and (now < mqtt_expires_at)
    if not mqtt_ok:
        mqtt_token, mqtt_expires_at = await _refresh_mqtt_token(token_rest, client_id)
        data["mqtt_token"] = mqtt_token
        data["mqtt_expires_at"] = mqtt_expires_at

    hass.config_entries.async_update_entry(config_entry, data=data)

    return {
        "access_token": data["access_token"],
        "user_id": user_id_str,
        "client_id": data["client_id"],
        "mqtt_token": data["mqtt_token"],
        "mqtt_server": MQTT_SERVER,
        "mqtt_port": MQTT_PORT,
    }


async def _refresh_rest_token(
    hass, email: str, password: str
) -> tuple[str, str, float]:
    """Authentifie sur l’API Beem, retourne (token_rest, user_id, expires_at)."""
    login_url = f"{BASE_URL}/user/login"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                login_url,
                json={"email": email, "password": password},
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "Accept": "application/json",
                },
            ) as resp:
                text = await resp.text()
                if resp.status == 401:
                    raise BeemAuthError("Identifiants invalides")
                if resp.status == 429:
                    _LOGGER.error(
                        "Erreur Beem : trop de requêtes (429) pour %s ! Attendez quelques minutes avant de réessayer.",
                        email,
                    )
                    _beem429_set_lock(hass, email)
                    raise BeemConnectionError(
                        "Trop de tentatives, limite API atteinte. Réessayez dans 5-30 minutes."
                    )
                if resp.status >= 500:
                    raise BeemConnectionError("Serveur Beem indisponible")
                if resp.status not in (200, 201):
                    _LOGGER.error("Erreur Beem login (%s) : %s", resp.status, text)
                    raise Exception("Erreur Beem : " + text)

                data = await resp.json()
                token_rest = data.get("accessToken")
                user_id = data.get("userId")
                if not token_rest or not user_id:
                    raise Exception("AccessToken ou userId manquant")

                expires_at = time.time() + REST_TOKEN_LIFETIME
                return token_rest, str(user_id), expires_at
    except aiohttp.ClientError as e:
        raise BeemConnectionError("Erreur réseau Beem") from e


async def _refresh_mqtt_token(token_rest: str, client_id: str) -> tuple[str, float]:
    """Demande un token MQTT (JWT) avec le token REST. Retourne (token, expires_at)."""
    mqtt_url = f"{BASE_URL}/devices/mqtt/token"
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {token_rest}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }
            payload = {"clientId": client_id, "clientType": "user"}
            async with session.post(
                mqtt_url, data=payload, headers=headers
            ) as mqtt_resp:
                mqtt_text = await mqtt_resp.text()
                if mqtt_resp.status == 429:
                    raise BeemConnectionError("Limite API MQTT atteinte (429).")
                if mqtt_resp.status != 200:
                    _LOGGER.error(
                        "Erreur token MQTT (%s) : %s", mqtt_resp.status, mqtt_text
                    )
                    raise Exception("Impossible d’obtenir le token MQTT")

                mqtt_data = await mqtt_resp.json()
                mqtt_token = mqtt_data.get("jwt")
                if not mqtt_token:
                    raise Exception("Token MQTT manquant")

                expires_at = time.time() + MQTT_TOKEN_LIFETIME
                return mqtt_token, expires_at
    except aiohttp.ClientError as e:
        raise BeemConnectionError("Erreur réseau Beem (MQTT)") from e


async def get_box_summary(token_rest: str) -> list:
    """Récupère le résumé de production des BeemBox pour le mois en cours."""
    url = f"{BASE_URL}/box/summary"
    now = datetime.now()
    payload = {"month": now.month, "year": now.year}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers={
                    "Authorization": f"Bearer {token_rest}",
                    "Accept": "application/json",
                },
                json=payload,
            ) as resp:
                if resp.status not in (200, 201):
                    _LOGGER.warning(
                        "Erreur récupération BeemBox summary (%s) : %s",
                        resp.status,
                        await resp.text(),
                    )
                    return []
                return await resp.json()
    except aiohttp.ClientError as e:
        _LOGGER.error("Erreur réseau Beem (Box Summary): %s", e)
        return []
    except Exception as e:
        _LOGGER.error("Erreur inattendue Beem (Box Summary): %s", e)
        return []


async def get_devices(token_rest: str) -> dict:
    """Retourne le payload complet de l'endpoint /devices. Propage les erreurs temporaires."""
    url = f"{BASE_URL}/devices"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={
                    "Authorization": f"Bearer {token_rest}",
                    "Accept": "application/json",
                },
            ) as resp:
                text = await resp.text()
                if resp.status == 401:
                    raise BeemAuthError("Token expiré ou invalide")
                if resp.status == 429:
                    raise BeemConnectionError("Limite API atteinte (429) sur /devices.")
                if resp.status >= 500:
                    raise BeemConnectionError("Serveur Beem indisponible (/devices)")
                if resp.status not in (200, 201):
                    _LOGGER.error(
                        "Erreur récupération devices Beem (%s) : %s", resp.status, text
                    )
                    raise Exception("Erreur Beem : " + text)

                return await resp.json()
    except BeemConnectionError:
        raise
    except Exception as e:
        _LOGGER.error("Erreur récupération devices Beem: %s", e)
        return {}


async def get_battery_data(token_rest: str, battery_serial: str | None = None):
    url = f"{BASE_URL}/batteries"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={
                    "Authorization": f"Bearer {token_rest}",
                    "Accept": "application/json",
                },
            ) as resp:
                text = await resp.text()
                if resp.status not in (200, 201):
                    _LOGGER.error(
                        "Erreur récupération batterie Beem (%s) : %s", resp.status, text
                    )
                    return None
                batteries = await resp.json()
                if not isinstance(batteries, list):
                    return None
                for b in batteries:
                    if (
                        battery_serial is None
                        or b.get("serialNumber") == battery_serial
                    ):
                        return b
    except Exception as e:
        _LOGGER.error("Erreur REST battery data: %s", e)
    return None


async def get_battery_live(token_rest: str, battery_serial: str):
    url = f"{BASE_URL}/batteries/{battery_serial}/live"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={
                    "Authorization": f"Bearer {token_rest}",
                    "Accept": "application/json",
                },
            ) as resp:
                text = await resp.text()
                if resp.status not in (200, 201):
                    _LOGGER.error(
                        "Erreur récupération live battery Beem (%s) : %s",
                        resp.status,
                        text,
                    )
                    return None
                data = await resp.json()
                return data
    except Exception as e:
        _LOGGER.error("Erreur REST battery live: %s", e)
    return None


async def invalidate_tokens(hass, config_entry: ConfigEntry, email: str) -> None:
    """Force l’expiration des tokens pour un prochain refresh et lève le verrou 429."""
    data = dict(config_entry.data)
    data["rest_expires_at"] = 0
    data["mqtt_expires_at"] = 0
    hass.config_entries.async_update_entry(config_entry, data=data)
    _LOGGER.info("Tokens Beem invalidés pour %s", email)
    _beem429_clear_lock(hass, email)


async def get_battery_live_data(token_rest: str, battery_id: int) -> dict:
    """Endpoint live-data (utilisé par le coordinator pour keep-alive)."""
    url = f"{BASE_URL}/batteries/{battery_id}/live-data"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={
                    "Authorization": f"Bearer {token_rest}",
                    "Accept": "application/json",
                },
            ) as resp:
                if resp.status not in (200, 201):
                    return {}
                return await resp.json()
    except Exception:
        return {}


async def get_battery_control_parameters(token_rest: str, battery_id: int) -> dict:
    """Récupère les paramètres de contrôle actuels de la batterie (mode, etc.)."""
    url = f"{BASE_URL}/batteries/{battery_id}/control-parameters"

    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {token_rest}",
                "Accept": "application/json",
            }
            async with session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    raise BeemAuthError(
                        "Token expiré ou invalide (get_control_parameters)"
                    )
                if resp.status not in (200, 201):
                    _LOGGER.warning(
                        "Impossible de récupérer les paramètres de contrôle pour la batterie %s (status: %s)",
                        battery_id,
                        resp.status,
                    )
                    return {}
                return await resp.json()
    except aiohttp.ClientError:
        _LOGGER.warning(
            "Erreur réseau Beem (get_control_parameters) pour la batterie %s",
            battery_id,
        )
        return {}


async def set_battery_control_parameters(
    token_rest: str, battery_id: int, params: dict
) -> bool:
    """Modifie un ou plusieurs paramètres de contrôle de la batterie."""
    url = f"{BASE_URL}/batteries/{battery_id}/control-parameters"

    _LOGGER.debug(
        "Modification des paramètres de la batterie %s -> %s", battery_id, params
    )

    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {token_rest}",
                "Content-Type": "application/json; charset=UTF-8",
                "Accept": "application/json",
            }
            async with session.patch(url, json=params, headers=headers) as resp:
                text = await resp.text()
                if resp.status not in (200, 201, 204):
                    _LOGGER.error(
                        "Erreur Beem modification des paramètres (%s) : %s",
                        resp.status,
                        text,
                    )
                    raise Exception(f"Erreur Beem : {text}")

                _LOGGER.info(
                    "Paramètres de la batterie %s modifiés avec succès : %s",
                    battery_id,
                    params,
                )
                return True
    except aiohttp.ClientError as e:
        raise BeemConnectionError(f"Erreur réseau Beem (set_parameters): {e}") from e
