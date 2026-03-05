# Hi3510 IP Camera - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Custom integration for Home Assistant to control IP cameras based on the **Hi3510/HiSilicon** chipset via their CGI HTTP API.

These cameras are sold under many brand names (Dericam, INSTAR, Wanscam, Sricam, and many unbranded Chinese models) and share the same `/cgi-bin/hi3510/param.cgi` protocol.

## Features

- **RTSP video streaming** and JPEG snapshots
- **Image settings**: brightness, contrast, saturation, sharpness
- **Flip & Mirror** switches (for ceiling-mounted cameras)
- **Infrared mode** control (auto / on / off)
- **OSD overlay** management: show/hide, position, camera name text
- **PTZ control** with preset positions
- **Motion detection** via SD card alarm file monitoring
- **SD card recording** management and diagnostics (free space, status)
- **ONVIF toggle**, audio volume control, reboot button
- **Config flow** with automatic connection validation
- **Device identification** via MAC address

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → **Custom repositories**
3. Add this repository URL and select **Integration** as category
4. Search for "Hi3510" and install
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/hi3510/` folder into your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Hi3510 IP Camera"
3. Enter the camera's IP address, port, username, and password
4. The integration will validate the connection and detect the camera

## Entities

| Platform | Entities |
|---|---|
| Camera | RTSP stream + snapshot |
| Switch | ONVIF, SD Recording, Flip, Mirror, OSD Timestamp, OSD Camera Name |
| Select | Infrared Mode, OSD Timestamp Position, OSD Name Position |
| Number | Brightness, Contrast, Saturation, Sharpness, Audio In/Out Volume |
| Text | OSD Camera Name text |
| Button | Reboot |
| Binary Sensor | Motion Detection |
| Sensor | SD Free Space, SD Total Space, SD Status |

## Supported Cameras

Any IP camera using the Hi3510 CGI protocol should work. Tested firmware versions:
- V9.x (limited feature set)
- V10.x, V11.x, V13.x
- V19.x, V21.x, V22.x

## Known Limitations

- OSD timestamp text (region 0) is read-only — it's a format pattern managed by the firmware
- Some older firmware versions (V9.x) don't support `setimageattr`, flip/mirror, or presets
- OSD position supports 2 positions (Top Left / Top Right) on older firmware, 4 positions on newer firmware
- The camera API uses HTTP Basic Auth with no encryption

## Languages

- English
- Italian

## License

MIT
