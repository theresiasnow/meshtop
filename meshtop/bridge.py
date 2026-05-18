"""Message bridge: routes TextMessages between radio and mesh sources."""

from __future__ import annotations

import threading
import time
from typing import Any, Protocol

from loguru import logger

from meshtop.config import BridgeConfig
from meshtop.sources.meshtastic import TextMessage


class Sender(Protocol):
    def send_message(self, dest: str, text: str) -> None: ...


class MessageBridge:
    """Routes incoming messages across source types per BridgeConfig rules.

    Loop prevention: tracks (from_id, text_prefix, minute_bucket) tuples.
    If the same message is seen twice in the same minute, the second is dropped.
    """

    def __init__(self, config: BridgeConfig, senders: dict[str, Any]) -> None:
        self._cfg = config
        # senders: source_type -> object with send_message(dest, text)
        self._senders = senders
        self._seen: set[tuple[str, str, int]] = set()
        self._seen_lock = threading.Lock()
        # Mapping of route directions to check
        self._routes: list[tuple[str, str, str]] = [
            # (source_type, config_attr, target_source_type)
            ("mesh", "mesh_to_aprs", "aprs"),
            ("mesh", "mesh_to_js8call", "js8call"),
            ("aprs", "aprs_to_mesh", "mesh"),
            ("js8call", "js8call_to_mesh", "mesh"),
        ]

    def route(self, msg: TextMessage) -> None:
        """Called for every incoming message. Forwards to enabled targets."""
        if not self._dedup(msg):
            return
        for src_type, cfg_attr, target_type in self._routes:
            if msg.source_type != src_type:
                continue
            if not getattr(self._cfg, cfg_attr, False):
                continue
            sender = self._senders.get(target_type)
            if sender is None:
                continue
            try:
                sender.send_message(msg.from_id, msg.text)
                logger.info(
                    f"Bridge: {src_type} → {target_type}: [{msg.from_id}] {msg.text[:40]}"
                )
            except Exception as e:
                logger.warning(f"Bridge send error ({src_type} → {target_type}): {e}")

    def _dedup(self, msg: TextMessage) -> bool:
        """Return True if this message should be forwarded (not a loop echo)."""
        minute = int(time.monotonic() // 60)
        key = (msg.from_id, msg.text[:32], minute)
        with self._seen_lock:
            if key in self._seen:
                logger.debug(f"Bridge: dropping duplicate from {msg.from_id}")
                return False
            self._seen.add(key)
            # Trim old entries (keep last 2 minutes)
            stale = {k for k in self._seen if k[2] < minute - 1}
            self._seen -= stale
        return True
