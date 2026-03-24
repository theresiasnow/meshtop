import signal
import sys
import threading
import time
from pathlib import Path

import typer
from loguru import logger
from rich.console import Console

from meshtop.config import load_config
from meshtop.position import Position
from meshtop.sinks.aprs import AprsSink
from meshtop.sinks.gpsd import GpsdSink
from meshtop.sinks.nmea_server import NmeaServer
from meshtop.sinks.rigtop import RigtopSink
from meshtop.sources.meshtastic import DeviceMetrics, MeshtasticSource, NodeInfo, TextMessage

app = typer.Typer(help="GPS bridge -- Meshtastic device to pi-star / APRS / gpsd / rigtop")
console = Console()



def _friendly_error(exc: Exception) -> str:
    msg = str(exc)
    lmsg = msg.lower()
    if "not found" in lmsg or "no device" in lmsg or "unable to find" in lmsg:
        return "No Meshtastic device found. Is Bluetooth on and the device nearby?"
    if "bluetooth" in lmsg and ("not available" in lmsg or "not enabled" in lmsg):
        return "Bluetooth adapter not available or not enabled."
    if "could not open port" in lmsg or "no such file" in lmsg:
        return f"Serial port not found: {msg}"
    if "access is denied" in lmsg or "permission denied" in lmsg:
        return f"Permission denied — check device access: {msg}"
    if "timed out waiting for connection" in lmsg:
        return (
            "Serial handshake timed out. Check: device is awake, "
            "Serial Console is enabled (Meshtastic app → Module Config → Serial), "
            "and no other app holds the port."
        )
    if "timeout" in lmsg:
        return "Connection timed out. Is the device powered on and in range?"
    return f"{type(exc).__name__}: {msg}"


def _build_source(cfg, on_position, on_telemetry, on_nodeinfo, on_text, on_status):
    """Instantiate and return the configured source (lora/serial/ble)."""
    src_type = cfg.source.type

    if src_type == "lora":
        return MeshtasticSource(
            cfg.source.lora,
            on_position=on_position,
            on_telemetry=on_telemetry,
            on_nodeinfo=on_nodeinfo,
            on_text=on_text,
            on_mqtt_status=on_status,
        )
    if src_type == "serial":
        from meshtop.sources.serial import SerialSource
        return SerialSource(
            cfg.source,
            on_position=on_position,
            on_telemetry=on_telemetry,
            on_nodeinfo=on_nodeinfo,
            on_text=on_text,
            on_status=on_status,
        )
    if src_type == "ble":
        from meshtop.sources.ble import BleSource
        return BleSource(
            cfg.source,
            on_position=on_position,
            on_telemetry=on_telemetry,
            on_nodeinfo=on_nodeinfo,
            on_text=on_text,
            on_status=on_status,
        )
    raise ValueError(f"Unknown source type: {src_type}")


_OPT_CONFIG = typer.Option(
    Path("meshtop.toml"), "--config", "-c", metavar="FILE", help="Config file"
)
_OPT_SOURCE = typer.Option(None, "--source", "-s", help="Source type (serial|ble|lora)")
_OPT_PORT = typer.Option(None, "--port", "-p", help="Serial port (e.g. COM3)")
_OPT_BLE = typer.Option(None, "--ble-device", help="BLE device name or address")
_OPT_NOTUI = typer.Option(False, "--no-tui", help="Plain console output (no TUI)")
_OPT_DEBUG = typer.Option(False, "--debug", help="Enable debug logging")


@app.command()
def main(
    config: Path = _OPT_CONFIG,
    source: str | None = _OPT_SOURCE,
    port: str | None = _OPT_PORT,
    ble_device: str | None = _OPT_BLE,
    no_tui: bool = _OPT_NOTUI,
    debug: bool = _OPT_DEBUG,
) -> None:
    tui = not no_tui

    cfg = load_config(config)

    if tui:
        logger.remove()
        log_level = "DEBUG" if debug else "INFO"
        logger.add("meshtop.log", level=log_level, rotation="1 MB", retention=3)
    elif debug:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    if source:
        cfg.source.type = source  # type: ignore[assignment]
    if port:
        cfg.source.port = port
    if ble_device:
        cfg.source.ble.device = ble_device

    # Start sinks
    sinks = []
    aprs_sink: AprsSink | None = None
    nmea_server: NmeaServer | None = None
    gpsd_sink: GpsdSink | None = None
    rigtop_sink: RigtopSink | None = None

    if cfg.aprs.enabled:
        aprs_sink = AprsSink(cfg.aprs)
        aprs_sink.start()
        sinks.append(aprs_sink)

    if cfg.nmea_server.enabled:
        nmea_server = NmeaServer(cfg.nmea_server)
        nmea_server.start()
        sinks.append(nmea_server)

    if cfg.gpsd.enabled:
        gpsd_sink = GpsdSink(cfg.gpsd)
        gpsd_sink.start()
        sinks.append(gpsd_sink)

    if cfg.rigtop.enabled:
        rigtop_sink = RigtopSink(cfg.rigtop)
        rigtop_sink.start()
        sinks.append(rigtop_sink)

    def _dispatch_position(pos: Position) -> None:
        if aprs_sink:
            aprs_sink.send(pos)
        if nmea_server:
            nmea_server.send(pos)
        if gpsd_sink:
            gpsd_sink.send(pos)
        if rigtop_sink:
            rigtop_sink.send(pos)

    if tui:
        from meshtop.tui import LorabridgeApp

        tui_app = LorabridgeApp(
            cfg,
            aprs=aprs_sink,
            nmea=nmea_server,
            gpsd=gpsd_sink,
            rigtop=rigtop_sink,
            serial_port=cfg.source.port,
        )
        if aprs_sink:
            aprs_sink.on_beacon = tui_app.on_beacon_sent

        def on_position(pos: Position) -> None:
            _dispatch_position(pos)
            tui_app.on_position(pos)

        def on_telemetry(m: DeviceMetrics) -> None:
            tui_app.on_telemetry(m)

        def on_nodeinfo(n: NodeInfo) -> None:
            tui_app.on_nodeinfo(n)

        def on_text(m: TextMessage) -> None:
            tui_app.on_text(m)

        def on_status(connected: bool) -> None:
            tui_app.on_mqtt_status(connected)

        src_ref: list = [None]

        def _drain(src) -> None:
            """Fire nodeinfo/position/telemetry from the interface node DB.
            Must run from a background thread while the TUI event loop is live.
            """
            from meshtop.sources._mesh_decode import fire_initial_nodes
            if hasattr(src, "_iface") and src._iface:
                fire_initial_nodes(
                    src._iface,
                    on_position=on_position,
                    on_nodeinfo=on_nodeinfo,
                    on_telemetry=on_telemetry,
                    source_tag=cfg.source.type,
                    on_my_node_id=lambda nid: setattr(tui_app, "_local_node_id", nid),
                )

        def on_connect(source_type: str, device: str) -> str | None:
            if src_ref[0] is not None:
                src_ref[0].stop()
                src_ref[0] = None
            cfg.source.type = source_type  # type: ignore[assignment]
            if source_type == "ble":
                cfg.source.ble.device = device
            elif source_type == "serial":
                cfg.source.port = device
            new_src = _build_source(
                cfg, on_position, on_telemetry, on_nodeinfo, on_text, on_status
            )
            try:
                new_src.start()
            except Exception as exc:
                src_ref[0] = new_src
                return _friendly_error(exc)
            src_ref[0] = new_src
            _drain(new_src)
            return None

        def on_disconnect() -> None:
            if src_ref[0] is not None:
                src_ref[0].stop()
                src_ref[0] = None
            cfg.source.type = "none"  # type: ignore[assignment]
            on_status(False)

        tui_app._on_connect = on_connect  # type: ignore[attr-defined]
        tui_app._on_disconnect = on_disconnect  # type: ignore[attr-defined]

        if cfg.source.type != "none":
            src_ref[0] = _build_source(
                cfg, on_position, on_telemetry, on_nodeinfo, on_text, on_status
            )

            def _connect_source() -> None:
                """Start source in background so the TUI event loop is running first."""
                try:
                    src_ref[0].start()
                except Exception as exc:
                    err = _friendly_error(exc)
                    logger.warning(f"Source start failed: {exc}")
                    try:
                        tui_app.call_from_thread(
                            lambda: tui_app.notify(
                                err, title="Connection failed", severity="error", timeout=12
                            )
                        )
                    except Exception:
                        pass
                    return
                _drain(src_ref[0])

            threading.Thread(target=_connect_source, daemon=True, name="src-connect").start()

        # Suppress noisy shutdown traces from background threads (BLE asyncio loops,
        # meshtastic publish thread) that try to use the event loop after it closes.
        _orig_hook = threading.excepthook

        def _quiet_thread_hook(args: threading.ExceptHookArgs) -> None:
            msg = str(args.exc_value).lower()
            if args.exc_type is KeyboardInterrupt:
                return
            if args.exc_type is RuntimeError and (
                "event loop is closed" in msg or "already running" in msg
            ):
                return
            _orig_hook(args)

        threading.excepthook = _quiet_thread_hook

        try:
            tui_app.run()
        finally:
            threading.excepthook = _orig_hook
            if src_ref[0]:
                try:
                    src_ref[0].stop()
                except Exception:
                    pass
            for sink in sinks:
                try:
                    sink.stop()
                except Exception:
                    pass
            import os
            os._exit(0)

    else:
        console.print(f"[bold green]meshtop[/] starting — source=[cyan]{cfg.source.type}[/]")

        def on_position(pos: Position) -> None:  # type: ignore[misc]
            console.print(
                f"[green]POS[/]  lat={pos.lat:.5f} lon={pos.lon:.5f} alt={pos.alt}m sats={pos.sats}"
            )
            _dispatch_position(pos)

        def on_telemetry(m: DeviceMetrics) -> None:  # type: ignore[misc]
            console.print(
                f"[yellow]TEL[/]  battery={m.battery_level}%"
                f"  voltage={m.voltage:.2f}V  uptime={m.uptime_seconds}s"
            )

        def on_nodeinfo(n: NodeInfo) -> None:  # type: ignore[misc]
            console.print(f"[blue]NODE[/] {n.long_name} ({n.short_name})  id={n.node_id}")

        def on_text(m: TextMessage) -> None:  # type: ignore[misc]
            console.print(f"[magenta]TXT[/]  [{m.from_id} -> {m.to_id}]: {m.text}")

        def on_status(connected: bool) -> None:  # type: ignore[misc]
            pass

        src = _build_source(cfg, on_position, on_telemetry, on_nodeinfo, on_text, on_status)
        try:
            src.start()
        except Exception as exc:
            console.print(f"[bold red]Connection failed:[/] {_friendly_error(exc)}")
            raise typer.Exit(1) from exc

        def shutdown(sig, frame):
            console.print("\n[bold]Shutting down...[/]")
            src.stop()
            for sink in sinks:
                sink.stop()
            raise typer.Exit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        while True:
            time.sleep(1)
