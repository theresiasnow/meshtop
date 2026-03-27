"""Meshtastic Bluetooth BLE source (wireless direct connection, no gateway)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from loguru import logger

from meshtop.config import SourceConfig
from meshtop.sources._mesh_decode import decode_packet

_WATCHDOG_TIMEOUT = 180  # seconds of silence before forcing reconnect


class BleSource:
    def __init__(
        self,
        cfg: SourceConfig,
        on_position: Callable | None = None,
        on_telemetry: Callable | None = None,
        on_nodeinfo: Callable | None = None,
        on_text: Callable | None = None,
        on_status: Callable[[bool], None] | None = None,
        on_traceroute: Callable | None = None,
    ) -> None:
        self._cfg = cfg
        self._on_position = on_position
        self._on_telemetry = on_telemetry
        self._on_nodeinfo = on_nodeinfo
        self._on_text = on_text
        self._on_status = on_status
        self._on_traceroute = on_traceroute
        self._iface = None
        self._receive_sub = None
        self._connect_sub = None
        self._disconnect_sub = None
        self._last_rx = 0.0
        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_stop = threading.Event()

    def start(self) -> None:
        from meshtastic.ble_interface import BLEClient, BLEInterface
        from pubsub import pub

        device = self._cfg.ble.device or None  # None = auto-discover first device

        # Subclass BLEInterface to call pair() before discover() so that a single
        # `ble on` handles first-time bonding without a "connect again" round-trip.
        class _PairableBLEInterface(BLEInterface):
            def connect(self, address=None):
                ble_device = self.find_device(address)
                client = BLEClient(ble_device.address, disconnected_callback=lambda _: self.close())
                client.connect()
                try:
                    client.pair()
                    logger.debug("BLE pair() succeeded (or already bonded)")
                except Exception as pair_exc:
                    logger.debug(f"BLE pair() skipped: {pair_exc}")
                client.discover()
                return client

        def on_receive(packet, interface) -> None:
            self._last_rx = time.monotonic()
            decode_packet(
                packet,
                on_position=self._on_position,
                on_telemetry=self._on_telemetry,
                on_nodeinfo=self._on_nodeinfo,
                on_text=self._on_text,
                on_traceroute=self._on_traceroute,
                source_tag="ble",
            )

        def on_connect(interface, topic=pub.AUTO_TOPIC) -> None:
            self._last_rx = time.monotonic()
            name = device or "auto"
            logger.info(f"Meshtastic BLE connected: {name}")
            if self._on_status:
                self._on_status(True)

        def on_disconnect(interface, topic=pub.AUTO_TOPIC) -> None:
            logger.warning("Meshtastic BLE disconnected")
            if self._on_status:
                self._on_status(False)

        self._receive_sub = on_receive
        self._connect_sub = on_connect
        self._disconnect_sub = on_disconnect

        pub.subscribe(on_receive, "meshtastic.receive")
        pub.subscribe(on_connect, "meshtastic.connection.established")
        pub.subscribe(on_disconnect, "meshtastic.connection.lost")

        logger.info(f"BleSource connecting to {device or 'first available device'}…")
        self._iface = _PairableBLEInterface(device)
        self._last_rx = time.monotonic()
        logger.info("BleSource started")

        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog, daemon=True, name="ble-watchdog"
        )
        self._watchdog_thread.start()

    def _watchdog(self) -> None:
        while not self._watchdog_stop.wait(timeout=30):
            if not self._iface:
                break
            age = time.monotonic() - self._last_rx
            if age >= _WATCHDOG_TIMEOUT:
                logger.warning(f"BLE watchdog: no packets for {age:.0f}s — forcing disconnect")
                try:
                    self._iface.close()
                except Exception:
                    pass
                break

    def stop(self) -> None:
        self._watchdog_stop.set()
        try:
            from pubsub import pub

            if self._receive_sub:
                pub.unsubscribe(self._receive_sub, "meshtastic.receive")
            if self._connect_sub:
                pub.unsubscribe(self._connect_sub, "meshtastic.connection.established")
            if self._disconnect_sub:
                pub.unsubscribe(self._disconnect_sub, "meshtastic.connection.lost")
        except Exception:
            pass
        if self._iface:
            iface, self._iface = self._iface, None
            t = threading.Thread(target=iface.close, daemon=True)
            t.start()
            t.join(timeout=3.0)  # give BLE stack 3 s to disconnect cleanly
        logger.info("BleSource stopped")
