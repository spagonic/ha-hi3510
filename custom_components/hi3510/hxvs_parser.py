"""Parser per container HXVS/HXVT delle IP camera HiSilicon/XiongMai.

Converte i file registrazione SD (.264) in MPEG-TS con timestamp
reali, pronto per il remux in MP4: ``ffmpeg -i input.ts -c copy out.mp4``

Formato container:
  - HXVS magic → H.264 (.264 files)
  - HXVT magic → H.265 (.265 files) — riconosciuto ma non supportato per playback
  - Frame video: header HXVF (16 bytes) + payload NAL
    HXVF layout: [4B magic][4B payload_size][4B timestamp_ms][4B frame_num]
  - Frame audio: header HXAF (16 bytes) + 4B sub-header + G.711 a-law payload
    HXAF layout: [4B magic][4B payload_size][4B timestamp_ms][4B reserved]
    Sub-header: [00 01 50 00] (stripped before muxing)
    Audio: G.711 a-law, 8kHz, mono, 160 bytes/frame (20ms)
  - NAL units dentro i frame video, preceduti da start code 00 00 00 01

NAL types mantenuti (H.264):
  SPS(7), PPS(8), IDR(5), P-frame(1)

NAL types scartati:
  SEI (H.264: 6) — non necessari per playback
"""
from __future__ import annotations

import logging
import struct

_LOGGER = logging.getLogger(__name__)

_H265_KEEP = frozenset({32, 33, 34, 19, 20, 0, 1})
_H264_KEEP = frozenset({7, 8, 5, 1})
_CONTAINER_TAGS = (b"HXVF", b"HXAF", b"HXVS", b"HXVT")
_NAL_START = b"\x00\x00\x00\x01"

# MPEG-TS constants
_TS_PACKET_SIZE = 188
_PAT_PID = 0x0000
_PMT_PID = 0x1000
_VIDEO_PID = 0x0100
_AUDIO_PID = 0x0101
_HXAF_HEADER_SIZE = 4  # sub-header nei frame audio (00 01 50 00)


def _crc32_mpeg(data: bytes) -> int:
    """CRC-32/MPEG-2 per tabelle PSI."""
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) if crc & 0x80000000 else (crc << 1)
            crc &= 0xFFFFFFFF
    return crc


def _encode_pcr(pcr_base: int) -> bytes:
    """Codifica PCR (33 bit base + 6 reserved + 9 ext=0) in 6 bytes."""
    buf = bytearray(6)
    buf[0] = (pcr_base >> 25) & 0xFF
    buf[1] = (pcr_base >> 17) & 0xFF
    buf[2] = (pcr_base >> 9) & 0xFF
    buf[3] = (pcr_base >> 1) & 0xFF
    buf[4] = ((pcr_base & 1) << 7) | 0x7E
    buf[5] = 0x00
    return bytes(buf)


def _encode_pts(pts: int) -> bytes:
    """Codifica PTS in 5 bytes PES."""
    buf = bytearray(5)
    buf[0] = 0x21 | ((pts >> 29) & 0x0E)
    buf[1] = (pts >> 22) & 0xFF
    buf[2] = ((pts >> 14) & 0xFE) | 0x01
    buf[3] = (pts >> 7) & 0xFF
    buf[4] = ((pts << 1) & 0xFE) | 0x01
    return bytes(buf)


def _write_ts_packets(
    out: bytearray, pid: int, cc: list[int], payload: bytes,
    pusi: bool, adapt_flags: int = 0, pcr: int | None = None,
) -> None:
    """Scrive pacchetti TS da 188 bytes per il payload dato."""
    offset = 0
    first = True
    while offset < len(payload):
        pkt = bytearray(_TS_PACKET_SIZE)
        pkt[0] = 0x47  # sync byte

        # Adaptation field (solo primo pacchetto se richiesto)
        adapt = bytearray()
        need_adapt = False
        if first and (adapt_flags or pcr is not None):
            need_adapt = True
            af = adapt_flags
            if pcr is not None:
                af |= 0x10  # PCR flag
            adapt.append(af)
            if pcr is not None:
                adapt.extend(_encode_pcr(pcr))

        header_size = 4 + (1 + len(adapt) if need_adapt else 0)
        avail = _TS_PACKET_SIZE - header_size
        chunk = payload[offset:offset + avail]

        # Stuffing per ultimo chunk incompleto
        if len(chunk) < avail and offset + len(chunk) >= len(payload):
            stuff = avail - len(chunk)
            if not need_adapt:
                need_adapt = True
                if stuff == 1:
                    adapt = bytearray()
                else:
                    adapt = bytearray([0x00])
                    adapt.extend(b'\xFF' * max(0, stuff - 2))
                avail = _TS_PACKET_SIZE - 4 - 1 - len(adapt)
                chunk = payload[offset:offset + avail]
            else:
                adapt.extend(b'\xFF' * stuff)
                avail = _TS_PACKET_SIZE - 4 - 1 - len(adapt)
                chunk = payload[offset:offset + avail]

        pkt[1] = (0x40 if (first and pusi) else 0x00) | ((pid >> 8) & 0x1F)
        pkt[2] = pid & 0xFF
        if need_adapt:
            pkt[3] = 0x30 | (cc[0] & 0x0F)
            pkt[4] = len(adapt)
            pkt[5:5 + len(adapt)] = adapt
            ps = 5 + len(adapt)
        else:
            pkt[3] = 0x10 | (cc[0] & 0x0F)
            ps = 4
        pkt[ps:ps + len(chunk)] = chunk
        out.extend(pkt)
        offset += len(chunk)
        cc[0] = (cc[0] + 1) & 0x0F
        first = False


def _parse_container(data: bytes) -> tuple[bool, str, frozenset, list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    """Parsa header container e trova tutti gli HXVF e HXAF.

    Returns:
        (is_h265, codec, keep_set, hxvf_list, hxaf_list)
        hxaf_list: [(offset, payload_size, timestamp_ms), ...]
    """
    magic = data[:4]
    if magic == b"HXVS":
        is_h265 = False
    elif magic == b"HXVT":
        is_h265 = True
    else:
        raise ValueError(f"Magic container sconosciuto: {magic!r}")

    codec = "h265" if is_h265 else "h264"
    keep = _H265_KEEP if is_h265 else _H264_KEEP
    data_len = len(data)

    hxvf_list: list[tuple[int, int, int]] = []
    pos = 0
    while pos < data_len - 16:
        pos = data.find(b"HXVF", pos)
        if pos == -1:
            break
        if pos + 16 > data_len:
            break
        psize = struct.unpack_from("<I", data, pos + 4)[0]
        ts_ms = struct.unpack_from("<I", data, pos + 8)[0]
        hxvf_list.append((pos, psize, ts_ms))
        pos += 4

    # Estrai frame audio HXAF
    hxaf_list: list[tuple[int, int, int]] = []
    pos = 0
    while pos < data_len - 16:
        pos = data.find(b"HXAF", pos)
        if pos == -1:
            break
        if pos + 16 > data_len:
            break
        psize = struct.unpack_from("<I", data, pos + 4)[0]
        ts_ms = struct.unpack_from("<I", data, pos + 8)[0]
        hxaf_list.append((pos, psize, ts_ms))
        pos += 16 + max(psize, 1)

    return is_h265, codec, keep, hxvf_list, hxaf_list


def _extract_frames(
    data: bytes, is_h265: bool, keep: frozenset, hxvf_list: list[tuple[int, int, int]],
) -> list[tuple[int, bytes, bool]]:
    """Estrai frame video dal container, raggruppando parametri con keyframe.

    Returns:
        Lista di (ts_ms, nal_bytes, is_keyframe).
    """
    data_len = len(data)

    def _extract_nals(start: int, end: int) -> tuple[bytes, bool]:
        nals = bytearray()
        is_kf = False
        i = start
        while i < end - 4:
            if data[i] != 0:
                i += 1
                continue
            if data[i:i + 4] != _NAL_START:
                i += 1
                continue
            hp = i + 4
            if hp >= end:
                break
            nb = data[hp]
            nt = ((nb >> 1) & 0x3F) if is_h265 else (nb & 0x1F)
            j = hp
            while j < end - 3:
                if data[j] == 0 and data[j:j + 4] == _NAL_START:
                    break
                if data[j] == 0x48 and data[j:j + 4] in _CONTAINER_TAGS:
                    break
                j += 1
            else:
                j = end
            if nt in keep:
                nals.extend(data[i:j])
                if not is_h265 and nt in (5, 7):
                    is_kf = True
                elif is_h265 and nt in (19, 20, 32):
                    is_kf = True
            i = j
        return bytes(nals), is_kf

    frames: list[tuple[int, bytes, bool]] = []
    pending_params = bytearray()

    for idx, (hpos, psize, ts_ms) in enumerate(hxvf_list):
        payload_start = hpos + 16
        payload_end = data_len
        for npos, _, _ in hxvf_list[idx + 1:]:
            payload_end = npos
            break
        hxaf = data.find(b"HXAF", payload_start, payload_end)
        if hxaf != -1:
            payload_end = hxaf

        nals, is_kf = _extract_nals(payload_start, payload_end)

        if psize <= 1000:
            if nals:
                pending_params.extend(nals)
        else:
            if is_kf and pending_params:
                nals = bytes(pending_params) + nals
                pending_params.clear()
            elif pending_params:
                pending_params.clear()
            if nals:
                frames.append((ts_ms, nals, is_kf))

    if not frames:
        raise ValueError("Nessun frame video trovato nel container")
    return frames


def hxvs_to_mpegts(data: bytes) -> tuple[bytes, int, str, bytes]:
    """Converte un file HXVS/HXVT in MPEG-TS (solo video) + audio raw separato.

    Per H.264: genera MPEG-TS con PES/PTS per remux ``ffmpeg -c copy``.
    Per H.265: ritorna codec="h265" con dati vuoti (non supportato).

    Audio G.711 a-law viene estratto come raw bytes separato (8kHz mono).
    Il chiamante deve passarlo a ffmpeg come secondo input:
    ``ffmpeg -f mpegts -i video.ts -f alaw -ar 8000 -ac 1 -i audio.raw ...``

    Returns:
        Tupla (ts_bytes, frame_count, codec_string, audio_raw_alaw).
        audio_raw_alaw è vuoto (b"") se non ci sono frame audio.
    """
    is_h265, codec, keep, hxvf_list, hxaf_list = _parse_container(data)

    # H.265 non supportato per playback — ritorna subito il codec
    # per permettere a views.py di mostrare il messaggio appropriato
    if is_h265:
        return b"", 0, codec, b""

    frames = _extract_frames(data, is_h265, keep, hxvf_list)

    # Estrai payload audio raw (strip 4-byte sub-header, concatena in ordine)
    audio_raw = bytearray()
    if hxaf_list:
        for apos, apsize, _ats_ms in hxaf_list:
            payload_start = apos + 16 + _HXAF_HEADER_SIZE
            payload_end = apos + 16 + apsize
            if payload_start < payload_end <= len(data):
                audio_raw.extend(data[payload_start:payload_end])

    # === Scrivi MPEG-TS (solo video) ===
    out = bytearray()
    cc_pat: list[int] = [0]
    cc_pmt: list[int] = [0]
    cc_vid: list[int] = [0]

    # PAT (Program Association Table)
    pat_sec = bytearray([0x00])  # table_id
    pat_body = bytearray()
    pat_body.extend(b'\x00\x01')  # transport_stream_id
    pat_body.append(0xC1)  # version=0, current_next=1
    pat_body.extend(b'\x00\x00')  # section/last_section
    pat_body.extend(b'\x00\x01')  # program_number=1
    pat_body.extend(struct.pack(">H", 0xE000 | _PMT_PID))
    sl = len(pat_body) + 4  # +CRC32
    pat_sec.extend(struct.pack(">H", 0xB000 | sl))
    pat_sec.extend(pat_body)
    pat_sec.extend(struct.pack(">I", _crc32_mpeg(pat_sec)))
    _write_ts_packets(out, _PAT_PID, cc_pat,
                      bytes(bytearray([0x00]) + pat_sec), pusi=True)

    # PMT (Program Map Table) — solo video
    stream_type = 0x1B  # H.264
    pmt_sec = bytearray([0x02])  # table_id
    pmt_body = bytearray()
    pmt_body.extend(b'\x00\x01')  # program_number
    pmt_body.append(0xC1)
    pmt_body.extend(b'\x00\x00')
    pmt_body.extend(struct.pack(">H", 0xE000 | _VIDEO_PID))  # PCR PID
    pmt_body.extend(b'\xF0\x00')  # program_info_length=0
    pmt_body.append(stream_type)
    pmt_body.extend(struct.pack(">H", 0xE000 | _VIDEO_PID))
    pmt_body.extend(b'\xF0\x00')  # ES_info_length=0
    sl = len(pmt_body) + 4
    pmt_sec.extend(struct.pack(">H", 0xB000 | sl))
    pmt_sec.extend(pmt_body)
    pmt_sec.extend(struct.pack(">I", _crc32_mpeg(pmt_sec)))
    _write_ts_packets(out, _PMT_PID, cc_pmt,
                      bytes(bytearray([0x00]) + pmt_sec), pusi=True)

    # Frame video come PES con PTS
    base_ts = frames[0][0]
    for ts_ms, nal_data, is_kf in frames:
        pts_90k = (ts_ms - base_ts) * 90  # ms → 90kHz clock

        # PES packet
        pes = bytearray()
        pes.extend(b'\x00\x00\x01')  # PES start code
        pes.append(0xE0)  # stream_id = video
        pes_data_len = 3 + 5 + len(nal_data)  # header(3) + PTS(5) + payload
        if pes_data_len > 65535:
            pes.extend(b'\x00\x00')  # unbounded
        else:
            pes.extend(struct.pack(">H", pes_data_len))
        pes.append(0x80)  # marker bits
        pes.append(0x80)  # PTS present
        pes.append(0x05)  # PES header data length
        pes.extend(_encode_pts(pts_90k))
        pes.extend(nal_data)

        af = 0x40 if is_kf else 0  # random_access_indicator
        pcr = pts_90k if is_kf else None
        _write_ts_packets(out, _VIDEO_PID, cc_vid, bytes(pes), pusi=True,
                          adapt_flags=af, pcr=pcr)

    _LOGGER.debug(
        "HXVS→MPEG-TS: %d bytes input → %d bytes output, %d video frames, "
        "%d audio frames (%d bytes raw alaw), codec=%s",
        len(data), len(out), len(frames), len(hxaf_list), len(audio_raw), codec,
    )
    return bytes(out), len(frames), codec, bytes(audio_raw)
