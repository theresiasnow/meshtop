"""rigctld radio status monitor (read-only)."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from loguru import logger

from meshtop.config import RigctldConfig


@dataclass
class RadioStatus:
    freq_hz: float = 0.0
    mode: str = ""
    passband: int = 0
    signal_strength: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


RadioStatusCallback = Callable[[RadioStatus], None]


class RigctldMonitor:
    """Polls rigctld for frequency, mode, and signal strength."""

    def __init__(
        self,
        cfg: RigctldConfig,
        on_radio_status: RadioStatusCallback | None = None,
        on_connected: Callable[[bool], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._on_radio_status = on_radio_status
        self._on_connected = on_connected
        self._running = False
        self._connected = False
        self._thread: threading.Thread | None = None
        self._last_status: RadioStatus = RadioStatus()

    # ------------------------------------------------------------------ public

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="rigctld")
        self._thread.start()
        logger.info(f"RigctldMonitor started — {self._cfg.host}:{self._cfg.port}")

    def stop(self) -> None:
        self._running = False
        logger.info("RigctldMonitor stopped")

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_status(self) -> RadioStatus:
        return self._last_status

    # ----------------------------------------------------------------- private

    def _loop(self) -> None:
        while self._running:
            try:
                self._connect_and_poll()
            except Exception as e:
                logger.warning(f"RigctldMonitor error: {e}")
            if self._running:
                logger.info("RigctldMonitor reconnecting in 30s")
                time.sleep(30)

    def _connect_and_poll(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((self._cfg.host, self._cfg.port))
        self._connected = True
        if self._on_connected:
            self._on_connected(True)
        logger.info(f"RigctldMonitor connected to {self._cfg.host}:{self._cfg.port}")

        try:
            while self._running:
                status = self._poll(sock)
                if status:
                    self._last_status = status
                    if self._on_radio_status:
                        self._on_radio_status(status)
                time.sleep(self._cfg.poll_interval)
        finally:
            self._connected = False
            try:
                sock.close()
            except Exception:
                pass
            if self._on_connected:
                self._on_connected(False)

    def _poll(self, sock: socket.socket) -> RadioStatus | None:
        try:
            freq_hz = self._cmd(sock, "f")
            mode_line = self._cmd(sock, "m")
            strength_line = self._cmd(sock, "l STRENGTH")
        except Exception as e:
            logger.debug(f"rigctld poll error: {e}")
            raise

        try:
            freq = float(freq_hz.strip()) if freq_hz.strip() else 0.0
        except ValueError:
            freq = 0.0

        mode_parts = mode_line.strip().split()
        mode = mode_parts[0] if mode_parts else ""
        try:
            passband = int(mode_parts[1]) if len(mode_parts) > 1 else 0
        except ValueError:
            passband = 0

        try:
            strength = float(strength_line.strip())
        except ValueError:
            strength = 0.0

        return RadioStatus(
            freq_hz=freq,
            mode=mode,
            passband=passband,
            signal_strength=strength,
            timestamp=datetime.now(UTC),
        )

    def _cmd(self, sock: socket.socket, command: str) -> str:
        """Send a single rigctld command and return the response line."""
        sock.sendall((command + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(256)
            if not chunk:
                raise ConnectionError("rigctld closed connection")
            buf += chunk
        return buf.decode("ascii", errors="replace").split("\n")[0]
