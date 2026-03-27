## v0.5.0 (2026-03-27)

### Feat

- **release**: add PyInstaller Windows installer, align with rigtop (#11)

## v0.4.1 (2026-03-27)

### Fix

- **tui**: rename wifi command to tcp (#10)

## v0.4.0 (2026-03-24)

### Feat

- **tui**: improve messaging UX and channel receive via MQTT observer

## v0.3.0 (2026-03-24)

### Feat

- **tui**: add channel encryption UI, msg history, and ! shortcut
- add WiFi/TCP source for devices with WiFi enabled
- **tui**: exchange positions and user info with specific nodes
- **tui**: add pos send, traceroute, and live-iface msg commands

### Fix

- **tui**: replace tooltips with visible cmd-hint bar
- **tui**: rename LorabridgeApp to MeshtopApp; add MQTT observer, log viewer, BLE watchdog

## v0.2.0 (2026-03-24)

### Feat

- **tui**: add Textual TUI with BLE/serial sources and multi-sink support
- **source**: implement Meshtastic MQTT source with protobuf decoding

### Fix

- **tui**: use localNode.nodeNum to identify local node for top-right panel
- **ble**: force clean exit; timeout BLE close to prevent hang on quit
- **tui**: show local node in top-right panel; update header on source change

### Refactor

- rename project from lorabridge to meshtop
