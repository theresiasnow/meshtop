import sys
import signal
import time
from pathlib import Path
from typing import Optional

import typer
from loguru import logger
from rich.console import Console

from lorabridge.config import load_config
from lorabridge.position import Position
from lorabridge.sources.meshtastic import MeshtasticSource, DeviceMetrics, NodeInfo, TextMessage

app = typer.Typer(help="GPS bridge -- Wio Tracker to pi-star / APRS / gpsd / rigtop")
console = Console()


@app.command()
def main(
    config: Path = typer.Option(Path("lorabridge.toml"), "--config", "-c", metavar="FILE", help="Config file"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Override source type (serial|lora)"),
    port: Optional[str] = typer.Option(None, "--port", "-p", help="Serial port (e.g. COM3)"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
) -> None:
    if debug:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    cfg = load_config(config)
    if source:
        cfg.source.type = source  # type: ignore[assignment]
    if port:
        cfg.source.port = port

    console.print(f"[bold green]lorabridge[/] starting — source=[cyan]{cfg.source.type}[/]")

    def on_position(pos: Position) -> None:
        console.print(f"[green]POS[/]  lat={pos.lat:.5f}  lon={pos.lon:.5f}  alt={pos.alt}m  sats={pos.sats}")

    def on_telemetry(m: DeviceMetrics) -> None:
        console.print(f"[yellow]TEL[/]  battery={m.battery_level}%  voltage={m.voltage:.2f}V  uptime={m.uptime_seconds}s")

    def on_nodeinfo(n: NodeInfo) -> None:
        console.print(f"[blue]NODE[/] {n.long_name} ({n.short_name})  id={n.node_id}")

    def on_text(m: TextMessage) -> None:
        console.print(f"[magenta]TXT[/]  [{m.from_id} -> {m.to_id}]: {m.text}")

    if cfg.source.type == "lora":
        src = MeshtasticSource(
            cfg.source.lora,
            on_position=on_position,
            on_telemetry=on_telemetry,
            on_nodeinfo=on_nodeinfo,
            on_text=on_text,
        )
        src.start()
    else:
        console.print("[red]Serial source not yet implemented[/]")
        raise typer.Exit(1)

    def shutdown(sig, frame):
        console.print("\n[bold]Shutting down...[/]")
        src.stop()
        raise typer.Exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    while True:
        time.sleep(1)
