"""Number entities per Hi3510 IP Camera."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Hi3510ApiClient
from .const import DOMAIN, IMAGE_NUMBER_PARAMS
from .coordinator import Hi3510DataCoordinator


@dataclass(frozen=True, kw_only=True)
class Hi3510NumberDescription(NumberEntityDescription):
    """Descrizione number Hi3510."""

    data_key: str  # chiave nel coordinator data
    value_key: str  # chiave nel dict del valore
    set_fn_name: str  # nome metodo API per SET
    set_param: str  # nome parametro per il SET


# Image settings
_IMAGE_ICONS = {
    "brightness": "mdi:brightness-6",
    "contrast": "mdi:contrast-box",
    "saturation": "mdi:palette",
    "sharpness": "mdi:blur",
}
NUMBER_DESCRIPTIONS: list[Hi3510NumberDescription] = []
for _param, (_min, _max, _step) in IMAGE_NUMBER_PARAMS.items():
    NUMBER_DESCRIPTIONS.append(
        Hi3510NumberDescription(
            key=_param,
            translation_key=_param,
            icon=_IMAGE_ICONS.get(_param),
            entity_category=EntityCategory.CONFIG,
            native_min_value=_min,
            native_max_value=_max,
            native_step=_step,
            data_key="image_attr",
            value_key=_param,
            set_fn_name="set_image_attr",
            set_param=_param,
        )
    )

# Audio volumes
NUMBER_DESCRIPTIONS.extend([
    Hi3510NumberDescription(
        key="audio_in_volume",
        translation_key="audio_in_volume",
        icon="mdi:microphone",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        data_key="audio_in",
        value_key="volume",
        set_fn_name="set_audio_in_volume",
        set_param="volume",
    ),
    Hi3510NumberDescription(
        key="audio_out_volume",
        translation_key="audio_out_volume",
        icon="mdi:volume-high",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        data_key="audio_out",
        value_key="ao_volume",
        set_fn_name="set_audio_out_volume",
        set_param="volume",
    ),
])


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        Hi3510Number(data["coordinator"], data["api"], entry, desc)
        for desc in NUMBER_DESCRIPTIONS
    ])


class Hi3510Number(CoordinatorEntity[Hi3510DataCoordinator], NumberEntity):
    """Number entity generica Hi3510."""

    _attr_has_entity_name = True
    entity_description: Hi3510NumberDescription

    def __init__(
        self,
        coordinator: Hi3510DataCoordinator,
        api: Hi3510ApiClient,
        entry: ConfigEntry,
        description: Hi3510NumberDescription,
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        desc = self.entity_description
        data = self.coordinator.data.get(desc.data_key)
        if data is None:
            return None
        val = data.get(desc.value_key)
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        desc = self.entity_description
        if desc.set_fn_name == "set_image_attr":
            await self._api.set_image_attr(**{desc.set_param: int(value)})
        elif desc.set_fn_name == "set_audio_in_volume":
            await self._api.set_audio_in_volume(int(value))
        elif desc.set_fn_name == "set_audio_out_volume":
            await self._api.set_audio_out_volume(int(value))
        await self.coordinator.async_request_refresh()
