"""Costanti per l'integrazione Hi3510 IP Camera."""

from __future__ import annotations

DOMAIN = "hi3510"

PLATFORMS = [
    "camera",
    "switch",
    "select",
    "number",
    "button",
    "binary_sensor",
    "text",
    "sensor",
]

# Config keys
CONF_RTSP_PORT = "rtsp_port"

# Defaults
DEFAULT_PORT = 80
DEFAULT_RTSP_PORT = 554
DEFAULT_USERNAME = "admin"
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_MOTION_INTERVAL = 3
DEFAULT_MOTION_OFF_DELAY = 30

# CGI endpoints
CGI_PARAM = "/cgi-bin/hi3510/param.cgi"
CGI_PTZ = "/cgi-bin/hi3510/ptzctrl.cgi"
CGI_PRESET = "/cgi-bin/hi3510/preset.cgi"
SNAPSHOT_PATH = "/tmpfs/auto.jpg"

# Infrared modes
IR_MODES = ["auto", "open", "close"]
IR_MODE_LABELS = {
    "auto": "Auto",
    "open": "On",
    "close": "Off",
}

# OSD position — derivata da place (top/bottom) + x (left/right)
# La cam usa place per top/bottom e coordinate x per left/right
OSD_POSITIONS = ["Top Left", "Top Right", "Bottom Left", "Bottom Right"]
OSD_X_THRESHOLD = 480  # x >= threshold = Right, x < threshold = Left
OSD_X_RIGHT = 976  # valore x per posizionamento a destra
OSD_X_LEFT = 0  # valore x per posizionamento a sinistra
OSD_PLACE_TOP = "0"  # valore place per top
OSD_PLACE_BOTTOM = "2"  # valore place per bottom

# PTZ
PTZ_ACTIONS = [
    "left", "right", "up", "down", "home", "stop",
    "leftup", "leftdown", "rightup", "rightdown",
    "hscan", "vscan",
    "zoomin", "zoomout", "focusin", "focusout", "irisin", "irisout",
]
PTZ_MAX_SPEED = 4
PTZ_MAX_PRESETS = 16

# Image settings
IMAGE_NUMBER_PARAMS: dict[str, tuple[int, int, int]] = {
    # key: (min, max, step)
    "brightness": (0, 255, 1),
    "contrast": (0, 255, 1),
    "saturation": (0, 255, 1),
    "sharpness": (0, 255, 1),
}

# SD status codes
SD_STATUS_MAP: dict[str, str] = {
    "0": "not_inserted",
    "1": "ok",
    "2": "error",
}

# Cache playback SD
CACHE_DIR = "hi3510_cache"
CACHE_MAX_AGE_DAYS = 7  # Default: file cache più vecchi di N giorni vengono eliminati

# Options keys
CONF_CACHE_RETENTION_DAYS = "cache_retention_days"
CONF_ALLOWED_NETWORKS = "allowed_networks"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MOTION_INTERVAL = "motion_interval"
DEFAULT_ALLOWED_NETWORKS = "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8"
