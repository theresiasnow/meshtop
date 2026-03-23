"""Full-screen TUI dashboard using Textual."""

from __future__ import annotations

import asyncio
import threading
import time as _time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import Header, Input, Label, ListItem, ListView, RichLog, Static

from lorabridge.position import Position
from lorabridge.sources.meshtastic import DeviceMetrics, NodeInfo, TextMessage

if TYPE_CHECKING:
    from lorabridge.config import Config
    from lorabridge.sinks.aprs import AprsSink
    from lorabridge.sinks.gpsd import GpsdSink
    from lorabridge.sinks.nmea_server import NmeaServer
    from lorabridge.sinks.rigtop import RigtopSink


# ── Panel widgets ─────────────────────────────────────────────────────────────


class PositionPanel(Static):
    DEFAULT_CSS = (
        "PositionPanel { border: round $primary; padding: 0 1; height: 100%; overflow-y: auto; }"
    )

    def on_mount(self) -> None:
        self.border_title = "Position"
        self.render_data(None)

    def render_data(self, pos: Position | None) -> None:
        COL, M = 9, " "
        txt = Text()

        def lbl(text: str) -> None:
            txt.append(f"{M}{text:<{COL - 1}} ", style="dim")

        if pos is None:
            txt.append(f"{M}No fix\n", style="dim")
        else:
            lbl("Fix")
            style = "bold green" if pos.fix else "yellow"
            txt.append("● YES\n" if pos.fix else "○ NO\n", style=style)
            lbl("Lat")
            txt.append(f"{pos.lat:.6f}\n", style="bold white")
            lbl("Lon")
            txt.append(f"{pos.lon:.6f}\n", style="bold white")
            lbl("Alt")
            txt.append(f"{pos.alt:.0f} m\n")
            lbl("Speed")
            txt.append(f"{pos.speed * 1.852:.1f} km/h\n")
            lbl("Course")
            txt.append(f"{pos.course:.0f}°\n")
            lbl("Sats")
            txt.append(f"{pos.sats}\n", style="bold green" if pos.sats >= 4 else "yellow")
            lbl("Updated")
            txt.append(pos.timestamp.strftime("%H:%M:%S"), style="dim")

        self.update(txt)


class TelemetryPanel(Static):
    DEFAULT_CSS = (
        "TelemetryPanel { border: round $accent; padding: 0 1; height: 100%; overflow-y: auto; }"
    )

    def on_mount(self) -> None:
        self.border_title = "Telemetry"
        self.render_data(None)

    def render_data(self, m: DeviceMetrics | None) -> None:
        COL, M = 9, " "
        txt = Text()

        def lbl(text: str) -> None:
            txt.append(f"{M}{text:<{COL - 1}} ", style="dim")

        if m is None:
            txt.append(f"{M}—\n", style="dim")
        else:
            lbl("Battery")
            bar_w = 12
            filled = int(m.battery_level / 100 * bar_w)
            bar = "█" * filled + "░" * (bar_w - filled)
            if m.battery_level >= 50:
                bstyle = "bold green"
            elif m.battery_level >= 20:
                bstyle = "yellow"
            else:
                bstyle = "bold red"
            txt.append(f"{m.battery_level}%  ", style=bstyle)
            txt.append(bar + "\n", style=bstyle)
            lbl("Voltage")
            txt.append(f"{m.voltage:.2f} V\n", style="bold")
            lbl("Uptime")
            h, rem = divmod(m.uptime_seconds, 3600)
            mm, s = divmod(rem, 60)
            txt.append(f"{h:02d}:{mm:02d}:{s:02d}\n", style="dim")
            lbl("Ch util")
            txt.append(f"{m.channel_utilization:.1f}%\n", style="dim")
            lbl("Air TX")
            txt.append(f"{m.air_util_tx:.1f}%\n", style="dim")

        self.update(txt)


class NodePanel(Static):
    DEFAULT_CSS = (
        "NodePanel { border: round $surface; padding: 0 1; height: 100%; overflow-y: auto; }"
    )

    def on_mount(self) -> None:
        self.border_title = "Node"
        self.render_data(None)

    def render_data(self, n: NodeInfo | None) -> None:
        COL, M = 7, " "
        txt = Text()

        def lbl(text: str) -> None:
            txt.append(f"{M}{text:<{COL - 1}} ", style="dim")

        if n is None:
            txt.append(f"{M}—\n", style="dim")
        else:
            lbl("Name")
            txt.append(f"{n.long_name}\n", style="bold cyan")
            lbl("Short")
            txt.append(f"{n.short_name}\n", style="cyan")
            lbl("ID")
            txt.append(f"{n.node_id}\n", style="dim")

        self.update(txt)


class NodesPanel(Static):
    DEFAULT_CSS = (
        "NodesPanel { border: round $surface; padding: 0 1; height: 6; overflow-y: auto; }"
    )

    def on_mount(self) -> None:
        self.border_title = "Nodes heard"
        self.render_data({})

    def render_data(self, nodes: dict[str, NodeInfo]) -> None:
        txt = Text()
        if not nodes:
            txt.append(" (none yet)", style="dim")
        else:
            for nid, n in list(nodes.items())[-6:]:  # show latest 6
                txt.append(f" {n.long_name:<12}", style="bold cyan")
                txt.append(f"  {n.short_name:<6}", style="cyan")
                txt.append(f"  {nid}\n", style="dim")
        self.update(txt)


class SinksPanel(Static):
    DEFAULT_CSS = "SinksPanel { border: round $surface; padding: 0 1; height: 7; }"

    def on_mount(self) -> None:
        self.border_title = "Connections"

    def render_data(
        self,
        src_connected: bool,
        src_type: str,
        src_detail: str,
        aprs: AprsSink | None,
        nmea: NmeaServer | None,
        gpsd: GpsdSink | None,
        rigtop: RigtopSink | None,
        beacon_count: int,
        beacon_enabled: bool,
    ) -> None:
        txt = Text()

        def row(active: bool, name: str, kind: str, status: str, extra: str = "") -> None:
            icon = "●" if active else "○"
            colour = "green" if active else "dim red"
            txt.append(f" {icon} ", style=colour)
            txt.append(f"{name:<12}", style="bold" if active else "dim")
            txt.append(f"  [{kind:<6}]  ", style="dim")
            txt.append(f"{status:<12}", style=colour)
            if extra:
                txt.append(extra, style="dim")
            txt.append("\n")

        _SRC_LABELS = {"lora": "MQTT", "serial": "USB serial", "ble": "Bluetooth"}
        _SRC_KINDS  = {"lora": "mqtt",  "serial": "usb",        "ble": "ble"}
        src_label = _SRC_LABELS.get(src_type, src_type.upper())
        src_kind  = _SRC_KINDS.get(src_type, src_type)
        src_status = "receiving" if src_connected else "connecting"
        row(src_connected, src_label, src_kind, src_status, f"  {src_detail}")

        if aprs is not None:
            extra = ""
            if aprs.connected and aprs.last_beacon > 0:
                ago = int(_time.monotonic() - aprs.last_beacon)
                extra = f"  beacon {ago}s ago  ({beacon_count} sent)"
            if not beacon_enabled and aprs.connected:
                extra += "  [beacon OFF]"
            status = "connected" if aprs.connected else "offline"
            row(aprs.connected, "APRS-IS", "tcp", status, extra)

        if nmea is not None:
            nc = nmea.client_count
            row(True, "NMEA srv", "tcp", "listening",
                f"  {nc} client{'s' if nc != 1 else ''}  :10110")

        if gpsd is not None:
            nc = gpsd.client_count
            row(True, "gpsd", "tcp", "listening", f"  {nc} client{'s' if nc != 1 else ''}  :2947")

        if rigtop is not None:
            nc = rigtop._server.client_count
            row(True, "rigtop", "tcp", "listening",
                f"  {nc} client{'s' if nc != 1 else ''}  :10111")

        self.update(txt)


# ── BLE device picker ─────────────────────────────────────────────────────────


class BlePickerScreen(ModalScreen):
    """Modal that scans for nearby BLE devices and returns the chosen address."""

    CSS = """
    BlePickerScreen { align: center middle; }
    #ble-dialog {
        width: 66;
        height: auto;
        max-height: 24;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #ble-title  { text-align: center; text-style: bold; color: $accent; margin-bottom: 1; }
    #ble-status { text-align: center; color: $text-muted; margin-bottom: 1; }
    #ble-list   { height: auto; max-height: 14; border: round $primary; }
    #ble-hint   { text-align: center; color: $text-disabled; margin-top: 1; }
    """

    BINDINGS: ClassVar[list] = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self) -> None:
        super().__init__()
        self._devices: list = []

    def compose(self) -> ComposeResult:
        with Vertical(id="ble-dialog"):
            yield Label("Bluetooth Device Scan", id="ble-title")
            yield Label("Starting scan…", id="ble-status")
            yield ListView(id="ble-list")
            yield Label("↑↓ navigate   Enter select   Esc cancel", id="ble-hint")

    async def on_mount(self) -> None:
        asyncio.get_event_loop().create_task(self._scan())

    async def _scan(self) -> None:
        status = self.query_one("#ble-status", Label)
        status.update("Scanning for Meshtastic devices… (5 s)")
        try:
            from meshtastic.ble_interface import BLEInterface
            loop = asyncio.get_event_loop()
            devices = await loop.run_in_executor(None, BLEInterface.scan)
        except Exception as e:
            status.update(f"[red]Scan error:[/] {e}")
            return

        self._devices = sorted(devices, key=lambda d: d.name or "\xff")
        lv = self.query_one("#ble-list", ListView)
        if not self._devices:
            status.update("[yellow]No devices found nearby[/]")
            return

        for i, dev in enumerate(self._devices):
            name = dev.name or "(unnamed)"
            lv.append(ListItem(Label(f"  {name:<26}  {dev.address}"), id=f"ble-{i}"))

        count = len(self._devices)
        status.update(f"Found {count} device{'s' if count != 1 else ''}")
        lv.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id is None:
            return
        idx = int(event.item.id.split("-")[1])
        self.dismiss(self._devices[idx].address)


# ── Serial port picker ────────────────────────────────────────────────────────


class SerialPickerScreen(ModalScreen):
    """Modal that lists available serial ports and returns the chosen device path."""

    CSS = """
    SerialPickerScreen { align: center middle; }
    #serial-dialog {
        width: 66;
        height: auto;
        max-height: 24;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #serial-title  { text-align: center; text-style: bold; color: $accent; margin-bottom: 1; }
    #serial-status { text-align: center; color: $text-muted; margin-bottom: 1; }
    #serial-list   { height: auto; max-height: 14; border: round $primary; }
    #serial-hint   { text-align: center; color: $text-disabled; margin-top: 1; }
    """

    BINDINGS: ClassVar[list] = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self) -> None:
        super().__init__()
        self._ports: list = []

    def compose(self) -> ComposeResult:
        with Vertical(id="serial-dialog"):
            yield Label("Select Serial Port", id="serial-title")
            yield Label("", id="serial-status")
            yield ListView(id="serial-list")
            yield Label("↑↓ navigate   Enter select   Esc cancel", id="serial-hint")

    def on_mount(self) -> None:
        self._populate()

    def _populate(self) -> None:
        try:
            from serial.tools.list_ports import comports
            ports = sorted(comports(), key=lambda p: p.device)
        except Exception as e:
            self.query_one("#serial-status", Label).update(f"[red]Error:[/] {e}")
            return

        lv = self.query_one("#serial-list", ListView)
        status = self.query_one("#serial-status", Label)

        if not ports:
            status.update("[yellow]No serial ports found[/]")
            return

        self._ports = ports
        for i, port in enumerate(ports):
            desc = port.description if port.description != port.device else ""
            label = f"  {port.device:<12}  {desc}" if desc else f"  {port.device}"
            lv.append(ListItem(Label(label), id=f"port-{i}"))

        count = len(ports)
        status.update(f"Found {count} port{'s' if count != 1 else ''}")
        lv.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id is None:
            return
        idx = int(event.item.id.split("-")[1])
        self.dismiss(self._ports[idx].device)


# ── Command completion ────────────────────────────────────────────────────────


class CommandSuggester(Suggester):
    _COMMANDS: ClassVar[dict[str, list[str]]] = {
        "msg": ["<NODE_ID|^all> <text>"],
        "send": ["<NODE_ID|^all> <text>"],
        "beacon": ["on", "off"],
        "ble": ["on", "off"],
        "serial": ["on", "off"],
        "pos": [],
        "node": [],
        "help": [],
        "q": [],
        "quit": [],
    }

    def __init__(self) -> None:
        super().__init__(use_cache=False, case_sensitive=False)

    async def get_suggestion(self, value: str) -> str | None:
        if not value:
            return None
        parts = value.split()
        if len(parts) == 1 and not value.endswith(" "):
            prefix = parts[0].lower()
            for cmd in sorted(self._COMMANDS):
                if cmd.startswith(prefix) and cmd != prefix:
                    return cmd
            return None
        cmd = parts[0].lower()
        candidates = self._COMMANDS.get(cmd, [])
        if not candidates:
            return None
        arg_prefix = parts[1] if len(parts) > 1 and not value.endswith(" ") else ""
        for arg in candidates:
            if arg.lower().startswith(arg_prefix.lower()):
                full = f"{parts[0]} {arg}"
                return full if full.lower() != value.lower().rstrip() else None
        return None


# ── Main app ──────────────────────────────────────────────────────────────────


class LorabridgeApp(App[None]):
    CSS = """
    Screen { layout: vertical; overflow: hidden hidden; }
    #top-row { height: 12; }
    PositionPanel { width: 2fr; }
    TelemetryPanel { width: 2fr; }
    NodePanel { width: 1fr; }
    #event-log { height: 1fr; border: round $surface; }
    #msg-log   { height: 5;   border: round yellow; }
    #cmd-bar {
        height: 3;
        border: tall $accent;
        background: $panel;
    }
    #cmd-prompt {
        width: auto;
        padding: 0 1;
        color: $accent;
        content-align: left middle;
    }
    #cmd-input {
        width: 1fr;
        border: none;
        background: $panel;
    }
    """

    BINDINGS: ClassVar[list] = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("escape", "clear_input", "Clear", show=False),
        Binding("f1", "show_help", "Help"),
    ]

    # ── Thread-safe messages ───────────────────────────────────────────────────

    class PositionReceived(Message):
        def __init__(self, pos: Position) -> None:
            super().__init__()
            self.pos = pos

    class TelemetryReceived(Message):
        def __init__(self, m: DeviceMetrics) -> None:
            super().__init__()
            self.m = m

    class NodeInfoReceived(Message):
        def __init__(self, n: NodeInfo) -> None:
            super().__init__()
            self.n = n

    class TextReceived(Message):
        def __init__(self, m: TextMessage) -> None:
            super().__init__()
            self.m = m

    class SourceStatus(Message):
        def __init__(self, connected: bool) -> None:
            super().__init__()
            self.connected = connected

    class BeaconSent(Message):
        pass

    def __init__(
        self,
        cfg: Config,
        aprs: AprsSink | None = None,
        nmea: NmeaServer | None = None,
        gpsd: GpsdSink | None = None,
        rigtop: RigtopSink | None = None,
        serial_port: str = "",
    ) -> None:
        super().__init__()
        self._cfg = cfg
        self._aprs = aprs
        self._nmea = nmea
        self._gpsd = gpsd
        self._rigtop = rigtop
        self._serial_port = serial_port
        self._src_connected = False
        self._beacon_count = 0
        self._beacon_enabled = True
        self._last_pos: Position | None = None
        self._last_node: NodeInfo | None = None
        # node_id -> NodeInfo, insertion order = heard order
        self._mesh_nodes: dict[str, NodeInfo] = {}
        # Set from cli.py after construction: (source_type, device) -> error_str | None
        self._on_connect: Callable[[str, str], str | None] | None = None
        self._on_disconnect: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="top-row"):
            yield PositionPanel(id="pos-panel")
            yield TelemetryPanel(id="tel-panel")
            yield NodePanel(id="node-panel")
        yield SinksPanel(id="sinks-panel")
        yield NodesPanel(id="nodes-panel")
        yield RichLog(id="event-log", highlight=True, markup=True)
        yield RichLog(id="msg-log", highlight=True, markup=True)
        with Horizontal(id="cmd-bar"):
            yield Label("❯ ", id="cmd-prompt")
            yield Input(
                placeholder="ble  •  serial  •  msg <NODE_ID> <text>  •  beacon on/off  •  pos",
                id="cmd-input",
                suggester=CommandSuggester(),
            )

    def on_mount(self) -> None:
        self.title = "lorabridge"
        _mode_map = {"lora": "MQTT", "serial": "USB", "ble": "BLE"}
        _mode = _mode_map.get(self._cfg.source.type, self._cfg.source.type.upper())
        self.sub_title = f"{self._cfg.aprs.callsign}  [{_mode}]"
        self.query_one("#msg-log", RichLog).border_title = "Messages"
        self.query_one("#event-log", RichLog).border_title = "Events"
        self.set_interval(1.0, self._tick)
        self._refresh_sinks()
        self.call_after_refresh(self.query_one("#cmd-input", Input).focus)

    def action_clear_input(self) -> None:
        inp = self.query_one("#cmd-input", Input)
        inp.value = ""

    def action_show_help(self) -> None:
        self._cmd_help()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.value = ""
        if raw:
            self.execute_command(raw)

    # ── Periodic refresh ──────────────────────────────────────────────────────

    def _tick(self) -> None:
        self._refresh_sinks()

    def _refresh_sinks(self) -> None:
        src_type = self._cfg.source.type
        if src_type == "lora":
            src_detail = self._cfg.source.lora.topic
            encrypted = any(ch.encrypted for ch in self._cfg.source.lora.channels.values())
            if encrypted:
                src_detail += "  [enc]"
        elif src_type == "ble":
            src_detail = self._cfg.source.ble.device or "auto"
        else:
            src_detail = self._cfg.source.port

        self.query_one("#sinks-panel", SinksPanel).render_data(
            src_connected=self._src_connected,
            src_type=src_type,
            src_detail=src_detail,
            aprs=self._aprs,
            nmea=self._nmea,
            gpsd=self._gpsd,
            rigtop=self._rigtop,
            beacon_count=self._beacon_count,
            beacon_enabled=self._beacon_enabled,
        )

    # ── Thread-safe callbacks (post non-blocking messages to the event loop) ──

    def on_position(self, pos: Position) -> None:
        self.post_message(LorabridgeApp.PositionReceived(pos))

    def on_telemetry(self, m: DeviceMetrics) -> None:
        self.post_message(LorabridgeApp.TelemetryReceived(m))

    def on_nodeinfo(self, n: NodeInfo) -> None:
        self.post_message(LorabridgeApp.NodeInfoReceived(n))

    def on_text(self, m: TextMessage) -> None:
        self.post_message(LorabridgeApp.TextReceived(m))

    def on_mqtt_status(self, connected: bool) -> None:
        self.post_message(LorabridgeApp.SourceStatus(connected))

    def on_beacon_sent(self) -> None:
        self.post_message(LorabridgeApp.BeaconSent())

    # ── Message handlers (run on the event loop) ──────────────────────────────

    def on_lorabridge_app_position_received(self, msg: PositionReceived) -> None:
        self._handle_position(msg.pos)

    def on_lorabridge_app_telemetry_received(self, msg: TelemetryReceived) -> None:
        self._handle_telemetry(msg.m)

    def on_lorabridge_app_node_info_received(self, msg: NodeInfoReceived) -> None:
        self._handle_nodeinfo(msg.n)

    def on_lorabridge_app_text_received(self, msg: TextReceived) -> None:
        self._handle_text(msg.m)

    def on_lorabridge_app_source_status(self, msg: SourceStatus) -> None:
        self._set_src_connected(msg.connected)

    def on_lorabridge_app_beacon_sent(self, msg: BeaconSent) -> None:
        self._inc_beacon()

    # ── Main-thread handlers ──────────────────────────────────────────────────

    def _handle_position(self, pos: Position) -> None:
        self._last_pos = pos
        self.query_one("#pos-panel", PositionPanel).render_data(pos)
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        fix = "●" if pos.fix else "○"
        self.query_one("#event-log", RichLog).write(
            f"[dim]{ts}[/]  [green]{fix} POS[/]  "
            f"lat={pos.lat:.5f}  lon={pos.lon:.5f}  alt={pos.alt:.0f}m  sats={pos.sats}"
        )

    def _handle_telemetry(self, m: DeviceMetrics) -> None:
        self.query_one("#tel-panel", TelemetryPanel).render_data(m)
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        self.query_one("#event-log", RichLog).write(
            f"[dim]{ts}[/]  [yellow]TEL[/]  "
            f"bat={m.battery_level}%  {m.voltage:.2f}V  up={m.uptime_seconds}s"
        )

    def _handle_nodeinfo(self, n: NodeInfo) -> None:
        self._last_node = n
        self._mesh_nodes[n.node_id] = n  # upsert, preserves insertion order on update
        self.query_one("#node-panel", NodePanel).render_data(n)
        self.query_one("#nodes-panel", NodesPanel).render_data(self._mesh_nodes)
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        self.query_one("#event-log", RichLog).write(
            f"[dim]{ts}[/]  [blue]NODE[/]  {n.long_name} ({n.short_name})  {n.node_id}"
        )

    def _handle_text(self, m: TextMessage) -> None:
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        self.query_one("#msg-log", RichLog).write(
            f"[dim]{ts}[/]  [magenta]{m.from_id}[/] [dim]->[/] [cyan]{m.to_id}[/]\n  {m.text}"
        )
        self.query_one("#event-log", RichLog).write(
            f"[dim]{ts}[/]  [magenta]TXT[/]  {m.from_id}: {m.text[:60]}"
        )

    def _set_src_connected(self, connected: bool) -> None:
        self._src_connected = connected
        self._refresh_sinks()

    def _inc_beacon(self) -> None:
        self._beacon_count += 1
        self._refresh_sinks()

    # ── Command execution ─────────────────────────────────────────────────────

    def execute_command(self, raw: str) -> None:
        parts = raw.strip().split()
        if not parts:
            return
        cmd, args = parts[0].lower(), parts[1:]
        dispatch = {
            "msg": self._cmd_msg,
            "send": self._cmd_msg,
            "beacon": self._cmd_beacon,
            "ble": self._cmd_ble,
            "serial": self._cmd_serial,
            "pos": lambda _: self._cmd_pos(),
            "node": lambda _: self._cmd_node(),
            "help": lambda _: self._cmd_help(),
            "q": lambda _: self.exit(),
            "quit": lambda _: self.exit(),
        }
        fn = dispatch.get(cmd)
        if fn:
            fn(args)
        else:
            self.notify(f"Unknown command: {cmd}  (type help)", severity="warning")

    def _cmd_msg(self, args: list[str]) -> None:
        if len(args) < 2:
            self.notify("Usage: msg <NODE_ID|^all> <text>", severity="warning")
            return
        dest, text = args[0], " ".join(args[1:])

        def _send() -> None:
            try:
                from lorabridge.mesh_sender import send_text

                result = send_text(self._cfg.source.lora, self._serial_port, dest, text)
                ts = datetime.now(UTC).strftime("%H:%M:%S")
                self.call_from_thread(
                    self.query_one("#msg-log", RichLog).write,
                    f"[dim]{ts}[/]  [cyan]TX[/] [dim]->[/] [magenta]{dest}[/]\n  {text}",
                )
                self.call_from_thread(self.notify, result)
            except Exception as e:
                self.call_from_thread(self.notify, str(e), "Send failed", "error")

        threading.Thread(target=_send, daemon=True).start()
        self.notify(f"Sending to {dest}…")

    def _cmd_beacon(self, args: list[str]) -> None:
        if not self._aprs:
            self.notify("APRS not configured", severity="warning")
            return
        if not args:
            state = "ON" if self._beacon_enabled else "OFF"
            self.notify(f"Beacon: {state}")
            return
        action = args[0].lower()
        if action == "on":
            self._beacon_enabled = True
            if self._aprs:
                self._aprs.beacon_enabled = True
            self._refresh_sinks()
            self.notify("Beacon ON — position will be transmitted", title="APRS")
        elif action == "off":
            self._beacon_enabled = False
            if self._aprs:
                self._aprs.beacon_enabled = False
            self._refresh_sinks()
            self.notify("Beacon OFF — position NOT transmitted", title="APRS")
        else:
            self.notify("Usage: beacon [on|off]", severity="warning")

    def _cmd_pos(self) -> None:
        pos = self._last_pos
        if pos is None:
            self.notify("No position data yet", severity="warning")
            return
        fix = "fix" if pos.fix else "no fix"
        self.notify(
            f"lat={pos.lat:.6f}  lon={pos.lon:.6f}  alt={pos.alt:.0f}m  "
            f"sats={pos.sats}  {fix}",
            title="Position",
            timeout=6,
        )

    def _cmd_node(self) -> None:
        if not self._mesh_nodes:
            self.notify("No nodes heard yet", severity="warning")
            return
        lines = [f"{n.long_name} ({n.short_name})  {nid}" for nid, n in self._mesh_nodes.items()]
        self.notify("\n".join(lines), title=f"Nodes ({len(self._mesh_nodes)})", timeout=8)

    def _cmd_ble(self, args: list[str]) -> None:
        action = args[0].lower() if args else "on"
        if action == "off":
            if self._on_disconnect is None:
                self.notify("Not connected", severity="warning")
                return
            def _do_off() -> None:
                self._on_disconnect()
                self.call_from_thread(lambda: self.notify("Bluetooth disconnected", title="BLE"))
            threading.Thread(target=_do_off, daemon=True).start()
            return
        # on / no arg → picker
        def _on_pick(addr: str | None) -> None:
            if addr is None:
                return
            if self._on_connect is None:
                self.notify(f"Device address: {addr}", title="BLE")
                return
            self.notify(f"Connecting to {addr}…", title="BLE", timeout=15)

            def _do() -> None:
                err = self._on_connect("ble", addr)
                if err:
                    self.call_from_thread(
                        lambda: self.notify(err, title="BLE connect failed", severity="error")
                    )
                else:
                    self.call_from_thread(
                        lambda: self.notify(f"Connected to {addr}", title="BLE")
                    )

            threading.Thread(target=_do, daemon=True).start()

        self.push_screen(BlePickerScreen(), _on_pick)

    def _cmd_serial(self, args: list[str]) -> None:
        action = args[0].lower() if args else "on"
        if action == "off":
            if self._on_disconnect is None:
                self.notify("Not connected", severity="warning")
                return
            def _do_off() -> None:
                self._on_disconnect()
                self.call_from_thread(lambda: self.notify("Serial disconnected", title="Serial"))
            threading.Thread(target=_do_off, daemon=True).start()
            return
        # on / no arg → picker
        def _on_pick(port: str | None) -> None:
            if port is None:
                return
            if self._on_connect is None:
                self.notify(f"Port: {port}", title="Serial")
                return
            self.notify(f"Connecting to {port}…", title="Serial")

            def _do() -> None:
                err = self._on_connect("serial", port)
                if err:
                    self.call_from_thread(
                        lambda: self.notify(err, title="Serial connect failed", severity="error")
                    )
                else:
                    self.call_from_thread(
                        lambda: self.notify(f"Connected to {port}", title="Serial")
                    )

            threading.Thread(target=_do, daemon=True).start()

        self.push_screen(SerialPickerScreen(), _on_pick)

    def _cmd_help(self) -> None:
        cmds = (
            "ble on  —  scan and connect via Bluetooth",
            "ble off  —  disconnect Bluetooth",
            "serial on  —  pick and connect via USB serial",
            "serial off  —  disconnect serial",
            "msg <NODE_ID|^all> <text>  —  send Meshtastic message",
            "send  (alias for msg)",
            "beacon on|off  —  toggle APRS beaconing",
            "pos  —  show current position",
            "node  —  list heard nodes",
            "help  —  this message",
            "q / quit  —  exit",
        )
        self.notify("\n".join(cmds), title="Commands", timeout=10)
