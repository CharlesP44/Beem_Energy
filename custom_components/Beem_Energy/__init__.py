import logging
import ssl
import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType
from aiomqtt import Client, ProtocolVersion

from .const import DOMAIN, PLATFORMS
from .beem_api import get_tokens, get_devices
from .coordinator import get_beem_coordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Initialisation globale, vide ici."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialisation d'une entrée de configuration."""
    data = entry.data
    email = data.get("email")
    password = data.get("password")

    # 1. Récupère les tokens (REST et MQTT, cache & refresh auto)
    tokens = await get_tokens(hass, entry, email, password)
    client_id = tokens["client_id"]
    token_mqtt = tokens["mqtt_token"]
    user_id = tokens["user_id"]
    token_rest = tokens["access_token"]

    # 2. Récupère la liste des batteries & energyswitch (REST direct, fallback)
    batteries, energyswitch_serial = await get_devices(token_rest)
    # ---- Conversion serials MAJUSCULE
    if batteries:
        for bat in batteries:
            if "serialNumber" in bat and bat["serialNumber"]:
                bat["serialNumber"] = str(bat["serialNumber"]).strip().upper()
    if energyswitch_serial:
        energyswitch_serial = str(energyswitch_serial).strip().upper()

    if not all([client_id, token_mqtt, user_id]) or not batteries:
        _LOGGER.error("Impossible de récupérer les tokens Beem ou les batteries.")
        raise ConfigEntryNotReady("Erreur d'authentification ou batterie absente.")

    # 3. Préparation du MQTT (asynchrone, sécurisé)
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
        )
        await mqtt_client.__aenter__()
    except Exception as err:
        _LOGGER.error("Échec de la connexion MQTT à Beem: %s", err)
        raise ConfigEntryNotReady from err

    _LOGGER.info("MQTT connecté à %s:%s", tokens.get("mqtt_server", "mqtt.beem.energy"), tokens.get("mqtt_port", 8084))

    # 4. Prépare topic energyswitch s'il y a lieu
    energyswitch_topic = None
    if energyswitch_serial:
        energyswitch_topic = f"brain/{energyswitch_serial}"
        _LOGGER.info("🔌 Topic MQTT energyswitch (online): %s", energyswitch_topic)

    # 5. Instancie le coordinator REST pour ce user/entry
    coordinator = await get_beem_coordinator(hass, entry, token_rest, email)

    # 6. Stocke toutes les infos par entrée/utilisateur (ISOLATION COMPLÈTE)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "mqtt_client": mqtt_client,
        "user_id": user_id,
        "client_id": client_id,
        "token_rest": token_rest,
        "batteries": batteries,  # REST snapshot, pour compat
        "energyswitch_topic": energyswitch_topic,
        "coordinator": coordinator,
        "mqtt_task": None,   # La vraie task est set par sensor.py !
    }

    _LOGGER.debug("[INIT] Entry %s : batteries=%s, energyswitch=%s, user_id=%s",
                  entry.entry_id, batteries, energyswitch_serial, user_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("[INIT] Setup_entry terminé pour %s.", entry.entry_id)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nettoyage à la suppression de l'intégration."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    mqtt_client = entry_data.get("mqtt_client")
    task = entry_data.get("mqtt_task")
    unloaded = True

    # Annule la tâche MQTT (robuste)
    if task:
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=5)
            _LOGGER.debug("Tâche MQTT correctement annulée pour %s", entry.entry_id)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout lors de l'annulation de la tâche MQTT : %s", entry.entry_id)
        except asyncio.CancelledError:
            _LOGGER.debug("Tâche MQTT annulée pour %s", entry.entry_id)
        except Exception as e:
            _LOGGER.warning("Exception inattendue lors de l'annulation de la tâche MQTT : %s", e)
            unloaded = False

    # Ferme le client MQTT proprement
    if mqtt_client:
        try:
            await mqtt_client.__aexit__(None, None, None)
        except Exception as e:
            _LOGGER.warning("Erreur lors de la fermeture MQTT : %s", e)
    else:
        _LOGGER.debug("Aucun client MQTT à fermer pour %s", entry.entry_id)

    platforms_unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if platforms_unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        _LOGGER.info("[INIT] Unload_entry terminé pour %s.", entry.entry_id)
    return platforms_unloaded and unloaded
