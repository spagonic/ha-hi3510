"""Binary sensor entity per Hi3510 IP Camera (motion detection)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Hi3510MotionCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        Hi3510MotionSensor(data["motion_coordinator"], entry),
    ])


class Hi3510MotionSensor(
    CoordinatorEntity[Hi3510MotionCoordinator], BinarySensorEntity
):
    """Binary sensor per motion detection via SD card monitoring."""

    _attr_has_entity_name = True
    _attr_translation_key = "motion"
    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(
        self,
        coordinator: Hi3510MotionCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_motion"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("motion", False)

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        if self.coordinator.data is None:
            return {}
        return {
            "alarm_file": self.coordinator.data.get("alarm_file"),
            "active_recording": self.coordinator.data.get("active_recording", False),
        }
