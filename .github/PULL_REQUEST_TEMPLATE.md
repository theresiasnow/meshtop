## Summary

<!-- What does this PR do? One paragraph is fine. -->

## Type of change

- [ ] Bug fix
- [ ] New feature / sink
- [ ] Refactor (no behaviour change)
- [ ] Docs / config
- [ ] CI / tooling

## Testing

<!-- How was this tested? Serial connection, LoRa gateway, APRS-IS, gpsd, etc. -->

- [ ] Imported cleanly (`uv run meshtop --help`)
- [ ] Tested against a live GPS source (serial or LoRa)
- [ ] Tested relevant sinks (NMEA server, APRS-IS, gpsd, rigtop)
- [ ] Ruff passes (`ruff check meshtop/ && ruff format --check meshtop/`)

## Ham radio notes

<!-- Callsign, GPS source, operating mode tested — helps reviewers replicate. -->
<!-- Leave blank if not applicable. -->

## Checklist

- [ ] New config fields have pydantic validators
- [ ] New sinks run as background threads and implement the sink callback interface
- [ ] Socket/serial errors handled with `OSError` / `ConnectionError`
- [ ] `loguru` used for logging (no bare `print` for debug output)
- [ ] `position.py` is the only shared data contract between sources and sinks
