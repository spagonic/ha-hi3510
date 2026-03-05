"""Camera entity per Hi3510 IP Camera (RTSP + snapshot + PTZ)."""

from __future__ import annotations

import logging

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Hi3510ApiClient, Hi3510Error
from .const import CONF_RTSP_PORT, DEFAULT_RTSP_PORT, DOMAIN, PTZ_ACTIONS, PTZ_MAX_PRESETS, PTZ_MAX_SPEED
from .coordinator import Hi3510DataCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        Hi3510Camera(data["coordinator"], data["api"], entry),
    ])


class Hi3510Camera(Camera):
    """Camera entity con RTSP streaming e snapshot."""

    _attr_has_entity_name = True
    _attr_name = None  # usa il nome del device
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self,
        coordinator: Hi3510DataCoordinator,
        api: Hi3510ApiClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._api = api
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_camera"

        # Costruisci URL RTSP
        user = entry.data[CONF_USERNAME]
        password = entry.data[CONF_PASSWORD]
        host = entry.data[CONF_HOST]
        rtsp_port = entry.data.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)
        self._stream_url = f"rtsp://{user}:{password}@{host}:{rtsp_port}/11"

    @property
    def device_info(self) -> DeviceInfo:
        info = self._coordinator.data.get("server_info", {}) if self._coordinator.data else {}
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.unique_id)},
            name=info.get("name", f"Hi3510 {self._api.host}"),
            manufacturer="Hi3510/HiSilicon",
            model=info.get("model", "Unknown"),
            sw_version=info.get("softVersion"),
            hw_version=info.get("hardVersion"),
        )

    @property
    def available(self) -> bool:
        return self._coordinator.last_update_success

    async def stream_source(self) -> str | None:
        return self._stream_url

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        try:
            return await self._api.get_snapshot()
        except Hi3510Error:
            _LOGGER.debug("Errore snapshot da %s", self._api.host)
            return None
