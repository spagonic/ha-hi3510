"""Button entity per Hi3510 IP Camera."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Hi3510ApiClient
from .const import DOMAIN


@dataclass(frozen=True, kw_only=True)
class Hi3510PtzButtonDescription(ButtonEntityDescription):
    """Descrizione button PTZ."""

    ptz_action: str
    ptz_speed: int = 1


PTZ_BUTTON_DESCRIPTIONS: list[Hi3510PtzButtonDescription] = [
    Hi3510PtzButtonDescription(key="ptz_left", translation_key="ptz_left", icon="mdi:arrow-left", ptz_action="left"),
    Hi3510PtzButtonDescription(key="ptz_right", translation_key="ptz_right", icon="mdi:arrow-right", ptz_action="right"),
    Hi3510PtzButtonDescription(key="ptz_up", translation_key="ptz_up", icon="mdi:arrow-up", ptz_action="up"),
    Hi3510PtzButtonDescription(key="ptz_down", translation_key="ptz_down", icon="mdi:arrow-down", ptz_action="down"),
    Hi3510PtzButtonDescription(key="ptz_home", translation_key="ptz_home", icon="mdi:home", ptz_action="home", ptz_speed=0),
    Hi3510PtzButtonDescription(key="ptz_zoom_in", translation_key="ptz_zoom_in", icon="mdi:magnify-plus", ptz_action="zoomin"),
    Hi3510PtzButtonDescription(key="ptz_zoom_out", translation_key="ptz_zoom_out", icon="mdi:magnify-minus", ptz_action="zoomout"),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    entities: list[ButtonEntity] = [Hi3510RebootButton(api, entry)]
    entities.extend(
        Hi3510PtzButton(api, entry, desc) for desc in PTZ_BUTTON_DESCRIPTIONS
    )
    async_add_entities(entities)


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


class Hi3510PtzButton(ButtonEntity):
    """Pulsante PTZ per movimento camera."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    entity_description: Hi3510PtzButtonDescription

    def __init__(
        self,
        api: Hi3510ApiClient,
        entry: ConfigEntry,
        description: Hi3510PtzButtonDescription,
    ) -> None:
        self._api = api
        self._entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    async def async_press(self) -> None:
        desc = self.entity_description
        await self._api.ptz_command(desc.ptz_action, desc.ptz_speed)
