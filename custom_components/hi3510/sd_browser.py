"""SD Browser con cache indice, merge video e indicatori cache locale."""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from datetime import datetime, date
from http import HTTPStatus
from pathlib import Path

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.components import persistent_notification as pn
from homeassistant.core import HomeAssistant

from .const import CACHE_DIR, DOMAIN
from .hxvs_parser import hxvs_to_mpegts

_LOGGER = logging.getLogger(__name__)

SD_INDEX_DIR = "hi3510_sd_index"
INDEX_TTL_TODAY = 3600
INDEX_TTL_PAST = 86400


def _is_local(request: web.Request, hass: HomeAssistant) -> bool:
    from .views import _is_local_request
    return _is_local_request(request, hass)


def _get_cam_name(hass: HomeAssistant, entry_id: str) -> str:
    from .views import _get_cam_name as _gcn
    return _gcn(hass, entry_id)


def _index_path(hass: HomeAssistant, entry_id: str, day: str) -> Path:
    return Path(hass.config.path(SD_INDEX_DIR)) / f"{entry_id}_{day}.json"


def _is_today(day: str) -> bool:
    return day == datetime.now().strftime("%y%m%d")


def _index_fresh(idx_file: Path, day: str) -> bool:
    if not idx_file.exists():
        return False
    age = time.time() - idx_file.stat().st_mtime
    return age < (INDEX_TTL_TODAY if _is_today(day) else INDEX_TTL_PAST)


def _cache_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(CACHE_DIR))


def _cached_files_for_entry(hass: HomeAssistant, entry_id: str) -> set[str]:
    cd = _cache_dir(hass)
    prefix = f"{entry_id}_"
    result: set[str] = set()
    if not cd.exists():
        return result
    for f in cd.iterdir():
        if f.suffix == ".mp4" and f.name.startswith(prefix):
            result.add(f.stem[len(prefix):])
    return result


def _merged_files_for_entry(hass: HomeAssistant, entry_id: str) -> set[str]:
    cd = _cache_dir(hass)
    prefix = f"{entry_id}_MERGED_"
    result: set[str] = set()
    if not cd.exists():
        return result
    for f in cd.iterdir():
        if f.suffix == ".mp4" and f.name.startswith(prefix):
            result.add(f.stem[len(f"{entry_id}_"):])
    return result


def _used_in_merge_for_entry(hass: HomeAssistant, entry_id: str) -> set[str]:
    cd = _cache_dir(hass)
    prefix = f"{entry_id}_MERGED_"
    result: set[str] = set()
    if not cd.exists():
        return result
    for f in cd.iterdir():
        if f.suffix == ".json" and f.name.startswith(prefix):
            try:
                meta = json.loads(f.read_text())
                for src in meta.get("sources", []):
                    result.add(src)
            except Exception:
                pass
    return result


def _cache_stats_for_entry(hass: HomeAssistant, entry_id: str) -> dict[str, dict[str, int]]:
    """Conta file in cache locale per mese YYMM -> {cached, merged}."""
    cd = _cache_dir(hass)
    prefix = f"{entry_id}_"
    stats: dict[str, dict[str, int]] = {}
    if not cd.exists():
        return stats
    for f in cd.iterdir():
        if f.suffix != ".mp4" or not f.name.startswith(prefix):
            continue
        stem = f.stem[len(prefix):]
        if stem.startswith("MERGED_") and len(stem) >= 11:
            ym = stem[7:11]
            stats.setdefault(ym, {"cached": 0, "merged": 0})
            stats[ym]["merged"] += 1
        elif len(stem) >= 7:
            ym = stem[1:5]
            stats.setdefault(ym, {"cached": 0, "merged": 0})
            stats[ym]["cached"] += 1
    return stats


async def _build_sd_index(hass: HomeAssistant, entry_id: str, day: str, force: bool = False) -> list[dict]:
    idx_file = _index_path(hass, entry_id, day)
    if not force and _index_fresh(idx_file, day):
        return json.loads(idx_file.read_text())
    data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not data or not isinstance(data, dict):
        return []
    api = data["api"]
    full_date = f"20{day}"
    sd_path = f"/sd/{full_date}/"
    try:
        subdirs = await api.browse_sd(sd_path)
    except Exception as err:
        _LOGGER.debug("browse_sd %s fallito: %s", sd_path, err)
        return []
    files: list[dict] = []
    for subdir in subdirs:
        if not subdir.startswith("record"):
            continue
        rec_path = f"{sd_path}{subdir}"
        if not rec_path.endswith("/"):
            rec_path += "/"
        try:
            entries = await api.browse_sd(rec_path)
        except Exception:
            continue
        for fname in entries:
            if not fname.endswith(".264"):
                continue
            files.append({"name": fname, "path": rec_path, "full": f"{rec_path}{fname}"})
    files.sort(key=lambda f: f["name"][1:14] if len(f["name"]) > 14 else f["name"])
    def _save():
        idx_file.parent.mkdir(parents=True, exist_ok=True)
        idx_file.write_text(json.dumps(files, ensure_ascii=False))
    await hass.async_add_executor_job(_save)
    return files


_SD_CSS = (
    "* {margin:0;padding:0;box-sizing:border-box}"
    " body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#111;color:#e1e1e1;padding:16px}"
    " a{color:#4fc3f7;text-decoration:none} a:hover{text-decoration:underline}"
    " h1{font-size:1.3em;margin-bottom:4px}"
    " .header{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:16px}"
    " .header-left{flex:1} .subtitle{color:#888;font-size:0.9em}"
    " .btn{background:#1565c0;color:#fff;border:none;border-radius:8px;padding:8px 16px;font-size:0.85em;cursor:pointer;transition:background 0.2s;display:inline-flex;align-items:center;gap:6px}"
    " .btn:hover{background:#1976d2}"
    " .btn-delete{background:#b71c1c} .btn-delete:hover{background:#d32f2f}"
    " .btn-merge{background:#e65100} .btn-merge:hover{background:#f57c00}"
    " .btn:disabled{background:#555;cursor:not-allowed}"
    " .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}"
    " .cam-card{background:#1c1c1c;border-radius:12px;padding:18px;cursor:pointer;transition:background 0.2s,transform 0.1s;text-align:center}"
    " .cam-card:hover{background:#252525;transform:translateY(-2px)}"
    " .cam-icon{font-size:2.5em;margin-bottom:8px} .cam-name{font-size:1.05em;font-weight:600;margin-bottom:4px}"
    " .empty{color:#666;text-align:center;padding:40px}"
    " .cal-nav{display:flex;align-items:center;justify-content:center;gap:16px;margin-bottom:12px}"
    " .cal-month{font-size:1.1em;font-weight:600;min-width:180px;text-align:center}"
    " .cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:16px}"
    " .cal-hdr{text-align:center;color:#888;font-size:0.75em;padding:4px}"
    " .cal-day{text-align:center;padding:6px 2px;border-radius:8px;font-size:0.85em;cursor:default;color:#555;position:relative}"
    " .cal-day.has{background:#1b5e20;color:#a5d6a7;cursor:pointer} .cal-day.has:hover{background:#2e7d32}"
    " .cal-day.sel{background:#0d47a1;color:#fff} .cal-day.today{border:1px solid #4fc3f7}"
    " .cal-badge{font-size:0.6em;display:block;margin-top:1px;color:#81c784} .cal-day.sel .cal-badge{color:#90caf9}"
)

_SD_CSS2 = (
    " .file-row{display:flex;align-items:center;gap:10px;padding:10px 14px;background:#1c1c1c;border-radius:10px;margin-bottom:6px;transition:background 0.2s;cursor:pointer}"
    " .file-row:hover{background:#252525} .file-row.active{background:#1a2a1a}"
    " .file-row input[type=checkbox]{width:18px;height:18px;cursor:pointer;flex-shrink:0}"
    " .file-info{flex:1;min-width:0} .file-name{font-size:0.92em} .file-meta{color:#888;font-size:0.78em;margin-top:2px}"
    " .file-icon{font-size:1.1em;flex-shrink:0} .player{margin-top:8px}"
    " .counter{color:#888;font-size:0.85em;margin-bottom:12px}"
    " .toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center}"
    " .spinner{display:inline-block;width:16px;height:16px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite}"
    " @keyframes spin{to{transform:rotate(360deg)}}"
    " .toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1b5e20;color:#fff;padding:12px 24px;border-radius:10px;font-size:0.9em;z-index:999;opacity:0;transition:opacity 0.3s}"
    " .toast.show{opacity:1}"
    " .layout{display:flex;gap:16px}"
    " .sidebar{width:200px;flex-shrink:0}"
    " .main-panel{flex:1;min-width:0}"
    " .month-item{padding:10px 12px;border-radius:8px;margin-bottom:4px;cursor:pointer;transition:background 0.2s;background:#1c1c1c;display:flex;justify-content:space-between;align-items:center;gap:6px}"
    " .month-item:hover{background:#252525} .month-item.active{background:#0d47a1;color:#fff}"
    " .month-label{font-size:0.9em}"
    " .month-badges{display:flex;gap:4px;font-size:0.7em;flex-shrink:0}"
    " .month-badges span{padding:2px 5px;border-radius:4px;white-space:nowrap}"
    " .badge-cached{background:#1b5e20;color:#a5d6a7} .badge-merged{background:#4a2800;color:#ffb74d}"
    " .filter-bar{display:flex;gap:4px;margin-bottom:12px;flex-wrap:wrap}"
    " .filter-btn{padding:6px 12px;border:none;border-radius:6px;cursor:pointer;font-size:0.8em;background:#333;color:#888;transition:all 0.2s}"
    " .filter-btn.active{background:#1565c0;color:#fff} .filter-btn:hover{background:#444} .filter-btn.active:hover{background:#1976d2}"
    " .file-row.used{opacity:0.6} .used-badge{color:#e65100;font-size:0.75em;margin-left:4px}"
    " @media(max-width:700px){.layout{flex-direction:column}.sidebar{width:100%;display:flex;flex-wrap:wrap;gap:4px}.month-item{flex:1;min-width:90px;text-align:center;flex-direction:column}}"
)


class Hi3510SdHubView(HomeAssistantView):
    requires_auth = False
    url = "/api/hi3510/sd"
    name = "api:hi3510_sd_hub"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        if not _is_local(request, self.hass):
            return web.Response(text="Forbidden", status=HTTPStatus.FORBIDDEN)
        entries_filter: set[str] | None = None
        entries_param = request.query.get("entries", "")
        if entries_param:
            entries_filter = {e.strip() for e in entries_param.split(",") if e.strip()}
        cams = []
        for entry_id, data in self.hass.data.get(DOMAIN, {}).items():
            if not isinstance(data, dict):
                continue
            if entries_filter and entry_id not in entries_filter:
                continue
            cam_name = _get_cam_name(self.hass, entry_id)
            cached = await self.hass.async_add_executor_job(_cached_files_for_entry, self.hass, entry_id)
            merged = await self.hass.async_add_executor_job(_merged_files_for_entry, self.hass, entry_id)
            cams.append({"entry_id": entry_id, "name": cam_name, "cached": len(cached) + len(merged)})
        cams.sort(key=lambda c: c["name"].lower())
        qs = f"?entries={entries_param}" if entries_param else ""
        import html as html_mod
        cards = ""
        for c in cams:
            ne = html_mod.escape(c["name"])
            url = f"/api/hi3510/sd/{c['entry_id']}{qs}"
            cnt = c["cached"]
            if cnt > 0:
                badge = f'<div style="color:#4caf50;font-size:0.8em;margin-top:4px">\U0001f7e2 {cnt} video</div>'
            else:
                badge = '<div style="color:#666;font-size:0.8em;margin-top:4px">\u26aa nessun video</div>'
            cards += f'<div class="cam-card" onclick="location.href=\'{url}\'"><div class="cam-icon">\U0001f4f9</div><div class="cam-name">{ne}</div>{badge}</div>'
        css = _SD_CSS + _SD_CSS2
        html = f'<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SD Browser</title><style>{css}</style></head><body>'
        html += f'<div class="header"><div class="header-left"><h1>\U0001f4be SD Browser</h1><div class="subtitle">{len(cams)} camere</div></div></div>'
        html += f'<div class="grid">{cards if cards else chr(60)+"div class="+chr(34)+"empty"+chr(34)+chr(62)+"Nessuna camera Hi3510 configurata"+chr(60)+"/div"+chr(62)}</div></body></html>'
        return web.Response(text=html, content_type="text/html")


class Hi3510SdBrowserView(HomeAssistantView):
    requires_auth = False
    url = "/api/hi3510/sd/{entry_id}"
    name = "api:hi3510_sd_browser"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        if not _is_local(request, self.hass):
            return web.Response(text="Forbidden", status=HTTPStatus.FORBIDDEN)
        if entry_id not in self.hass.data.get(DOMAIN, {}):
            return web.Response(text="Camera non trovata", status=HTTPStatus.NOT_FOUND)
        entries_param = request.query.get("entries", "")
        cam_name = _get_cam_name(self.hass, entry_id)
        import html as html_mod
        name_esc = html_mod.escape(cam_name)
        back_qs = f"?entries={entries_param}" if entries_param else ""
        back_url = f"/api/hi3510/sd{back_qs}"
        html = _browser_html(name_esc, entry_id, back_url)
        return web.Response(text=html, content_type="text/html")


def _browser_html(cam_name: str, eid: str, back_url: str) -> str:
    css = _SD_CSS + _SD_CSS2
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SD - {cam_name}</title><style>{css}</style></head><body>
<div class="header">
  <div class="header-left">
    <a href="{back_url}" style="font-size:0.85em">\u2190 Tutte le camere</a>
    <h1>\U0001f4f9 {cam_name}</h1>
    <div class="subtitle" id="stats">Seleziona un mese</div>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <button class="btn btn-delete" id="btn-clear" onclick="clearCache()" style="display:none">\U0001f5d1\ufe0f Svuota cache</button>
  </div>
</div>
<div class="layout">
  <div class="sidebar" id="sidebar"><div class="empty" style="padding:16px;font-size:0.85em">\u23f3 Caricamento...</div></div>
  <div class="main-panel">
    <div id="cal-section" style="display:none">
      <div class="cal-nav"><div class="cal-month" id="cal-month-label"></div></div>
      <div class="cal-grid" id="cal-grid"></div>
    </div>
    <div id="day-label" style="color:#4fc3f7;font-size:0.95em;margin-bottom:8px;display:none"></div>
    <div class="counter" id="counter" style="display:none"></div>
    <div class="toolbar" id="toolbar" style="display:none">
      <button class="btn" id="btn-sel-all" onclick="toggleSelectAll()">\u2611\ufe0f Tutti</button>
      <button class="btn" id="btn-sel-range" onclick="selectRange()">\U0001f4cf Intervallo</button>
      <button class="btn btn-merge" id="btn-merge" onclick="doMerge()" disabled>\U0001f517 Unisci</button>
      <button class="btn" id="btn-refresh" onclick="refreshDay()">\U0001f504 Aggiorna</button>
    </div>
    <div class="filter-bar" id="filter-bar" style="display:none">
      <button class="filter-btn active" id="flt-all" onclick="setFilter('all')">Tutti</button>
      <button class="filter-btn" id="flt-alarm" onclick="setFilter('alarm')">\U0001f534 Allarmi</button>
      <button class="filter-btn" id="flt-rec" onclick="setFilter('rec')">\U0001f4f9 Registrazioni</button>
      <button class="filter-btn" id="flt-merged" onclick="setFilter('merged')">\U0001f517 Uniti</button>
      <button class="filter-btn" id="flt-cached" onclick="setFilter('cached')">\U0001f4be In cache</button>
    </div>
    <div id="file-list"></div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
""" + _browser_js(eid) + """
</script></body></html>"""


def _browser_js(eid: str) -> str:
    return _JS_TEMPLATE.replace("__EID__", eid)


_JS_TEMPLATE = r"""
const ENTRY='__EID__';
const IX='/api/hi3510/sd/__EID__/index';
const MU='/api/hi3510/sd/__EID__/month';
const SU='/api/hi3510/sd/__EID__/cache_stats';
const MR='/api/hi3510/sd/__EID__/merge';
const CL='/api/hi3510/sd/__EID__/clear';
const DL='/api/hi3510/sd/__EID__/download';
const CF='/api/hi3510/cache_file/__EID__/';
const MI=['Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno','Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'];
const DI=['Lun','Mar','Mer','Gio','Ven','Sab','Dom'];
let curYear,curMonth,curDay=null;
let dayFiles=[],dayMerged=[],cachedSet=new Set(),usedSet=new Set();
let daysWithData={},allSelectMode=false,currentFilter='all';
let sdMonths=[],cacheStats={};

(function(){loadSidebar()})();

async function loadSidebar(){
  try{
    const[sR,cR]=await Promise.all([fetch(MU+'?ym=ALL'),fetch(SU)]);
    let sD={};try{sD=await sR.json()}catch(e){}
    try{cacheStats=await cR.json()}catch(e){}
    const ms=new Set();
    if(sD.months)sD.months.forEach(m=>ms.add(m));
    Object.keys(cacheStats).forEach(ym=>ms.add(ym));
    sdMonths=Array.from(ms).sort().reverse();
    renderSidebar();
    if(sdMonths.length>0)selectMonth(sdMonths[0]);
    else document.getElementById('sidebar').innerHTML='<div class="empty" style="padding:16px;font-size:0.85em">Nessun dato</div>';
  }catch(e){
    document.getElementById('sidebar').innerHTML='<div class="empty" style="padding:16px;font-size:0.85em">Errore: '+e.message+'</div>';
  }
}
"""

_JS_TEMPLATE += r"""
function renderSidebar(){
  const sb=document.getElementById('sidebar');let h='';
  sdMonths.forEach(ym=>{
    const y=2000+parseInt(ym.substring(0,2)),m=parseInt(ym.substring(2,4));
    const label=MI[m-1]+' '+y;
    const cs=cacheStats[ym]||{};const c=cs.cached||0,mg=cs.merged||0;
    const act=(curYear===y&&curMonth===m-1);
    let badges='';
    if(c>0)badges+='<span class="badge-cached">\ud83d\udcbe '+c+'</span>';
    if(mg>0)badges+='<span class="badge-merged">\ud83d\udd17 '+mg+'</span>';
    h+='<div class="month-item'+(act?' active':'')+'" onclick="selectMonth(\''+ym+'\')"><span class="month-label">'+label+'</span><div class="month-badges">'+badges+'</div></div>';
  });
  sb.innerHTML=h||'<div class="empty" style="padding:16px;font-size:0.85em">Nessun mese</div>';
}

async function selectMonth(ym){
  const y=2000+parseInt(ym.substring(0,2)),m=parseInt(ym.substring(2,4))-1;
  curYear=y;curMonth=m;curDay=null;daysWithData={};
  renderSidebar();
  document.getElementById('cal-section').style.display='block';
  document.getElementById('file-list').innerHTML='';
  document.getElementById('day-label').style.display='none';
  document.getElementById('counter').style.display='none';
  document.getElementById('toolbar').style.display='none';
  document.getElementById('filter-bar').style.display='none';
  document.getElementById('stats').textContent='Caricamento '+MI[m]+'...';
  renderCalendar();
  await loadMonthIndex(y,m);
  document.getElementById('stats').textContent=MI[m]+' '+y+' \u2014 '+Object.keys(daysWithData).length+' giorni con registrazioni';
}

async function loadMonthIndex(y,m){
  const ym=String(y%100).padStart(2,'0')+String(m+1).padStart(2,'0');
  try{
    const r=await fetch(MU+'?ym='+ym);const d=await r.json();
    if(d.days)for(const[day,count]of Object.entries(d.days))daysWithData[day]=count;
  }catch(e){console.error('loadMonthIndex:',e)}
  renderCalendar();
}
"""

_JS_TEMPLATE += r"""
function renderCalendar(){
  document.getElementById('cal-month-label').textContent=MI[curMonth]+' '+curYear;
  const grid=document.getElementById('cal-grid');grid.innerHTML='';
  DI.forEach(d=>{const el=document.createElement('div');el.className='cal-hdr';el.textContent=d;grid.appendChild(el)});
  const fd=new Date(curYear,curMonth,1);let sd=fd.getDay();sd=sd===0?6:sd-1;
  const dim=new Date(curYear,curMonth+1,0).getDate();
  const today=new Date();
  const ym=String(curYear%100).padStart(2,'0')+String(curMonth+1).padStart(2,'0');
  for(let i=0;i<sd;i++){const el=document.createElement('div');el.className='cal-day';grid.appendChild(el)}
  for(let d=1;d<=dim;d++){
    const el=document.createElement('div');
    const dd=String(d).padStart(2,'0');const dk=ym+dd;
    let cls='cal-day';const cnt=daysWithData[dk];
    if(cnt){cls+=' has';el.onclick=()=>showDay(d);el.title=cnt+' file su SD'}
    if(d===curDay)cls+=' sel';
    if(d===today.getDate()&&curMonth===today.getMonth()&&curYear===today.getFullYear())cls+=' today';
    el.className=cls;
    let inner=''+d;
    if(cnt)inner+='<span class="cal-badge">'+cnt+'</span>';
    el.innerHTML=inner;el.id='day-'+d;grid.appendChild(el);
  }
}

async function showDay(day){
  curDay=day;renderCalendar();
  const dd=String(day).padStart(2,'0');
  const ym=String(curYear%100).padStart(2,'0')+String(curMonth+1).padStart(2,'0');
  const dk=ym+dd;
  document.getElementById('day-label').style.display='block';
  document.getElementById('day-label').textContent=day+' '+MI[curMonth]+' '+curYear+' \u2014 caricamento...';
  document.getElementById('file-list').innerHTML='<div class="empty"><div class="spinner"></div> Caricamento...</div>';
  try{
    const r=await fetch(IX+'?day='+dk);const data=await r.json();
    dayFiles=data.files||[];dayMerged=data.merged||[];
    cachedSet=new Set(data.cached||[]);usedSet=new Set(data.used||[]);
    currentFilter='all';
    document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
    document.getElementById('flt-all').classList.add('active');
    renderFileList();
  }catch(e){
    document.getElementById('file-list').innerHTML='<div class="empty">Errore: '+e.message+'</div>';
  }
}
"""

_JS_TEMPLATE += r"""
function refreshDay(){
  if(!curDay)return;
  const dd=String(curDay).padStart(2,'0');
  const ym=String(curYear%100).padStart(2,'0')+String(curMonth+1).padStart(2,'0');
  const dk=ym+dd;
  document.getElementById('file-list').innerHTML='<div class="empty"><div class="spinner"></div> Aggiornamento...</div>';
  fetch(IX+'?day='+dk+'&force=1').then(r=>r.json()).then(data=>{
    dayFiles=data.files||[];dayMerged=data.merged||[];
    cachedSet=new Set(data.cached||[]);usedSet=new Set(data.used||[]);
    renderFileList();
    daysWithData[dk]=dayFiles.length||undefined;
    if(!dayFiles.length)delete daysWithData[dk];
    renderCalendar();showToast('Lista aggiornata');
  }).catch(e=>{document.getElementById('file-list').innerHTML='<div class="empty">Errore: '+e.message+'</div>'});
}

function setFilter(f){
  currentFilter=f;
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
  const ids={all:'flt-all',alarm:'flt-alarm',rec:'flt-rec',merged:'flt-merged',cached:'flt-cached'};
  document.getElementById(ids[f]).classList.add('active');
  renderFileList();
}

function renderFileList(){
  const day=curDay;
  const cachedCount=dayFiles.filter(f=>cachedSet.has(f.name.replace('.264',''))).length;
  const usedCount=dayFiles.filter(f=>usedSet.has(f.name.replace('.264',''))).length;
  document.getElementById('day-label').textContent=day+' '+MI[curMonth]+' '+curYear+' \u2014 '+dayFiles.length+' file';
  document.getElementById('counter').style.display='block';
  document.getElementById('counter').textContent='\ud83d\udcbe '+cachedCount+'/'+dayFiles.length+' in cache | \u2713 '+usedCount+' gi\u00e0 uniti | \ud83d\udd17 '+dayMerged.length+' merged';
  document.getElementById('toolbar').style.display=dayFiles.length||dayMerged.length?'flex':'none';
  document.getElementById('filter-bar').style.display=dayFiles.length||dayMerged.length?'flex':'none';
  document.getElementById('btn-clear').style.display=cachedCount>0||dayMerged.length>0?'':'none';
  let html='';
"""

_JS_TEMPLATE += r"""
  // Merged files
  if(currentFilter==='all'||currentFilter==='merged'){
    dayMerged.slice().sort((a,b)=>a.localeCompare(b)).forEach((m,mi)=>{
      const mUrl=CF+ENTRY+'_'+m+'.mp4';
      let mLabel=m;
      if(m.startsWith('MERGED_')&&m.length>=27){
        try{const ts=m.substring(14,16)+':'+m.substring(16,18)+':'+m.substring(18,20);
        const te=m.substring(21,23)+':'+m.substring(23,25)+':'+m.substring(25,27);
        mLabel='\ud83d\udd17 '+ts+' \u2192 '+te}catch(e){}
      }
      html+='<div class="file-row" id="mrow-'+mi+'" style="border-left:3px solid #e65100" data-type="merged" data-merged="'+escH(m)+'">'
        +'<input type="checkbox" id="mchk-'+mi+'" onchange="updateMergeBtn()" onclick="event.stopPropagation()">'
        +'<span class="file-icon">\ud83d\udd17</span>'
        +'<div class="file-info" onclick="playMerged(this,\''+escH(mUrl)+'\')"><div class="file-name">'+escH(mLabel)+'</div><div class="file-meta">'+escH(m)+'</div></div>'
        +'</div>';
    });
  }
  // Source files
  dayFiles.forEach((f,i)=>{
    const name=f.name;const baseName=name.replace('.264','');
    const isAlarm=name[0]==='A';const isRec=name[0]==='P';
    const isCached=cachedSet.has(baseName);const isUsed=usedSet.has(baseName);
    if(currentFilter==='alarm'&&!isAlarm)return;
    if(currentFilter==='rec'&&!isRec)return;
    if(currentFilter==='merged')return;
    if(currentFilter==='cached'&&!isCached)return;
    const icon=isCached?'\ud83d\udcbe':'\u2601\ufe0f';
    let timeLabel=name;
    if(name.length>=22&&name[7]==='_'&&name[14]==='_'){
      try{const ts=name.substring(8,10)+':'+name.substring(10,12)+':'+name.substring(12,14);
      const te=name.substring(15,17)+':'+name.substring(17,19)+':'+name.substring(19,21);
      const prefix=isAlarm?'\ud83d\udd34 ':isRec?'\ud83d\udcf9 ':'';
      timeLabel=prefix+ts+' \u2192 '+te}catch(e){}
    }
    const playUrl=isCached?CF+ENTRY+'_'+baseName+'.mp4':'';
    const usedBadge=isUsed?'<span class="used-badge">\u2713 unito</span>':'';
    const rowClass='file-row'+(isUsed?' used':'');
    html+='<div class="'+rowClass+'" id="row-'+i+'" data-idx="'+i+'" data-name="'+escH(name)+'" data-cached="'+(isCached?1:0)+'" data-type="source">'
      +'<input type="checkbox" id="chk-'+i+'" onchange="updateMergeBtn()" onclick="event.stopPropagation()">'
      +'<span class="file-icon">'+icon+'</span>'
      +'<div class="file-info" onclick="togglePlay('+i+',\''+escH(playUrl)+'\','+isCached+')">'
      +'<div class="file-name">'+escH(timeLabel)+usedBadge+'</div>'
      +'<div class="file-meta">'+escH(name)+'</div></div></div>';
  });
  if(!html)html='<div class="empty">Nessun file per questo filtro</div>';
  document.getElementById('file-list').innerHTML=html;
  allSelectMode=false;
}
function escH(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
"""

_JS_TEMPLATE += r"""
async function togglePlay(idx,url,isCached){
  const row=document.getElementById('row-'+idx);
  if(row.classList.contains('active')){
    row.classList.remove('active');const p=row.querySelector('.player');
    if(p){const v=p.querySelector('video');if(v){v.pause();v.src=''}p.remove()}return;
  }
  document.querySelectorAll('.file-row.active').forEach(r=>{
    r.classList.remove('active');const p=r.querySelector('.player');
    if(p){const v=p.querySelector('video');if(v){v.pause();v.src=''}p.remove()}
  });
  if(!isCached){
    const f=dayFiles[idx];if(!f)return;
    row.classList.add('active');
    const player=document.createElement('div');player.className='player';
    player.innerHTML='<div style="padding:16px;text-align:center"><div class="spinner"></div><div style="margin-top:8px;color:#888;font-size:0.85em" id="dl-status-'+idx+'">Download in corso...</div></div>';
    row.appendChild(player);
    const iconEl=row.querySelector('.file-icon');if(iconEl)iconEl.textContent='\u23f3';
    try{
      const r=await fetch(DL,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:f.name,path:f.path,full:f.full})});
      const data=await r.json();
      if(data.error){showToast('Errore: '+data.error);player.remove();row.classList.remove('active');if(iconEl)iconEl.textContent='\u2601\ufe0f';return}
      cachedSet.add(f.name.replace('.264',''));
      if(iconEl)iconEl.textContent='\ud83d\udcbe';
      row.dataset.cached='1';
      const mp4Url=CF+ENTRY+'_'+f.name.replace('.264','')+'.mp4';
      player.innerHTML='<video controls preload="none" style="width:100%;border-radius:8px;margin-top:8px"></video>';
      player.querySelector('video').src=mp4Url;player.querySelector('video').play();
      showToast('\u2705 Scaricato e convertito');
      const cc=document.getElementById('counter');
      if(cc){const nc=dayFiles.filter(x=>cachedSet.has(x.name.replace('.264',''))).length;
      const uc=dayFiles.filter(x=>usedSet.has(x.name.replace('.264',''))).length;
      cc.textContent='\ud83d\udcbe '+nc+'/'+dayFiles.length+' in cache | \u2713 '+uc+' gi\u00e0 uniti | \ud83d\udd17 '+dayMerged.length+' merged'}
    }catch(e){showToast('Errore download: '+e.message);player.remove();row.classList.remove('active');if(iconEl)iconEl.textContent='\u2601\ufe0f'}
    return;
  }
  row.classList.add('active');
  const player=document.createElement('div');player.className='player';
  player.innerHTML='<video controls preload="none" style="width:100%;border-radius:8px;margin-top:8px"></video>';
  row.appendChild(player);player.querySelector('video').src=url;player.querySelector('video').play();
}
function playMerged(el,url){
  const row=el.closest('.file-row');
  if(row.classList.contains('active')){
    row.classList.remove('active');const p=row.querySelector('.player');
    if(p){const v=p.querySelector('video');if(v){v.pause();v.src=''}p.remove()}return;
  }
  row.classList.add('active');
  const player=document.createElement('div');player.className='player';
  player.innerHTML='<video controls preload="none" style="width:100%;border-radius:8px;margin-top:8px"></video>';
  row.appendChild(player);player.querySelector('video').src=url;player.querySelector('video').play();
}
function toggleSelectAll(){
  allSelectMode=!allSelectMode;
  document.querySelectorAll('#file-list input[type=checkbox]').forEach(c=>c.checked=allSelectMode);
  document.getElementById('btn-sel-all').textContent=allSelectMode?'\u2610 Deseleziona':'\u2611\ufe0f Tutti';
  updateMergeBtn();
}
function selectRange(){
  const checked=[];
  document.querySelectorAll('#file-list input[type=checkbox]').forEach((c,i)=>{if(c.checked)checked.push(i)});
  if(checked.length<2){showToast('Seleziona almeno 2 file');return}
  const min=Math.min(...checked),max=Math.max(...checked);
  document.querySelectorAll('#file-list input[type=checkbox]').forEach((c,i)=>{if(i>=min&&i<=max)c.checked=true});
  updateMergeBtn();showToast('Selezionati '+(min+1)+' - '+(max+1));
}
function updateMergeBtn(){
  let count=0;document.querySelectorAll('#file-list input[type=checkbox]').forEach(c=>{if(c.checked)count++});
  const btn=document.getElementById('btn-merge');
  btn.disabled=count<2;
  btn.textContent=count>=2?'\ud83d\udd17 Unisci '+count:'\ud83d\udd17 Unisci';
}
"""

_JS_TEMPLATE += r"""
async function doMerge(){
  const selected=[];
  document.querySelectorAll('#file-list .file-row[data-type="source"] input[type=checkbox]:checked').forEach(c=>{
    const row=c.closest('.file-row');const idx=parseInt(row.dataset.idx);
    if(idx<dayFiles.length)selected.push(dayFiles[idx]);
  });
  document.querySelectorAll('#file-list .file-row[data-type="merged"] input[type=checkbox]:checked').forEach(c=>{
    const row=c.closest('.file-row');const mn=row.dataset.merged;
    selected.push({name:mn+'.mp4',path:'',full:'MERGED:'+mn});
  });
  if(selected.length<2)return;
  const btn=document.getElementById('btn-merge');
  btn.disabled=true;btn.innerHTML='<span class="spinner"></span> Unione...';
  try{
    const r=await fetch(MR,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({files:selected})});
    const data=await r.json();
    if(data.error)showToast('Errore: '+data.error);
    else{showToast('\u2705 '+data.message);setTimeout(()=>showDay(curDay),1000)}
  }catch(e){showToast('Errore: '+e.message)}
  finally{btn.disabled=false;btn.textContent='\ud83d\udd17 Unisci'}
}
async function clearCache(){
  if(!confirm('Eliminare tutti i video in cache locale per questa camera?'))return;
  const btn=document.getElementById('btn-clear');
  btn.disabled=true;btn.textContent='\u23f3 Eliminazione...';
  try{
    const r=await fetch(CL,{method:'DELETE'});const data=await r.json();
    showToast('Cache svuotata: '+data.removed+' file rimossi');
    btn.style.display='none';if(curDay)showDay(curDay);
    // Ricarica sidebar
    try{const csR=await fetch(SU);cacheStats=await csR.json()}catch(e){}
    renderSidebar();
  }catch(e){showToast('Errore: '+e.message)}
  finally{btn.disabled=false;btn.textContent='\ud83d\uddd1\ufe0f Svuota cache'}
}
function showToast(msg){
  const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),3000);
}
"""


# ── API Views ────────────────────────────────────────────────────────────────

class Hi3510SdMonthView(HomeAssistantView):
    requires_auth = False
    url = "/api/hi3510/sd/{entry_id}/month"
    name = "api:hi3510_sd_month"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        if not _is_local(request, self.hass):
            return web.Response(text="Forbidden", status=HTTPStatus.FORBIDDEN)
        ym = request.query.get("ym", "")
        if not ym:
            return web.json_response({"error": "Parametro ym mancante"}, status=400)
        data = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if not data or not isinstance(data, dict):
            return web.json_response({"error": "Camera non trovata"}, status=404)
        api = data["api"]
        try:
            sd_entries = await api.browse_sd("/sd/")
        except Exception as err:
            _LOGGER.debug("browse_sd /sd/ fallito: %s", err)
            return web.json_response({"days": {}, "months": []})
        if ym == "ALL":
            months: set[str] = set()
            for entry_name in sd_entries:
                clean = entry_name.rstrip("/")
                if len(clean) == 8 and clean.isdigit():
                    months.add(clean[2:6])
            return web.json_response({"months": sorted(months)})
        if len(ym) != 4 or not ym.isdigit():
            return web.json_response({"error": "ym deve essere YYMM o ALL"}, status=400)
        full_ym = f"20{ym}"
        days: dict[str, int] = {}
        for entry_name in sd_entries:
            clean = entry_name.rstrip("/")
            if len(clean) == 8 and clean.isdigit() and clean[:6] == full_ym:
                day_key = clean[2:]
                idx_file = _index_path(self.hass, entry_id, day_key)
                if idx_file.exists():
                    try:
                        cached_data = json.loads(await self.hass.async_add_executor_job(idx_file.read_text))
                        days[day_key] = len(cached_data)
                    except Exception:
                        days[day_key] = 1
                else:
                    days[day_key] = 1
        return web.json_response({"ym": ym, "days": days})


class Hi3510SdCacheStatsView(HomeAssistantView):
    requires_auth = False
    url = "/api/hi3510/sd/{entry_id}/cache_stats"
    name = "api:hi3510_sd_cache_stats"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        if not _is_local(request, self.hass):
            return web.Response(text="Forbidden", status=HTTPStatus.FORBIDDEN)
        stats = await self.hass.async_add_executor_job(_cache_stats_for_entry, self.hass, entry_id)
        return web.json_response(stats)


class Hi3510SdIndexView(HomeAssistantView):
    requires_auth = False
    url = "/api/hi3510/sd/{entry_id}/index"
    name = "api:hi3510_sd_index"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        if not _is_local(request, self.hass):
            return web.Response(text="Forbidden", status=HTTPStatus.FORBIDDEN)
        day = request.query.get("day", "")
        if not day or len(day) != 6 or not day.isdigit():
            return web.json_response({"error": "Parametro day mancante (YYMMDD)"}, status=400)
        force = request.query.get("force", "") == "1"
        files = await _build_sd_index(self.hass, entry_id, day, force=force)
        cached_set = await self.hass.async_add_executor_job(_cached_files_for_entry, self.hass, entry_id)
        merged_set = await self.hass.async_add_executor_job(_merged_files_for_entry, self.hass, entry_id)
        used_set = await self.hass.async_add_executor_job(_used_in_merge_for_entry, self.hass, entry_id)
        day_merged = set()
        for m in merged_set:
            if m.startswith("MERGED_") and len(m) >= 13 and m[7:13] == day:
                day_merged.add(m)
        cached_names = [f["name"].replace(".264", "") for f in files if f["name"].replace(".264", "") in cached_set]
        used_names = [f["name"].replace(".264", "") for f in files if f["name"].replace(".264", "") in used_set]
        return web.json_response({
            "day": day, "files": files, "cached": cached_names,
            "merged": list(day_merged), "used": used_names,
        })


class Hi3510SdMergeView(HomeAssistantView):
    requires_auth = False
    url = "/api/hi3510/sd/{entry_id}/merge"
    name = "api:hi3510_sd_merge"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        if not _is_local(request, self.hass):
            return web.Response(text="Forbidden", status=HTTPStatus.FORBIDDEN)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "JSON non valido"}, status=400)
        files = body.get("files", [])
        if len(files) < 2:
            return web.json_response({"error": "Servono almeno 2 file"}, status=400)
        data = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if not data or not isinstance(data, dict):
            return web.json_response({"error": "Camera non trovata"}, status=404)
        self.hass.async_create_task(self._do_merge(entry_id, files, data["api"]))
        return web.json_response({"message": f"Merge avviato per {len(files)} file. Riceverai una notifica al termine."})

    async def _do_merge(self, entry_id: str, files: list[dict], api) -> None:
        cache_dir = _cache_dir(self.hass)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cam_name = _get_cam_name(self.hass, entry_id)
        notif_id = f"hi3510_merge_{entry_id}_{int(time.time())}"
        total = len(files)
        pn.async_create(self.hass, f"Merge {total} file per {cam_name}...", "Hi3510 SD Merge", notif_id)
        mp4_paths: list[Path] = []
        try:
            for i, f in enumerate(files):
                fname = f["name"]
                full_path = f["full"]
                base_name = fname.replace(".264", "")
                cache_key = f"{entry_id}_{base_name}"
                mp4_file = cache_dir / f"{cache_key}.mp4"
                if mp4_file.exists() and mp4_file.stat().st_size > 0:
                    mp4_paths.append(mp4_file)
                    continue
                pn.async_create(self.hass, f"Download {i+1}/{total}: {fname}...", "Hi3510 SD Merge", notif_id)
                try:
                    raw_data = await api.download_sd_file(full_path)
                except Exception as err:
                    _LOGGER.error("Merge download fallito %s: %s", full_path, err)
                    pn.async_create(self.hass, f"Download fallito: {fname} - {err}", "Hi3510 SD Merge", notif_id)
                    return
                if len(raw_data) < 100:
                    continue
                pn.async_create(self.hass, f"Conversione {i+1}/{total}: {fname}...", "Hi3510 SD Merge", notif_id)
                try:
                    ts_data, frame_count, codec = await self.hass.async_add_executor_job(hxvs_to_mpegts, raw_data)
                except ValueError as err:
                    _LOGGER.error("Merge parse fallito %s: %s", fname, err)
                    continue
                if codec == "h265" or frame_count == 0:
                    continue
                try:
                    mp4_data = await self._ffmpeg_remux(ts_data)
                except Exception as err:
                    _LOGGER.error("Merge remux fallito %s: %s", fname, err)
                    continue
                await self.hass.async_add_executor_job(mp4_file.write_bytes, mp4_data)
                mp4_paths.append(mp4_file)

            if len(mp4_paths) < 2:
                pn.async_create(self.hass, f"Merge annullato: solo {len(mp4_paths)} file convertiti", "Hi3510 SD Merge", notif_id)
                return
            pn.async_create(self.hass, f"Concatenazione {len(mp4_paths)} file per {cam_name}...", "Hi3510 SD Merge", notif_id)
            merged_mp4 = await self._ffmpeg_concat(mp4_paths, entry_id, files)
            if merged_mp4 and merged_mp4.exists():
                source_names = [f["name"].replace(".264", "") for f in files]
                meta_path = merged_mp4.with_suffix(".json")
                meta_data = {"sources": source_names, "created": int(time.time()), "count": len(source_names)}
                await self.hass.async_add_executor_job(meta_path.write_text, json.dumps(meta_data, ensure_ascii=False))
                size_mb = round(merged_mp4.stat().st_size / 1048576, 1)
                pn.async_create(self.hass, f"Merge completato: {merged_mp4.name} ({size_mb} MB). {len(source_names)} sorgenti marcati.", "Hi3510 SD Merge", notif_id)
            else:
                pn.async_create(self.hass, "Concatenazione ffmpeg fallita", "Hi3510 SD Merge", notif_id)
        except Exception as err:
            _LOGGER.exception("Merge error: %s", err)
            pn.async_create(self.hass, f"Errore merge: {err}", "Hi3510 SD Merge", notif_id)

    async def _ffmpeg_remux(self, ts_data: bytes) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".ts", delete=False) as tmp_in:
            tmp_in.write(ts_data)
            input_path = tmp_in.name
        output_path = input_path.rsplit(".", 1)[0] + ".mp4"
        cmd = ["ffmpeg", "-y", "-i", input_path, "-c", "copy", "-movflags", "+faststart", output_path]
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg exit {proc.returncode}: {stderr.decode(errors='replace')[-300:]}")
            return await self.hass.async_add_executor_job(Path(output_path).read_bytes)
        finally:
            for p in (input_path, output_path):
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass

    async def _ffmpeg_concat(self, mp4_paths: list[Path], entry_id: str, files: list[dict]) -> Path | None:
        first_name = files[0]["name"]
        last_name = files[-1]["name"]
        day_str = first_name[1:7] if len(first_name) > 7 else "000000"
        start_time = first_name[8:14] if len(first_name) >= 14 else "000000"
        end_time = last_name[15:21] if len(last_name) >= 21 else "235959"
        merged_name = f"{entry_id}_MERGED_{day_str}_{start_time}_{end_time}.mp4"
        merged_path = _cache_dir(self.hass) / merged_name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as lst:
            for p in mp4_paths:
                lst.write(f"file '{p}'\n")
            list_path = lst.name
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", "-movflags", "+faststart", str(merged_path)]
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            if proc.returncode != 0:
                _LOGGER.error("ffmpeg concat fallito: %s", stderr.decode(errors='replace')[-500:])
                return None
            return merged_path
        except Exception as err:
            _LOGGER.error("ffmpeg concat exception: %s", err)
            return None
        finally:
            try:
                Path(list_path).unlink(missing_ok=True)
            except OSError:
                pass


class Hi3510SdDownloadView(HomeAssistantView):
    """Download singolo file SD, conversione HXVS→MP4, salvataggio in cache."""
    requires_auth = False
    url = "/api/hi3510/sd/{entry_id}/download"
    name = "api:hi3510_sd_download"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        if not _is_local(request, self.hass):
            return web.Response(text="Forbidden", status=HTTPStatus.FORBIDDEN)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "JSON non valido"}, status=400)
        fname = body.get("name", "")
        full_path = body.get("full", "")
        if not fname or not full_path:
            return web.json_response({"error": "Parametri mancanti"}, status=400)
        data = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if not data or not isinstance(data, dict):
            return web.json_response({"error": "Camera non trovata"}, status=404)
        api = data["api"]
        base_name = fname.replace(".264", "")
        cache_dir = _cache_dir(self.hass)
        cache_dir.mkdir(parents=True, exist_ok=True)
        mp4_file = cache_dir / f"{entry_id}_{base_name}.mp4"
        if mp4_file.exists() and mp4_file.stat().st_size > 0:
            return web.json_response({"ok": True, "cached": True})
        try:
            raw_data = await api.download_sd_file(full_path)
        except Exception as err:
            return web.json_response({"error": f"Download fallito: {err}"}, status=502)
        if len(raw_data) < 100:
            return web.json_response({"error": "File troppo piccolo"}, status=502)
        try:
            ts_data, frame_count, codec = await self.hass.async_add_executor_job(hxvs_to_mpegts, raw_data)
        except ValueError as err:
            return web.json_response({"error": f"Formato non supportato: {err}"}, status=422)
        if codec == "h265":
            return web.json_response({"error": "H.265 non supportato"}, status=422)
        if frame_count == 0:
            return web.json_response({"error": "Nessun frame video"}, status=422)
        try:
            mp4_data = await self._ffmpeg_remux(ts_data)
        except Exception as err:
            return web.json_response({"error": f"Conversione fallita: {err}"}, status=500)
        await self.hass.async_add_executor_job(mp4_file.write_bytes, mp4_data)
        return web.json_response({"ok": True, "cached": False, "size": len(mp4_data)})

    async def _ffmpeg_remux(self, ts_data: bytes) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".ts", delete=False) as tmp_in:
            tmp_in.write(ts_data)
            input_path = tmp_in.name
        output_path = input_path.rsplit(".", 1)[0] + ".mp4"
        cmd = ["ffmpeg", "-y", "-i", input_path, "-c", "copy", "-movflags", "+faststart", output_path]
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg exit {proc.returncode}: {stderr.decode(errors='replace')[-300:]}")
            return await self.hass.async_add_executor_job(Path(output_path).read_bytes)
        finally:
            for p in (input_path, output_path):
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass


class Hi3510SdClearView(HomeAssistantView):
    requires_auth = False
    url = "/api/hi3510/sd/{entry_id}/clear"
    name = "api:hi3510_sd_clear"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def delete(self, request: web.Request, entry_id: str) -> web.Response:
        if not _is_local(request, self.hass):
            return web.Response(text="Forbidden", status=HTTPStatus.FORBIDDEN)
        def _do_clear() -> int:
            count = 0
            cd = _cache_dir(hass)
            prefix = f"{entry_id}_"
            if cd.exists():
                for f in cd.iterdir():
                    if f.name.startswith(prefix) and f.suffix in (".mp4", ".json"):
                        try:
                            f.unlink()
                            count += 1
                        except OSError:
                            pass
            idx_dir = Path(hass.config.path(SD_INDEX_DIR))
            if idx_dir.exists():
                for f in idx_dir.iterdir():
                    if f.name.startswith(prefix) and f.suffix == ".json":
                        try:
                            f.unlink()
                        except OSError:
                            pass
            return count
        hass = self.hass
        removed = await hass.async_add_executor_job(_do_clear)
        return web.json_response({"removed": removed})
