# my-evolve

A re-implementation of AlphaEvolve: an evolutionary loop in which LLMs rewrite a
program, a sandbox runs it, an evaluator scores it, and a database of islands
and MAP-Elites grids chooses what to build on next. It is a rewrite of
my-alphaevolve, taking selected ideas from OpenEvolve and ShinkaEvolve.

The design is in [docs/design-decisions.md](docs/design-decisions.md), how it
differs from the three reference implementations in
[docs/differences.md](docs/differences.md), and the order in which it is built
in [docs/implementation-plan.md](docs/implementation-plan.md).

## Layout

| Path | Contents |
|---|---|
| `src/my_evolve/` | The package |
| `examples/` | Ready-made problems, one folder each: function minimization and circle packing |
| `scripts/` | Files you launch directly |
| `tests/` | Automatic checks |
| `docs/` | The design and the plan |
| `pyproject.toml` | Project description and tool settings |

## Setup

Run once, from the repository root. Python 3.11 or later is needed.

Linux and macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Everyday commands

These are written for Linux and macOS. On Windows, replace `.venv/bin/python`
with `.venv\Scripts\python.exe`.

```bash
# Run the tests (those that need Docker are skipped without it)
.venv/bin/python -m unittest discover tests

# Check the types
.venv/bin/python -m mypy

# Check for common mistakes and style problems
.venv/bin/python -m ruff check

# Reformat the code automatically
.venv/bin/python -m ruff format
```
