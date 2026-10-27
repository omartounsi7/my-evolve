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
| `examples/` | Ready-made problems, one folder each: circle packing and function minimization ([examples/README.md](examples/README.md)) |
| `scripts/` | Files you launch directly: `run.py` |
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

## Running a problem

A run needs Docker running (programs run in its containers) and the problem file's
models reachable: for `problem.yaml`, a local Ollama server with both models pulled;
for `problem_claude.yaml`, the `ANTHROPIC_API_KEY` environment variable.

```bash
.venv/bin/python scripts/run.py examples/circle_packing/initial_program.py examples/circle_packing/evaluation.py --config examples/circle_packing/problem.yaml --iterations 100
```

| Flag | Meaning | Default |
|---|---|---|
| `--config` | The problem file: the problem and every setting of its runs | required |
| `--iterations` | Completed iterations in all | 100 |
| `--output` | The run folder | `runs/<problem>_<date>_<time>` |
| `--workers` | Iterations in progress at once | 1 |
| `--seed` | The seed of the run's random draws | drawn, and saved |
| `--unsafe-local-sandbox` | Run programs as plain processes, without any isolation: tests and trusted code only | off |
| `--verbose` | Show each iteration's details on the console | off |

The console shows one line per iteration; the run folder holds every program
(`programs.jsonl`), every LLM call (`llm_calls.jsonl`), the progress
(`history.csv`), the best program (`best_program.py`, and snapshots in `best/`),
and `log.txt`.

To stop a run, press Ctrl+C: no new iteration starts, and those in progress finish
and are saved. Press it again (or send SIGTERM, on Linux and macOS) to stop at once:
the iterations in progress are lost, and their containers removed.

## Everyday commands

These are written for Linux and macOS. On Windows, replace `.venv/bin/python`
with `.venv\Scripts\python.exe`.

```bash
# Run the tests (those that need Docker are skipped without it)
.venv/bin/python -m unittest discover tests

# The same, with the slow tests too (about a minute more)
MY_EVOLVE_SLOW_TESTS=1 .venv/bin/python -m unittest discover tests

# Check the types, then each example's evaluation file on its own (their names are the same)
.venv/bin/python -m mypy
.venv/bin/python -m mypy examples/circle_packing/evaluation.py
.venv/bin/python -m mypy examples/function_minimization/evaluation.py

# Check for common mistakes and style problems
.venv/bin/python -m ruff check

# Reformat the code automatically
.venv/bin/python -m ruff format
```
