"""Select entities per Hi3510 IP Camera."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Hi3510ApiClient
from .const import DOMAIN, IR_MODES, IR_MODE_LABELS, OSD_PLACE_MAP, OSD_PLACE_REVERSE
from .coordinator import Hi3510DataCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    api = data["api"]

    entities: list[SelectEntity] = [
        Hi3510InfraredSelect(coordinator, api, entry),
    ]

    # OSD place selects: solo per regioni supportate
    osd_data = coordinator.data.get("osd", {}) if coordinator.data else {}
    for region in range(2):
        if osd_data.get(region) is not None:
            entities.append(Hi3510OsdPlaceSelect(coordinator, api, entry, region))

    async_add_entities(entities)


class Hi3510InfraredSelect(CoordinatorEntity[Hi3510DataCoordinator], SelectEntity):
    """Select per modalità infrarossi."""

    _attr_has_entity_name = True
    _attr_translation_key = "infrared"
    _attr_icon = "mdi:flashlight"
    _attr_options = list(IR_MODE_LABELS.values())  # ["Auto", "On", "Off"]

    def __init__(
        self,
        coordinator: Hi3510DataCoordinator,
        api: Hi3510ApiClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_infrared"
        # Mappa inversa: label → valore CGI
        self._label_to_mode = {v: k for k, v in IR_MODE_LABELS.items()}

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        mode = self.coordinator.data.get("infrared")
        if mode is None:
            return None
        return IR_MODE_LABELS.get(mode, mode)

    async def async_select_option(self, option: str) -> None:
        mode = self._label_to_mode.get(option, option)
        await self._api.set_infrared(mode)
        await self.coordinator.async_request_refresh()


class Hi3510OsdPlaceSelect(CoordinatorEntity[Hi3510DataCoordinator], SelectEntity):
    """Select per posizione OSD (angolo dello schermo)."""

    _attr_has_entity_name = True
    _attr_options = list(OSD_PLACE_MAP.values())  # Top Left, Top Right, Bottom Left, Bottom Right

    _REGION_ICONS = {0: "mdi:clock-outline", 1: "mdi:tag-text-outline"}

    def __init__(
        self,
        coordinator: Hi3510DataCoordinator,
        api: Hi3510ApiClient,
        entry: ConfigEntry,
        region: int,
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._entry = entry
        self._region = region
        self._attr_unique_id = f"{entry.unique_id}_osd_place_{region}"
        self._attr_translation_key = f"osd_place_{region}"
        self._attr_icon = self._REGION_ICONS.get(region, "mdi:map-marker")

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        osd_data = self.coordinator.data.get("osd", {}).get(self._region)
        if osd_data is None:
            return None
        place = osd_data.get(f"place_{self._region}")
        if place is None:
            return None
        return OSD_PLACE_MAP.get(place, place)

    async def async_select_option(self, option: str) -> None:
        new_place = OSD_PLACE_REVERSE.get(option)
        if new_place is None:
            return

        # Validazione anti-overlap: controlla che l'altra region non sia sulla stessa posizione
        other_region = 1 - self._region
        osd_data = self.coordinator.data.get("osd", {}) if self.coordinator.data else {}
        other_osd = osd_data.get(other_region)
        if other_osd is not None:
            other_place = other_osd.get(f"place_{other_region}")
            if other_place == new_place:
                other_label = OSD_PLACE_MAP.get(other_place, other_place)
                raise HomeAssistantError(
                    f"Position '{option}' is already used by OSD region {other_region}. "
                    f"Move region {other_region} first to avoid overlap."
                )

        ok = await self._api.set_overlay_attr(self._region, place=new_place)
        if not ok:
            raise HomeAssistantError(
                f"Camera rejected position '{option}' for OSD region {self._region}. "
                f"This position may not be supported by your camera firmware."
            )
        await self.coordinator.async_request_refresh()
