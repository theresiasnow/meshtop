"""Shared decoder for meshtastic SerialInterface / BLEInterface packets.

Both interfaces deliver packets as Python dicts (MessageToDict output) with
camelCase keys — unlike the MQTT source which works with raw protobufs.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from meshtop.position import Position
from meshtop.sources.meshtastic import DeviceMetrics, NodeInfo, TextMessage, TraceRoute


def fire_initial_nodes(
    iface: Any,
    on_position: Callable | None = None,
    on_nodeinfo: Callable | None = None,
    on_telemetry: Callable | None = None,
    source_tag: str = "",
    on_my_node_id: Callable[[str], None] | None = None,
) -> None:
    """Emit callbacks for all nodes in the interface node database.

    Must be called from a background thread while the TUI event loop is already
    running (i.e. after tui_app.run() has started), otherwise call_from_thread
    will silently drop the updates.
    """
    if on_my_node_id:
        try:
            my_num = getattr(getattr(iface, "localNode", None), "nodeNum", None) or getattr(
                getattr(iface, "myInfo", None), "myNodeNum", None
            )
            if my_num:
                on_my_node_id(f"!{my_num:08x}")
                logger.debug(f"[{source_tag}] local node id: !{my_num:08x}")
        except Exception as e:
            logger.debug(f"[{source_tag}] local node id error: {e}")
    nodes: dict = getattr(iface, "nodes", None) or {}
    logger.info(f"[{source_tag}] fire_initial_nodes: {len(nodes)} node(s) in DB")
    for node_id, node in nodes.items():
        logger.info(f"[{source_tag}]   {node_id}  keys={list(node.keys())}")
        try:
            if on_nodeinfo and "user" in node:
                u = node["user"]
                lh = node.get("lastHeard")
                raw_role = u.get("role", "")
                role = "" if raw_role == "CLIENT" else raw_role
                on_nodeinfo(
                    NodeInfo(
                        node_id=u.get("id", node_id),
                        long_name=u.get("longName", ""),
                        short_name=u.get("shortName", ""),
                        role=role,
                        snr=node.get("snr"),
                        hops_away=node.get("hopsAway"),
                        last_heard=datetime.fromtimestamp(lh, UTC) if lh else None,
                        battery_level=node.get("deviceMetrics", {}).get("batteryLevel"),
                        voltage=node.get("deviceMetrics", {}).get("voltage"),
                    )
                )
            if on_position and "position" in node:
                p = node["position"]
                lat_i = p.get("latitudeI", 0)
                lon_i = p.get("longitudeI", 0)
                if lat_i or lon_i:
                    on_position(
                        Position(
                            lat=lat_i * 1e-7,
                            lon=lon_i * 1e-7,
                            alt=float(p.get("altitude", 0)),
                            speed=0.0,
                            course=0.0,
                            fix=True,
                            sats=p.get("satsInView", 0),
                            timestamp=datetime.now(UTC),
                        )
                    )
            if on_telemetry and "deviceMetrics" in node:
                dm = node["deviceMetrics"]
                on_telemetry(
                    DeviceMetrics(
                        battery_level=dm.get("batteryLevel", 0),
                        voltage=dm.get("voltage", 0.0),
                        uptime_seconds=dm.get("uptimeSeconds", 0),
                        channel_utilization=dm.get("channelUtilization", 0.0),
                        air_util_tx=dm.get("airUtilTx", 0.0),
                    )
                )
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
    on_traceroute: Callable | None = None,
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
            _node(decoded.get("user", {}), from_id, packet, on_nodeinfo)
        elif portnum == "TEXT_MESSAGE_APP" and on_text:
            _txt(decoded, packet, from_id, on_text)
        elif portnum == "TRACEROUTE_APP" and on_traceroute:
            _trace(decoded, from_id, on_traceroute, source_tag)
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
    cb(
        DeviceMetrics(
            battery_level=dm.get("batteryLevel", 0),
            voltage=dm.get("voltage", 0.0),
            uptime_seconds=dm.get("uptimeSeconds", 0),
            channel_utilization=dm.get("channelUtilization", 0.0),
            air_util_tx=dm.get("airUtilTx", 0.0),
        )
    )


def _node(user: dict, from_id: str, packet: dict, cb: Callable) -> None:
    if not user:
        return
    hop_start = packet.get("hopStart", 0)
    hop_limit = packet.get("hopLimit", 0)
    hops_away = (hop_start - hop_limit) if hop_start else None
    raw_role = user.get("role", "")
    role = "" if raw_role == "CLIENT" else raw_role
    cb(
        NodeInfo(
            node_id=user.get("id", from_id),
            long_name=user.get("longName", ""),
            short_name=user.get("shortName", ""),
            role=role,
            snr=packet.get("rxSnr"),
            rssi=packet.get("rxRssi"),
            hops_away=hops_away,
            last_heard=datetime.now(UTC),
        )
    )


def _trace(decoded: dict, from_id: str, cb: Callable, tag: str) -> None:
    route_ints = decoded.get("routeDiscovery", {}).get("route", [])
    route = [_nid(n) for n in route_ints]
    hops = " → ".join(route) if route else "(direct)"
    logger.info(f"[{tag}] TRACE from {from_id}: {hops}")
    cb(TraceRoute(from_id=from_id, route=route))


def _txt(decoded: dict, packet: dict, from_id: str, cb: Callable) -> None:
    to_int = packet.get("to", 0xFFFFFFFF)
    to_id = "broadcast" if to_int == 0xFFFFFFFF else _nid(to_int)
    text = decoded.get("text", "")
    channel = str(packet.get("channel", 0))
    cb(TextMessage(from_id=from_id, to_id=to_id, text=text, channel=channel))
