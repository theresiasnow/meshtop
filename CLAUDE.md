# lorabridge — Claude Code instructions

## Python / tooling

This project uses **uv** for all Python tasks. Always prefer:

```
uv run python       # instead of python / .venv/Scripts/python.exe
uv run pytest       # instead of python -m pytest
uv run ruff         # instead of python -m ruff
uv run pylint       # instead of python -m pylint
```

Never call `.venv/Scripts/python.exe` directly.

## Project layout

```
lorabridge/
  __init__.py
  __main__.py
  cli.py           # entry point, argument parsing, startup/shutdown, rich output
  config.py        # Pydantic models + TOML loader
  position.py      # Position dataclass (lat, lon, alt, speed, course, fix)
  sources/
    __init__.py
    serial.py      # USB-serial NMEA (Wio Tracker direct, pyserial + pynmea2)
    lora.py        # LoRa-gateway via MQTT (TTN v3 / Chirpstack, paho-mqtt)
  sinks/
    __init__.py
    nmea_server.py # TCP NMEA server for pi-star (default port 10110)
    aprs.py        # APRS-IS beacon (callsign, passcode, interval)
    gpsd.py        # gpsd-compatible JSON server (port 2947)
    rigtop.py      # NMEA TCP server consumed by rigtop as gps2ip source
tests/
  test_config.py
  test_nmea.py
```

## Code style

- Line length: 100
- Linter: ruff (select E, F, W, I, UP, B, SIM, RUF, PTH, PIE, TRY, G, C4, PERF)
- No docstrings or type annotations required on code you didn't write

## Key conventions

- Config is loaded once in `cli.main()` — pass values down, don't re-read TOML at runtime
- Sources produce `Position` objects via callback; sinks consume them
- All sinks run as background threads; main thread owns the source loop
- `position.py` is the shared data contract — no sink/source imports the other

## Commit messages

All commits must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope)?: short description
```

Valid types: `build`, `bump`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, `test`

## Running

```
uv run lorabridge --help
uv run lorabridge --source serial --port COM3
uv run lorabridge --source lora --config lorabridge.toml
uv run pytest tests/
uv run ruff check lorabridge/
```

## Branch workflow

Same as rigtop — `feat/*` / `fix/*`, never commit directly to main.
