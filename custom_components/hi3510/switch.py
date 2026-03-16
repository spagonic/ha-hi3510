"""Switch entities per Hi3510 IP Camera."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Hi3510ApiClient
from .const import DOMAIN
from .coordinator import Hi3510DataCoordinator


@dataclass(frozen=True, kw_only=True)
class Hi3510SwitchDescription(SwitchEntityDescription):
    """Descrizione switch Hi3510."""

    data_key: str  # chiave nel coordinator data
    value_key: str  # chiave nel dict del valore
    set_fn_name: str  # nome metodo API per SET
    set_on_args: dict[str, Any]  # args per turn_on
    set_off_args: dict[str, Any]  # args per turn_off


SWITCH_DESCRIPTIONS: list[Hi3510SwitchDescription] = [
    Hi3510SwitchDescription(
        key="onvif",
        translation_key="onvif",
        icon="mdi:video-wireless",
        entity_category=EntityCategory.CONFIG,
        data_key="onvif",
        value_key="ov_enable",
        set_fn_name="set_onvif_attr",
        set_on_args={"enable": True},
        set_off_args={"enable": False},
    ),
    Hi3510SwitchDescription(
        key="recording",
        translation_key="recording",
        icon="mdi:record-rec",
        data_key="plan_rec",
        value_key="planrec_enable",
        set_fn_name="set_plan_rec_attr",
        set_on_args={"enable": True},
        set_off_args={"enable": False},
    ),
    Hi3510SwitchDescription(
        key="flip",
        translation_key="flip",
        icon="mdi:flip-vertical",
        entity_category=EntityCategory.CONFIG,
        data_key="image_attr",
        value_key="flip",
        set_fn_name="set_image_attr",
        set_on_args={"flip": "on"},
        set_off_args={"flip": "off"},
    ),
    Hi3510SwitchDescription(
        key="mirror",
        translation_key="mirror",
        icon="mdi:flip-horizontal",
        entity_category=EntityCategory.CONFIG,
        data_key="image_attr",
        value_key="mirror",
        set_fn_name="set_image_attr",
        set_on_args={"mirror": "on"},
        set_off_args={"mirror": "off"},
    ),
]

# OSD region show switches (solo region 0 e 1)
_osd_icons = {0: "mdi:clock-outline", 1: "mdi:tag-text-outline"}
for _region in range(2):
    SWITCH_DESCRIPTIONS.append(
        Hi3510SwitchDescription(
            key=f"osd_region_{_region}",
            translation_key=f"osd_region_{_region}",
            icon=_osd_icons[_region],
            entity_category=EntityCategory.CONFIG,
            data_key=f"osd_{_region}",
            value_key=f"show_{_region}",
            set_fn_name="_set_osd_show",
            set_on_args={"region": _region, "show": True},
            set_off_args={"region": _region, "show": False},
        )
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    # Rileva quali regioni OSD sono supportate dalla cam
    osd_data = coordinator.data.get("osd", {}) if coordinator.data else {}
    supported_osd = {r for r in range(4) if osd_data.get(r) is not None}

    entities = []
    for desc in SWITCH_DESCRIPTIONS:
        # Salta OSD per regioni non supportate
        if desc.data_key.startswith("osd_"):
            region = int(desc.data_key.split("_")[1])
            if region not in supported_osd:
                continue
        entities.append(Hi3510Switch(coordinator, data["api"], entry, desc))

    async_add_entities(entities)


class Hi3510Switch(CoordinatorEntity[Hi3510DataCoordinator], SwitchEntity):
    """Switch entity generica Hi3510."""

    _attr_has_entity_name = True
    entity_description: Hi3510SwitchDescription

    def __init__(
        self,
        coordinator: Hi3510DataCoordinator,
        api: Hi3510ApiClient,
        entry: ConfigEntry,
        description: Hi3510SwitchDescription,
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
    def is_on(self) -> bool | None:
        desc = self.entity_description
        if self.coordinator.data is None:
            return None
        # OSD: dati in coordinator.data["osd"][region]
        if desc.data_key.startswith("osd_"):
            region = int(desc.data_key.split("_")[1])
            osd_data = self.coordinator.data.get("osd", {}).get(region)
            if osd_data is None:
                return None
            return osd_data.get(desc.value_key) == "1"
        # Standard
        data = self.coordinator.data.get(desc.data_key)
        if data is None:
            return None
        val = data.get(desc.value_key)
        if val is None:
            return None
        return val in ("1", "on")

    async def async_turn_on(self, **kwargs: Any) -> None:
        desc = self.entity_description
        if desc.set_fn_name == "_set_osd_show":
            region = desc.set_on_args["region"]
            await self._api.set_overlay_attr(region, show="1")
        else:
            fn = getattr(self._api, desc.set_fn_name)
            await fn(**desc.set_on_args)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        desc = self.entity_description
        if desc.set_fn_name == "_set_osd_show":
            region = desc.set_off_args["region"]
            await self._api.set_overlay_attr(region, show="0")
        else:
            fn = getattr(self._api, desc.set_fn_name)
            await fn(**desc.set_off_args)
        await self.coordinator.async_request_refresh()
