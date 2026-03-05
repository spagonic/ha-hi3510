"""DataUpdateCoordinator per Hi3510 IP Camera."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Hi3510ApiClient, Hi3510ConnectionError, Hi3510Error
from .const import DEFAULT_MOTION_INTERVAL, DEFAULT_MOTION_OFF_DELAY, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class Hi3510DataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator principale: polling ogni 30s di tutti i parametri."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, api: Hi3510ApiClient, entry: ConfigEntry
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
            config_entry=entry,
        )
        self.api = api
        self._consecutive_errors = 0

    async def _async_update_data(self) -> dict[str, Any]:
        """Raccoglie tutti i dati dalla camera."""
        data: dict[str, Any] = {}

        calls: list[tuple[str, Any]] = [
            ("server_info", self.api.get_server_info),
            ("image_attr", self.api.get_image_attr),
            ("infrared", self.api.get_infrared),
            ("onvif", self.api.get_onvif_attr),
            ("plan_rec", self.api.get_plan_rec_attr),
            ("md_attr", self.api.get_md_attr),
            ("audio_in", self.api.get_audio_in_volume),
            ("audio_out", self.api.get_audio_out_volume),
        ]

        all_failed = True
        for key, func in calls:
            data[key] = await self._safe_call(func)
            if data[key] is not None:
                all_failed = False

        # OSD: solo region 0 (timestamp) e 1 (nome camera)
        data["osd"] = {}
        for region in range(2):
            result = await self._safe_call(self.api.get_overlay_attr, region)
            data["osd"][region] = result
            if result is not None:
                all_failed = False

        if all_failed:
            self._consecutive_errors += 1
            if self._consecutive_errors >= 3:
                raise UpdateFailed(
                    f"Camera {self.api.host} non raggiungibile"
                )
        else:
            self._consecutive_errors = 0

        return data

    async def _safe_call(self, func: Any, *args: Any) -> Any:
        """Chiama func, ritorna None se fallisce."""
        try:
            return await func(*args)
        except Hi3510ConnectionError:
            return None
        except Hi3510Error as err:
            _LOGGER.debug("Errore polling %s: %s", func.__name__, err)
            return None
        except Exception:
            _LOGGER.debug("Errore inatteso polling %s", func.__name__, exc_info=True)
            return None


class Hi3510MotionCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator motion detection: polling SD ogni 3s."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, api: Hi3510ApiClient, entry: ConfigEntry
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_motion",
            update_interval=timedelta(seconds=DEFAULT_MOTION_INTERVAL),
            config_entry=entry,
        )
        self.api = api
        self._last_alarm_files: set[str] = set()
        self._last_alarm_time: float = 0
        self._current_day: str = ""
        self._current_record_folder: str = ""

    async def _async_update_data(self) -> dict[str, Any]:
        """Controlla nuovi file alarm sulla SD."""
        today = datetime.now().strftime("%Y%m%d")

        # Cambio giorno: resetta
        if today != self._current_day:
            self._current_day = today
            self._current_record_folder = ""
            self._last_alarm_files = set()

        # Trova ultima cartella recordNNN del giorno
        day_path = f"/sd/{today}/"
        try:
            folders = await self.api.browse_sd(day_path)
            record_folders = sorted(
                [f for f in folders if f.rstrip("/").startswith("record")]
            )
            if record_folders:
                self._current_record_folder = record_folders[-1]
        except Exception:
            _LOGGER.debug("SD non accessibile per motion detection")
            return {"motion": False, "alarm_file": None}

        if not self._current_record_folder:
            return {"motion": False, "alarm_file": None}

        # Lista file nella cartella record corrente
        record_path = f"{day_path}{self._current_record_folder}"
        try:
            files = await self.api.browse_sd(record_path)
        except Exception:
            return {"motion": False, "alarm_file": None}

        # Cerca nuovi file A_* (alarm)
        alarm_files = {f for f in files if f.startswith("A")}
        new_alarms = alarm_files - self._last_alarm_files

        if new_alarms:
            self._last_alarm_time = time.time()
            self._last_alarm_files = alarm_files
            active = [f for f in new_alarms if "999999" in f]
            return {
                "motion": True,
                "alarm_file": sorted(new_alarms)[-1],
                "active_recording": bool(active),
            }

        self._last_alarm_files = alarm_files

        # Timeout: motion OFF dopo N secondi senza nuovi alarm
        elapsed = time.time() - self._last_alarm_time
        motion_on = elapsed < DEFAULT_MOTION_OFF_DELAY if self._last_alarm_time > 0 else False

        return {
            "motion": motion_on,
            "alarm_file": None,
            "active_recording": False,
        }
