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
| `--iterations` | How many iterations in all, those of earlier sessions included | required |
| `--output` | The run folder; a folder holding a run continues it | `runs/<problem>_<date>_<time>` |
| `--workers` | How many iterations may be in flight at once | 1 |
| `--target-score` | Stop once the best score reaches it | none |
| `--patience` | Stop after this many iterations, skipped ones included, without a better best score | none |
| `--seed` | The seed of the run's random draws (a continued run keeps its own) | drawn, and printed |
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
| `run.json` | The run's id, its seed, the fingerprints a continued run is checked against, and one record per session |
| `problem.yaml` | A copy of the problem file, from the first session |
| `log.txt` | Everything logged, with the time |

The first Ctrl+C lets the iterations in progress finish, then ends the run; a second one,
or SIGTERM, stops it at once. Either way, everything finished is already saved.

To continue a run, stopped or crashed, run the same command with `--output` naming its
folder: its programs are read back, the initial program is not evaluated again, and
`--iterations` counts the iterations already done, so a larger value extends the run.
Iterations that were in progress when it stopped are done again. A run is not continued
if its initial program, its evaluation file, its problem file (the `llm` section aside) or
its Docker image changed: the message says which. The `llm` section and the flags may
change between sessions; `run.json` records each session's.

## The report

```bash
.venv/bin/python scripts/report.py runs/circle_packing_1
```

draws into the run folder's `report/` folder, with matplotlib:

| File | Contents |
|---|---|
| `progress.png` | The best score so far against completed iterations, with every working child's score as a dot |
| `output_0010.png`, ... | The best program's output at every snapshot and at the end, if the evaluation file defines `visualize(output_data, path)`: circle packing's draws the circles |
| `grids_0010.png`, ... | Every island's MAP-Elites grid at every snapshot and at the end: an empty cell white, an occupied one blue, deeper for higher scores, on one scale for the whole run; a 3D grid as one square per bin of its third feature |
| `grids.gif` | The grid images, one after another |

The run folder itself is only read, so a run still in progress can be reported on.

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
