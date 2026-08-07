# Failure triage — meshtop

| Symptom | Likely cause |
|---|---|
| `cz check` failure | a commit message is not commitizen/conventional format. Fix by rewording the offending commit (`git rebase -i`), not by relaxing the check. Only the PR's own commit range is checked. |
| `ruff check` E/F/I/UP/B errors | lint violation — `uv run ruff check meshtop/ --fix`, then fix the remainder by hand |
| `ruff format --check` failure | formatting drift only — run `uv run ruff format meshtop/` and commit the result |
| `pytest` assertion / import error | broken test or a code change broke an existing test |
| Import smoke test failure | the package does not import cleanly from a bare `uv sync` — usually a missing runtime dependency that is only in the `dev` group |
| `meshtop --help` failure | the CLI entry point is broken — often a bad `[project.scripts]` entry or an import error at module load |
| A matrix cell fails on windows-latest only | path separators, line endings, or a POSIX-only assumption — reproduce with the same Python on Windows before changing shared code |
| CodeQL alert | security/quality finding — read the alert (PR Security tab or `gh api`), understand the vulnerability class, then fix the code. Don't dismiss it to go green. |
| Build wheel failure | packaging metadata problem in `pyproject.toml`, not a code bug |
