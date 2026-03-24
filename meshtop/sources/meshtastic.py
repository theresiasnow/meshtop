import struct
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from loguru import logger
from meshtastic.protobuf import portnums_pb2
from meshtastic.protobuf.mesh_pb2 import MeshPacket, User
from meshtastic.protobuf.mesh_pb2 import Position as MeshPosition
from meshtastic.protobuf.mqtt_pb2 import ServiceEnvelope
from meshtastic.protobuf.telemetry_pb2 import Telemetry

from meshtop.config import LoraSourceConfig, expand_psk
from meshtop.position import Position


@dataclass
class DeviceMetrics:
    battery_level: int = 0
    voltage: float = 0.0
    uptime_seconds: int = 0
    channel_utilization: float = 0.0
    air_util_tx: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class NodeInfo:
    node_id: str = ""
    long_name: str = ""
    short_name: str = ""
    hw_model: int = 0


@dataclass
class TextMessage:
    from_id: str = ""
    to_id: str = ""
    text: str = ""
    channel: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class TraceRoute:
    from_id: str = ""
    route: list[str] = field(default_factory=list)  # intermediate hop node IDs


PositionCallback = Callable[[Position], None]
TelemetryCallback = Callable[[DeviceMetrics], None]
NodeInfoCallback = Callable[[NodeInfo], None]
TextCallback = Callable[[TextMessage], None]
TraceRouteCallback = Callable[[TraceRoute], None]
MqttStatusCallback = Callable[[bool], None]


class MeshtasticSource:
    def __init__(
        self,
        cfg: LoraSourceConfig,
        on_position: PositionCallback | None = None,
        on_telemetry: TelemetryCallback | None = None,
        on_nodeinfo: NodeInfoCallback | None = None,
        on_text: TextCallback | None = None,
        on_mqtt_status: MqttStatusCallback | None = None,
    ) -> None:
        self._cfg = cfg
        self._on_position = on_position
        self._on_telemetry = on_telemetry
        self._on_nodeinfo = on_nodeinfo
        self._on_text = on_text
        self._on_mqtt_status = on_mqtt_status
        # Primary channel (index 0) key — used as fallback for any unnamed channel
        pk = expand_psk(cfg.primary_key) if cfg.primary_key else b""
        self._primary_key: bytes | None = pk or None
        # Named secondary channel key lookup: channel_name -> bytes
        self._channel_keys: dict[str, bytes] = {}
        self._enabled_channels: set[str] = set()
        for name, ch in cfg.channels.items():
            if ch.enabled:
                self._enabled_channels.add(name)
            if ch.enabled and ch.encrypted and ch.key:
                self._channel_keys[name] = expand_psk(ch.key)
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.username_pw_set(cfg.username, cfg.password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ public

    def start(self) -> None:
        self._client.connect(self._cfg.broker, self._cfg.port, keepalive=60)
        self._thread = threading.Thread(target=self._client.loop_forever, daemon=True)
        self._thread.start()
        logger.info(f"MeshtasticSource started — broker={self._cfg.broker} topic={self._cfg.topic}")

    def stop(self) -> None:
        self._client.disconnect()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("MeshtasticSource stopped")

    def reload_channels(self) -> None:
        """Rebuild primary key, channel key / enabled-set from current cfg."""
        pk = expand_psk(self._cfg.primary_key) if self._cfg.primary_key else b""
        self._primary_key = pk or None
        new_keys: dict[str, bytes] = {}
        new_enabled: set[str] = set()
        for name, ch in self._cfg.channels.items():
            if ch.enabled:
                new_enabled.add(name)
            if ch.enabled and ch.encrypted and ch.key:
                new_keys[name] = expand_psk(ch.key)
        self._channel_keys = new_keys
        self._enabled_channels = new_enabled
        logger.info(f"Primary key set: {bool(self._primary_key)}  named channels: {list(new_keys)}")

    # ----------------------------------------------------------------- private

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        logger.info(f"MQTT connected rc={rc}, subscribing to {self._cfg.topic}")
        client.subscribe(self._cfg.topic)
        if self._on_mqtt_status:
            self._on_mqtt_status(True)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None) -> None:
        logger.info(f"MQTT disconnected rc={rc}")
        if self._on_mqtt_status:
            self._on_mqtt_status(False)

    def _on_message(self, client, userdata, msg) -> None:
        node_filter = self._cfg.node_id
        if node_filter and node_filter not in msg.topic:
            logger.debug(f"filtered: {msg.topic}")
            return
        logger.debug(f"incoming: {msg.topic}")
        # Extract channel name from topic: msh/EU_868/SE/2/e/LongFast/!nodeid
        parts = msg.topic.split("/")
        channel_name = parts[-2] if len(parts) >= 2 else ""
        try:
            envelope = ServiceEnvelope()
            envelope.ParseFromString(msg.payload)
            self._handle_packet(envelope.packet, channel_name)
        except Exception as e:
            logger.debug(f"Failed to parse envelope on {msg.topic}: {e}")

    def _handle_packet(self, packet: MeshPacket, channel_name: str = "") -> None:
        data = None
        if packet.HasField("decoded"):
            # Accept all decoded packets regardless of channel
            data = packet.decoded
        elif packet.HasField("encrypted"):
            # Named secondary channel key first; fall back to primary channel key
            key = self._channel_keys.get(channel_name) or self._primary_key
            if key:
                data = self._decrypt(packet, key)

        if data is None:
            return

        pn = data.portnum
        try:
            if pn == portnums_pb2.POSITION_APP:
                self._handle_position(data.payload)
            elif pn == portnums_pb2.TELEMETRY_APP:
                self._handle_telemetry(data.payload)
            elif pn == portnums_pb2.NODEINFO_APP:
                self._handle_nodeinfo(data.payload, packet)
            elif pn == portnums_pb2.TEXT_MESSAGE_APP:
                self._handle_text(data.payload, packet, channel_name)
        except Exception as e:
            logger.debug(f"Failed to decode portnum={pn}: {e}")

    def _handle_position(self, payload: bytes) -> None:
        if not self._on_position:
            return
        p = MeshPosition()
        p.ParseFromString(payload)
        if not p.latitude_i and not p.longitude_i:
            return  # no fix
        pos = Position(
            lat=p.latitude_i * 1e-7,
            lon=p.longitude_i * 1e-7,
            alt=float(p.altitude),
            speed=p.ground_speed * 0.539957 if p.ground_speed else 0.0,  # m/s -> knots
            course=float(p.ground_track) if p.ground_track else 0.0,
            fix=True,
            sats=p.sats_in_view,
            timestamp=datetime.now(UTC),
        )
        logger.info(f"Position: lat={pos.lat:.5f} lon={pos.lon:.5f} alt={pos.alt}m sats={pos.sats}")
        self._on_position(pos)

    def _handle_telemetry(self, payload: bytes) -> None:
        if not self._on_telemetry:
            return
        t = Telemetry()
        t.ParseFromString(payload)
        dm = t.device_metrics
        metrics = DeviceMetrics(
            battery_level=dm.battery_level,
            voltage=dm.voltage,
            uptime_seconds=dm.uptime_seconds,
            channel_utilization=dm.channel_utilization,
            air_util_tx=dm.air_util_tx,
        )
        logger.debug(f"Telemetry: battery={metrics.battery_level}% voltage={metrics.voltage:.2f}V")
        self._on_telemetry(metrics)

    def _handle_nodeinfo(self, payload: bytes, packet: MeshPacket) -> None:
        if not self._on_nodeinfo:
            return
        u = User()
        u.ParseFromString(payload)
        node = NodeInfo(
            node_id=f"!{getattr(packet, 'from'):08x}",
            long_name=u.long_name,
            short_name=u.short_name,
            hw_model=u.hw_model,
        )
        logger.debug(f"NodeInfo: {node.long_name} ({node.short_name})")
        self._on_nodeinfo(node)

    def _handle_text(self, payload: bytes, packet: MeshPacket, channel: str = "") -> None:
        if not self._on_text:
            return
        from_id = f"!{getattr(packet, 'from'):08x}"
        to_id = f"!{packet.to:08x}" if packet.to != 0xFFFFFFFF else "broadcast"
        text = payload.decode("utf-8", errors="replace")
        msg = TextMessage(from_id=from_id, to_id=to_id, text=text, channel=channel)
        logger.info(f"Text [{from_id} -> {to_id}] ch={channel!r}: {text}")
        self._on_text(msg)

    def _decrypt(self, packet: MeshPacket, key: bytes):
        from meshtastic.protobuf.mesh_pb2 import Data
        try:
            pid = packet.id
            fn = getattr(packet, "from")
            nonce = struct.pack("<Q", pid) + struct.pack("<Q", fn)
            cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
            raw = cipher.decryptor().update(bytes(packet.encrypted))
            data = Data()
            data.ParseFromString(raw)
        except Exception as e:
            logger.debug(f"Decrypt failed pid={packet.id:#010x} channel key: {e}")
            return None
        else:
            return data
