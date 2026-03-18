"""HTTP proxy view per playback registrazioni SD Hi3510.

Flusso:
1. Browser richiede /api/hi3510/playback/{entry_id}/{path_b64}/{filename_b64}
2. Il proxy scarica il file .264/.265 dalla SD della camera via HTTP
3. Estrae i NAL raw con hxvs_parser (rimuove container HXVS/HXVT)
4. Remux con ffmpeg in MP4 (solo copy, nessuna ricodifica)
5. Streama l'MP4 al browser

Cache browser:
- /api/hi3510/cache → hub con griglia cam
- /api/hi3510/cache/{entry_id} → calendario mese + lista video giorno
- /api/hi3510/cache_file/{entry_id}/{filename} → serve MP4
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from base64 import urlsafe_b64decode, urlsafe_b64encode
from http import HTTPStatus
from pathlib import Path

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.components import persistent_notification as pn
from homeassistant.core import HomeAssistant, callback

from .const import CACHE_DIR, CACHE_MAX_AGE_DAYS, CONF_ALLOWED_NETWORKS, CONF_CACHE_RETENTION_DAYS, DEFAULT_ALLOWED_NETWORKS, DOMAIN
from .hxvs_parser import hxvs_to_mpegts

_LOGGER = logging.getLogger(__name__)

import ipaddress

_DEFAULT_NETWORKS = tuple(
    ipaddress.ip_network(n) for n in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
        "127.0.0.0/8", "::1/128", "fe80::/10",
    )
)


def _get_allowed_networks(hass: HomeAssistant) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Legge le reti ammesse dalle options di qualsiasi entry hi3510."""
    for entry_id, data in hass.data.get(DOMAIN, {}).items():
        if not isinstance(data, dict):
            continue
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.options.get(CONF_ALLOWED_NETWORKS):
            nets = []
            for n in entry.options[CONF_ALLOWED_NETWORKS].split(","):
                n = n.strip()
                if n:
                    try:
                        nets.append(ipaddress.ip_network(n, strict=False))
                    except ValueError:
                        pass
            nets.extend([
                ipaddress.ip_network("127.0.0.0/8"),
                ipaddress.ip_network("::1/128"),
            ])
            return tuple(nets)
    return _DEFAULT_NETWORKS


def _is_local_request(request: web.Request, hass: HomeAssistant) -> bool:
    """Verifica che la richiesta arrivi da una rete ammessa."""
    peername = request.transport.get_extra_info("peername")
    if not peername:
        return False
    try:
        addr = ipaddress.ip_address(peername[0])
    except ValueError:
        return False
    return any(addr in net for net in _get_allowed_networks(hass))


def cleanup_cache(hass: HomeAssistant) -> int:
    """Elimina file cache più vecchi della retention configurata."""
    import time

    retention_days = CACHE_MAX_AGE_DAYS
    for entry_id, data in hass.data.get(DOMAIN, {}).items():
        if not isinstance(data, dict):
            continue
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and CONF_CACHE_RETENTION_DAYS in entry.options:
            retention_days = entry.options[CONF_CACHE_RETENTION_DAYS]
            break

    cache_dir = Path(hass.config.path(CACHE_DIR))
    if not cache_dir.exists():
        return 0

    max_age_secs = retention_days * 86400
    now = time.time()
    removed = 0

    for f in cache_dir.iterdir():
        if f.is_file() and f.suffix == ".mp4":
            age = now - f.stat().st_mtime
            if age > max_age_secs:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass

    if removed:
        _LOGGER.info("Cache cleanup: rimossi %d file (>%d giorni)", removed, retention_days)
    return removed


def _get_cam_name(hass: HomeAssistant, entry_id: str) -> str:
    """Ottieni nome camera dal device registry."""
    from homeassistant.helpers import device_registry as dr
    data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not data or not isinstance(data, dict):
        return f"Camera {entry_id[:8]}"
    api = data["api"]
    cam_name = f"Hi3510 {api.host}"
    device_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_reg, entry_id):
        cam_name = device.name_by_user or device.name or cam_name
        break
    return cam_name


def _parse_file_date(orig_name: str) -> str | None:
    """Estrae data YYMMDD dal nome file tipo A260314_094243_094257.264 → '260314'."""
    if len(orig_name) < 7:
        return None
    candidate = orig_name[1:7]
    if candidate.isdigit():
        return candidate
    return None


@callback
def async_generate_playback_proxy_url(
    entry_id: str, sd_path: str, filename: str
) -> str:
    """Genera URL proxy per un file registrazione SD."""
    path_b64 = urlsafe_b64encode(sd_path.encode()).decode()
    file_b64 = urlsafe_b64encode(filename.encode()).decode()
    return Hi3510PlaybackView.url.format(
        entry_id=entry_id, path_b64=path_b64, file_b64=file_b64
    )



# ─── CSS condiviso ───────────────────────────────────────────────────────────

_SHARED_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #111; color: #e1e1e1; padding: 16px;
}
a { color: #4fc3f7; text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { font-size: 1.3em; margin-bottom: 4px; }
.header { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.header-left { flex:1; }
.subtitle { color:#888; font-size:0.9em; }
.btn {
  background:#1565c0; color:#fff; border:none; border-radius:8px;
  padding:8px 16px; font-size:0.85em; cursor:pointer; transition:background 0.2s;
}
.btn:hover { background:#1976d2; }
.btn-delete { background:#b71c1c; }
.btn-delete:hover { background:#d32f2f; }
.btn:disabled { background:#555; cursor:not-allowed; }
.card {
  background:#1c1c1c; border-radius:12px; padding:14px;
  margin-bottom:10px; cursor:pointer; transition:background 0.2s;
}
.card:hover { background:#252525; }
.card.active { background:#1a2a1a; cursor:default; }
.info { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:4px; }
.filename { font-size:0.95em; }
.meta { color:#888; font-size:0.8em; }
.player { margin-top:10px; }
.empty { color:#666; text-align:center; padding:40px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:12px; }
.cam-card {
  background:#1c1c1c; border-radius:12px; padding:18px; cursor:pointer;
  transition:background 0.2s, transform 0.1s; text-align:center;
}
.cam-card:hover { background:#252525; transform:translateY(-2px); }
.cam-icon { font-size:2.5em; margin-bottom:8px; }
.cam-name { font-size:1.05em; font-weight:600; margin-bottom:4px; }
.cam-badge { font-size:0.85em; padding:3px 10px; border-radius:12px; display:inline-block; margin-top:6px; }
.cam-badge.has { background:#1b5e20; color:#a5d6a7; }
.cam-badge.empty { background:#333; color:#888; }
/* Calendario */
.cal-nav { display:flex; align-items:center; justify-content:center; gap:16px; margin-bottom:16px; }
.cal-nav button { background:none; border:none; color:#4fc3f7; font-size:1.4em; cursor:pointer; padding:4px 8px; }
.cal-nav button:hover { color:#81d4fa; }
.cal-month { font-size:1.1em; font-weight:600; min-width:180px; text-align:center; }
.cal-grid { display:grid; grid-template-columns:repeat(7,1fr); gap:4px; margin-bottom:16px; max-width:400px; margin-left:auto; margin-right:auto; }
.cal-hdr { text-align:center; color:#888; font-size:0.75em; padding:4px; }
.cal-day {
  text-align:center; padding:8px 4px; border-radius:8px; font-size:0.85em;
  cursor:default; color:#555;
}
.cal-day.has { background:#1b5e20; color:#a5d6a7; cursor:pointer; }
.cal-day.has:hover { background:#2e7d32; }
.cal-day.sel { background:#0d47a1; color:#fff; }
.cal-day.today { border:1px solid #4fc3f7; }
"""



# ─── PlaybackView (invariata) ────────────────────────────────────────────────

class Hi3510PlaybackView(HomeAssistantView):
    """Proxy view per playback registrazioni SD."""

    requires_auth = True
    url = "/api/hi3510/playback/{entry_id}/{path_b64}/{file_b64}"
    name = "api:hi3510_playback"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(
        self,
        request: web.Request,
        entry_id: str,
        path_b64: str,
        file_b64: str,
    ) -> web.StreamResponse:
        """Scarica, converti e servi il file registrazione come MP4."""
        try:
            sd_path = urlsafe_b64decode(path_b64).decode()
            filename = urlsafe_b64decode(file_b64).decode()
        except Exception:
            return web.Response(
                text="Parametri URL non validi", status=HTTPStatus.BAD_REQUEST
            )

        full_path = f"{sd_path}{filename}"
        _LOGGER.debug("Playback richiesto: %s", full_path)

        try:
            data = self.hass.data[DOMAIN][entry_id]
        except KeyError:
            return web.Response(
                text="Camera non trovata", status=HTTPStatus.NOT_FOUND
            )
        api = data["api"]

        cache_dir = Path(self.hass.config.path(CACHE_DIR))
        cache_key = f"{entry_id}_{filename}".replace("/", "_")
        cache_file = cache_dir / f"{cache_key}.mp4"

        if cache_file.exists() and cache_file.stat().st_size > 0:
            _LOGGER.debug("Cache hit: %s", cache_file)
            return await self._serve_file(request, cache_file)

        notif_id = f"hi3510_playback_{cache_key}"
        short_name = filename.rsplit(".", 1)[0]

        self._notify(notif_id, f"⬇️ Download da camera: {short_name}...", "Hi3510 Playback")
        try:
            raw_data = await api.download_sd_file(full_path)
        except Exception as err:
            self._dismiss(notif_id)
            _LOGGER.error("Download SD fallito %s: %s", full_path, err)
            return web.Response(text=f"Download fallito: {err}", status=HTTPStatus.BAD_GATEWAY)

        if len(raw_data) < 100:
            self._dismiss(notif_id)
            return web.Response(text="File troppo piccolo", status=HTTPStatus.BAD_GATEWAY)

        raw_mb = len(raw_data) / 1048576

        self._notify(notif_id, f"🔄 Conversione: {short_name} ({raw_mb:.1f} MB)...", "Hi3510 Playback")
        try:
            ts_data, frame_count, codec, audio_raw = await self.hass.async_add_executor_job(
                hxvs_to_mpegts, raw_data
            )
        except ValueError as err:
            self._dismiss(notif_id)
            _LOGGER.error("Parser HXVS fallito %s: %s", filename, err)
            return web.Response(
                text=f"Formato non supportato: {err}",
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )

        if frame_count == 0 and codec != "h265":
            self._dismiss(notif_id)
            return web.Response(text="Nessun frame video trovato", status=HTTPStatus.UNPROCESSABLE_ENTITY)

        if codec == "h265":
            self._dismiss(notif_id)
            return web.Response(
                text="H.265 non supportato per il playback. Impostare la camera in H.264.",
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )

        self._notify(notif_id, f"🎬 Remux ffmpeg: {short_name} ({frame_count} frames)...", "Hi3510 Playback")
        try:
            mp4_data = await self._ffmpeg_remux(ts_data, codec, audio_raw)
        except Exception as err:
            self._dismiss(notif_id)
            _LOGGER.error("ffmpeg fallito %s: %s", filename, err)
            return web.Response(text=f"Conversione fallita: {err}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            await self.hass.async_add_executor_job(cache_file.write_bytes, mp4_data)
        except OSError as err:
            _LOGGER.warning("Cache write fallito: %s", err)

        self._dismiss(notif_id)
        return await self._serve_mp4_bytes(request, mp4_data)

    def _notify(self, notif_id: str, message: str, title: str) -> None:
        pn.async_create(self.hass, message, title, notif_id)

    def _dismiss(self, notif_id: str) -> None:
        pn.async_dismiss(self.hass, notif_id)

    async def _ffmpeg_remux(self, ts_data: bytes, codec: str, audio_raw: bytes = b"") -> bytes:
        """Remux MPEG-TS H.264 in MP4, con audio G.711 a-law se presente."""
        with tempfile.NamedTemporaryFile(suffix=".ts", delete=False) as tmp_in:
            tmp_in.write(ts_data)
            input_path = tmp_in.name

        audio_path = None
        if audio_raw:
            with tempfile.NamedTemporaryFile(suffix=".alaw", delete=False) as tmp_aud:
                tmp_aud.write(audio_raw)
                audio_path = tmp_aud.name

        output_path = input_path.rsplit(".", 1)[0] + ".mp4"
        cmd = ["ffmpeg", "-y", "-f", "mpegts", "-i", input_path]
        if audio_path:
            cmd.extend(["-f", "alaw", "-ar", "8000", "-ac", "1", "-i", audio_path])
        cmd.extend(["-c:v", "copy"])
        if audio_path:
            cmd.extend(["-c:a", "aac", "-b:a", "64k"])
        else:
            cmd.append("-an")
        cmd.extend(["-movflags", "+faststart", output_path])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg exit {proc.returncode}: {stderr.decode(errors='replace')[-300:]}")
            mp4_data = await self.hass.async_add_executor_job(Path(output_path).read_bytes)
            return mp4_data
        finally:
            for p in (input_path, output_path, audio_path):
                if p:
                    try:
                        Path(p).unlink(missing_ok=True)
                    except OSError:
                        pass

    async def _serve_file(self, request: web.Request, file_path: Path) -> web.StreamResponse:
        stat = file_path.stat()
        response = web.StreamResponse(status=200, headers={
            "Content-Type": "video/mp4", "Content-Length": str(stat.st_size),
            "Cache-Control": "public, max-age=86400",
        })
        await response.prepare(request)
        data = await self.hass.async_add_executor_job(file_path.read_bytes)
        await response.write(data)
        await response.write_eof()
        return response

    async def _serve_mp4_bytes(self, request: web.Request, data: bytes) -> web.StreamResponse:
        response = web.StreamResponse(status=200, headers={
            "Content-Type": "video/mp4", "Content-Length": str(len(data)),
        })
        await response.prepare(request)
        await response.write(data)
        await response.write_eof()
        return response



# ─── Cache Hub View (griglia cam) ────────────────────────────────────────────

class Hi3510CacheHubView(HomeAssistantView):
    """Hub con griglia di tutte le cam hi3510 e conteggio video mese corrente."""

    requires_auth = False
    url = "/api/hi3510/cache"
    name = "api:hi3510_cache_hub"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        if not _is_local_request(request, self.hass):
            return web.Response(text="Forbidden", status=HTTPStatus.FORBIDDEN)

        # Filtro opzionale: ?entries=id1,id2,id3
        entries_filter: set[str] | None = None
        entries_param = request.query.get("entries", "")
        if entries_param:
            entries_filter = {e.strip() for e in entries_param.split(",") if e.strip()}

        from datetime import datetime
        now = datetime.now()
        ym = f"{now.year % 100:02d}{now.month:02d}"

        cache_dir = Path(self.hass.config.path(CACHE_DIR))

        def _count_per_entry() -> dict[str, int]:
            counts: dict[str, int] = {}
            if not cache_dir.exists():
                return counts
            for f in cache_dir.iterdir():
                if f.suffix != ".mp4":
                    continue
                name = f.stem
                if len(name) < 28 or name[26] != "_":
                    continue
                eid = name[:26]
                if entries_filter and eid not in entries_filter:
                    continue
                orig = name[27:]
                d = _parse_file_date(orig)
                if d and d[:4] == ym:
                    counts[eid] = counts.get(eid, 0) + 1
            return counts

        counts = await self.hass.async_add_executor_job(_count_per_entry)

        # Costruisci lista cam (filtrata se richiesto)
        cams = []
        for entry_id, data in self.hass.data.get(DOMAIN, {}).items():
            if not isinstance(data, dict):
                continue
            if entries_filter and entry_id not in entries_filter:
                continue
            cam_name = _get_cam_name(self.hass, entry_id)
            cnt = counts.get(entry_id, 0)
            cams.append({"entry_id": entry_id, "name": cam_name, "count": cnt})

        cams.sort(key=lambda c: c["name"].lower())

        html = await self.hass.async_add_executor_job(
            self._render_html, cams, now.strftime("%B %Y"), entries_param
        )
        return web.Response(text=html, content_type="text/html")

    @staticmethod
    def _render_html(cams: list[dict], month_label: str, entries_param: str) -> str:
        import html as html_mod

        qs = f"?entries={entries_param}" if entries_param else ""
        cards = ""
        for c in cams:
            name_esc = html_mod.escape(c["name"])
            url = f"/api/hi3510/cache/{c['entry_id']}{qs}"
            cnt = c["count"]
            if cnt > 0:
                badge = f'<span class="cam-badge has">🟢 {cnt} video</span>'
            else:
                badge = '<span class="cam-badge empty">⚫ nessuna registrazione</span>'
            cards += f"""
            <div class="cam-card" onclick="location.href='{url}'">
              <div class="cam-icon">📹</div>
              <div class="cam-name">{name_esc}</div>
              {badge}
            </div>"""

        return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Registrazioni Cache</title>
<style>{_SHARED_CSS}</style>
</head><body>
<div class="header">
  <div class="header-left">
    <h1>📁 Registrazioni Cache</h1>
    <div class="subtitle">{html_mod.escape(month_label)} · {len(cams)} camere</div>
  </div>
</div>
<div class="grid">
{cards if cards else '<div class="empty">Nessuna camera Hi3510 configurata</div>'}
</div>
</body></html>"""



# ─── Cache Browser View (calendario per cam) ─────────────────────────────────

class Hi3510CacheBrowserView(HomeAssistantView):
    """Pagina cache per singola cam con navigazione calendario mese."""

    requires_auth = False
    url = "/api/hi3510/cache/{entry_id}"
    name = "api:hi3510_cache_browser"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        if not _is_local_request(request, self.hass):
            return web.Response(text="Forbidden", status=HTTPStatus.FORBIDDEN)
        try:
            self.hass.data[DOMAIN][entry_id]
        except KeyError:
            return web.Response(text="Camera non trovata", status=HTTPStatus.NOT_FOUND)

        entries_param = request.query.get("entries", "")
        cam_name = _get_cam_name(self.hass, entry_id)
        cache_dir = Path(self.hass.config.path(CACHE_DIR))
        prefix = f"{entry_id}_"

        def _scan_files() -> list[dict]:
            result: list[dict] = []
            if not cache_dir.exists():
                return result
            for f in sorted(cache_dir.iterdir(), key=lambda p: p.name[28:41] if len(p.name) > 41 else p.name, reverse=True):
                if f.suffix == ".mp4" and f.name.startswith(prefix):
                    stat = f.stat()
                    orig = f.stem[len(prefix):]
                    d = _parse_file_date(orig)
                    result.append({
                        "name": orig,
                        "size_mb": round(stat.st_size / 1048576, 1),
                        "mtime": stat.st_mtime,
                        "url": f"/api/hi3510/cache_file/{entry_id}/{f.name}",
                        "date": d,  # YYMMDD or None
                    })
            return result

        files = await self.hass.async_add_executor_job(_scan_files)

        html = await self.hass.async_add_executor_job(
            self._render_html, cam_name, files, entry_id, entries_param
        )
        return web.Response(text=html, content_type="text/html")

    async def delete(self, request: web.Request, entry_id: str) -> web.Response:
        if not _is_local_request(request, self.hass):
            return web.Response(text="Forbidden", status=HTTPStatus.FORBIDDEN)
        cache_dir = Path(self.hass.config.path(CACHE_DIR))
        prefix = f"{entry_id}_"

        def _do_delete() -> int:
            count = 0
            if not cache_dir.exists():
                return 0
            for f in cache_dir.iterdir():
                if f.suffix == ".mp4" and f.name.startswith(prefix):
                    try:
                        f.unlink()
                        count += 1
                    except OSError:
                        pass
            return count

        removed = await self.hass.async_add_executor_job(_do_delete)
        return web.json_response({"removed": removed})

    @staticmethod
    def _render_html(cam_name: str, files: list[dict], entry_id: str, entries_param: str) -> str:
        import html as html_mod
        import json
        from datetime import datetime

        back_qs = f"?entries={entries_param}" if entries_param else ""
        back_url = f"/api/hi3510/cache{back_qs}"

        # Prepara dati JSON per il JS: lista file con date
        files_json = []
        for f in files:
            dt = datetime.fromtimestamp(f["mtime"]).strftime("%d/%m/%Y %H:%M")
            # Formatta orario dal nome file se possibile (HHMMSS_HHMMSS)
            orig = f["name"]
            time_label = ""
            if len(orig) >= 20 and orig[7] == "_" and orig[14] == "_":
                try:
                    t_start = f"{orig[8:10]}:{orig[10:12]}:{orig[12:14]}"
                    t_end = f"{orig[15:17]}:{orig[17:19]}:{orig[19:21]}"
                    time_label = f"{t_start} → {t_end}"
                except (IndexError, ValueError):
                    pass
            files_json.append({
                "name": f["name"],
                "size_mb": f["size_mb"],
                "mtime_fmt": dt,
                "url": f["url"],
                "date": f["date"] or "",
                "time_label": time_label,
            })

        total_mb = sum(f["size_mb"] for f in files)
        name_esc = html_mod.escape(cam_name)
        delete_url = f"/api/hi3510/cache/{entry_id}"
        files_js = json.dumps(files_json, ensure_ascii=False)

        return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cache - {name_esc}</title>
<style>{_SHARED_CSS}</style>
</head><body>
<div class="header">
  <div class="header-left">
    <a href="{back_url}" style="font-size:0.85em">← Tutte le camere</a>
    <h1>📹 {name_esc}</h1>
    <div class="subtitle" id="stats">{len(files)} video in cache · {total_mb:.1f} MB totali</div>
  </div>
  {'<button class="btn btn-delete" onclick="clearCache()">🗑️ Svuota cache</button>' if files else ''}
</div>

<div class="cal-nav">
  <button onclick="changeMonth(-1)">◀</button>
  <div class="cal-month" id="cal-month-label"></div>
  <button onclick="changeMonth(1)">▶</button>
</div>
<div class="cal-grid" id="cal-grid"></div>

<div id="day-label" style="color:#4fc3f7;font-size:0.95em;margin-bottom:10px;display:none"></div>
<div id="file-list"></div>

<script>
const FILES = {files_js};
const DELETE_URL = '{delete_url}';
const MONTHS_IT = ['Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
  'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'];
const DAYS_IT = ['Lun','Mar','Mer','Gio','Ven','Sab','Dom'];

let curYear, curMonth;

// Inizializza al mese corrente
(function init() {{
  const now = new Date();
  curYear = now.getFullYear();
  curMonth = now.getMonth();
  renderCalendar();
}})();

function changeMonth(delta) {{
  curMonth += delta;
  if (curMonth < 0) {{ curMonth = 11; curYear--; }}
  if (curMonth > 11) {{ curMonth = 0; curYear++; }}
  renderCalendar();
  document.getElementById('file-list').innerHTML = '';
  document.getElementById('day-label').style.display = 'none';
}}

function getFilesForYM(y, m) {{
  // y=2026, m=2 (0-based) → ym="2603"
  const ym = String(y % 100).padStart(2,'0') + String(m+1).padStart(2,'0');
  return FILES.filter(f => f.date && f.date.substring(0,4) === ym);
}}

function getDaysWithFiles(y, m) {{
  const files = getFilesForYM(y, m);
  const days = new Set();
  files.forEach(f => {{
    const dd = parseInt(f.date.substring(4,6), 10);
    if (dd > 0) days.add(dd);
  }});
  return days;
}}

function renderCalendar() {{
  const label = document.getElementById('cal-month-label');
  label.textContent = MONTHS_IT[curMonth] + ' ' + curYear;

  const grid = document.getElementById('cal-grid');
  grid.innerHTML = '';

  // Header giorni
  DAYS_IT.forEach(d => {{
    const el = document.createElement('div');
    el.className = 'cal-hdr';
    el.textContent = d;
    grid.appendChild(el);
  }});

  const firstDay = new Date(curYear, curMonth, 1);
  let startDow = firstDay.getDay(); // 0=dom
  startDow = startDow === 0 ? 6 : startDow - 1; // 0=lun

  const daysInMonth = new Date(curYear, curMonth + 1, 0).getDate();
  const daysWithFiles = getDaysWithFiles(curYear, curMonth);
  const today = new Date();

  // Celle vuote prima
  for (let i = 0; i < startDow; i++) {{
    const el = document.createElement('div');
    el.className = 'cal-day';
    grid.appendChild(el);
  }}

  for (let d = 1; d <= daysInMonth; d++) {{
    const el = document.createElement('div');
    let cls = 'cal-day';
    if (daysWithFiles.has(d)) {{
      cls += ' has';
      el.onclick = () => showDay(d);
    }}
    if (d === today.getDate() && curMonth === today.getMonth() && curYear === today.getFullYear()) {{
      cls += ' today';
    }}
    el.className = cls;
    el.textContent = d;
    el.id = 'day-' + d;
    grid.appendChild(el);
  }}
}}

function showDay(day) {{
  // Evidenzia giorno selezionato
  document.querySelectorAll('.cal-day.sel').forEach(e => e.classList.remove('sel'));
  const el = document.getElementById('day-' + day);
  if (el) el.classList.add('sel');

  const dd = String(day).padStart(2, '0');
  const ym = String(curYear % 100).padStart(2,'0') + String(curMonth+1).padStart(2,'0');
  const target = ym + dd;

  const dayFiles = FILES.filter(f => f.date === target);
  dayFiles.sort((a, b) => a.name.substring(1).localeCompare(b.name.substring(1)));

  const dayLabel = document.getElementById('day-label');
  dayLabel.textContent = day + ' ' + MONTHS_IT[curMonth] + ' ' + curYear + ' — ' + dayFiles.length + ' video';
  dayLabel.style.display = 'block';

  const list = document.getElementById('file-list');
  if (dayFiles.length === 0) {{
    list.innerHTML = '<div class="empty">Nessun video per questo giorno</div>';
    return;
  }}

  let html = '';
  dayFiles.forEach(f => {{
    const label = f.time_label || f.name;
    html += '<div class="card" onclick="playVideo(this, \\'' + f.url.replace(/'/g, "\\\\'") + '\\')">' +
      '<div class="info">' +
        '<span class="filename">🎬 ' + escHtml(label) + '</span>' +
        '<span class="meta">' + f.size_mb + ' MB · ' + f.mtime_fmt + '</span>' +
      '</div>' +
      '<div class="player" style="display:none">' +
        '<video controls preload="none" style="width:100%;border-radius:8px"></video>' +
      '</div>' +
    '</div>';
  }});
  list.innerHTML = html;
}}

function escHtml(s) {{
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}}

function playVideo(card, url) {{
  if (card.classList.contains('active')) return;
  document.querySelectorAll('.card.active').forEach(c => {{
    c.classList.remove('active');
    const p = c.querySelector('.player');
    const v = p.querySelector('video');
    v.pause(); v.src = '';
    p.style.display = 'none';
  }});
  card.classList.add('active');
  const player = card.querySelector('.player');
  const video = player.querySelector('video');
  player.style.display = 'block';
  video.src = url;
  video.play();
}}

async function clearCache() {{
  if (!confirm('Eliminare tutti i video in cache per questa camera?')) return;
  const btn = document.querySelector('.btn-delete');
  btn.disabled = true;
  btn.textContent = '⏳ Eliminazione...';
  try {{
    const resp = await fetch(DELETE_URL, {{method: 'DELETE'}});
    const data = await resp.json();
    document.getElementById('file-list').innerHTML = '<div class="empty">Cache svuotata (' + data.removed + ' file rimossi)</div>';
    document.getElementById('stats').textContent = '0 video in cache · 0 MB totali';
    document.getElementById('day-label').style.display = 'none';
    btn.style.display = 'none';
    renderCalendar();
  }} catch(e) {{
    btn.disabled = false;
    btn.textContent = '🗑️ Svuota cache';
    alert('Errore: ' + e.message);
  }}
}}
</script>
</body></html>"""



# ─── Cache File View (invariata) ─────────────────────────────────────────────

class Hi3510CacheFileView(HomeAssistantView):
    """Serve un singolo file MP4 dalla cache."""

    requires_auth = False
    url = "/api/hi3510/cache_file/{entry_id}/{filename}"
    name = "api:hi3510_cache_file"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(
        self, request: web.Request, entry_id: str, filename: str
    ) -> web.StreamResponse:
        if not _is_local_request(request, self.hass):
            return web.Response(text="Forbidden", status=HTTPStatus.FORBIDDEN)
        if "/" in filename or "\\" in filename or ".." in filename:
            return web.Response(text="Invalid filename", status=HTTPStatus.BAD_REQUEST)

        cache_dir = Path(self.hass.config.path(CACHE_DIR))
        file_path = cache_dir / filename

        if not file_path.exists() or not file_path.suffix == ".mp4":
            return web.Response(text="File non trovato", status=HTTPStatus.NOT_FOUND)

        if not filename.startswith(f"{entry_id}_"):
            return web.Response(text="Accesso negato", status=HTTPStatus.FORBIDDEN)

        file_size = await self.hass.async_add_executor_job(lambda: file_path.stat().st_size)

        # Supporto HTTP Range per seek nel video
        range_header = request.headers.get("Range")
        start = 0
        end = file_size - 1

        if range_header and range_header.startswith("bytes="):
            try:
                range_spec = range_header[6:]
                parts = range_spec.split("-", 1)
                if parts[0]:
                    start = int(parts[0])
                if parts[1]:
                    end = int(parts[1])
                end = min(end, file_size - 1)
            except (ValueError, IndexError):
                start = 0
                end = file_size - 1

        content_length = end - start + 1

        if range_header:
            response = web.StreamResponse(
                status=206,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(content_length),
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=86400",
                },
            )
        else:
            response = web.StreamResponse(
                status=200,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(file_size),
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=86400",
                },
            )

        await response.prepare(request)

        def _read_chunk() -> bytes:
            with open(file_path, "rb") as f:
                f.seek(start)
                return f.read(content_length)

        data = await self.hass.async_add_executor_job(_read_chunk)
        await response.write(data)
        await response.write_eof()
        return response
