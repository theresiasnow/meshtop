import argparse
from pathlib import Path

from rich.console import Console

from lorabridge.config import load_config

console = Console()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lorabridge",
        description="GPS bridge -- Wio Tracker to pi-star / APRS / gpsd / rigtop",
    )
    parser.add_argument("--source", choices=["serial", "lora"], help="Override source type")
    parser.add_argument("--port", help="Serial port (e.g. COM3 or /dev/ttyUSB0)")
    parser.add_argument("--config", default="lorabridge.toml", metavar="FILE")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    if args.source:
        cfg.source.type = args.source
    if args.port:
        cfg.source.port = args.port

    console.print(f"[bold green]lorabridge[/] starting — source=[cyan]{cfg.source.type}[/]")
    console.print("(not yet implemented — run in next session)")
