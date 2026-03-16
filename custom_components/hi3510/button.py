"""Button entity per Hi3510 IP Camera."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Hi3510ApiClient
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        Hi3510RebootButton(data["api"], entry),
    ])


class Hi3510RebootButton(ButtonEntity):
    """Pulsante reboot camera."""

    _attr_has_entity_name = True
    _attr_translation_key = "reboot"
    _attr_icon = "mdi:restart"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, api: Hi3510ApiClient, entry: ConfigEntry) -> None:
        self._api = api
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_reboot"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    async def async_press(self) -> None:
        await self._api.reboot()
