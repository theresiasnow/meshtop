"""TCP NMEA server — clients connect and receive GPRMC/GPGGA sentences.

pi-star connects to this on port 10110 as a GPS source.
"""

import socket
import threading
from datetime import UTC, datetime

from loguru import logger

from lorabridge.config import NmeaServerConfig
from lorabridge.position import Position


def _nmea_checksum(sentence: str) -> str:
    """XOR of all bytes between $ and * (exclusive)."""
    cs = 0
    for ch in sentence:
        cs ^= ord(ch)
    return f"{cs:02X}"


def _format_gprmc(pos: Position) -> str:
    now = datetime.now(UTC)
    time_str = now.strftime("%H%M%S.00")
    date_str = now.strftime("%d%m%y")
    status = "A" if pos.fix else "V"

    lat = abs(pos.lat)
    lat_deg = int(lat)
    lat_min = (lat - lat_deg) * 60
    lat_hemi = "N" if pos.lat >= 0 else "S"

    lon = abs(pos.lon)
    lon_deg = int(lon)
    lon_min = (lon - lon_deg) * 60
    lon_hemi = "E" if pos.lon >= 0 else "W"

    speed_knots = pos.speed * 1.944  # m/s → knots
    body = (
        f"GPRMC,{time_str},{status},"
        f"{lat_deg:02d}{lat_min:07.4f},{lat_hemi},"
        f"{lon_deg:03d}{lon_min:07.4f},{lon_hemi},"
        f"{speed_knots:.1f},{pos.course:.1f},{date_str},,,"
    )
    return f"${body}*{_nmea_checksum(body)}\r\n"


def _format_gpgga(pos: Position) -> str:
    now = datetime.now(UTC)
    time_str = now.strftime("%H%M%S.00")
    quality = 1 if pos.fix else 0

    lat = abs(pos.lat)
    lat_deg = int(lat)
    lat_min = (lat - lat_deg) * 60
    lat_hemi = "N" if pos.lat >= 0 else "S"

    lon = abs(pos.lon)
    lon_deg = int(lon)
    lon_min = (lon - lon_deg) * 60
    lon_hemi = "E" if pos.lon >= 0 else "W"

    body = (
        f"GPGGA,{time_str},"
        f"{lat_deg:02d}{lat_min:07.4f},{lat_hemi},"
        f"{lon_deg:03d}{lon_min:07.4f},{lon_hemi},"
        f"{quality},{pos.sats:02d},1.0,{pos.alt:.1f},M,0.0,M,,"
    )
    return f"${body}*{_nmea_checksum(body)}\r\n"


class NmeaServer:
    """TCP server that pushes NMEA sentences to all connected clients."""

    def __init__(self, cfg: NmeaServerConfig) -> None:
        self._cfg = cfg
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._server_sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def start(self) -> None:
        self._stop.clear()
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("0.0.0.0", self._cfg.port))
        self._server_sock.listen(5)
        self._server_sock.settimeout(1.0)
        self._accept_thread = threading.Thread(
            target=self._accept_loop, daemon=True, name="nmea-accept"
        )
        self._accept_thread.start()
        logger.info(f"NMEA server listening on port {self._cfg.port}")

    def stop(self) -> None:
        self._stop.set()
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        if self._accept_thread:
            self._accept_thread.join(timeout=3)
        with self._lock:
            for s in self._clients:
                try:
                    s.close()
                except Exception:
                    pass
            self._clients.clear()
        logger.info("NMEA server stopped")

    def send(self, pos: Position) -> None:
        if not pos.fix:
            return
        sentences = _format_gprmc(pos) + _format_gpgga(pos)
        data = sentences.encode("ascii")
        with self._lock:
            dead = []
            for s in self._clients:
                try:
                    s.sendall(data)
                except OSError:
                    dead.append(s)
            for s in dead:
                self._clients.remove(s)
                try:
                    s.close()
                except Exception:
                    pass

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = self._server_sock.accept()  # type: ignore[union-attr]
                logger.info(f"NMEA client connected: {addr}")
                with self._lock:
                    self._clients.append(conn)
            except TimeoutError:
                continue
            except OSError:
                break
