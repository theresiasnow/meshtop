## Summary

<!-- What does this PR do? One paragraph is fine. -->

## Type of change

- [ ] Bug fix
- [ ] New feature / sink or source
- [ ] Refactor (no behaviour change)
- [ ] Docs / config
- [ ] CI / tooling

## Testing

<!-- How was this tested? Serial port, MQTT, TUI smoke, --help, etc. -->

- [ ] Imported cleanly (`uv run meshtop --help`)
- [ ] Tested against a live device / MQTT broker
- [ ] Ruff passes (`ruff check meshtop/ && ruff format --check meshtop/`)

## Device / radio notes

<!-- Device model, firmware version, operating mode tested — helps reviewers replicate. -->
<!-- Leave blank if not applicable. -->

## Checklist

- [ ] New config fields have pydantic validators
- [ ] New sinks inherit `PositionSink` / new sources produce `Position` objects
- [ ] Socket/serial errors handled with `OSError` / `ConnectionError`
- [ ] `loguru` used for logging (no bare `print` for debug output)
- [ ] Commit messages follow Conventional Commits (`feat:`, `fix:`, `chore:`, etc.)
