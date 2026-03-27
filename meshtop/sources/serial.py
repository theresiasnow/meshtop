"""Meshtastic USB-serial source (direct device connection, no gateway)."""

from __future__ import annotations

from collections.abc import Callable

from loguru import logger

from meshtop.config import SourceConfig
from meshtop.sources._mesh_decode import decode_packet


class SerialSource:
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

    def start(self) -> None:
        from meshtastic.serial_interface import SerialInterface
        from pubsub import pub

        def on_receive(packet, interface) -> None:
            decode_packet(
                packet,
                on_position=self._on_position,
                on_telemetry=self._on_telemetry,
                on_nodeinfo=self._on_nodeinfo,
                on_text=self._on_text,
                on_traceroute=self._on_traceroute,
                source_tag="serial",
            )

        def on_connect(interface, topic=pub.AUTO_TOPIC) -> None:
            logger.info(f"Meshtastic serial connected: {self._cfg.port}")
            if self._on_status:
                self._on_status(True)

        def on_disconnect(interface, topic=pub.AUTO_TOPIC) -> None:
            logger.warning("Meshtastic serial disconnected")
            if self._on_status:
                self._on_status(False)

        self._receive_sub = on_receive
        self._connect_sub = on_connect
        self._disconnect_sub = on_disconnect

        pub.subscribe(on_receive, "meshtastic.receive")
        pub.subscribe(on_connect, "meshtastic.connection.established")
        pub.subscribe(on_disconnect, "meshtastic.connection.lost")

        try:
            self._iface = SerialInterface(self._cfg.port, timeout=30)
        except Exception:
            import gc

            gc.collect()  # ensure partially-constructed SerialInterface releases the port
            raise
        logger.info(f"SerialSource started on {self._cfg.port}")

    def stop(self) -> None:
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
            try:
                self._iface.close()
            except Exception:
                pass
            self._iface = None
        logger.info("SerialSource stopped")
