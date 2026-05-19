"""APRS over RF via KISS TCP (Direwolf or hardware TNC)."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

import aprslib
from loguru import logger

from meshtop.config import TncSourceConfig
from meshtop.position import Position
from meshtop.sources.meshtastic import NodeInfo, TextMessage

# KISS framing constants
_FEND = 0xC0
_FESC = 0xDB
_TFEND = 0xDC
_TFESC = 0xDD
_CMD_DATA = 0x00


def _kiss_unwrap(frame: bytes) -> bytes | None:
    """Strip KISS framing from a single frame (between FENDs, including command byte)."""
    if len(frame) < 2:
        return None
    cmd = frame[0]
    if cmd & 0x0F != 0:  # not port 0 data
        return None
    payload = frame[1:]
    out = bytearray()
    i = 0
    while i < len(payload):
        b = payload[i]
        if b == _FESC:
            i += 1
            if i < len(payload):
                nb = payload[i]
                out.append(_FEND if nb == _TFEND else _FESC if nb == _TFESC else nb)
        else:
            out.append(b)
        i += 1
    return bytes(out)


def _kiss_wrap(ax25_frame: bytes) -> bytes:
    """Wrap an AX.25 frame in a KISS DATA frame."""
    escaped = bytearray()
    for b in ax25_frame:
        if b == _FEND:
            escaped += bytes([_FESC, _TFEND])
        elif b == _FESC:
            escaped += bytes([_FESC, _TFESC])
        else:
            escaped.append(b)
    return bytes([_FEND, _CMD_DATA]) + bytes(escaped) + bytes([_FEND])


def _build_ax25_ui(src_call: str, dst_call: str, info: bytes) -> bytes:
    """Build a minimal AX.25 UI frame for APRS."""

    def encode_call(call: str, ssid: int = 0, last: bool = False) -> bytes:
        call = call.upper().ljust(6)[:6]
        encoded = bytes(ord(c) << 1 for c in call)
        ssid_byte = (0b01100000 | ((ssid & 0x0F) << 1)) | (0x01 if last else 0x00)
        return encoded + bytes([ssid_byte])

    # Parse SSID suffix e.g. "N0CALL-9"
    def _split(addr: str):
        parts = addr.split("-", 1)
        return parts[0], int(parts[1]) if len(parts) > 1 else 0

    src, src_ssid = _split(src_call)
    dst_call_clean = "APRS"
    header = encode_call(dst_call_clean) + encode_call(src, src_ssid, last=True)
    # Control (UI=0x03), PID (No Layer 3=0xF0)
    return header + bytes([0x03, 0xF0]) + info


def _aprs_position_str(pos: Position, callsign: str, comment: str = "meshtop") -> str:
    """Format an APRS uncompressed position string."""
    lat = pos.lat
    lon = pos.lon
    lat_deg = int(abs(lat))
    lat_min = (abs(lat) - lat_deg) * 60
    lon_deg = int(abs(lon))
    lon_min = (abs(lon) - lon_deg) * 60
    lat_str = f"{lat_deg:02d}{lat_min:05.2f}{'N' if lat >= 0 else 'S'}"
    lon_str = f"{lon_deg:03d}{lon_min:05.2f}{'E' if lon >= 0 else 'W'}"
    return f"!{lat_str}/{lon_str}>{comment}"


class AprsTncSource:
    """Two-way APRS over KISS TCP (Direwolf or hardware TNC)."""

    def __init__(
        self,
        cfg: TncSourceConfig,
        on_position: Callable[[Position], None] | None = None,
        on_nodeinfo: Callable[[NodeInfo], None] | None = None,
        on_text: Callable[[TextMessage], None] | None = None,
        on_status: Callable[[bool], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._on_position = on_position
        self._on_nodeinfo = on_nodeinfo
        self._on_text = on_text
        self._on_status = on_status
        self._sock: socket.socket | None = None
        self._running = False
        self._connected = False
        self._thread: threading.Thread | None = None
        self._beacon_thread: threading.Thread | None = None
        self._last_pos: Position | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="aprs-tnc")
        self._thread.start()
        if self._cfg.beacon_interval > 0:
            self._beacon_thread = threading.Thread(
                target=self._beacon_loop, daemon=True, name="aprs-beacon"
            )
            self._beacon_thread.start()
        logger.info(f"AprsTncSource started — {self._cfg.host}:{self._cfg.port}")

    def stop(self) -> None:
        self._running = False
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
        logger.info("AprsTncSource stopped")

    def update_position(self, pos: Position) -> None:
        """Update the last known position (for beaconing)."""
        self._last_pos = pos

    def send_message(self, dest: str, text: str) -> None:
        """Send an APRS message via KISS TNC."""
        callsign = self._cfg.callsign
        if self._cfg.ssid:
            callsign = f"{callsign}-{self._cfg.ssid}"
        dest = dest.upper()
        seq = datetime.now(UTC).strftime("%S")  # simple sequence number
        info = f":{dest:<9}:{text}{{{seq}}}".encode()
        ax25 = _build_ax25_ui(callsign, "APRS", info)
        self._send_raw(ax25)

    def send_position(self, pos: Position) -> None:
        """Send an APRS position beacon via KISS TNC."""
        callsign = self._cfg.callsign
        if self._cfg.ssid:
            callsign = f"{callsign}-{self._cfg.ssid}"
        info = _aprs_position_str(pos, callsign).encode()
        ax25 = _build_ax25_ui(callsign, "APRS", info)
        self._send_raw(ax25)
        logger.debug(f"APRS position beacon sent: {pos.lat:.5f},{pos.lon:.5f}")

    # ----------------------------------------------------------------- private

    def _send_raw(self, ax25_frame: bytes) -> None:
        with self._lock:
            sock = self._sock
        if sock is None:
            logger.debug("AprsTncSource: not connected, dropping outbound frame")
            return
        try:
            sock.sendall(_kiss_wrap(ax25_frame))
        except Exception as e:
            logger.warning(f"AprsTncSource send error: {e}")

    def _loop(self) -> None:
        while self._running:
            try:
                self._connect_and_read()
            except Exception as e:
                logger.warning(f"AprsTncSource error: {e}")
            if self._running:
                logger.info("AprsTncSource reconnecting in 30s")
                time.sleep(30)

    def _connect_and_read(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((self._cfg.host, self._cfg.port))
        sock.settimeout(None)
        with self._lock:
            self._sock = sock
        self._connected = True
        if self._on_status:
            self._on_status(True)
        logger.info(f"AprsTncSource connected to {self._cfg.host}:{self._cfg.port}")

        buf = bytearray()
        try:
            while self._running:
                data = sock.recv(1024)
                if not data:
                    break
                buf.extend(data)
                self._process_buf(buf)
        finally:
            self._connected = False
            with self._lock:
                self._sock = None
            try:
                sock.close()
            except Exception:
                pass
            if self._on_status:
                self._on_status(False)

    def _process_buf(self, buf: bytearray) -> None:
        """Extract complete KISS frames from buf, decode and dispatch."""
        while True:
            start = buf.find(_FEND)
            if start == -1:
                buf.clear()
                return
            # Remove leading garbage before first FEND
            if start > 0:
                del buf[:start]
            # Find the closing FEND
            end = buf.find(_FEND, 1)
            if end == -1:
                return  # frame not complete yet
            frame_bytes = bytes(buf[1:end])
            del buf[: end + 1]
            if not frame_bytes:
                continue  # double-FEND separator
            raw_ax25 = _kiss_unwrap(frame_bytes)
            if raw_ax25:
                self._decode_aprs(raw_ax25)

    def _decode_aprs(self, ax25_frame: bytes) -> None:
        try:
            parsed = aprslib.parse(ax25_frame.decode("ascii", errors="replace"))
        except Exception as e:
            logger.debug(f"APRS decode failed: {e}")
            return
        self._dispatch(parsed)

    def _dispatch(self, p: dict) -> None:
        from_call = p.get("from", "")
        ts = datetime.now(UTC)

        # Fire NodeInfo for every heard station
        if from_call and self._on_nodeinfo:
            node = NodeInfo(
                node_id=from_call,
                long_name=from_call,
                short_name=from_call[:4],
                last_heard=ts,
                source_type="aprs",
            )
            self._on_nodeinfo(node)

        fmt = p.get("format", "")

        if fmt in ("uncompressed", "compressed", "mice", "object", "item") and self._on_position:
            lat = p.get("latitude")
            lon = p.get("longitude")
            if lat is not None and lon is not None:
                pos = Position(
                    lat=float(lat),
                    lon=float(lon),
                    alt=float(p.get("altitude", 0) or 0),
                    speed=float(p.get("speed", 0) or 0) * 0.539957,  # km/h to knots
                    course=float(p.get("course", 0) or 0),
                    fix=True,
                    timestamp=ts,
                )
                logger.debug(f"APRS position from {from_call}: {pos.lat:.5f},{pos.lon:.5f}")
                self._on_position(pos)

        elif fmt == "message" and self._on_text:
            msg_text = p.get("message_text", "") or ""
            addressee = p.get("addresse", "") or ""
            msg = TextMessage(
                from_id=from_call,
                to_id=addressee.strip(),
                text=msg_text.strip(),
                channel="APRS",
                timestamp=ts,
                source_type="aprs",
            )
            logger.info(f"APRS message from {from_call} to {addressee}: {msg_text}")
            self._on_text(msg)

    def _beacon_loop(self) -> None:
        interval = self._cfg.beacon_interval
        time.sleep(interval)  # initial delay
        while self._running:
            if self._last_pos and self._connected:
                try:
                    self.send_position(self._last_pos)
                except Exception as e:
                    logger.warning(f"APRS beacon error: {e}")
            time.sleep(interval)
