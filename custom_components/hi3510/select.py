"""Select entities per Hi3510 IP Camera."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Hi3510ApiClient
from .const import (
    DOMAIN,
    IR_MODES,
    IR_MODE_LABELS,
    OSD_POSITIONS,
    OSD_X_THRESHOLD,
    OSD_X_RIGHT,
    OSD_X_LEFT,
    OSD_PLACE_TOP,
    OSD_PLACE_BOTTOM,
    PTZ_MAX_PRESETS,
)
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
        Hi3510PtzPresetSelect(api, entry),
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
    _attr_entity_category = EntityCategory.CONFIG
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
    """Select per posizione OSD (angolo dello schermo).

    Le cam Hi3510 usano 'place' per top/bottom e 'x' per left/right.
    place < 2 = top, place >= 2 = bottom.
    x < OSD_X_THRESHOLD = left, x >= OSD_X_THRESHOLD = right.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = OSD_POSITIONS  # Top Left, Top Right, Bottom Left, Bottom Right

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

    def _derive_position(self, osd_data: dict[str, str]) -> str | None:
        """Deriva la posizione visiva da place + x."""
        r = self._region
        place = osd_data.get(f"place_{r}")
        x_str = osd_data.get(f"x_{r}")
        if place is None:
            return None
        try:
            place_int = int(place)
            x_val = int(x_str) if x_str is not None else 0
        except (ValueError, TypeError):
            return None
        is_top = place_int < 2
        is_left = x_val < OSD_X_THRESHOLD
        if is_top and is_left:
            return "Top Left"
        if is_top and not is_left:
            return "Top Right"
        if not is_top and is_left:
            return "Bottom Left"
        return "Bottom Right"

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        osd_data = self.coordinator.data.get("osd", {}).get(self._region)
        if osd_data is None:
            return None
        return self._derive_position(osd_data)

    def _derive_position_for_region(self, region: int) -> str | None:
        """Deriva la posizione visiva per una regione qualsiasi."""
        if self.coordinator.data is None:
            return None
        osd_data = self.coordinator.data.get("osd", {}).get(region)
        if osd_data is None:
            return None
        place = osd_data.get(f"place_{region}")
        x_str = osd_data.get(f"x_{region}")
        if place is None:
            return None
        try:
            place_int = int(place)
            x_val = int(x_str) if x_str is not None else 0
        except (ValueError, TypeError):
            return None
        is_top = place_int < 2
        is_left = x_val < OSD_X_THRESHOLD
        if is_top and is_left:
            return "Top Left"
        if is_top and not is_left:
            return "Top Right"
        if not is_top and is_left:
            return "Bottom Left"
        return "Bottom Right"

    async def async_select_option(self, option: str) -> None:
        # Mappa opzione → place + x
        if option == "Top Left":
            new_place, new_x = OSD_PLACE_TOP, OSD_X_LEFT
        elif option == "Top Right":
            new_place, new_x = OSD_PLACE_TOP, OSD_X_RIGHT
        elif option == "Bottom Left":
            new_place, new_x = OSD_PLACE_BOTTOM, OSD_X_LEFT
        elif option == "Bottom Right":
            new_place, new_x = OSD_PLACE_BOTTOM, OSD_X_RIGHT
        else:
            return

        # Validazione anti-overlap
        other_region = 1 - self._region
        other_pos = self._derive_position_for_region(other_region)
        if other_pos == option:
            raise HomeAssistantError(
                f"Position '{option}' is already used by OSD region {other_region}. "
                f"Move region {other_region} first to avoid overlap."
            )

        ok = await self._api.set_overlay_attr(
            self._region, place=new_place, x=str(new_x), y="0"
        )
        if not ok:
            raise HomeAssistantError(
                f"Camera rejected position '{option}' for OSD region {self._region}. "
                f"This position may not be supported by your camera firmware."
            )
        await self.coordinator.async_request_refresh()



class Hi3510PtzPresetSelect(SelectEntity):
    """Select per andare a un preset PTZ."""

    _attr_has_entity_name = True
    _attr_translation_key = "ptz_preset"
    _attr_icon = "mdi:crosshairs-gps"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = [str(i) for i in range(1, PTZ_MAX_PRESETS + 1)]

    def __init__(self, api: Hi3510ApiClient, entry: ConfigEntry) -> None:
        self._api = api
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_ptz_preset"
        self._current: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    @property
    def current_option(self) -> str | None:
        return self._current

    async def async_select_option(self, option: str) -> None:
        await self._api.ptz_preset_go(int(option))
        self._current = option
        self.async_write_ha_state()
