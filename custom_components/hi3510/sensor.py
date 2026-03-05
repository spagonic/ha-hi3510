"""Sensor entities per Hi3510 IP Camera (diagnostica SD)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SD_STATUS_MAP
from .coordinator import Hi3510DataCoordinator


@dataclass(frozen=True, kw_only=True)
class Hi3510SensorDescription(SensorEntityDescription):
    """Descrizione sensor Hi3510."""

    value_key: str
    is_space: bool = False  # True = converte KB → MB


SENSOR_DESCRIPTIONS: list[Hi3510SensorDescription] = [
    Hi3510SensorDescription(
        key="sd_free_space",
        translation_key="sd_free_space",
        icon="mdi:micro-sd",
        native_unit_of_measurement="MB",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_key="sdfreespace",
        is_space=True,
    ),
    Hi3510SensorDescription(
        key="sd_total_space",
        translation_key="sd_total_space",
        icon="mdi:micro-sd",
        native_unit_of_measurement="MB",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_key="sdtotalspace",
        is_space=True,
    ),
    Hi3510SensorDescription(
        key="sd_status",
        translation_key="sd_status",
        icon="mdi:sd",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_key="sdstatus",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        Hi3510Sensor(data["coordinator"], entry, desc)
        for desc in SENSOR_DESCRIPTIONS
    ])


class Hi3510Sensor(CoordinatorEntity[Hi3510DataCoordinator], SensorEntity):
    """Sensor entity diagnostica Hi3510."""

    _attr_has_entity_name = True
    entity_description: Hi3510SensorDescription

    def __init__(
        self,
        coordinator: Hi3510DataCoordinator,
        entry: ConfigEntry,
        description: Hi3510SensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    @property
    def native_value(self) -> str | float | None:
        if self.coordinator.data is None:
            return None
        info = self.coordinator.data.get("server_info")
        if info is None:
            return None
        desc = self.entity_description
        val = info.get(desc.value_key)
        if val is None:
            return None
        if desc.is_space:
            try:
                return round(int(val) / 1024, 1)  # KB → MB
            except (ValueError, TypeError):
                return None
        # SD status: mappa codice → stringa
        if desc.value_key == "sdstatus":
            return SD_STATUS_MAP.get(val, val)
        return val

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Attributi diagnostici extra sul sensor SD status."""
        if self.entity_description.value_key != "sdstatus":
            return {}
        if self.coordinator.data is None:
            return {}
        attrs: dict[str, str | None] = {}
        info = self.coordinator.data.get("server_info") or {}
        attrs["model"] = info.get("model")
        attrs["firmware"] = info.get("softVersion")
        attrs["hardware"] = info.get("hardVersion")
        attrs["ip"] = info.get("ip") or self._entry.data.get("host")
        attrs["mac"] = info.get("macaddress")
        return {k: v for k, v in attrs.items() if v is not None}
