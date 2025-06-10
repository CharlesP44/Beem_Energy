"""Beem Integration - Init file."""

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import BeemCoordinator
from .config_flow import BeemOptionsFlowHandler
from .storage import BeemSecureStorage
from .api import BeemApiClient

PLATFORMS = ["sensor"]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Beem Integration from a config entry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    email = entry.data.get("email")
    battery_id = entry.data.get("battery_id")  # Optional, can be None

    if not email:
        _LOGGER.error("L'adresse e-mail est manquante dans l'entrée de configuration.")
        return False

    # Retrieve password securely from storage
    storage = BeemSecureStorage(hass)
    password = await storage.get_password(email)

    if not password:
        _LOGGER.error("Mot de passe introuvable pour %s. Impossible de configurer l'intégration.", email)
        return False

    token = entry.options.get("token")

    # Create Beem API client
    api_client = BeemApiClient(
        email=email,
        password=password,
        token=token,
        hass=hass,
        entry=entry,
    )

    # Attempt login if no token is present
    if not token:
        try:
            login_ok = await api_client.login()
        except Exception as err:
            _LOGGER.exception("Exception lors de la tentative de connexion à l'API Beem")
            raise ConfigEntryNotReady from err

        if not login_ok:
            _LOGGER.error("Connexion API Beem échouée pour l'utilisateur %s", email)
            return False

        token = api_client.token
        _LOGGER.info("Token obtenu avec succès depuis l'API.")

    # Create and refresh coordinator
    coordinator = BeemCoordinator(
        hass=hass,
        api=api_client,
        battery_id=battery_id,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.error("Erreur lors du premier rafraîchissement des données : %s", err)
        raise ConfigEntryNotReady from err

    hass.data[DOMAIN][entry.entry_id] = coordinator

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception as err:
        _LOGGER.error("Erreur lors du chargement des plateformes : %s", err)
        raise ConfigEntryNotReady from err

    _LOGGER.info("Intégration Beem configurée avec succès (%s)", email)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        _LOGGER.info("Entrée Beem %s déchargée avec succès.", entry.entry_id)
    else:
        _LOGGER.warning("Impossible de décharger l'entrée Beem %s.", entry.entry_id)

    return unload_ok


async def async_get_options_flow(config_entry):
    """Gestionnaire de flow d’options personnalisées."""
    return BeemOptionsFlowHandler(config_entry)
