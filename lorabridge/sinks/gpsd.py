"""gpsd-compatible JSON TCP server (port 2947).

Implements enough of the gpsd protocol for clients like gpspipe, cgps,
and applications that link against libgps:

  - On connect, send a VERSION banner.
  - Respond to ?WATCH= with DEVICES + WATCH ack.
  - Push TPV (position) and SKY (satellite count) when a fix arrives.

Reference: https://gpsd.gitlab.io/gpsd/gpsd_json.html
"""

import json
import socket
import threading
from datetime import UTC, datetime

from loguru import logger

from lorabridge.config import GpsdConfig
from lorabridge.position import Position

_VERSION = {
    "class": "VERSION",
    "release": "3.25",
    "rev": "lorabridge",
    "proto_major": 3,
    "proto_minor": 14,
}

_DEVICES = {
    "class": "DEVICES",
    "devices": [
        {
            "class": "DEVICE",
            "path": "/dev/meshtastic",
            "driver": "lorabridge",
            "activated": "",
        }
    ],
}

_WATCH_ACK = {
    "class": "WATCH",
    "enable": True,
    "json": True,
    "nmea": False,
    "raw": 0,
    "scaled": False,
    "timing": False,
}


def _tpv(pos: Position) -> dict:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {
        "class": "TPV",
        "device": "/dev/meshtastic",
        "mode": 3 if pos.fix else 1,
        "time": now,
        "lat": pos.lat,
        "lon": pos.lon,
        "alt": pos.alt,
        "altHAE": pos.alt,
        "speed": pos.speed,
        "track": pos.course,
        "ept": 0.005,
        "epx": 15.0,
        "epy": 15.0,
        "epv": 25.0,
    }


def _sky(pos: Position) -> dict:
    return {
        "class": "SKY",
        "device": "/dev/meshtastic",
        "uSat": pos.sats,
        "nSat": pos.sats,
        "satellites": [],
    }


class GpsdSink:
    def __init__(self, cfg: GpsdConfig) -> None:
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
            target=self._accept_loop, daemon=True, name="gpsd-accept"
        )
        self._accept_thread.start()
        logger.info(f"gpsd server listening on port {self._cfg.port}")

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
        logger.info("gpsd server stopped")

    def send(self, pos: Position) -> None:
        if not pos.fix:
            return
        msgs = [
            (json.dumps(_tpv(pos)) + "\n").encode(),
            (json.dumps(_sky(pos)) + "\n").encode(),
        ]
        with self._lock:
            dead = []
            for s in self._clients:
                try:
                    for msg in msgs:
                        s.sendall(msg)
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
                logger.info(f"gpsd client connected: {addr}")
                t = threading.Thread(
                    target=self._handle_client,
                    args=(conn,),
                    daemon=True,
                    name=f"gpsd-client-{addr}",
                )
                t.start()
            except TimeoutError:
                continue
            except OSError:
                break

    def _handle_client(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(5.0)
            # Send VERSION banner immediately
            conn.sendall((json.dumps(_VERSION) + "\n").encode())
            buf = ""
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(256).decode("ascii", errors="replace")
                    if not chunk:
                        break
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line.startswith("?WATCH=") or line == "?WATCH;":
                            conn.sendall((json.dumps(_DEVICES) + "\n").encode())
                            conn.sendall((json.dumps(_WATCH_ACK) + "\n").encode())
                            with self._lock:
                                if conn not in self._clients:
                                    self._clients.append(conn)
                except TimeoutError:
                    continue
        except OSError:
            pass
        finally:
            with self._lock:
                if conn in self._clients:
                    self._clients.remove(conn)
            try:
                conn.close()
            except Exception:
                pass
            logger.debug("gpsd client disconnected")
