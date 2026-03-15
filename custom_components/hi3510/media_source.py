"""Espone le registrazioni SD delle IP camera Hi3510 come media source."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from pathlib import Path

from .const import CACHE_DIR, DOMAIN
from .views import async_generate_playback_proxy_url

_LOGGER = logging.getLogger(__name__)

# Pattern nome file: A_YYMMDD_HHMMSS_HHMMSS.264/.265 o AYYMMDD_... (senza underscore dopo tipo)
_FILE_RE = re.compile(
    r"^([AP])_?(\d{6})_(\d{6})_(\d{6})\.(\d{3})$"
)


async def async_get_media_source(hass: HomeAssistant) -> Hi3510MediaSource:
    """Set up Hi3510 media source."""
    return Hi3510MediaSource(hass)


def _parse_filename(name: str) -> dict | None:
    """Parsa nome file registrazione SD.

    Es: A_260315_000045_000114.265
    → type=Alarm, date=26-03-15, start=00:00:45, end=00:01:14, ext=265
    """
    m = _FILE_RE.match(name)
    if not m:
        return None
    rec_type, date_s, start_s, end_s, ext = m.groups()
    try:
        start_time = f"{start_s[:2]}:{start_s[2:4]}:{start_s[4:6]}"
        end_time = f"{end_s[:2]}:{end_s[2:4]}:{end_s[4:6]}"
    except (IndexError, ValueError):
        return None
    return {
        "type": "Alarm" if rec_type == "A" else "Plan",
        "type_short": rec_type,
        "start": start_time,
        "end": end_time,
        "ext": ext,
    }


def _get_entry_data(hass: HomeAssistant, entry_id: str) -> dict:
    """Recupera api/coordinator da hass.data per un config entry."""
    try:
        return hass.data[DOMAIN][entry_id]
    except KeyError as err:
        raise Unresolvable(f"Config entry {entry_id} non trovato") from err


class Hi3510MediaSource(MediaSource):
    """Registrazioni SD delle IP camera Hi3510."""

    name = "Hi3510 Recordings"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Risolvi un file registrazione in URL proxy per playback."""
        if not item.identifier or not item.identifier.startswith("FILE|"):
            raise Unresolvable(f"Identificatore sconosciuto: {item.identifier}")

        parts = item.identifier.split("|")
        if len(parts) != 4:
            raise Unresolvable(f"Formato identificatore non valido: {item.identifier}")

        _, entry_id, sd_path, filename = parts
        # Verifica che l'entry esista
        _get_entry_data(self.hass, entry_id)

        proxy_url = async_generate_playback_proxy_url(entry_id, sd_path, filename)
        return PlayMedia(proxy_url, "video/mp4")

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Naviga le registrazioni SD."""
        if not item.identifier:
            return await self._async_root()

        parts = item.identifier.split("|")
        item_type = parts[0]

        if item_type == "CAM" and len(parts) == 2:
            return await self._async_camera_days(parts[1])
        if item_type == "DAY" and len(parts) == 3:
            return await self._async_day_files(parts[1], parts[2])

        raise Unresolvable(f"Identificatore sconosciuto: {item.identifier}")

    async def _async_root(self) -> BrowseMediaSource:
        """Root: lista tutte le camere hi3510 configurate."""
        children: list[BrowseMediaSource] = []
        device_reg = dr.async_get(self.hass)

        for entry_id, data in self.hass.data.get(DOMAIN, {}).items():
            if not isinstance(data, dict) or "api" not in data:
                continue
            api = data["api"]
            # Trova il nome del device
            device_name = f"Hi3510 {api.host}"
            for device in dr.async_entries_for_config_entry(device_reg, entry_id):
                device_name = device.name_by_user or device.name or device_name
                break

            children.append(
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"CAM|{entry_id}",
                    media_class=MediaClass.CHANNEL,
                    media_content_type=MediaType.PLAYLIST,
                    title=f"📹 {device_name}",
                    can_play=False,
                    can_expand=True,
                )
            )

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.APP,
            media_content_type="",
            title="Hi3510 Recordings",
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def _async_camera_days(self, entry_id: str) -> BrowseMediaSource:
        """Lista i giorni con registrazioni sulla SD di una camera."""
        data = _get_entry_data(self.hass, entry_id)
        api = data["api"]

        try:
            entries = await api.browse_sd("/sd/")
        except Exception as err:
            raise Unresolvable(f"SD non accessibile: {err}") from err

        # Filtra solo cartelle giorno (YYYYMMDD/)
        day_folders = sorted(
            [d.rstrip("/") for d in entries if d.rstrip("/").isdigit() and len(d.rstrip("/")) == 8],
            reverse=True,
        )

        children: list[BrowseMediaSource] = []
        for day in day_folders:
            # Formatta data leggibile
            try:
                dt = datetime.strptime(day, "%Y%m%d")
                title = dt.strftime("%d/%m/%Y")
            except ValueError:
                title = day

            children.append(
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"DAY|{entry_id}|{day}",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.PLAYLIST,
                    title=f"📅 {title}",
                    can_play=False,
                    can_expand=True,
                )
            )

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"CAM|{entry_id}",
            media_class=MediaClass.CHANNEL,
            media_content_type=MediaType.PLAYLIST,
            title=f"Hi3510 {api.host}",
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def _async_day_files(self, entry_id: str, day: str) -> BrowseMediaSource:
        """Lista i file registrazione di un giorno specifico."""
        data = _get_entry_data(self.hass, entry_id)
        api = data["api"]

        day_path = f"/sd/{day}/"
        try:
            entries = await api.browse_sd(day_path)
        except Exception as err:
            raise Unresolvable(f"Giorno {day} non accessibile: {err}") from err

        # Trova tutte le cartelle record
        rec_folders = sorted([f for f in entries if f.rstrip("/").startswith("record")])

        # Set di file già in cache per lookup veloce
        cache_dir = Path(self.hass.config.path(CACHE_DIR))

        def _get_cached_keys() -> set[str]:
            if not cache_dir.exists():
                return set()
            return {f.stem for f in cache_dir.iterdir() if f.suffix == ".mp4"}

        cached_keys = await self.hass.async_add_executor_job(_get_cached_keys)

        children: list[BrowseMediaSource] = []
        for rec_folder in rec_folders:
            rec_path = f"{day_path}{rec_folder}"
            try:
                files = await api.browse_sd(rec_path)
            except Exception:
                continue

            for filename in sorted(files):
                # Solo file completati (no 999999 = in corso)
                if "999999" in filename:
                    continue
                info = _parse_filename(filename)
                if not info:
                    continue

                # H.265 non supportato per playback — skip
                if info["ext"] == "265":
                    continue

                icon = "🔴🔴" if info["type_short"] == "A" else "🟢🟢"
                cache_key = f"{entry_id}_{filename}".replace("/", "_")
                if cache_key not in cached_keys:
                    icon = "🔴" if info["type_short"] == "A" else "🟢"

                title = f"{icon} {info['start']}–{info['end']} ({info['type']})"

                children.append(
                    BrowseMediaSource(
                        domain=DOMAIN,
                        identifier=f"FILE|{entry_id}|{rec_path}|{filename}",
                        media_class=MediaClass.VIDEO,
                        media_content_type=MediaType.VIDEO,
                        title=title,
                        can_play=True,
                        can_expand=False,
                    )
                )

        try:
            dt = datetime.strptime(day, "%Y%m%d")
            day_title = dt.strftime("%d/%m/%Y")
        except ValueError:
            day_title = day

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"DAY|{entry_id}|{day}",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.PLAYLIST,
            title=f"📅 {day_title} ({len(children)} registrazioni)",
            can_play=False,
            can_expand=True,
            children=children,
        )
