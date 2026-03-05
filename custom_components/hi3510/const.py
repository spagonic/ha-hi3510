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

# OSD position
OSD_PLACE_MAP: dict[str, str] = {
    "0": "Top Left",
    "1": "Top Right",
    "2": "Bottom Left",
    "3": "Bottom Right",
}
OSD_PLACE_REVERSE: dict[str, str] = {v: k for k, v in OSD_PLACE_MAP.items()}

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
