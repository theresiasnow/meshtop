import socket
import threading
import time

from loguru import logger

from lorabridge.config import AprsConfig
from lorabridge.position import Position


def _format_lat(lat: float) -> str:
    hemi = "N" if lat >= 0 else "S"
    lat = abs(lat)
    deg = int(lat)
    minutes = (lat - deg) * 60
    return f"{deg:02d}{minutes:05.2f}{hemi}"


def _format_lon(lon: float) -> str:
    hemi = "E" if lon >= 0 else "W"
    lon = abs(lon)
    deg = int(lon)
    minutes = (lon - deg) * 60
    return f"{deg:03d}{minutes:05.2f}{hemi}"


class AprsSink:
    def __init__(self, cfg: AprsConfig) -> None:
        self._cfg = cfg
        self._sock: socket.socket | None = None
        self._connected = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last_beacon = 0.0
        self._keepalive_thread: threading.Thread | None = None
        self._filter_sent = False
        self.on_beacon: callable | None = None  # called after each successful beacon
        self.beacon_enabled: bool = True        # toggled by TUI :beacon on/off

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def last_beacon(self) -> float:
        return self._last_beacon

    def start(self) -> None:
        self._stop.clear()
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name="aprs-keepalive"
        )
        self._keepalive_thread.start()
        logger.info(
            f"AprsSink started — {self._cfg.server}:{self._cfg.port} as {self._cfg.callsign}"
        )

    def stop(self) -> None:
        self._stop.set()
        if self._keepalive_thread:
            self._keepalive_thread.join(timeout=5)
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
            self._connected = False
        logger.info("AprsSink stopped")

    def send(self, pos: Position) -> None:
        if not pos.fix or not self.beacon_enabled:
            return
        now = time.monotonic()
        if now - self._last_beacon < self._cfg.interval:
            return
        with self._lock:
            sock = self._sock
            connected = self._connected
        if not connected or sock is None:
            return
        lat_str = _format_lat(pos.lat)
        lon_str = _format_lon(pos.lon)
        packet = (
            f"{self._cfg.callsign}>APRS,TCPIP*:"
            f"!{lat_str}/{lon_str}>{self._cfg.comment}\r\n"
        )
        try:
            sock.sendall(packet.encode("ascii"))
            self._last_beacon = now
            logger.info(f"APRS beacon: {packet.strip()}")
            if self.on_beacon:
                self.on_beacon()
            if not self._filter_sent:
                self._send_filter(f"r/{pos.lat:.1f}/{pos.lon:.1f}/200")
        except OSError as e:
            logger.warning(f"APRS send failed: {e}")
            with self._lock:
                self._connected = False

    def _connect(self) -> None:
        try:
            sock = socket.create_connection((self._cfg.server, self._cfg.port), timeout=15)
            sock.settimeout(30)
            banner = sock.recv(512).decode("ascii", errors="replace").strip()
            logger.info(f"APRS-IS banner: {banner}")
            login = f"user {self._cfg.callsign} pass {self._cfg.passcode} vers lorabridge 1.0\r\n"
            sock.sendall(login.encode("ascii"))
            resp = sock.recv(512).decode("ascii", errors="replace").strip()
            logger.info(f"APRS-IS login: {resp}")
            if "verified" not in resp.lower():
                logger.warning(f"APRS-IS login may have failed: {resp}")
            with self._lock:
                self._sock = sock
                self._connected = True
            logger.info(f"APRS-IS connected to {self._cfg.server}:{self._cfg.port}")
        except OSError as e:
            logger.error(f"APRS-IS connection failed: {e}")
            with self._lock:
                self._connected = False

    def _send_filter(self, filt: str) -> None:
        with self._lock:
            sock = self._sock
        if sock is None:
            return
        try:
            sock.sendall(f"#filter {filt}\r\n".encode("ascii"))
            self._filter_sent = True
            logger.info(f"APRS-IS filter set: {filt}")
        except OSError as e:
            logger.warning(f"APRS-IS filter send failed: {e}")

    def _keepalive_loop(self) -> None:
        self._connect()
        while not self._stop.wait(60):
            with self._lock:
                sock = self._sock
            if sock is None:
                self._connect()
                continue
            try:
                sock.sendall(b"#keepalive\r\n")
            except OSError:
                logger.warning("APRS-IS keepalive failed, reconnecting")
                with self._lock:
                    self._connected = False
                    try:
                        self._sock.close()
                    except Exception:
                        pass
                    self._sock = None
                self._connect()
