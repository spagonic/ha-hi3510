"""Text entities per Hi3510 IP Camera (OSD overlay text)."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Hi3510ApiClient
from .const import DOMAIN
from .coordinator import Hi3510DataCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    # Rileva quali regioni OSD sono supportate dalla cam
    osd_data = coordinator.data.get("osd", {}) if coordinator.data else {}
    supported_osd = {r for r in range(4) if osd_data.get(r) is not None}

    async_add_entities([
        Hi3510OsdText(coordinator, data["api"], entry, 1)
    ] if 1 in supported_osd else [])


class Hi3510OsdText(CoordinatorEntity[Hi3510DataCoordinator], TextEntity):
    """Text entity per OSD overlay di una regione."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_max = 32

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
        self._attr_unique_id = f"{entry.unique_id}_osd_text_{region}"
        self._attr_translation_key = f"osd_text_{region}"
        self._attr_icon = "mdi:form-textbox"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        osd_data = self.coordinator.data.get("osd", {}).get(self._region)
        if osd_data is None:
            return None
        return osd_data.get(f"name_{self._region}", "")

    async def async_set_value(self, value: str) -> None:
        await self._api.set_overlay_attr(self._region, name=value)
        await self.coordinator.async_request_refresh()
