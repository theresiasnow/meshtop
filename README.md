# meshtop

GPS bridge for Meshtastic devices — reads position, telemetry and messages via Bluetooth (BLE), USB serial or LoRa/MQTT and forwards to pi-star, APRS-IS, gpsd, and rigtop.

## Terminal requirements

meshtop uses a full-screen TUI that requires a terminal with **true color** and **Unicode** support.

| Platform | Recommended | Works | Avoid |
|---|---|---|---|
| Windows | [Windows Terminal](https://aka.ms/terminal) | Git Bash (mintty), WSL | cmd.exe, PowerShell 5 console |
| macOS | [iTerm2](https://iterm2.com) | Terminal.app (macOS 12+) | — |
| Linux | Any modern terminal (GNOME Terminal, Konsole, Alacritty, kitty) | — | — |

**Font:** use a monospace font that includes Unicode box-drawing characters — most system defaults work (Consolas, SF Mono, DejaVu Sans Mono). [Nerd Fonts](https://www.nerdfonts.com) give the best look but are not required.

**Color:** the TUI requires 256-color or true-color (24-bit) support. In Windows Terminal this is on by default. In other terminals set `COLORTERM=truecolor` if colors look wrong.

## Connecting via Bluetooth (BLE)

Before connecting from meshtop, two things must be true:

1. **Disable Bluetooth PIN on the device.**
   In the Meshtastic app: *Radio Config → Bluetooth → Pairing Mode → No PIN* (or Fixed with PIN disabled).
   With PIN enabled, Windows pairing fails silently and the app cannot connect.

2. **Disconnect any other app first.**
   Meshtastic devices only allow one BLE connection at a time. Close the Meshtastic mobile app (or turn off Bluetooth on the phone) before running `ble on` in meshtop.

## Connecting via USB serial

Enable Serial Console on the device:
*Radio Config → Module Config → Serial → Enabled: ON*

Without this the device does not speak the Meshtastic protocol over USB and the connection will time out.

## Usage

```
uv run meshtop                        # start with TUI (reads meshtop.toml)
uv run meshtop --source ble           # connect via Bluetooth on startup
uv run meshtop --source serial --port COM4
uv run meshtop --no-tui --debug       # plain console output with debug logging
```

### TUI commands

| Command | Description |
|---|---|
| `ble on` | Scan for nearby Meshtastic devices and connect via BLE |
| `ble off` | Disconnect BLE |
| `serial on` | Pick a serial port and connect |
| `serial off` | Disconnect serial |
| `wifi <HOST>` | Set WiFi/TCP node for sending (e.g. `wifi 192.168.1.100`); on MQTT source keeps receiving via MQTT |
| `wifi off` | Clear WiFi/TCP send target |
| `beacon on/off` | Enable or disable APRS beacon |
| `msg [#<ch>] <NODE\|^all> <text>` | Send a text message — node can be short name, hex suffix or full ID; `#1` selects secondary channel |
| `! <text>` | Send to last `msg` recipient (shortcut) |
| `pos send <NODE>` | Send your current position to a node |
| `trace <NODE>` | Send a traceroute request |
| `info <NODE>` | Send node info request |
| `channel` | Open channel encryption settings |
| `node` | List all heard nodes |
| `log` | Dump recent event log |
| `help` | List all commands |

Up/down arrows in the command bar navigate command history.


<!-- Triggering workflow with this comment -->