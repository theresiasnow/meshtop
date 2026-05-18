"""JS8Call two-way source via JS8Call TCP API."""

from __future__ import annotations

import json
import re
import socket
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from loguru import logger

from meshtop.config import Js8CallSourceConfig
from meshtop.position import Position
from meshtop.sources.meshtastic import NodeInfo, TextMessage

# Matches "@GRID <locator>" anywhere in a message, e.g. "@GRID FN31"
_GRID_RE = re.compile(r"@GRID\s+([A-Ra-r]{2}\d{2}(?:[A-Xa-x]{2})?)", re.IGNORECASE)


def _maidenhead_to_latlon(grid: str) -> tuple[float, float] | None:
    """Convert a Maidenhead grid locator to (lat, lon). Returns None on error."""
    try:
        import maidenhead

        lat, lon = maidenhead.to_location(grid)
    except Exception:
        return None
    else:
        return lat, lon


class Js8CallSource:
    """Two-way messaging source using the JS8Call TCP API."""

    def __init__(
        self,
        cfg: Js8CallSourceConfig,
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
        self._lock = threading.Lock()
        self._seen_ids: set[str] = set()  # deduplicate inbox messages

    # ------------------------------------------------------------------ public

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="js8call")
        self._thread.start()
        logger.info(f"Js8CallSource started — {self._cfg.host}:{self._cfg.port}")

    def stop(self) -> None:
        self._running = False
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
        logger.info("Js8CallSource stopped")

    def send_message(self, dest: str, text: str) -> None:
        """Send a directed message via JS8Call."""
        self._send_api({"type": "TX.SEND_MESSAGE", "params": {"TO": dest.upper(), "TEXT": text}})

    def send_position(self, pos: Position) -> None:
        """Broadcast position as a @GRID message to @ALLCALL."""
        try:
            import maidenhead

            grid = maidenhead.to_maiden(pos.lat, pos.lon)
        except Exception:
            logger.debug("Js8CallSource: maidenhead not available, skipping position send")
            return
        self.send_message("@ALLCALL", f"@GRID {grid}")

    # ----------------------------------------------------------------- private

    def _send_api(self, msg: dict) -> None:
        with self._lock:
            sock = self._sock
        if sock is None:
            logger.debug("Js8CallSource: not connected, dropping outbound message")
            return
        try:
            data = json.dumps(msg) + "\n"
            sock.sendall(data.encode())
        except Exception as e:
            logger.warning(f"Js8CallSource send error: {e}")

    def _loop(self) -> None:
        while self._running:
            try:
                self._connect_and_read()
            except Exception as e:
                logger.warning(f"Js8CallSource error: {e}")
            if self._running:
                logger.info("Js8CallSource reconnecting in 30s")
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
        logger.info(f"Js8CallSource connected to {self._cfg.host}:{self._cfg.port}")

        # Kick off inbox poll in a side thread
        poll_stop = threading.Event()
        poll_thread = threading.Thread(
            target=self._poll_inbox, args=(poll_stop,), daemon=True, name="js8-inbox"
        )
        poll_thread.start()

        buf = b""
        try:
            while self._running:
                data = sock.recv(4096)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._handle_event(line.decode("utf-8", errors="replace").strip())
        finally:
            poll_stop.set()
            self._connected = False
            with self._lock:
                self._sock = None
            try:
                sock.close()
            except Exception:
                pass
            if self._on_status:
                self._on_status(False)

    def _poll_inbox(self, stop: threading.Event) -> None:
        interval = self._cfg.poll_interval
        while not stop.wait(interval):
            self._send_api({"type": "INBOX.GET_MESSAGES", "params": {}})

    def _handle_event(self, line: str) -> None:
        if not line:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.debug(f"JS8Call non-JSON: {line[:80]}")
            return

        etype = event.get("type", "")
        params = event.get("params", {})

        if etype in ("RX.DIRECTED", "RX.ACTIVITY"):
            self._handle_rx(params)
        elif etype == "INBOX.MESSAGES":
            messages = params.get("MESSAGES") or []
            for m in messages:
                self._handle_inbox_msg(m)

    def _handle_rx(self, params: dict) -> None:
        from_call = params.get("FROM", "") or params.get("CALLSIGN", "")
        to_call = params.get("TO", "") or self._cfg.callsign
        text = params.get("TEXT", "") or params.get("VALUE", "")
        if not from_call or not text:
            return
        ts = datetime.now(UTC)
        self._dispatch_message(from_call, to_call, text, ts)

    def _handle_inbox_msg(self, m: dict) -> None:
        msg_id = m.get("ID", "") or m.get("UTC", "")
        if msg_id in self._seen_ids:
            return
        if msg_id:
            self._seen_ids.add(msg_id)
            # Trim seen set to avoid unbounded growth
            if len(self._seen_ids) > 500:
                self._seen_ids = set(list(self._seen_ids)[-250:])

        from_call = m.get("FROM", "")
        to_call = m.get("TO", "") or self._cfg.callsign
        text = m.get("TEXT", "") or m.get("MESSAGE", "")
        if not from_call or not text:
            return
        try:
            ts = datetime.fromisoformat(m.get("UTC", ""))
        except Exception:
            ts = datetime.now(UTC)
        self._dispatch_message(from_call, to_call, text, ts)

    def _dispatch_message(self, from_call: str, to_call: str, text: str, ts: datetime) -> None:
        # Fire NodeInfo for the sender
        if self._on_nodeinfo:
            node = NodeInfo(
                node_id=from_call,
                long_name=from_call,
                short_name=from_call[:4],
                last_heard=ts,
                source_type="js8call",
            )
            self._on_nodeinfo(node)

        # Check for @GRID position in message
        m = _GRID_RE.search(text)
        if m and self._on_position:
            latlon = _maidenhead_to_latlon(m.group(1))
            if latlon:
                pos = Position(lat=latlon[0], lon=latlon[1], fix=True, timestamp=ts)
                logger.debug(f"JS8Call grid from {from_call}: {m.group(1)}")
                self._on_position(pos)

        if self._on_text:
            msg = TextMessage(
                from_id=from_call,
                to_id=to_call,
                text=text,
                channel="JS8",
                timestamp=ts,
                source_type="js8call",
            )
            logger.info(f"JS8 message from {from_call}: {text[:60]}")
            self._on_text(msg)
