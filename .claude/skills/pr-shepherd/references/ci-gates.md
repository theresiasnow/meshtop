# CI gates — meshtop

The checks that run on PRs in this project. Most live in the single `CI` workflow
(`.github/workflows/ci.yml`); CodeQL and the Copilot review are separate workflows.

| Check | What it tests |
|---|---|
| Commit messages | `uv run cz check` over the PR's commit range — commitizen/conventional format. **PR-only**; does not run on pushes to a branch. |
| Lint | `uv run ruff check meshtop/` and `uv run ruff format --check meshtop/` |
| Smoke test (matrix) | `uv sync`, an import smoke test, and `uv run meshtop --help` |
| Tests (matrix) | `uv run pytest tests/ -v --tb=short` |
| Build wheel | packaging build |
| CodeQL | security/quality analysis — **does run on PRs**, a real gate |
| Copilot review | advisory AI review; skips on draft PRs and non-`main` bases |

Notes:

- **Smoke and Tests run as a matrix** over `ubuntu-latest` + `windows-latest` on
  Python 3.14, so each appears more than once in `gh pr checks`. A single red cell
  fails the gate — read which OS before assuming the code is broken everywhere;
  a Windows-only failure is usually a path or line-ending issue.
- **Commit messages only runs on `pull_request`.** A green CI on a branch push does
  not mean your commit messages pass; the check first appears when the PR opens.
- **Copilot review is advisory** — it does not block merge. Read it, but a red or
  missing Copilot check is not a reason to hold the PR.
- CodeQL also runs on a Monday cron, but the PR run is the one that gates here.
