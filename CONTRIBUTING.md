# Contributing to fit-stitch

Thanks for your interest in contributing!

## Code of Conduct

This project follows our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold it.

## How to Contribute

### Reporting Bugs

- Use the bug report issue template
- Include the exact command you ran, expected vs. actual behavior, and your device model
- **Never attach personal FIT files** — they contain GPS traces of where you live and train. Describe the file (device, sport, message counts) or reproduce with a synthetic file instead

### Suggesting Features

- Use the feature request issue template
- Explain the problem you're solving, not just the solution

### Submitting Changes

1. Fork the repo and create a branch from `main`
2. Make your changes, add tests (synthetic fixtures only — see `tests/conftest.py`)
3. Ensure `poetry run pytest`, `poetry run ruff check .` and `poetry run ruff format --check .` pass
4. Open a PR against `main`

### Branch Naming

- `feature/` — new functionality
- `fix/` — bug fixes
- `chore/` — maintenance
- `docs/` — documentation

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `ci:`. Keep the subject line under 72 characters.

### Coding Standards

- Catch the most specific exception possible — no bare `except:` or `except Exception:`
- Keep the three project invariants (documented in `CLAUDE.md`) intact
- Match the existing code style; ruff enforces formatting

## Development Setup

```bash
poetry install
poetry run pytest
```

## Questions?

Open a discussion or email contact@vimoswim.com.
