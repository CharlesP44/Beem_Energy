import logging
from datetime import timedelta
import aiohttp

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .beem_api import get_devices

_LOGGER = logging.getLogger(__name__)

async def get_battery_live_data(token_rest, battery_id):
    """Récupère les données live de la batterie."""
    url = f"https://api-x.beem.energy/beemapp/batteries/{battery_id}/live-data"
    headers = {"Authorization": f"Bearer {token_rest}"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    _LOGGER.warning(f"Erreur REST Beem live-data pour batterie {battery_id}: {resp.status}")
                    return {}
                data = await resp.json()
                return data or {}
    except Exception as exc:
        _LOGGER.warning(f"Exception get_battery_live_data: {exc}")
        return {}

class BeemCoordinator(DataUpdateCoordinator):
    """Coordonne le polling REST (et fallback) pour Beem, multi-utilisateur."""

    def __init__(self, hass, config_entry, token_rest, email):
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{email}",
            update_interval=timedelta(seconds=120),
        )
        self.hass = hass
        self.config_entry = config_entry
        self.token_rest = token_rest
        self.email = email

        self.data = {}
        self.batteries_by_serial = {}
        self.solar_equipments_by_mppt = {}
        self.solar_equipments_by_serial = {}
        self.beemboxes_by_id = {}

    async def _async_update_data(self):
        """Récupère les données REST à intervalle régulier et merge live-data."""
        try:
            batteries, energyswitch_serial = await get_devices(self.token_rest)
            self.batteries_by_serial = {}
            self.solar_equipments_by_mppt = {}
            self.solar_equipments_by_serial = {}
            self.beemboxes_by_id = {}

            beemboxes_list = []
            solar_equipments_list = []

            if batteries:
                # --- Batteries : mapping par serial
                for bat in batteries:
                    serial = str(bat.get("serialNumber"))
                    battery_id = bat.get("id")
                    bat_data = dict(bat)

                    if battery_id:
                        live_data = await get_battery_live_data(self.token_rest, battery_id)
                        if live_data:
                            bat_data.update(live_data)

                    if serial:
                        self.batteries_by_serial[serial] = bat_data

                    # Solar Equipments pour cette batterie
                    solar_equips = []
                    for equip in bat.get("solarEquipments", []):
                        mppt_id = equip.get("mpptId")
                        if mppt_id:
                            self.solar_equipments_by_mppt[f"{serial}_{mppt_id}"] = dict(equip)
                        solar_equips.append(dict(equip))
                    if serial:
                        self.solar_equipments_by_serial[serial] = solar_equips
                        solar_equipments_list.extend(solar_equips)

                    for box in bat.get("beemboxes", []):
                        box_id = box.get("macAddress") or box.get("id")
                        if box_id:
                            self.beemboxes_by_id[str(box_id)] = dict(box)
                        beemboxes_list.append(dict(box))

                main_battery_serial = str(batteries[0].get("serialNumber"))
                main_battery = self.batteries_by_serial.get(main_battery_serial, {})

            else:
                main_battery = {}
                main_battery_serial = None

            self.data = {
                "battery": main_battery,
                "main_battery_serial": main_battery_serial,
                "batteries": batteries,
                "batteries_by_serial": self.batteries_by_serial,
                "energyswitch_serial": energyswitch_serial,
                "solar_equipments": solar_equipments_list,
                "solar_equipments_by_serial": self.solar_equipments_by_serial,
                "solar_equipments_by_mppt": self.solar_equipments_by_mppt,
                "beemboxes": beemboxes_list,
                "beemboxes_by_id": self.beemboxes_by_id,
            }

            _LOGGER.debug("Données REST Beem prêtes (main=%s): %s", main_battery_serial, self.data)
            return self.data
        except Exception as err:
            raise UpdateFailed(f"Erreur inattendue REST Beem : {err}")

    def get_battery_data(self, serial=None):
        if not self.data.get("batteries_by_serial"):
            return None
        if serial:
            return self.data["batteries_by_serial"].get(str(serial))
        return self.data.get("battery", {})

    def get_solar_equipments_for_serial(self, serial):
        return self.data.get("solar_equipments_by_serial", {}).get(str(serial), [])

    def get_solar_equipment(self, mppt_id=None, serial=None):
        if mppt_id and serial:
            return self.data["solar_equipments_by_mppt"].get(f"{serial}_{mppt_id}")
        return self.data.get("solar_equipments", [])

    def get_beembox(self, box_id=None):
        if box_id:
            return self.data["beemboxes_by_id"].get(str(box_id))
        return self.data.get("beemboxes", [])


async def get_beem_coordinator(hass, config_entry, token_rest, email):
    key = f"beem_coordinator_{config_entry.entry_id}"
    if key not in hass.data:
        hass.data[key] = BeemCoordinator(hass, config_entry, token_rest, email)
        await hass.data[key].async_config_entry_first_refresh()
    return hass.data[key]
