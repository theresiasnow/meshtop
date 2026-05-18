---
name: radio-mesh-integration
description: Design spec for extending meshtop with Direwolf/TNC APRS-RF, JS8Call, rigctld, and message bridge
metadata:
  type: project
---

# Radio/Mesh Integration Design

**Date:** 2026-05-18  
**Status:** Implemented

## Context

meshtop is a GPS bridge and Meshtastic TUI. This feature extends it with two-way RF radio integration alongside the existing Meshtastic mesh connection:

- **Direwolf / KISS TNC** — full two-way APRS over RF (positions + messages)
- **JS8Call** — two-way weak-signal text messages and position sharing via JS8 digital mode
- **rigctld** — read-only transceiver status monitoring (frequency, mode, signal strength)
- **MessageBridge** — configurable bidirectional message routing between mesh and radio with loop prevention

## Architecture

The existing source/sink/TUI structure is unchanged. New additions are layered on top:

```
Direwolf (KISS TCP) ──► AprsTncSource ──┐
JS8Call (TCP API)   ──► Js8CallSource ──┼──► on_message/on_position callbacks ──► TUI
                                         │         │
                                         │    MessageBridge ──► routes back to sources' send_*()
                                         │
                                         └──► TUI (source tags [MESH]/[APRS]/[JS8])

rigctld (TCP)       ──► RigctldMonitor ──► on_radio_status ──► TUI RadioPanel
```

## New Files

| File | Purpose |
|---|---|
| `meshtop/sources/aprs_tnc.py` | KISS TCP client; APRS decode/encode; `send_message()`, `send_position()` |
| `meshtop/sources/js8call.py` | JS8Call TCP API; inbox poll; Maidenhead decode; `send_message()`, `send_position()` |
| `meshtop/monitors/__init__.py` | Package init |
| `meshtop/monitors/rigctld.py` | rigctld TCP poll; `RadioStatus` dataclass; `on_radio_status` callback |
| `meshtop/bridge.py` | `MessageBridge` — routing rules + loop prevention |
| `tests/test_bridge.py` | Bridge routing and loop prevention tests |
| `tests/test_aprs_tnc.py` | KISS framing and APRS position format tests |
| `tests/test_js8call.py` | Maidenhead decode and `@GRID` regex tests |

## Modified Files

| File | Change |
|---|---|
| `meshtop/sources/meshtastic.py` | Added `source_type: str = "mesh"` to `TextMessage` and `NodeInfo` |
| `meshtop/config.py` | Added `TncSourceConfig`, `Js8CallSourceConfig`, `RigctldConfig`, `BridgeConfig` models |
| `meshtop/cli.py` | Instantiates new sources/monitor/bridge; wires callbacks; starts/stops in lifecycle |
| `meshtop/tui.py` | `RadioPanel`; source tags in MessagesPanel; SinksPanel TNC/JS8Call rows; NodesPanel (RF)/(JS8) tags |
| `pyproject.toml` | Added `aprslib>=0.7`, `maidenhead>=1.0` |
| `meshtop.example.toml` | Added `[tnc]`, `[js8call]`, `[radio]`, `[bridge]` sections |

## Key Design Decisions

**KISS framing inline:** Implemented ~40 lines in `aprs_tnc.py` rather than adding a `kiss3` library dependency. KISS is simple enough to implement correctly.

**`source_type` on dataclasses:** Adding this field to `TextMessage` and `NodeInfo` is backwards-compatible (default `"mesh"`). Enables source tagging in TUI without breaking existing callsites.

**Loop prevention:** The bridge uses a `set` of `(from_id, text[:32], minute_bucket)` tuples. Same message in the same minute window is only forwarded once. Stale keys (>1 min old) are pruned on each call.

**rigctld as monitor not source:** rigctld is read-only (status display only). It doesn't produce `Position` or `TextMessage` objects so it belongs in `monitors/` not `sources/`.

## Config

```toml
[tnc]
enabled = false
host = "localhost"
port = 8001           # Direwolf KISSPORT
callsign = "N0CALL"
ssid = 9
beacon_interval = 600

[js8call]
enabled = false
host = "localhost"
port = 2237
callsign = "N0CALL"
poll_interval = 10

[radio]
enabled = false
host = "localhost"
port = 4532
poll_interval = 5

[bridge]
mesh_to_aprs = false
mesh_to_js8call = false
aprs_to_mesh = false
js8call_to_mesh = false
```

## Verification

```bash
uv run ruff check meshtop/    # all clear
uv run --no-sync python -m pytest tests/   # 41/41 pass

# Manual test with Direwolf:
# Add to Direwolf.conf: KISSPORT 8001
# Set [tnc] enabled=true, callsign=<your call>
# Run meshtop — TNC row appears in Connections panel

# Manual test with JS8Call:
# Settings → Reporting → TCP Server → enable, port 2237
# Set [js8call] enabled=true
# Run meshtop — JS8Call row appears in Connections panel

# Manual test rigctld:
# rigctld -m 1 -r /dev/null    (dummy rig for testing)
# Set [radio] enabled=true
# Run meshtop — RadioPanel appears showing 0.000 MHz until real rig connects
```
