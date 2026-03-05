"""Client API asincrono per il protocollo CGI Hi3510."""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp

from .const import CGI_PARAM, CGI_PRESET, CGI_PTZ, SNAPSHOT_PATH

_LOGGER = logging.getLogger(__name__)

_RESPONSE_RE = re.compile(r'var\s+(\w+)\s*=\s*"?(.*?)"?\s*;')


class Hi3510Error(Exception):
    """Base exception."""


class Hi3510ConnectionError(Hi3510Error):
    """Errore di connessione."""


class Hi3510AuthError(Hi3510Error):
    """Errore di autenticazione."""


class Hi3510CommandError(Hi3510Error):
    """Errore nel comando CGI."""


class Hi3510ApiClient:
    """Client asincrono per il protocollo CGI Hi3510."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        self._host = host
        self._port = port
        self._auth = aiohttp.BasicAuth(username, password)
        self._session = session
        self._base = f"http://{host}:{port}"
        self._timeout = aiohttp.ClientTimeout(total=10)

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    # ── Core ─────────────────────────────────────────────────────

    @staticmethod
    def parse_response(text: str) -> dict[str, str]:
        """Parsa risposta CGI Hi3510: var key="value"; → dict."""
        if "[Error]" in text:
            raise Hi3510CommandError(text.strip())
        result: dict[str, str] = {}
        for match in _RESPONSE_RE.finditer(text):
            result[match.group(1)] = match.group(2)
        return result

    async def execute(
        self, cmd: str, params: dict[str, str] | None = None
    ) -> dict[str, str]:
        """Esegue un comando CGI param.cgi e ritorna il dict parsato."""
        qp: dict[str, str] = {"cmd": cmd}
        if params:
            qp.update(params)
        text = await self._get(CGI_PARAM, qp)
        return self.parse_response(text)

    async def execute_set(
        self, cmd: str, params: dict[str, str] | None = None
    ) -> bool:
        """Esegue un comando SET e ritorna True se [Succeed]."""
        qp: dict[str, str] = {"cmd": cmd}
        if params:
            qp.update(params)
        text = await self._get(CGI_PARAM, qp)
        _LOGGER.debug("SET %s response: %s", cmd, text.strip()[:200])
        return "[Succeed]" in text

    @staticmethod
    def _build_qs(params: dict[str, str]) -> str:
        """Costruisce query string manualmente per compatibilità Hi3510.

        La camera si aspetta parametri con trattino (es. -brightness=128)
        passati esattamente così nella URL. aiohttp potrebbe codificarli
        in modo diverso, quindi costruiamo la query string a mano.
        """
        from urllib.parse import quote
        parts = []
        for k, v in params.items():
            # Chiavi raw (con trattino), valori URL-encoded
            parts.append(f"{k}={quote(str(v), safe='')}")
        return "&".join(parts)

    async def _get(self, path: str, params: dict[str, str] | None = None) -> str:
        """HTTP GET generico, ritorna il body text."""
        url = f"{self._base}{path}"
        if params:
            url = f"{url}?{self._build_qs(params)}"
        _LOGGER.debug("HTTP GET: %s", url)
        try:
            async with self._session.get(
                url, auth=self._auth, timeout=self._timeout
            ) as resp:
                if resp.status == 401:
                    raise Hi3510AuthError("HTTP 401 Unauthorized")
                resp.raise_for_status()
                return await resp.text()
        except Hi3510Error:
            raise
        except aiohttp.ClientError as err:
            raise Hi3510ConnectionError(
                f"Connessione fallita a {self._host}: {err}"
            ) from err
        except TimeoutError as err:
            raise Hi3510ConnectionError(
                f"Timeout connessione a {self._host}"
            ) from err

    async def _get_bytes(self, path: str) -> bytes:
        """HTTP GET che ritorna bytes (per snapshot)."""
        url = f"{self._base}{path}"
        try:
            async with self._session.get(
                url, auth=self._auth, timeout=self._timeout
            ) as resp:
                if resp.status == 401:
                    raise Hi3510AuthError("HTTP 401 Unauthorized")
                resp.raise_for_status()
                return await resp.read()
        except Hi3510Error:
            raise
        except aiohttp.ClientError as err:
            raise Hi3510ConnectionError(
                f"Connessione fallita a {self._host}: {err}"
            ) from err
        except TimeoutError as err:
            raise Hi3510ConnectionError(
                f"Timeout connessione a {self._host}"
            ) from err

    # ── Info ─────────────────────────────────────────────────────

    async def get_server_info(self) -> dict[str, str]:
        return await self.execute("getserverinfo")

    async def get_net_attr(self) -> dict[str, str]:
        return await self.execute("getnetattr")

    async def get_wireless_attr(self) -> dict[str, str]:
        return await self.execute("getwirelessattr")

    # ── Image ────────────────────────────────────────────────────

    async def get_image_attr(self) -> dict[str, str]:
        return await self.execute("getimageattr")

    async def set_image_attr(self, **kwargs: str | int) -> bool:
        """SET immagine. IMPORTANTE: invia TUTTI i parametri correnti + quelli modificati,
        perché la camera resetta i parametri non specificati ai default."""
        # Leggi i valori correnti
        current = await self.get_image_attr()
        # Parametri che la camera accetta nel SET
        settable = [
            "brightness", "contrast", "saturation", "sharpness",
            "flip", "mirror", "wdr",
        ]
        params: dict[str, str] = {}
        for key in settable:
            if key in kwargs:
                params[f"-{key}"] = str(kwargs[key])
            elif key in current:
                params[f"-{key}"] = current[key]
        return await self.execute_set("setimageattr", params)

    # ── Infrared ─────────────────────────────────────────────────

    async def get_infrared(self) -> str:
        """Ritorna la modalità IR: 'auto', 'open', 'close'."""
        data = await self.execute("getinfrared")
        return data.get("infraredstat", "auto")

    async def set_infrared(self, mode: str) -> bool:
        return await self.execute_set("setinfrared", {"-infraredstat": mode})

    # ── ONVIF ────────────────────────────────────────────────────

    async def get_onvif_attr(self) -> dict[str, str]:
        return await self.execute("getonvifattr")

    async def set_onvif_attr(self, enable: bool, port: int = 8080) -> bool:
        return await self.execute_set("setonvifattr", {
            "-ov_enable": "1" if enable else "0",
            "-ov_port": str(port),
        })

    # ── Plan Recording ───────────────────────────────────────────

    async def get_plan_rec_attr(self) -> dict[str, str]:
        return await self.execute("getplanrecattr")

    async def set_plan_rec_attr(self, enable: bool) -> bool:
        return await self.execute_set("setplanrecattr", {
            "-planrec_enable": "1" if enable else "0",
        })

    # ── Motion Detection ─────────────────────────────────────────

    async def get_md_attr(self) -> dict[str, str]:
        return await self.execute("getmdattr")

    async def set_md_attr(
        self,
        zone: int = 1,
        enable: bool = True,
        x: int = 0,
        y: int = 0,
        w: int = 1920,
        h: int = 1080,
        sensitivity: int = 75,
    ) -> bool:
        return await self.execute_set("setmdattr", {
            "-enable": "1" if enable else "0",
            "-name": str(zone),
            "-x": str(x),
            "-y": str(y),
            "-w": str(w),
            "-h": str(h),
            "-s": str(sensitivity),
        })

    # ── OSD Overlay ──────────────────────────────────────────────

    async def get_overlay_attr(self, region: int) -> dict[str, str]:
        return await self.execute("getoverlayattr", {"-region": str(region)})

    async def set_overlay_attr(self, region: int, **kwargs: str | int) -> bool:
        """SET OSD overlay. NOTA: i parametri SET usano nomi SENZA suffisso _N
        (es. -show, -name) anche se il GET ritorna show_N, name_N.
        ATTENZIONE: region 0 è il timestamp — il name è un pattern di formato
        gestito dal firmware e NON deve essere modificato via CGI (corrompe l'OSD)."""
        params: dict[str, str] = {"-region": str(region)}
        for k, v in kwargs.items():
            import re as _re
            clean_key = _re.sub(r'_\d+$', '', k)
            # Protezione: non mandare -name per region 0 (timestamp)
            if region == 0 and clean_key == "name":
                _LOGGER.warning("Ignorato set name su region 0 (timestamp) — corrompe OSD")
                continue
            params[f"-{clean_key}"] = str(v)
        return await self.execute_set("setoverlayattr", params)

    # ── Audio ────────────────────────────────────────────────────

    async def get_audio_in_volume(self) -> dict[str, str]:
        return await self.execute("getaudioinvolume")

    async def set_audio_in_volume(self, volume: int) -> bool:
        return await self.execute_set("setaudioinvolume", {
            "-volume": str(volume),
        })

    async def get_audio_out_volume(self) -> dict[str, str]:
        """GET audio out. NOTA: la chiave è 'ao_volume', non 'volume'."""
        return await self.execute("getaudiooutvolume")

    async def set_audio_out_volume(self, volume: int) -> bool:
        """SET audio out. Il GET ritorna 'ao_volume' ma il SET usa '-volume'."""
        return await self.execute_set("setaudiooutvolume", {
            "-volume": str(volume),
        })



    # ── Reboot ───────────────────────────────────────────────────

    async def reboot(self) -> bool:
        return await self.execute_set("sysreboot")

    # ── Snapshot ─────────────────────────────────────────────────

    async def get_snapshot(self) -> bytes:
        """Scarica snapshot JPEG."""
        return await self._get_bytes(SNAPSHOT_PATH)

    # ── PTZ ──────────────────────────────────────────────────────

    async def ptz_command(self, action: str, step: int = 0) -> bool:
        text = await self._get(CGI_PTZ, {"-step": str(step), "-act": action})
        return "[Succeed]" in text

    async def ptz_preset_go(self, number: int) -> bool:
        text = await self._get(CGI_PRESET, {
            "-act": "presetgo", "-number": str(number),
        })
        return "[Succeed]" in text

    async def ptz_preset_save(self, number: int) -> bool:
        text = await self._get(CGI_PRESET, {
            "-act": "presetsave", "-number": str(number),
        })
        return "[Succeed]" in text

    # ── SD Browsing ──────────────────────────────────────────────

    async def browse_sd(self, path: str = "/sd/") -> list[str]:
        """Naviga la SD card, ritorna lista di entry (nomi con / se cartelle)."""
        text = await self._get(path)
        entries: list[str] = []
        for match in re.finditer(r'<a\s+href="([^"]+)"', text):
            name = match.group(1)
            if name in ("../", "/") or name.startswith("?") or "/.." in name:
                continue
            # Normalizza: rimuovi prefisso path se link assoluto
            if name.startswith(path) and name != path:
                name = name[len(path):]
            elif name.startswith("/"):
                continue
            entries.append(name)
        return entries
