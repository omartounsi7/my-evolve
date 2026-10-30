# my-evolve

A re-implementation of AlphaEvolve: an evolutionary loop in which an LLM rewrites a
program, an evaluator scores it, and a database chooses what to build on next. It is
a rewrite of my-alphaevolve, taking selected ideas from OpenEvolve and ShinkaEvolve.

The design is in [docs/design-decisions.md](docs/design-decisions.md), how it differs
from the three reference implementations in [docs/differences.md](docs/differences.md),
and the order in which it is built in
[docs/implementation-plan.md](docs/implementation-plan.md).

## Layout

| Path | Contents |
|---|---|
| `src/my_evolve/` | The package |
| `examples/` | Ready-made problems, one folder each ([examples/README.md](examples/README.md)) |
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

A run needs Docker, installed and running: every program runs in a container of its
own, without network, with a read-only file system except `/tmp`, and limited memory,
CPUs and processes (the problem file's `sandbox` section). The image is built the first
time, with the problem file's `packages`.

It also needs the problem file's model reachable: for the circle-packing example, a
local [Ollama](https://ollama.com) server with `qwen3-coder:30b` pulled
(`ollama pull qwen3-coder:30b`). Ollama silently cuts prompts longer than its context
length; start it with `OLLAMA_CONTEXT_LENGTH=32768` or more.

```bash
.venv/bin/python scripts/run.py examples/circle_packing/initial_program.py examples/circle_packing/evaluation.py --config examples/circle_packing/problem.yaml --iterations 20 --output runs/circle_packing_1
```

| Flag | Meaning | Default |
|---|---|---|
| `--config` | The problem file: the problem's description and its LLM | required |
| `--iterations` | How many children to ask the LLM for | required |
| `--output` | The run folder; it must not hold a run already | `runs/<problem>_<date>_<time>` |
| `--seed` | The seed of the run's random draws | drawn, and printed |
| `--unsafe-local-sandbox` | Run programs as plain processes, without any isolation: tests and trusted code only | off |
| `--verbose` | Show each iteration's details on the console (`log.txt` always has them) | off |

The console shows one line per iteration (`--verbose` adds details), and a summary at
the end. The run folder holds:

| File | Contents |
|---|---|
| `programs.jsonl` | Every program, one line of JSON each, written as it is stored |
| `llm_calls.jsonl` | Every LLM call: the user message, the reply, the tokens |
| `history.csv` | One row per completed iteration: the progress of the run |
| `best_program.py` | The best program so far, under a comment header |
| `best/iteration_0010.py`, ... | The best program every `snapshot_every` iterations |
| `run.json` | The run's id, its seed, and one record per session |
| `problem.yaml` | A copy of the problem file |
| `log.txt` | Everything logged, with the time |

Ctrl+C stops the run; every program evaluated so far is already saved.

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

# Check the formatting, or reformat the code automatically
.venv/bin/python -m ruff format --check
.venv/bin/python -m ruff format
```
