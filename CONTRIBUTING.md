# Contributing

AutomatiQ is in early alpha. Things are rough and changing fast — contributions, bug reports, and ideas are all welcome.

## Setup

```bash
git clone https://github.com/StoneSteel27/AutomatiQ.git
cd AutomatiQ
pip install uv
uv pip install -e ".[dev]"
pre-commit install
```

See the [README](README.md) for full install and configuration details.

## Code style

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting. The rules are defined in `pyproject.toml`.

If `pre-commit` passes, you're good. To run manually:

```bash
ruff check src/ scripts/
ruff format src/ scripts/
```

- Line length: 121
- Python 3.11+
- Double quotes

## Pull requests

1. Fork the repo
2. Create a branch
3. Make your changes
4. Ensure pre-commit passes
5. Open a PR

CI runs the same pre-commit checks on every PR — if it's green locally, it'll be green in CI.

## Issues

Found a bug? Have an idea? Open an issue. No template required — just describe what's wrong or what you'd like to see.
