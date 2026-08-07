# Fix commands — meshtop

The order to apply fixes in, the commands that apply them, and this repo's
commit-message style.

## Branching

Work on a branch; never commit to `main` directly. CI runs on pushes to
`main`, `feat/**`, `fix/**`, `refactor/**`, `chore/**`, and `docs/**`, so a
branch outside those prefixes gets no CI until the PR opens.

## Fix order

1. Lint / formatting (fastest, often mechanical)
2. Test failures
3. Smoke / CLI failures
4. Review comments
5. CodeQL alerts

## Lint / formatting

```bash
uv run ruff check meshtop/ --fix
uv run ruff format meshtop/
uv run ruff check meshtop/          # confirm zero remaining
```

## Tests

```bash
uv run pytest tests/ -v --tb=short
```

Read the failure, fix the code or the test (prefer fixing code unless the test is
wrong).

## Smoke / CLI

```bash
uv sync            # no dev group — this is what the smoke job installs
uv run meshtop --help
```

A smoke failure that tests pass through usually means a runtime dependency is
declared only in the `dev` group.

## Commit style

**Commitizen / conventional commits — this is a CI gate (`cz check`), not a
convention.** A malformed message fails the build.

```
feat(cli): add --json output to the status command
fix(serial): handle a closed port during reconnect
chore: bump ruff to 0.14
```
