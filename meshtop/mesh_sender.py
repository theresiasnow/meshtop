"""Send packets to the Meshtastic mesh.

Prefers the already-running BLE/serial interface (iface parameter) to avoid
opening a second connection. Falls back to TCP (device_host) or a fresh serial
connection when no live interface is available.
"""

from __future__ import annotations

from typing import Any

from meshtop.config import LoraSourceConfig


def _fallback_iface(cfg: LoraSourceConfig, serial_port: str):
    """Context-manager that yields a fresh send interface (TCP or serial)."""
    if cfg.device_host:
        from meshtastic.tcp_interface import TCPInterface

        return TCPInterface(cfg.device_host)
    if serial_port:
        from meshtastic.serial_interface import SerialInterface

        return SerialInterface(serial_port)
    raise ValueError(
        "No send interface — set source.lora.device_host (TCP) "
        "or use --port (serial) in meshtop.toml"
    )


def send_text(
    cfg: LoraSourceConfig,
    serial_port: str,
    dest: str,
    text: str,
    iface: Any = None,
    channel_index: int = 0,
) -> str:
    """Send a Meshtastic text message. Returns a status string."""
    if iface is not None:
        iface.sendText(text, destinationId=dest, channelIndex=channel_index)
        return f"Sent to {dest}"
    with _fallback_iface(cfg, serial_port) as i:
        i.sendText(text, destinationId=dest, channelIndex=channel_index)
    return f"Sent to {dest} via {'TCP' if cfg.device_host else 'serial'}"


def send_position(iface: Any, lat: float, lon: float, alt: float = 0, dest: str = "^all") -> None:
    """Send a position packet — to a specific node or broadcast to the mesh."""
    iface.sendPosition(lat, lon, int(alt), destinationId=dest, wantResponse=dest != "^all")


def send_user_info(iface: Any, dest: str) -> None:
    """Send local node's user info (name, short name) to a specific node."""
    from meshtastic import mesh_pb2, portnums_pb2

    local = iface.localNode
    node_num = iface.myInfo.my_node_num
    node_id = f"!{node_num:08x}"
    u = mesh_pb2.User()
    u.id = node_id
    if local.localConfig and hasattr(local, "nodeInfo") and local.nodeInfo:
        info = local.nodeInfo
        u.long_name = (
            getattr(info, "user", {}).get("longName", "")
            if isinstance(getattr(info, "user", None), dict)
            else getattr(getattr(info, "user", None), "longName", "")
        )
        u.short_name = (
            getattr(info, "user", {}).get("shortName", "")
            if isinstance(getattr(info, "user", None), dict)
            else getattr(getattr(info, "user", None), "shortName", "")
        )
    # Prefer the nodes dict which is always populated after connection
    node_entry = (iface.nodes or {}).get(node_id) or (iface.nodes or {}).get(node_num)
    if node_entry:
        user_data = node_entry.get("user", {})
        u.long_name = user_data.get("longName", u.long_name)
        u.short_name = user_data.get("shortName", u.short_name)
    iface.sendData(
        u.SerializeToString(),
        destinationId=dest,
        portNum=portnums_pb2.PortNum.NODEINFO_APP,
        wantAck=True,
        wantResponse=True,
    )


def send_traceroute(iface: Any, dest: str) -> None:
    """Send a traceroute request to dest (node ID like '!7a78e5e3')."""
    iface.sendTraceRoute(dest, hopLimit=7)
