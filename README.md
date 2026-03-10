# Hi3510 IP Camera - Home Assistant Integration

<p align="center">
  <img src="custom_components/hi3510/brand/icon@2x.png" alt="Hi3510 IP Camera" width="200">
</p>

[![HACS Validation](https://github.com/spagonic/ha-hi3510/actions/workflows/hacs.yaml/badge.svg)](https://github.com/spagonic/ha-hi3510/actions/workflows/hacs.yaml)
[![Validate with hassfest](https://github.com/spagonic/ha-hi3510/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/spagonic/ha-hi3510/actions/workflows/hassfest.yaml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Custom integration for Home Assistant to control IP cameras that use the **Hi3510 CGI protocol** (`/cgi-bin/hi3510/param.cgi`).

This protocol is used by hundreds of camera models based on **HiSilicon** (now HiStar) SoCs. Despite the "Hi3510" name, the protocol is shared across multiple chip generations including Hi3510, Hi3518A, Hi3518C, Hi3518EV100, Hi3518EV200/201, Hi3516CV100/200/300, Hi3516EV200/300, and others. These cameras are manufactured by dozens of Chinese OEMs and sold worldwide under many brand names.

The integration communicates entirely over the local network (no cloud dependency) using HTTP Basic Auth and RTSP.

## Compatible Cameras

### How to identify a compatible camera

Your camera is likely compatible if:

1. **It uses the CamHi, HiP2P, Ctronics, or HiSilicon app** for mobile access
2. **Its web UI** is accessible at `http://<ip>/web/admin.html`
3. **The URL** `http://<ip>/cgi-bin/hi3510/param.cgi?cmd=getserverinfo` returns data in the format `var key="value";`
4. **The HTTP 401 response** contains `WWW-Authenticate: Basic realm="hi3510"` or similar

### Confirmed compatible brands and models

The following brands are known to sell cameras using the Hi3510 CGI protocol. Not every model from these brands uses this protocol — newer or higher-end models may use different firmware.

| Brand | Known compatible models / series | Notes |
|---|---|---|
| **SV3C** | B01W, B06W, B01POE, SV-B01W-1080P, SV-B06W-5MP | Budget outdoor/indoor WiFi and PoE cameras |
| **Ctronics** | CTIPC series (outdoor PTZ, bullet, dome) | Outdoor PTZ and bullet cameras |
| **Dericam** | S1, S2, M801W, H503W | Indoor/outdoor WiFi cameras |
| **INSTAR** | IN-6001HD, IN-6012HD, IN-6014HD, IN-5905HD, IN-5907HD, IN-7011HD, IN-8003HD, IN-8015HD, IN-9008HD, IN-9020HD | German brand, well-documented |
| **Wansview** | NCM-series (NCM621W, NCM622W, NCM624W, NCM625GA) | Indoor pan/tilt and outdoor bullet |
| **Tenvis** | IPROBOT3, TH661, T8862, TH692 | Indoor pan/tilt cameras |
| **Wanscam** | HW0021, HW0023, HW0025, HW0026, HW0036, HW0042, HW0045, JW0004, JW0008, K21 | Wide range of indoor/outdoor models |
| **Sricam** | SP005, SP006, SP007, SP008, SP009, SP012, SP015, SP017, SP019, SP020 | Budget indoor/outdoor cameras |
| **Hiseeu** | FH series, TZ series, PTZ cameras | Budget surveillance cameras |
| **BESDER** | Various bullet and dome models | OEM/budget brand on AliExpress |
| **Hamrolte** | Various bullet and dome models | OEM/budget brand on AliExpress |
| **Gadinan** | Various bullet, dome, and PTZ models | OEM/budget brand on AliExpress |
| **Jennov** | WiFi PTZ and bullet cameras | Amazon/AliExpress brand |
| **ESCAM** | QF001, QF002, QF003, QD900, G02, G15 | Budget indoor/outdoor cameras |
| **Vstarcam** | C7824WIP, C7837WIP, C38S, C16S | Indoor pan/tilt cameras |
| **Floureon** | Various outdoor bullet models | Budget brand (discontinued) |
| **KKMoon** | Various PTZ and bullet models | Budget brand on Amazon/AliExpress |
| **JOOAN** | JA-series bullet and dome cameras | Budget brand |
| **Unitoptek** | Mini PTZ, bullet, dome models | OEM brand on AliExpress |
| **Anran** | Various PoE and WiFi models | Budget surveillance brand |
| **Loosafe** | Various bullet and dome models | OEM brand |
| **Techage** | Various PoE and WiFi cameras | Budget NVR kit brand |


> **Note**: Many unbranded or white-label cameras sold on Amazon, AliExpress, Banggood, and similar marketplaces also use this protocol. If the camera's mobile app is CamHi, HiP2P, or similar, it very likely uses the Hi3510 CGI protocol.

### Confirmed HiSilicon SoCs

These cameras use various HiSilicon chips, all sharing the same CGI protocol:

| SoC | Resolution | Typical use |
|---|---|---|
| Hi3510 | VGA/720P | Legacy models (2010–2014) |
| Hi3518A | 720P | Early HD models |
| Hi3518C | 720P/960P | Mid-range models |
| Hi3518EV100 | 720P/960P | Common in 2014–2016 models |
| Hi3518EV200/201 | 1080P | Very common, 2016–2020 models |
| Hi3516CV100 | 1080P | Higher-end 2014–2016 models |
| Hi3516CV200 | 1080P | Mid-range 2016–2018 models |
| Hi3516CV300 | 1080P/3MP | 2017–2019 models |
| Hi3516EV200 | 3MP/4MP | 2019–2021 models |
| Hi3516EV300 | 5MP | Higher-end 2019–2022 models |

### Tested model codes

These specific model codes have been tested with this integration:

| Model Code | Firmware | Brand | SoC |
|---|---|---|---|
| C6F0SoZ0N0PnL2 | V21.x | Ctronics | Hi3518EV200 |
| C6F0SpZ3N0PgL2 | V22.x | Ctronics | Hi3518EV200 |
| C6F0SoZ3N0P9L2 | V19.x | Generic | Hi3518EV200 |
| C6F0SgZ3N0P5L0 | V10.x/V11.x | Generic (HX vendor) | Hi3518EV200 |
| C6F0SgZ0N0P3L0 | V11.x | SV3C (B01W) | Hi3518EV200 |
| C6F0SgZ3N0P5L2 | V11.x | Generic | Hi3518EV200 |
| C9F0SgZ0N0P7L0 | V13.x | Generic | Hi3516EV300 |
| C9F0SeZ0N0P2L0 | V9.x | Generic | Hi3518EV100 |

### Image sensors found in compatible cameras

The firmware supports auto-detection of these image sensors via I2C:

| Sensor | Resolution | Typical cameras |
|---|---|---|
| Sony IMX122 | 1080P | Higher-end models |
| Sony IMX291 | 1080P | Low-light optimized models |
| SmartSens SC2135 | 1080P | Budget 1080P models |
| GalaxyCore GC2023 | 1080P | Budget models |
| GalaxyCore GC2033 | 1080P | Budget models |
| OmniVision OV2718 | 1080P | Mid-range models |

## Features

### Camera (RTSP Stream & Snapshot)

- Live video stream via RTSP (`rtsp://<host>:<rtsp_port>/11`)
- JPEG snapshots from `/tmpfs/auto.jpg`
- Configurable RTSP port (default: 554)

### Network Discovery

The config flow includes automatic network scanning:

1. Choose "Scan network" or "Manual entry"
2. The scan probes all IPs on local subnets for Hi3510 cameras (port 80)
3. Cameras are identified by their CGI response format or HTTP 401 realm
4. Already-configured cameras are filtered out
5. Scan results are cached across flow instances — no rescanning when adding multiple cameras
6. A "Rescan network" option is available to refresh the list

### Switches

| Entity | Description |
|---|---|
| ONVIF | Enable/disable ONVIF protocol |
| SD Recording | Toggle continuous SD card recording |
| Flip | Flip video vertically (for ceiling mount) |
| Mirror | Mirror video horizontally |
| OSD Timestamp | Show/hide timestamp overlay (region 0) |
| OSD Camera Name | Show/hide camera name overlay (region 1) |

### Selects

| Entity | Description |
|---|---|
| Infrared Mode | Auto / On / Off |
| OSD Timestamp Position | Top Left / Top Right / Bottom Left / Bottom Right |
| OSD Name Position | Top Left / Top Right / Bottom Left / Bottom Right |

OSD position selects include anti-overlap validation.

### Numbers

| Entity | Range | Description |
|---|---|---|
| Brightness | 0–255 | Image brightness |
| Contrast | 0–255 | Image contrast |
| Saturation | 0–255 | Color saturation |
| Sharpness | 0–255 | Image sharpness |
| Audio Input Volume | 0–100 | Microphone volume |
| Audio Output Volume | 0–100 | Speaker volume |

All image parameters are sent together to prevent firmware from resetting unspecified values.

### Text

| Entity | Description |
|---|---|
| OSD Text Region 1 | Editable camera name overlay text. Region 0 (timestamp) is read-only. |

### Button

| Entity | Description |
|---|---|
| Reboot | Sends reboot command (30–60s downtime) |

### Binary Sensor

| Entity | Description |
|---|---|
| Motion Detection | Monitors SD card for alarm files (`A*` prefix). Polls every 3s, auto-off after 30s. Requires SD card. |

### Sensors

| Entity | Description |
|---|---|
| SD Free Space | Available SD space in MB |
| SD Total Space | Total SD capacity in MB |
| SD Status | OK / Not Inserted / Error |

## Setup

### Config Flow

1. **Settings** → **Devices & Services** → **Add Integration** → **Hi3510 IP Camera**
2. Choose **Scan network** (automatic) or **Manual entry**
3. Enter credentials (username, password, RTSP port)
4. The integration validates the connection and identifies the camera by MAC address

### Options Flow

Update connection parameters (host, port, credentials, RTSP port) without removing the camera.

## Architecture

### Polling

- Main coordinator: every 30s (image, OSD, infrared, ONVIF, recording, audio, SD info)
- Motion coordinator: every 3s (SD card alarm file browsing)

### Safety

- **OSD Region 0 protection**: writing `-name` on region 0 is blocked — it corrupts OSD on some firmware and can brick the camera
- **Image parameter preservation**: all values sent together on any change
- **OSD anti-overlap**: prevents both overlays in the same corner
- **Graceful degradation**: 3 consecutive failures → camera marked unavailable

## Installation

### HACS (recommended)

1. Open HACS → **Integrations** → **Custom repositories**
2. Add `https://github.com/spagonic/ha-hi3510` as **Integration**
3. Search "Hi3510" and install
4. Restart Home Assistant

### Manual

Copy `custom_components/hi3510/` to your HA `config/custom_components/` directory and restart.

## Known Limitations

- OSD timestamp text (region 0) is read-only — writing corrupts OSD on some firmware
- Some older firmware (V9.x) lacks `setimageattr`, flip/mirror, or presets
- OSD position: 2 options on older firmware, 4 on newer
- HTTP Basic Auth with no encryption
- Motion detection requires an SD card
- PTZ presets must be configured via the camera's web UI

## Languages

- English
- Italian

## License

MIT

---

<p align="center">
  <sub>🤖 This integration was entirely developed with the assistance of artificial intelligence (Kiro AI IDE).</sub>
</p>
