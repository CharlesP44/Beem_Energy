# Copyright (c) 2025 CharlesP44 
# SPDX-License-Identifier: MIT
import aiohttp
import time
import logging
from homeassistant.config_entries import ConfigEntry
from .exceptions import BeemAuthError, BeemConnectionError
from .const import (
    BASE_URL,
    MQTT_SERVER,
    MQTT_PORT,
    REST_TOKEN_LIFETIME,
    MQTT_TOKEN_LIFETIME,
)

_LOGGER = logging.getLogger(__name__)

BEEM_429_DELAY = 20 * 60  # 20 min (en secondes)
BEEM_429_MEMKEY = "beem_429_lock_ts"

# ----- Blocage 429 par utilisateur (en RAM) -----
def _beem429_set_lock(hass, email):
    """Active le blocage anti-429 pour un utilisateur."""
    if BEEM_429_MEMKEY not in hass.data:
        hass.data[BEEM_429_MEMKEY] = {}
    hass.data[BEEM_429_MEMKEY][email] = time.time()

def _beem429_clear_lock(hass, email):
    """Supprime le blocage anti-429 pour un utilisateur."""
    if BEEM_429_MEMKEY in hass.data:
        hass.data[BEEM_429_MEMKEY].pop(email, None)

def _beem429_locked(hass, email):
    """Renvoie True si blocage 429 actif pour l'email."""
    d = hass.data.get(BEEM_429_MEMKEY, {})
    ts = d.get(email)
    if ts is None:
        return False
    return (time.time() - ts) < BEEM_429_DELAY

def _beem429_next_try(hass, email):
    d = hass.data.get(BEEM_429_MEMKEY, {})
    ts = d.get(email)
    if ts is None:
        return None
    return ts + BEEM_429_DELAY

# -------------------- API ----------------------

async def try_login(email, password):
    login_url = f"{BASE_URL}/user/login"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                login_url,
                json={"email": email, "password": password},
                headers={"Content-Type": "application/json; charset=UTF-8"}
            ) as resp:
                text = await resp.text()
                if resp.status == 401:
                    raise BeemAuthError("Identifiants invalides")
                elif resp.status == 429:
                    _LOGGER.error("Erreur Beem : trop de requêtes (429) ! Attendez quelques minutes avant de réessayer.")
                    raise BeemConnectionError("Trop de tentatives, limite API atteinte. Réessayez dans 5-30 minutes.")
                elif resp.status >= 500:
                    raise BeemConnectionError("Serveur Beem indisponible")
                elif resp.status not in (200, 201):
                    _LOGGER.error("Erreur Beem login (%s) : %s", resp.status, text)
                    raise Exception("Erreur Beem : " + text)
                data = await resp.json()
                token_rest = data.get("accessToken")
                user_id = data.get("userId")
                if not token_rest or not user_id:
                    raise Exception("AccessToken ou userId manquant")
                return {
                    "access_token": token_rest,
                    "user_id": user_id
                }
    except aiohttp.ClientError as e:
        raise BeemConnectionError("Erreur réseau Beem") from e

async def get_tokens(hass, config_entry: ConfigEntry, email: str, password: str):
    # ----- ANTI-429 PAR UTILISATEUR -----
    if _beem429_locked(hass, email):
        next_try = _beem429_next_try(hass, email)
        wait_minutes = int((next_try - time.time()) // 60) + 1
        msg = f"L'API Beem bloque temporairement les connexions (429) pour {email}. Attendez {wait_minutes} min avant de réessayer."
        _LOGGER.error("⛔ Auth Beem bloquée pour %s suite à un 429. Prochain essai dans %s min.", email, wait_minutes)
        await hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": "Beem Energy - Limite API atteinte",
                "message": msg,
            },
            blocking=True
        )
        raise BeemConnectionError(msg)

    data = dict(config_entry.data)
    now = time.time()

    # 1. Vérification/refresh du token REST
    token_rest = data.get("access_token")
    rest_expires_at = data.get("rest_expires_at", 0)
    user_id = data.get("user_id")
    rest_ok = token_rest and (now < rest_expires_at) and user_id

    if not rest_ok:
        try:
            token_rest, user_id, rest_expires_at = await _refresh_rest_token(hass, email, password)
            data["access_token"] = token_rest
            data["user_id"] = user_id
            data["rest_expires_at"] = rest_expires_at
            _beem429_clear_lock(hass, email)
        except BeemConnectionError as exc:
            if "429" in str(exc).lower() or "limite api" in str(exc).lower():
                _beem429_set_lock(hass, email)
                _LOGGER.error("🔒 Blocage 429 détecté côté Beem API pour %s. Auth désactivée temporairement.", email)
                await hass.services.async_call(
                    "persistent_notification", "create",
                    {
                        "title": "Beem Energy - Blocage API",
                        "message": f"Trop de tentatives (429) pour {email}, Home Assistant attend 20 min avant nouvel essai.",
                    },
                    blocking=True
                )
            raise

    # 2. Génération du clientId
    client_id = data.get("client_id")
    user_id_str = str(user_id)
    if not client_id or not user_id or client_id.find(user_id_str) == -1:
        client_id = f"beemapp-{user_id_str}-{round(now * 1000)}"
        data["client_id"] = client_id

    # 3. Vérification/refresh du token MQTT
    mqtt_token = data.get("mqtt_token")
    mqtt_expires_at = data.get("mqtt_expires_at", 0)
    mqtt_ok = mqtt_token and (now < mqtt_expires_at)
    if not mqtt_ok:
        mqtt_token, mqtt_expires_at = await _refresh_mqtt_token(token_rest, client_id)
        data["mqtt_token"] = mqtt_token
        data["mqtt_expires_at"] = mqtt_expires_at

    # 4. Persiste tout
    hass.config_entries.async_update_entry(config_entry, data=data)

    return {
        "access_token": data["access_token"],
        "user_id": user_id_str,
        "client_id": data["client_id"],
        "mqtt_token": data["mqtt_token"],
        "mqtt_server": MQTT_SERVER,
        "mqtt_port": MQTT_PORT
    }

async def _refresh_rest_token(hass, email, password):
    """Authentifie sur l’API Beem, retourne (token_rest, user_id, expires_at)."""
    login_url = f"{BASE_URL}/user/login"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                login_url,
                json={"email": email, "password": password},
                headers={"Content-Type": "application/json; charset=UTF-8"}
            ) as resp:
                text = await resp.text()
                if resp.status == 401:
                    raise BeemAuthError("Identifiants invalides")
                elif resp.status == 429:
                    _LOGGER.error("Erreur Beem : trop de requêtes (429) pour %s ! Attendez quelques minutes avant de réessayer.", email)
                    _beem429_set_lock(hass, email)
                    raise BeemConnectionError("Trop de tentatives, limite API atteinte. Réessayez dans 5-30 minutes.")
                elif resp.status >= 500:
                    raise BeemConnectionError("Serveur Beem indisponible")
                elif resp.status not in (200, 201):
                    _LOGGER.error("Erreur Beem login (%s) : %s", resp.status, text)
                    raise Exception("Erreur Beem : " + text)

                data = await resp.json()
                token_rest = data.get("accessToken")
                user_id = data.get("userId")

                if not token_rest or not user_id:
                    raise Exception("AccessToken ou userId manquant")

                expires_at = time.time() + REST_TOKEN_LIFETIME
                return token_rest, user_id, expires_at

    except aiohttp.ClientError as e:
        raise BeemConnectionError("Erreur réseau Beem") from e

async def _refresh_mqtt_token(token_rest, client_id):
    """Demande un token MQTT (jwt) avec le token REST. Retourne (token, expires_at)"""
    mqtt_url = f"{BASE_URL}/devices/mqtt/token"
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {token_rest}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            payload = {
                "clientId": client_id,
                "clientType": "user"
            }
            async with session.post(mqtt_url, data=payload, headers=headers) as mqtt_resp:
                mqtt_text = await mqtt_resp.text()
                if mqtt_resp.status != 200:
                    _LOGGER.error("Erreur token MQTT (%s) : %s", mqtt_resp.status, mqtt_text)
                    raise Exception("Impossible d’obtenir le token MQTT")

                mqtt_data = await mqtt_resp.json()
                mqtt_token = mqtt_data.get("jwt")
                if not mqtt_token:
                    raise Exception("Token MQTT manquant")

                expires_at = time.time() + MQTT_TOKEN_LIFETIME
                return mqtt_token, expires_at
    except aiohttp.ClientError as e:
        raise BeemConnectionError("Erreur réseau Beem (MQTT)") from e

# ----------- REST BATTERIES + SOLAR EQUIPMENTS (pour sensors manquants) ---------------

async def get_devices(token_rest):
    url = f"{BASE_URL}/devices"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={"Authorization": f"Bearer {token_rest}"}) as resp:
                text = await resp.text()
                if resp.status != 200:
                    _LOGGER.error("Erreur récupération devices Beem (%s) : %s", resp.status, text)
                    raise Exception("Erreur Beem : " + text)
                payload = await resp.json()
                batteries = payload.get("batteries", [])
                energyswitches = payload.get("energySwitches", [])
                energyswitch_serial = energyswitches[0].get("serialNumber") if energyswitches else None
                return batteries, energyswitch_serial
    except Exception as e:
        _LOGGER.error("Erreur récupération devices Beem: %s", e)
        return [], None

async def get_battery_data(token_rest, battery_serial=None):
    url = f"{BASE_URL}/batteries"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={"Authorization": f"Bearer {token_rest}"}) as resp:
                text = await resp.text()
                if resp.status != 200:
                    _LOGGER.error("Erreur récupération batterie Beem (%s) : %s", resp.status, text)
                    return None
                batteries = await resp.json()
                if not isinstance(batteries, list):
                    return None
                for b in batteries:
                    if battery_serial is None or b.get("serialNumber") == battery_serial:
                        return b
    except Exception as e:
        _LOGGER.error("Erreur REST battery data: %s", e)
    return None

async def get_battery_live(token_rest, battery_serial):
    url = f"{BASE_URL}/batteries/{battery_serial}/live"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={"Authorization": f"Bearer {token_rest}"}) as resp:
                text = await resp.text()
                if resp.status != 200:
                    _LOGGER.error("Erreur récupération live battery Beem (%s) : %s", resp.status, text)
                    return None
                data = await resp.json()
                return data
    except Exception as e:
        _LOGGER.error("Erreur REST battery live: %s", e)
    return None

async def invalidate_tokens(hass, config_entry: ConfigEntry, email):
    data = dict(config_entry.data)
    data["rest_expires_at"] = 0
    data["mqtt_expires_at"] = 0
    hass.config_entries.async_update_entry(config_entry, data=data)
    _LOGGER.info("Tokens Beem invalidés pour %s", email)
    _beem429_clear_lock(hass, email)

async def get_battery_live_data(token_rest, battery_id):
    url = f"{BASE_URL}/batteries/{battery_id}/live-data"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={"Authorization": f"Bearer {token_rest}"}) as resp:
                if resp.status != 200:
                    return {}
                return await resp.json()
    except Exception as e:
        return {}
