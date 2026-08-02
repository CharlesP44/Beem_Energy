# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
import logging
import ssl
import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType
from aiomqtt import Client, ProtocolVersion
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PLATFORMS
from .beem_api import get_tokens, get_devices
from .coordinator import get_beem_coordinator, async_remove_beem_coordinator
from .exceptions import BeemConnectionError
from . import services

CONFIG_SCHEMA = cv.empty_config_schema("beem_energy")

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Initialisation globale, vide ici."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialisation d'une entrée de configuration."""
    data = entry.data
    email = data.get("email")
    password = data.get("password")

    try:
        tokens = await get_tokens(hass, entry, email, password)
    except BeemConnectionError as err:
        msg = str(err).lower()
        if "429" in msg or "limite api" in msg or "bloqu" in msg or "réessayez" in msg:
            raise ConfigEntryNotReady(str(err)) from err
        raise

    client_id = tokens["client_id"]
    token_mqtt = tokens["mqtt_token"]
    user_id = tokens["user_id"]
    token_rest = tokens["access_token"]

    try:
        devices_payload = await get_devices(token_rest)
        batteries = devices_payload.get("batteries", []) or []
        energyswitches = devices_payload.get("energySwitches", []) or []
        energyswitch_serial = (
            energyswitches[0].get("serialNumber") if energyswitches else None
        )
    except Exception as err:
        raise ConfigEntryNotReady(f"Beem devices indisponibles: {err}") from err

    if batteries:
        for bat in batteries:
            if "serialNumber" in bat and bat["serialNumber"]:
                bat["serialNumber"] = str(bat["serialNumber"]).strip().upper()
    if energyswitch_serial:
        energyswitch_serial = str(energyswitch_serial).strip().upper()

    if not all([client_id, token_mqtt, user_id]):
        _LOGGER.error("Tokens Beem incomplets (client_id/mqtt_token/user_id).")
        raise ConfigEntryNotReady("Erreur d'authentification (temporaire ?).")

    try:

        def make_ssl_context():
            ctx = ssl.create_default_context()
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
            return ctx

        context = await hass.async_add_executor_job(make_ssl_context)
        mqtt_client = Client(
            hostname=tokens.get("mqtt_server", "mqtt.beem.energy"),
            port=tokens.get("mqtt_port", 8084),
            username="unused",
            password=token_mqtt,
            tls_context=context,
            transport="websockets",
            protocol=ProtocolVersion.V5,
            identifier=client_id,
            keepalive=45,
        )
    except Exception as err:
        _LOGGER.error("Échec de la connexion MQTT à Beem: %s", err)
        raise ConfigEntryNotReady from err

    _LOGGER.info(
        "MQTT connecté à %s:%s",
        tokens.get("mqtt_server", "mqtt.beem.energy"),
        tokens.get("mqtt_port", 8084),
    )

    energyswitch_topic = None
    if energyswitch_serial:
        energyswitch_topic = f"brain/{energyswitch_serial}"
        _LOGGER.info("🔌 Topic MQTT energyswitch (online): %s", energyswitch_topic)

    # Détection d'éventuelles maisons multiples : préférer l'endpoint paginated si disponible,
    # sinon tomber en fallback sur les houseId présents sur les appareils.
    house_ids: set[str] = set()

    try:
        from .beem_api import get_houses as _get_houses

        houses_list = await _get_houses(token_rest)
        for h in houses_list or []:
            hid = h.get("id") or h.get("houseId")
            if hid:
                house_ids.add(str(hid))
    except Exception:
        # ignore et fallback
        pass

    # Fallback : collecter houseId depuis les devices retournés par /devices
    if not house_ids and devices_payload:
        for bat in batteries:
            hid = bat.get("houseId") or bat.get("house_id")
            if hid:
                house_ids.add(str(hid))
        for box in devices_payload.get("beemboxes", []) or []:
            hid = box.get("houseId") or box.get("house_id")
            if hid:
                house_ids.add(str(hid))

    if len(house_ids) <= 1:
        # Comportement inchangé pour 0 ou 1 maison
        coordinator = await get_beem_coordinator(hass, entry, token_rest, email, password)
        stored_coordinator = coordinator
        coordinators_map = None
    else:
        # Crée un coordinator par maison. Ne pas agréger — conserver le premier en 'coordinator' pour compatibilité.
        coordinators_map: dict[str, object] = {}
        for hid in sorted(house_ids):
            c = await get_beem_coordinator(
                hass, entry, token_rest, email, password, house_id=hid
            )
            coordinators_map[hid] = c
        # Garder le premier coordinator comme valeur 'coordinator' pour compatibilité descendante
        first_hid = sorted(house_ids)[0]
        stored_coordinator = coordinators_map[first_hid]

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "mqtt_client": mqtt_client,
        "user_id": user_id,
        "client_id": client_id,
        "token_rest": token_rest,
        "batteries": batteries,
        "energyswitch_topic": energyswitch_topic,
        "energyswitch_serial": energyswitch_serial,
        "coordinator": stored_coordinator,
        "coordinators": coordinators_map,
        "mqtt_task": None,
    }

    _LOGGER.debug(
        "[INIT] Entry %s : batteries=%s, energyswitch=%s, user_id=%s",
        entry.entry_id,
        [b.get("serialNumber") for b in batteries],
        energyswitch_serial,
        user_id,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    services.async_register_services(hass, entry)

    _LOGGER.info("[INIT] Setup_entry terminé pour %s.", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nettoyage à la suppression de l'intégration."""
    _LOGGER.info("Déchargement de l'intégration Beem Energy pour %s", entry.entry_id)

    services.async_unload_services(hass)

    platforms_unloaded = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )

    if platforms_unloaded:
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)

        if entry_data:
            mqtt_client = entry_data.get("mqtt_client")
            if mqtt_client:
                try:
                    await mqtt_client.__aexit__(None, None, None)
                    _LOGGER.info("Client MQTT Cloud Beem fermé proprement.")
                except Exception as e:
                    _LOGGER.warning(
                        "Erreur lors de la fermeture du client MQTT : %s", e
                    )

            # Cancel periodic tasks (timers) to avoid leaks after reload/unload
            timed_tasks = entry_data.get("timed_tasks", [])
            if timed_tasks:
                _LOGGER.info("Annulation de %d tâches périodiques (timers).", len(timed_tasks))
                for cancel_task in list(timed_tasks):
                    try:
                        # cancel_task is the unsubscribe/cancel callable returned by async_track_time_interval
                        cancel_task()
                    except Exception as e:
                        _LOGGER.debug("Erreur lors de l'annulation d'une tâche périodique: %s", e)

            # Cancel the beem cloud listener task if present
            beem_task = entry_data.get("beem_cloud_task_battery")
            if beem_task:
                try:
                    if hasattr(beem_task, "cancel"):
                        beem_task.cancel()
                        # Await it briefly to allow cancellation to propagate
                        try:
                            await beem_task
                        except asyncio.CancelledError:
                            _LOGGER.debug("beem_cloud_task_battery annulé avec succès")
                        except Exception as e:
                            _LOGGER.debug("Erreur lors de l'attente d'annulation de beem_task: %s", e)
                except Exception as e:
                    _LOGGER.debug("Erreur lors de l'annulation du beem_cloud_task_battery: %s", e)

            hass.data[DOMAIN].pop(entry.entry_id, None)
            _LOGGER.info(
                "Données pour l'entrée %s nettoyées de hass.data.", entry.entry_id
            )

        async_remove_beem_coordinator(hass, entry.entry_id)
    else:
        _LOGGER.error("Échec du déchargement des plateformes pour %s.", entry.entry_id)

    return platforms_unloaded
