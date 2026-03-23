"""Shared decoder for meshtastic SerialInterface / BLEInterface packets.

Both interfaces deliver packets as Python dicts (MessageToDict output) with
camelCase keys — unlike the MQTT source which works with raw protobufs.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from lorabridge.position import Position
from lorabridge.sources.meshtastic import DeviceMetrics, NodeInfo, TextMessage


def fire_initial_nodes(
    iface: Any,
    on_position: Callable | None = None,
    on_nodeinfo: Callable | None = None,
    on_telemetry: Callable | None = None,
    source_tag: str = "",
) -> None:
    """Emit callbacks for all nodes in the interface node database.

    Must be called from a background thread while the TUI event loop is already
    running (i.e. after tui_app.run() has started), otherwise call_from_thread
    will silently drop the updates.
    """
    nodes: dict = getattr(iface, "nodes", None) or {}
    logger.info(f"[{source_tag}] fire_initial_nodes: {len(nodes)} node(s) in DB")
    for node_id, node in nodes.items():
        logger.info(f"[{source_tag}]   {node_id}  keys={list(node.keys())}")
        try:
            if on_nodeinfo and "user" in node:
                u = node["user"]
                on_nodeinfo(NodeInfo(
                    node_id=u.get("id", node_id),
                    long_name=u.get("longName", ""),
                    short_name=u.get("shortName", ""),
                ))
            if on_position and "position" in node:
                p = node["position"]
                lat_i = p.get("latitudeI", 0)
                lon_i = p.get("longitudeI", 0)
                if lat_i or lon_i:
                    on_position(Position(
                        lat=lat_i * 1e-7,
                        lon=lon_i * 1e-7,
                        alt=float(p.get("altitude", 0)),
                        speed=0.0,
                        course=0.0,
                        fix=True,
                        sats=p.get("satsInView", 0),
                        timestamp=datetime.now(UTC),
                    ))
            if on_telemetry and "deviceMetrics" in node:
                dm = node["deviceMetrics"]
                on_telemetry(DeviceMetrics(
                    battery_level=dm.get("batteryLevel", 0),
                    voltage=dm.get("voltage", 0.0),
                    uptime_seconds=dm.get("uptimeSeconds", 0),
                    channel_utilization=dm.get("channelUtilization", 0.0),
                    air_util_tx=dm.get("airUtilTx", 0.0),
                ))
        except Exception as e:
            logger.debug(f"[{source_tag}] initial node drain error {node_id}: {e}")


def _nid(node_int: int) -> str:
    return f"!{node_int:08x}"


def decode_packet(
    packet: dict,
    on_position: Callable | None,
    on_telemetry: Callable | None,
    on_nodeinfo: Callable | None,
    on_text: Callable | None,
    node_filter: str = "",
    source_tag: str = "",
) -> None:
    """Decode one meshtastic packet dict and call the appropriate callback."""
    from_int = packet.get("from", 0)
    from_id = _nid(from_int)

    if node_filter and node_filter != from_id:
        logger.debug(f"[{source_tag}] filtered: {from_id}")
        return

    decoded = packet.get("decoded", {})
    portnum = decoded.get("portnum", "")
    logger.info(f"[{source_tag}] rx {from_id}  portnum={portnum}")

    try:
        if portnum == "POSITION_APP" and on_position:
            _pos(decoded.get("position", {}), on_position, source_tag)
        elif portnum == "TELEMETRY_APP" and on_telemetry:
            _tel(decoded.get("telemetry", {}), on_telemetry)
        elif portnum == "NODEINFO_APP" and on_nodeinfo:
            _node(decoded.get("user", {}), from_id, on_nodeinfo)
        elif portnum == "TEXT_MESSAGE_APP" and on_text:
            _txt(decoded, packet, from_id, on_text)
    except Exception as e:
        logger.debug(f"[{source_tag}] decode error portnum={portnum}: {e}")


def _pos(p: dict, cb: Callable, tag: str) -> None:
    lat_i = p.get("latitudeI", 0)
    lon_i = p.get("longitudeI", 0)
    if not lat_i and not lon_i:
        return
    pos = Position(
        lat=lat_i * 1e-7,
        lon=lon_i * 1e-7,
        alt=float(p.get("altitude", 0)),
        speed=p.get("groundSpeed", 0) * 0.539957,  # m/s -> knots
        course=float(p.get("groundTrack", 0)),
        fix=True,
        sats=p.get("satsInView", 0),
        timestamp=datetime.now(UTC),
    )
    logger.info(f"[{tag}] POS lat={pos.lat:.5f} lon={pos.lon:.5f} alt={pos.alt}m sats={pos.sats}")
    cb(pos)


def _tel(tel: dict, cb: Callable) -> None:
    dm = tel.get("deviceMetrics", {})
    if not dm:
        return
    cb(DeviceMetrics(
        battery_level=dm.get("batteryLevel", 0),
        voltage=dm.get("voltage", 0.0),
        uptime_seconds=dm.get("uptimeSeconds", 0),
        channel_utilization=dm.get("channelUtilization", 0.0),
        air_util_tx=dm.get("airUtilTx", 0.0),
    ))


def _node(user: dict, from_id: str, cb: Callable) -> None:
    if not user:
        return
    cb(NodeInfo(
        node_id=user.get("id", from_id),
        long_name=user.get("longName", ""),
        short_name=user.get("shortName", ""),
    ))


def _txt(decoded: dict, packet: dict, from_id: str, cb: Callable) -> None:
    to_int = packet.get("to", 0xFFFFFFFF)
    to_id = "broadcast" if to_int == 0xFFFFFFFF else _nid(to_int)
    text = decoded.get("text", "")
    cb(TextMessage(from_id=from_id, to_id=to_id, text=text))
