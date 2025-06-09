from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .api import BeemApiClient

_LOGGER = logging.getLogger(__name__)


class BeemCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, api: BeemApiClient, battery_id: int = None):
        """Initialise le coordinateur Beem."""
        self.hass = hass
        self.api_client = api
        self.battery_id = battery_id
        self.solar_equipments = []
        self.beemboxes = []

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{battery_id if battery_id else 'pnp'}",
            update_interval=timedelta(seconds=60),
        )

    async def _async_update_data(self):
        """Tâche périodique : mise à jour des données."""
        try:
            data = {}

            # 🔋 Partie batterie BeemSolid
            if self.battery_id is not None:
                # 1. Récupération des batteries
                batteries = await self.api_client.get_batteries()
                if not batteries:
                    raise UpdateFailed("Erreur lors de la récupération des batteries")

                # 2. Trouver la bonne batterie
                battery_data = next((b for b in batteries if b.get("id") == self.battery_id), None)
                if battery_data is None:
                    raise UpdateFailed(f"Batterie {self.battery_id} non trouvée")

                # 3. Équipements solaires
                self.solar_equipments = battery_data.get("solarEquipments", [])

                # 4. Données live
                live_data = await self.api_client.get_live_data(self.battery_id)
                if live_data is None:
                    _LOGGER.warning("Token expiré. Tentative de reconnexion...")
                    if not self.api_client.password:
                        raise UpdateFailed("Mot de passe requis pour renouveler le token")

                    login_successful = await self.api_client.login()
                    if not login_successful:
                        raise UpdateFailed("Échec du renouvellement du token")

                    live_data = await self.api_client.get_live_data(self.battery_id)
                    if live_data is None:
                        raise UpdateFailed("Données live toujours indisponibles après reconnexion")

                    await self._update_token_in_entry()
                    self.async_update_listeners()

                # 5. Injecter les équipements solaires dans les données live
                live_data["solarEquipments"] = self.solar_equipments
                data["battery"] = live_data

            # ☀️ Partie BeemBox (PnP)
            try:
                self.beemboxes = await self.api_client.get_beemboxes()
                data["beemboxes"] = self.beemboxes
            except Exception as box_err:
                _LOGGER.warning(f"Erreur lors de la récupération des BeemBox: {box_err}")
                self.beemboxes = []
                data["beemboxes"] = []

            return data

        except Exception as err:
            raise UpdateFailed(f"Erreur inattendue lors de l’update : {err}")

    async def _update_token_in_entry(self):
        """Met à jour dynamiquement le token dans l'entrée de configuration."""
        entry = next(
            (
                e for e in self.hass.config_entries.async_entries(DOMAIN)
                if e.data.get("email") == self.api_client.email
                and (self.battery_id is None or e.data.get("battery_id") == self.battery_id)
            ),
            None
        )

        if entry:
            new_options = dict(entry.options)
            new_options["token"] = self.api_client.token
            await self.hass.config_entries.async_update_entry(entry, options=new_options)
            _LOGGER.info("Token mis à jour dans les options de configuration Beem.")
