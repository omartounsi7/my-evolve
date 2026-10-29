# Implementation plan for my-evolve

The order in which my-evolve is built from [design-decisions.md](design-decisions.md) (D1 to D79). The design
says what the finished system does; this plan says in which order to get there. It changes nothing in the design.

This is the second plan. The first one, carried out on the branch `my-evolve-v1`, built every module in its final
form in a single step: each step added several hundred lines of finished, intricate code at once, and it became
hard to follow what was being built. This plan works the other way round:

> **Build simple components, then improve them gradually.**

Phase 0 builds the four components of AlphaEvolve (the database, the prompt sampler, the LLM, the evaluator) in
the simplest form that works, and wires the loop so that it runs end to end. Every later step improves one thing,
and the loop still runs after it. The components reach their designed form one small step at a time.

Read against: design-decisions.md and [differences.md](differences.md) at `bf6b6de`; my-alphaevolve ("v1") at
`4a1e438`; openevolve at `da3d701`; ShinkaEvolve at `8adc053`.

## The loop

This is the AlphaEvolve controller loop, as my-evolve writes it from Phase 0 on:

```python
parent, examples = database.sample()            # examples: the diagram's "inspirations" (D26)
prompt = prompt_builder.build(parent, examples)
reply = llm.complete(prompt)
code = extract_code(reply)                      # the diagram's apply_diff: the LLM returns the whole file (D11)
result = evaluator.evaluate(code)
database.add(Program.new_child(parent, code, result, iteration))
```

These six lines keep their shape to the end. What changes is what happens inside each call, plus three additions
around them: checks between the reply and the evaluation (Phase 2), an island drawn first (Phase 3), and worker
threads running several iterations at once (Phase 4). Names follow section 14 of the design from the start, so
nothing needs renaming later.

## How each step is carried out

- **One idea per step.** A step changes one thing, and its diff can be read in one sitting: as a rule of thumb,
  under about 300 changed lines, tests included. A step that grows past that is split in two.
- **The loop always runs.** A step ends with ruff (lint and format), mypy in strict mode and every test passing
  (D57), including the end-to-end test `tests/test_loop.py` (step 0.8: the loop on a toy problem with a fake LLM).
  A step that changes what a real run does also ends with a short real run (`--iterations 5`, local Ollama).
- **Simplifications are written down.** Each step's **Not yet** says what it deliberately leaves out, and names
  the step that adds it. So the code is always simpler than the design in known ways, never by accident.
- **Settings arrive with their feature.** The problem file accepts only the keys the code already uses; an unknown
  key is an error from step 0.3 on (D44; differences.md Part D, openevolve item 9).
- **The design stays the target.** A decision that changes during the build is changed in design-decisions.md in
  the same commit.
- **Explained as it is built** (D59). A step's text here is its design; a detail it leaves open is settled when
  the step starts. Once a step is done, a short walk-through of its diff says what changed, where, and why.
- **One commit per step**, named after it ("Step 1.3: evaluating through the worker"). The code has v1's
  plain-English docstrings and comments (D58).
- **The v1 branch is a reference, not a source.** `my-evolve-v1` has working code for most of what follows. It
  can be read, and its test data reused (the parity programs and openevolve's recorded scores), but its modules
  are not copied whole: each step writes only what that step needs.
- **Platforms** (D55). The code avoids anything specific to one system. This machine tests Linux; Windows is
  tested at the milestones, if a Windows machine is at hand.

## Overview

| Step | Builds | Decisions |
|---|---|---|
| **Phase 0** | **The loop, end to end** | |
| 0.1 | Project skeleton | D55–D58 |
| 0.2 | The circle-packing problem, and a toy problem for the tests | D3, D4 |
| 0.3 | Records: `Result`, `Program`, `Problem` | D43, D44, D60, D72, D73 |
| 0.4 | Evaluator, basic: `exec` in the run's own process | D5, D65 |
| 0.5 | Database, basic: random parent and examples | D22, D39, D63 |
| 0.6 | Prompt, basic: parent and examples | D25, D67 |
| 0.7 | LLM, basic: one model; the first code block of the reply | D11, D32, D66, D68 |
| 0.8 | The loop and the command line | D20, D45, D47, D70 |
| M0 | The first real run | |
| **Phase 1** | **The evaluator** | |
| 1.1 | Statuses: `ok`, `failed`, `invalid` | D7, D73, D76 |
| 1.2 | The sandbox worker and its messages | D77 |
| 1.3 | Evaluating through the worker; status `error` | D5, D8, D64, D65 |
| 1.4 | A time limit; status `timeout` | D41, D64 |
| 1.5 | When the program misbehaves | D10, D64 |
| 1.6 | Exact plain data | D8, D77 |
| 1.7 | Packages and the evaluation image | D71 |
| 1.8 | The Docker sandbox | D40, D41 |
| 1.9 | Containers never outlive a run | D42 |
| 1.10 | Feedback and metrics | D6, D10, D30, D76 |
| 1.11 | The cascade | D9, D65 |
| 1.12 | Circle packing, scored exactly as openevolve does | D3, D9, D10 |
| 1.13 | Function minimization, and time limits on single calls | D3, D8, D76 |
| M1 | The first run in the sandbox | |
| **Phase 2** | **The prompt and the LLM** | |
| 2.1 | Every LLM call saved | D35, D47, D50, D66 |
| 2.2 | v1's reply parser | D68 |
| 2.3 | Descriptions | D15, D68 |
| 2.4 | Evolve blocks enforced; status `rejected` | D12, D13, D74 |
| 2.5 | Compiling and entry functions | D13, D74 |
| 2.6 | Duplicates | D13, D24, D63 |
| 2.7 | The prompt of Appendix A | D25–D27, D29, D30, D67 |
| 2.8 | Model settings and API keys | D32–D34, D46 |
| 2.9 | The ensemble | D31, D34, D66, D72 |
| M2 | The first run with an ensemble | |
| **Phase 3** | **The database** | |
| 3.1 | ShinkaEvolve's parent rule | D19, D75 |
| 3.2 | Example programs, as designed | D26 |
| 3.3 | Islands | D23, D62, D63 |
| 3.4 | MAP-Elites grids on code complexity | D16–D18, D61, D74 |
| 3.5 | Output features | D9, D17, D18 |
| 3.6 | Migration | D23, D63 |
| 3.7 | openevolve's parent rule and the archive | D19, D21, D75 |
| M3 | The first run with the whole database | |
| **Phase 4** | **The run** | |
| 4.1 | Logging and the summary | D35, D51, D52, D78 |
| 4.2 | The complete run folder | D45, D47, D69 |
| 4.3 | Several iterations at once | D36, D70 |
| 4.4 | Errors inside an iteration | D34, D38 |
| 4.5 | Ctrl+C and SIGTERM | D53, D54, D79 |
| 4.6 | Continuing a run | D39, D49 |
| 4.7 | Refusing to continue a changed problem | D50 |
| 4.8 | Target score and patience | D37 |
| 4.9 | The report: progress and drawings | D6, D51, D79 |
| 4.10 | The report: grids | D51, D79 |
| M4 | The whole design | |
| **Phase 5** | **The experiments** | |
| 5.1 | Function minimization | D3 |
| 5.2 | Baselines: openevolve with the same models | D3 |
| 5.3 | Circle packing | D3, Appendix B |

## How each component grows

| Component | In Phase 0 | Then, step by step |
|---|---|---|
| Evaluator | `exec` in the run's own process; `evaluate(namespace)` receives a plain dictionary; a score or an error | statuses (1.1) → the program in a worker process (1.2, 1.3) → a time limit (1.4) → misbehaving programs (1.5) → exact data (1.6) → Docker (1.7–1.9) → feedback (1.10) → the cascade (1.11) → openevolve's exact scores (1.12, 1.13) → output features (3.5) → output data (4.9) |
| Prompt | one system message; the parent and two examples, each with its score and code | allowed packages (1.7) → feedback (1.10) → descriptions (2.3) → the evolve-block rule (2.4) → Appendix A's text and size limits (2.7) → failed examples (3.2) |
| LLM and reply | one model; the reply's text; its first code block | calls saved, with tokens (2.1) → v1's parser (2.2) → descriptions (2.3) → checks before evaluation (2.4–2.6) → settings and keys (2.8) → the ensemble (2.9) |
| Database | every program, in memory; parent and examples drawn uniformly among working programs | fingerprints (2.6) → ShinkaEvolve's rule (3.1) → examples as designed (3.2) → islands (3.3) → grids (3.4, 3.5) → migration (3.6) → openevolve's rule and the archive (3.7) → replay (4.6) |
| Loop and run folder | one iteration after another; console lines; `programs.jsonl`, `best_program.py` | `llm_calls.jsonl`, `run.json` (2.1) → logging (4.1) → the full run folder (4.2) → threads (4.3) → errors (4.4) → Ctrl+C (4.5) → continuing (4.6, 4.7) → target and patience (4.8) → the report (4.9, 4.10) |

The evaluator comes right after Phase 0 because, until step 1.8, the LLM's code runs with your files and your
network: inside the run's own process in Phase 0, in a process of its own from step 1.3. From Milestone 1 on,
every run is sandboxed.

---

## Phase 0: the loop, end to end

The goal: `scripts/run.py` evolves the circle-packing program with a real LLM and prints the scores. Each of the
four components is as simple as it can be while doing its job: a few hundred lines of code in all.

### Step 0.1. Project skeleton
- **Builds.** `pyproject.toml`: the package `my_evolve` in `src/`, Python 3.11 or later, dependencies `openai` and
  `pyyaml`; development extras ruff, mypy, `types-PyYAML` and numpy (evaluation files run on the host, D8); v1's
  ruff and mypy settings (mypy strict), with `py311` as target. An empty `src/my_evolve/__init__.py`; a `tests/`
  folder with one test that imports the package; a README with the set-up and the check commands, for Linux and
  Windows; `runs/` added to `.gitignore`.
- **Check.** `pip install -e ".[dev]"` works; ruff, mypy and `unittest` pass.

### Step 0.2. The circle-packing problem, and a toy problem
- **Builds.** `examples/circle_packing/initial_program.py`: openevolve's, at `da3d701`, unchanged, EVOLVE-BLOCK
  markers included (D3), with openevolve's licence in `examples/`. A first `evaluation.py`: `evaluate(namespace)`
  calls `namespace["run_packing"]()`, checks the shapes and that every circle lies in the unit square without
  overlapping another (openevolve's `validate_packing`), and returns the sum of the radii divided by 2.635; an
  illegal packing raises `ValueError` with the reason. A `problem.yaml` with `name`, `description` (the system
  message of openevolve's `config_phase_1.yaml`, followed by the contract of `run_packing`, D4) and an `llm`
  section (`model`, `api_base`: Appendix B's `qwen3-coder:30b` on the local Ollama server).
  For the tests, a toy problem in `tests/toy/`: an initial program whose `solve()` returns a number, scored as
  that number, up to 10. It evaluates in milliseconds.
- **Not yet.** openevolve's exact checks and its two stages (1.12).
- **Check.** A test runs the initial program with `exec` and scores it: 0.364 (a sum of about 0.959).

### Step 0.3. Records: `Result`, `Program`, `Problem`
- **Builds.** `program.py`: `Result` with `score` (none for a failed program) and `error`; `Program` with `id` (a
  UUID), `code`, `result`, `parent_id`, `generation`, `iteration`; `Program.new_child(parent, code, result,
  iteration)`; `to_dict()`, where a missing score is `null`, never `-Infinity` (Part D, v1 item 5).
  `problem.py`: `Problem` (`name`, `description`, `llm.model`, `llm.api_base`) and `Problem.load(path)`: the YAML
  read as plain data, required keys checked, unknown keys refused with their location (D44).
- **Not yet.** Every other attribute of D60, D72 and D73: each arrives with the step that uses it.
- **Check.** `new_child` sets the parent and the generation; `to_dict` gives plain JSON values; a missing or an
  unknown key in the problem file is a clear error.

### Step 0.4. The evaluator, basic
- **Builds.** `evaluator.py`: `Evaluator(evaluation_path)` loads the evaluation file with v1's loader (helper
  files next to it can be imported, and are forgotten afterwards) and takes its `evaluate`. `evaluate(code)`
  returns a `Result`: run the code with `exec` in a fresh namespace whose `__name__` is `program` (so that its
  `if __name__ == "__main__":` part does not run); call the evaluation file's `evaluate` with that dictionary;
  check that the score is a finite number and not a boolean (v1); turn any exception into a result without a
  score, whose error is the exception's type and message.
- **Not yet.** Isolation and time limits: until Phase 1, the LLM's code runs inside the run's own process, with
  your files and network, and a program that never ends stops the run. Phase 0's runs are short, and watched
  (Ctrl+C stops them). Statuses (1.1).
- **From.** v1's `load_score_function` (`my-alphaevolve/src/my_alphaevolve/problem.py`) and `score_program`
  (`evaluator.py`).
- **Check.** On the toy problem, a working program gets its score, a program that raises gets its error, a score
  that is a boolean or not finite is refused. Circle packing's initial program scores 0.364 through the evaluator.

### Step 0.5. The database, basic
- **Builds.** `database.py`: `Database(rng)` keeps every program (D22), by id, in the order added. `add(program)`;
  `best()`, the highest score, the earliest on a tie; `sample()`, a parent drawn uniformly among the working
  programs and up to 2 example programs drawn uniformly among the other working programs. One `random.Random`
  makes every draw of the run, seeded from `--seed`, or from a seed drawn at random (D39).
- **Not yet.** ShinkaEvolve's parent rule (3.1); failed programs among the examples (3.2); islands and grids
  (3.3, 3.4).
- **Check.** Failed programs are never drawn; the parent is never one of its own examples; the same seed gives
  the same draws.

### Step 0.6. The prompt, basic
- **Builds.** `prompt.py`: `Prompt` (`system`, `user`); `PromptBuilder(problem)` builds the system message once: a
  one-line instruction, the problem's description, and "reply with the complete program in a ```python block".
  `build(parent, examples)`: the user message shows each example's score and code, then the parent's score and
  code, then "Write the improved program."
- **Not yet.** Appendix A's exact text, the best score so far, and the size limits (2.7); descriptions (2.3);
  feedback (1.10).
- **Check.** The exact text for a fixed parent and two examples; braces in the code are kept as written.

### Step 0.7. The LLM, basic
- **Builds.** `llm.py`: `LLMError`; an abstract `LLM` with `complete(prompt)`, which returns the reply's text;
  `OpenAICompatibleLLM(model, api_base)`, which sends the system and user messages with the synchronous `openai`
  client (as v1: the package imported only when needed, a 300 s timeout, the package's own 2 retries, an empty
  reply as an `LLMError`). `reply_parser.py`: `extract_code(reply)`, the first fenced code block, or the whole
  reply if there is none. `tests/fakes.py`: `FakeLLM`, which returns replies written in advance.
- **Not yet.** API keys and generation settings (2.8); several models (2.9); token counts (2.1); v1's robust
  parsing (2.2).
- **From.** `my-alphaevolve/src/my_alphaevolve/llm.py`.
- **Check.** `extract_code` on replies with one block, several, and none; by hand, one question to the local
  Ollama model.

### Step 0.8. The loop and the command line
- **Builds.** `loop.py`: `run(...)` evaluates the initial program and stops if it has no score (D20); adds it; then
  runs the six lines of the loop once per iteration, printing one line each (iteration, the child's score or its
  error, the best score). An `LLMError` skips the iteration. The run folder given by `--output` gets
  `programs.jsonl`, one line per program, appended as it is added (D47, D48), and `best_program.py`, rewritten when
  the best changes. `scripts/run.py INITIAL_PROGRAM EVALUATION_FILE --config PROBLEM_FILE --iterations N --output
  FOLDER --seed S`: D45's form, with its first flags.
- **Not yet.** Threads (4.3); any Ctrl+C handling beyond Python's own (4.5); continuing a run (4.6); the rest of
  the run folder (2.1, 4.2).
- **Check.** `tests/test_loop.py`: the toy problem, with a `FakeLLM` replying a better program, a program that
  raises, and a reply without code; the programs stored, the best one, `programs.jsonl`. This end-to-end test
  stays, and grows with every phase.

### Milestone 0. The first real run
20 iterations of circle packing with `qwen3-coder:30b` on the local Ollama server. Look at the replies, the scores
and the time an iteration takes. This run is the baseline for what follows: my-alphaevolve's loop, plus example
programs and a system message.

---

## Phase 1: the evaluator

By the end of this phase the evaluator is the design's: the program runs in a Docker container and only answers
calls, while the evaluation file runs on the host (D8); a cascade decides how far a program goes (D9); every
outcome has a status (D7); and both problems get exactly openevolve's scores (D3). Steps 1.1 to 1.9 run the
program safely; steps 1.10 to 1.13 make the evaluation say more.

### Step 1.1. Statuses
- **Builds.** `Status`, for now with `ok`, `failed` and `invalid` (D7); `Result.status`, with a score for `ok`
  only, and `is_ok`. `evaluation_api.py`, what evaluation files import, with `InvalidProgram(reason)`, raised for
  an illegal answer; circle packing's evaluation raises it in place of `ValueError`, naming the problem ("circles
  3 and 7 overlap"). The status is saved in `programs.jsonl` and shown on the console line.
- **Not yet.** `error` (1.3: while the program runs in the same process, an exception from the program and a
  mistake in the evaluation file look alike); `timeout` (1.4); `rejected` (2.4).
- **Check.** A test per status; only `ok` programs are drawn.

### Step 1.2. The sandbox worker and its messages
- **Builds.** `sandbox_protocol.py`: `send` and `receive`, one JSON message per line. `sandbox_worker.py`, run as
  `python -m my_evolve.sandbox_worker` (D77): it reads a `load` message, runs the code in a fresh namespace named
  `program`, and answers `loaded` (the top-level names, each `function`, `data` or `other`) or `load_failed` (the
  error and its traceback); then it answers each `call` (an id, a function name, its arguments) with `return`
  (the id, the value) or `raised` (the id, the error, the traceback). For now, values are JSON, with numpy arrays
  and numbers turned into lists and Python numbers (1.6 makes this exact). What the program prints goes to the
  error output, so the protocol's stream carries messages only. Neither module imports anything outside the
  standard library, except numpy when it is installed; `__init__.py` stays empty (section 14.1).
- **Not yet.** Used by the evaluator (1.3).
- **Check.** Tests drive the worker through its pipes: names and kinds in `loaded`; `return`; `raised` with the
  traceback; the `__main__` part not run; prints kept off the protocol's stream; `sys.exit` while loading gives
  `load_failed`.

### Step 1.3. Evaluating through the worker
- **Builds.** `sandbox.py`: `LocalSandbox.start(code)` starts the worker as a subprocess and loads the program,
  giving a `SandboxSession` with `call(name, args, kwargs)` and `get(name)`. `ProgramNamespace`, what `evaluate`
  receives in place of the dictionary: a function's name gives a `RemoteFunction`, which calls that function in
  the worker; a plain-data global gives its value; anything else, or a missing name, raises `ProgramFailure`
  (added to `evaluation_api.py`). The evaluator starts a session per evaluation and always closes it. A
  `ProgramFailure` gives `failed`; any other exception from the evaluation file gives the new status `error`
  ("evaluator:" and the traceback), which is not the program's fault (D7, D65).
  The evaluation files do not change: `namespace["run_packing"]()` reads the same whether the namespace is a
  dictionary or stands in front of another process (D5).
- **Not yet.** A time limit (1.4). The program still has your files and network (until 1.8).
- **Check.** The initial programs score as before; an exception in the program gives `failed` with its traceback;
  a mistake in the evaluation file gives `error`; a missing name gives `failed`; the end-to-end test passes
  unchanged.

### Step 1.4. A time limit
- **Builds.** `evaluation.stage_time_limit` in the problem file (60 s, D41; with a single stage, it limits the
  whole evaluation). A reader thread puts the worker's messages in a queue, so that waiting for an answer can
  stop at the deadline; the worker is then killed and `StageTimeout` raised, giving the new status `timeout`.
- **Not yet.** Limits on single calls (1.13).
- **Check.** A program that never returns gets `timeout` after the limit, and its process is gone; a program
  within the limit is unaffected.

### Step 1.5. When the program misbehaves
- **Builds.** The worker's error output goes to a temporary file, so a program that prints without end fills a
  file, not the memory; its end (`error_tail`) is added to every failure (D10). A worker that dies gives a
  `ProgramFailure` saying how (exit code 137: "stopped, most likely for using too much memory", as in v1). A
  message whose id the host is not waiting for is ignored, so a program writing a forged `return` gains nothing
  (Part D, v1 item 3).
- **Check.** One test each: endless printing, `os._exit`, a forged message, the error output in a failure.

### Step 1.6. Exact plain data
- **Builds.** `encode` and `decode` (D77), in place of 1.2's lists: tuples, non-finite floats and dictionaries
  tagged so that they come back unchanged; numpy arrays of numbers sent as their type, shape and bytes in base64,
  never through pickle (D8); `NotPlainData` for anything else, sent back as `raised`.
- **Check.** Round trips of every kind of value; the refusals; circle packing's evaluation receives numpy arrays
  again.

### Step 1.7. Packages and the evaluation image
- **Builds.** `packages` in the problem file, `name==version` only (D71); `evaluation.Dockerfile` (v1's, without
  the problem's folder); `DockerSandbox.ensure_image(packages)`, which builds the image on first use, tagged with a
  hash of the Dockerfile and the list. The system message names the allowed packages. Circle packing lists numpy,
  scipy and matplotlib at v1's versions.
- **Not yet.** Running programs in containers (1.8).
- **Check** (skipped without Docker, as in v1). The image is built once and then reused; changing the list
  changes the tag; a pip option is refused.

### Step 1.8. The Docker sandbox
- **Builds.** `DockerSandbox.command()`: `docker run --rm -i` with D41's limits (no network; a read-only file
  system except a temporary `/tmp`; 1 GB of memory without swap; 1 CPU; 64 processes; no capabilities and no new
  privileges; user `nobody`; the numeric libraries' thread variables set to the CPU count; the package folder
  mounted read-only), and the `sandbox` section of the problem file (`memory`, `cpus`, `max_processes`).
  `SandboxError` (Docker missing or stopped, an image that fails to build, a container that cannot start) gives
  `error`. Docker becomes the default; `--unsafe-local-sandbox` keeps the local sandbox, with a warning (D40).
- **From.** `DockerEvaluator` in `my-alphaevolve/src/my_alphaevolve/evaluator.py`; `tests/docker_check.py`.
- **Check** (skipped without Docker). v1's isolation tests (no network, nothing writable but `/tmp`, the memory
  limit); the listed packages importable, others not; no environment variable of the host visible; both initial
  programs score as before.

### Step 1.9. Containers never outlive a run
- **Builds.** Each container is labelled with the run's id (drawn when the run starts; saved from 2.1 on), and
  `remove_leftovers()` removes the run's containers at start-up and when the run stops. Inside the container the
  worker runs under `timeout`, 10 s longer than the stage's limit, so it stops even if the host process dies (D42).
- **Check** (skipped without Docker). No container is left after a timeout; `remove_leftovers` removes the run's
  containers and no others; a container stops on its own when the process that started it is killed.

### Step 1.10. Feedback and metrics
- **Builds.** Evaluation functions now return a `StageResult` (`score`, `metrics`, `feedback`, D76), and
  `InvalidProgram` carries feedback too. `Result` gains `metrics`, `feedback` and `duration`. The prompt shows the
  feedback of the parent and of each example, cut to `prompt.max_feedback_chars` (2,000, D10, D30). Circle
  packing's evaluation writes feedback as it checks ("Circles 3 and 7 overlap (distance 0.112, radii sum 0.130)").
- **Check.** Feedback reaches the prompt, truncated; metrics are saved; an evaluation function that returns a bare
  number gives `error`.

### Step 1.11. The cascade
- **Builds.** `evaluate_stage1`, `evaluate_stage2`, … (or `evaluate` alone, a single stage) and
  `evaluation.thresholds` (D9). Each stage starts a fresh session with its own time limit (D8, D41). Stage k+1 runs
  only if stage k's score reaches the k-th threshold. `merge`: the later score replaces the earlier, metrics are
  merged. A later stage that fails or times out keeps `ok` and records "stage k:" and its error; `InvalidProgram`
  at any stage makes the program `invalid`. `Result.stage_reached`. `checked` refuses, as `error`, anything that
  could not be saved: a score that is not a finite number, metrics that are not finite numbers, feedback that is
  not text (the first plan's P5).
- **From.** openevolve's cascade (`openevolve/openevolve/evaluator.py`).
- **Check.** One test per rule of D9, with small evaluation files in `tests/`; fewer thresholds than stages is
  refused when the evaluator is created.

### Step 1.12. Circle packing, scored exactly as openevolve does
- **Builds.** Circle packing's evaluation becomes a port of openevolve's `examples/circle_packing/evaluator.py` at
  `da3d701`: two stages, threshold 0.5, its checks and tolerance, `InvalidProgram` where openevolve gives 0, and
  feedback for every check (D3, D9, D10). A parity test scores a fixed set of programs and compares the results
  with openevolve's own, recorded once by a script run against the openevolve checkout (the v1 branch's
  `tests/parity/` can be reused).
- **Check.** The parity test. In Docker, openevolve's best program (a sum of 2.635977, 22.7 s per evaluation by
  openevolve's record) must finish each stage within 60 s on one CPU, or the problem file's limits change.

### Step 1.13. Function minimization, and time limits on single calls
- **Builds.** The second problem: openevolve's initial program, its evaluator ported (stage 1: one call of
  `run_search`, limited to 5 s, threshold 1.3; stage 2: 10 calls of 5 s each, reliability scored too; the
  function's value always recomputed from (x, y), Part D, v1 item 4) and its problem file. For it,
  `RemoteFunction.with_timeout(seconds)` and `call_with_timeout` (openevolve's `run_with_timeout`), which raise
  `CallTimeout`, which an evaluator may catch; the next call starts a fresh worker with the program loaded again
  (D8). `StageTimeout` is deliberately not a kind of `CallTimeout` (D76).
- **Check.** Its parity test; a trial over 5 s is skipped in stage 2 and gives `timeout` in stage 1; catching
  `CallTimeout` never hides the stage's limit.

### Milestone 1. The first run in the sandbox
Milestone 0's run again, now in Docker with openevolve's scoring. Look at the counts by status and at the time an
iteration takes, split between the LLM, the container starts and the stages.

---

## Phase 2: the prompt and the LLM

By the end of this phase every LLM call is saved, the prompt is Appendix A's, the LLM describes its programs and
may change only the evolve blocks, children are checked before they cost an evaluation, and the LLM is a weighted
ensemble of models.

### Step 2.1. Every LLM call saved
- **Builds.** `complete` returns an `LLMReply` (`text`, `model`, `input_tokens`, `output_tokens`, `duration`) and
  each child keeps its `LLMUsage` (D35, D60). `llm_calls.jsonl` (D47): the iteration, the program's id, the model,
  the user message, the reply, the tokens, the duration, and the error of a failed call. A first `run.json`: the
  run's id, its seed and the system message, written once (D50; completed in 4.2 and 4.7).
- **Check.** One line per call, failed calls included; token counts, 0 when the server gives none.

### Step 2.2. v1's reply parser
- **Builds.** `extract_code` with v1's rules (D68): thinking sections removed; fenced blocks, else one-line blocks;
  `choose_code_block` keeps the blocks that are valid Python, drops those that are the parent, and takes the
  longest; a block opened but never closed gives everything after its opening.
- **From.** `my-alphaevolve/src/my_alphaevolve/reply_parser.py` and its tests, almost whole.
- **Check.** v1's parser tests.

### Step 2.3. Descriptions
- **Builds.** The reply format asks for a `<DESCRIPTION>` of the program that stands on its own, never mentioning
  another program (D15, Appendix A). `extract_description` and `parse_reply`, which returns a `ParsedReply`
  (`code`, `description`). `Program.description`, shown in the prompt for the parent and each example.
- **Check.** The description found in any letter case; code quoted inside it never taken for the program; a reply
  without a description keeps its code; an empty description is none.

### Step 2.4. Evolve blocks enforced
- **Builds.** `checks.py`: `split_evolve_blocks` and `same_outside_code` (D74); the rule in the system message
  (D12). The new status `rejected`: a child that changes code outside the blocks, or a marker, is stored with the
  reason and never evaluated (D13). The initial program's blocks must split cleanly, or the run refuses to start.
- **Check.** Each way of breaking the markers (moved, removed, added, altered, a start inside a block); a change
  outside the blocks; blank lines and spaces at line ends ignored, spaces at line starts not; a rejected child in
  the end-to-end test.

### Step 2.5. Compiling and entry functions
- **Builds.** `check_child` (D74), with D13's checks in order: no code, or a syntax error; the evolve blocks (2.4);
  every function named by `entry_functions` (a new, required key of the problem file) defined at the top level.
  The initial program is checked against itself.
- **Check.** Each rejection with its reason, in that order.

### Step 2.6. Duplicates
- **Builds.** `fingerprint(tree)`: the SHA-256 of the syntax tree, which comments and spacing do not change;
  `Program.fingerprint`; `Database.fingerprints`, recording those of `ok`, `failed`, `timeout` and `invalid`
  programs. A child whose fingerprint is known is rejected, "same program as" the program that has it (D13, D24).
- **Check.** Comments and spacing leave the fingerprint unchanged; a duplicate of a failed program is rejected, of
  a rejected one not; a child identical to its parent costs no evaluation (Part D, v1 item 6).

### Step 2.7. The prompt of Appendix A
- **Builds.** Both messages exactly as in Appendix A (D25, D27, D29): the rules, "higher scores are better",
  "# Previous attempts" with "Attempt n: score s" (or the status and error of a failed attempt), the parent with
  the best score so far, empty fields left out with their label. `prompt.example_programs` (2, D26) replaces
  Phase 0's constant; the character budget `prompt.max_chars` (60,000) drops examples, last first, with a warning
  (D30).
- **Check.** The exact text of both messages; over the budget, the last example goes first.

### Step 2.8. Model settings and API keys
- **Builds.** In the `llm` section: `api_key: ${VARIABLE}` (`parse_key`; a key written in the file is refused,
  D46); `max_tokens` (16,384), `temperature`, `reasoning_effort`, `reasoning` (guessed from the name when unset,
  `is_reasoning_model`), `timeout` (300 s), `retries` (2) (D32–D34). Settings left unset are not sent; a reasoning
  model gets `max_completion_tokens`, and a temperature set for one is refused when the file is loaded. A
  `problem_claude.yaml` per problem, with Appendix B's main Claude model.
- **From.** v1's fake OpenAI-compatible server (`my-alphaevolve/tests/fake_llm_server.py`), extended to record the
  parameters it receives.
- **Check.** Each setting sent, or not, as it should be; the key read from its variable, with a clear error when
  the variable is not set; by hand, one request to Anthropic's endpoint if `ANTHROPIC_API_KEY` is set.

### Step 2.9. The ensemble
- **Builds.** The `llm` section takes openevolve's layout: shared values, and `models`, each with a `name`, a
  `weight` and any shared key it overrides (`build_llm`, D72). `Ensemble` (D66): `draw()` with the run's generator
  (D31); failures counted per model, and 3 in a row (`llm.max_failures_in_a_row`) drop that model and rescale the
  others' weights; `NoModelLeft` stops the run; `check_all()` sends a one-line request to every model before the
  first iteration (D34). The console line names the model. The problem files get Appendix B's two batches.
- **Check.** Draws in proportion to the weights, with a seeded generator; a dropped model and the rescaled
  weights; `NoModelLeft`; `check_all` stops at the first model that fails.

### Milestone 2. The first run with an ensemble
Batch 1's two models on circle packing. Look in `llm_calls.jsonl`: do replies keep the `<DESCRIPTION>` tags, how
many children are rejected and why (with no repair, D14, each one is a lost iteration), and how big the prompts
are next to Ollama's context: 60,000 characters of prompt plus 16,384 reply tokens may not fit in
`OLLAMA_CONTEXT_LENGTH=32768` (Appendix B).

---

## Phase 3: the database

By the end of this phase the database is the design's: islands, each with a fixed MAP-Elites grid; ShinkaEvolve's
parent rule over each island's elites; example programs drawn from the island, failed ones included; migrations
between islands; and openevolve's rule as an option.

### Step 3.1. ShinkaEvolve's parent rule
- **Builds.** `ParentSelector` and `WeightedSelector` (D75), for now over all the working programs: each weighted
  by sigmoid(λ × (score − median) / spread) × 1 / (1 + children). The spread is the median absolute deviation, or
  the standard deviation if that is 0; when both are 0, every sigmoid term is 0.5 (D19). `Database.children`:
  every `llm` child counts, whatever its status, except `error`. The `parents` section: `strategy` (`weighted`
  only, for now) and `lambda` (1).
- **From.** `WeightedSamplingStrategy` in `ShinkaEvolve/shinka/database/parents.py`, with λ = 1 instead of 10.
- **Check.** On a made-up population, the draw frequencies match the formula; both spread fallbacks; which
  children count.

### Step 3.2. Example programs, as designed
- **Builds.** `sample_examples` (D26): drawn among every program, failed ones included, except the parent,
  `error` programs and children without code; without replacement, shown in the order drawn, unlabelled.
  `Program.example_ids` (D60).
- **Check.** The excluded kinds are never drawn; a failed example shows its status and its error.

### Step 3.3. Islands
- **Builds.** `Island` (`index`, `program_ids`, D62) and `islands.count` (3, D23). The initial program belongs to
  no island; each island starts with a copy of it (`Program.origin`: `initial`, `llm` or `copy`;
  `Program.island`; `copy_to`; `seed_islands`, D60, D63). Each iteration draws an island uniformly; the parent and
  the examples come from it, and the child lives on it. The console line shows the island.
- **Not yet.** Grids (3.4); migration (3.6): until then, the islands evolve apart.
- **Check.** Draws stay on the iteration's island; a copy never replaces the initial program as the best; a
  copy's children count for that copy.

### Step 3.4. MAP-Elites grids on code complexity
- **Builds.** `count_block_nodes`, the syntax-tree nodes inside the evolve blocks (D17, D74), and
  `Program.code_complexity`. `grid.py`: `Grid` (D61), with fixed bins: `feature_values` (log2 of the ratio to the
  initial program, D18), `cell_of` (a value out of range goes to the nearest end bin), `place` (a cell is taken
  when empty, or by a strictly higher score), `elite_list` in cell order, `best`. One grid per island; an island's
  population becomes its elites, and parents are drawn among them (D23). The `grid` section; by default
  `code_complexity` from −1 to +3, in 10 bins.
- **From.** openevolve's MAP-Elites (`_calculate_feature_coords` in `openevolve/openevolve/database.py`), but with
  bins fixed when the run starts (Part D, openevolve item 6).
- **Check.** Bins at the edges and out of range; only nodes inside the blocks counted; a displaced elite stays in
  the database and can still be an example; elites listed in cell order, so that draws repeat.

### Step 3.5. Output features
- **Builds.** `StageResult.features` and `Result.features`, from stage 1 only (D9, D17): every output feature the
  problem names must be there and finite, or the result is `error`. Circle packing's `radii_spread` and
  `radius_centre_correlation`; 2D and 3D grids, with 5 and 3 bins per feature by default (D18).
- **Check.** Features from stage 1 only; a missing one gives `error`; the initial program's two features; a cell
  of a 3D grid.

### Step 3.6. Migration
- **Builds.** `Database.migrate` (D63), every `islands.migration_interval` (25) completed iterations: on each
  island, 10% of its elites (at least one), drawn among those other than its best, are copied to every other
  island, where a copy takes its cell only if the cell is empty or holds a lower score (D23). Migrants are stored
  like any program. Settings: `migration_share`, `migrants` (`random_non_best`, `best`, `random`), `destinations`
  (`all_others`, `ring`), `mode` (`copy`, or `move`: origin `move`, the program leaves its grid and keeps its
  children count).
- **From.** openevolve's `migrate_programs`; ShinkaEvolve's moves and its protection of each island's best.
- **Check.** Each setting; at least one migrant per island; an arrival does not migrate again in the same round.

### Step 3.7. openevolve's parent rule and the archive
- **Builds.** `Database.archive(k)` (D21): the k best `ok` programs, copies of one program counted once (by
  fingerprint). `OpenEvolveSelector` (D75): 20% uniform among the island's elites, 70% among the archive's
  programs made on this island (or the whole archive if none was), 10% in proportion to the score.
  `parents.strategy: openevolve` and `parents.archive_size` (10).
- **From.** `sample_from_island` in `openevolve/openevolve/database.py`.
- **Check.** The three branches' frequencies; copies counted once; the whole archive when none of it is from the
  island; the child lives on the iteration's island even when its parent comes from another.

### Milestone 3. The first run with the whole database
Milestone 2's run with three islands, the default grid and the weighted rule. Milestones 2 and 3 differ only in
the database, so they are a first, rough look at what it brings.

---

## Phase 4: the run

By the end of this phase runs use several workers, survive a crash or Ctrl+C and can be continued, stop on a
target score or when they stall, and leave a report.

### Step 4.1. Logging and the summary
- **Builds.** `logs.py`: `setup_logging(folder, verbose)` (D78). The console shows messages alone, `--verbose`
  adds details, `log.txt` in the run folder gets everything with timestamps; every `print` becomes a logger call;
  the console line of D52. The end-of-run summary (D51): iterations done, why the run stopped, the best score and
  its iteration, the counts by status, and the tokens and cost per model (`price_input`, `price_output` in the
  `llm` section, D35).
- **Check.** `log.txt` gets the details the console leaves out; no API key appears in any output.

### Step 4.2. The complete run folder
- **Builds.** `storage.py`: `Storage` (D69), whose appends reach the disk before returning. `history.csv`, one row
  per completed iteration, skipped ones included (`HistoryRow`); a snapshot of the best program in
  `best/iteration_0000.py`, then every `snapshot_every` (10) completed iterations; `best_program.py` with its
  header (score, iteration, id, description); `problem.yaml`, a copy of the problem file; `run.json` written whole
  or not at all, with one record per session; `Program.created_at`; the default `--output`,
  `runs/<name>_<date>_<time>` (D45, D47).
- **From.** `RunStorage` in `my-alphaevolve/src/my_alphaevolve/storage.py`.
- **Check.** v1's storage tests; `best_program.py` has the program's fingerprint (its header is comments only); a
  crash while writing `run.json` leaves the previous one.

### Step 4.3. Several iterations at once
- **Builds.** `WorkerPool` (D70): `--workers` daemon threads. Each iteration alternates between threads (D36): the
  main thread draws and builds the prompt; a worker asks the LLM and parses the reply; the main thread runs the
  checks, so that the duplicate check sees every stored program; a worker evaluates; the main thread stores. Only
  the main thread uses the database and the run folder, and it waits in steps of 0.2 s, so that Ctrl+C reaches it
  on Windows too (D53). `IterationState` and `Context` hold what an iteration and the run need. See P2.
- **Check.** Several iterations in flight at once (with a fake LLM that waits); one worker and one seed repeat
  the same draws.

### Step 4.4. Errors inside an iteration
- **Builds.** D38: an unexpected exception that is not the program's fault gives the child `error`, or, before a
  child exists, records the iteration as `error`; `max_errors_in_a_row` (3) stops the run; a failed LLM call
  records the iteration as `skipped`, and it still counts as completed (D34); an exception in the main thread
  itself stops the run at once.
- **Check.** 3 errors in a row stop the run; a skipped iteration counts; the LLM's failures and the errors are
  counted apart.

### Step 4.5. Ctrl+C and SIGTERM
- **Builds.** D53: the first Ctrl+C lets the iterations in flight finish and be saved, then ends the run with its
  summary. D54: a second Ctrl+C, or SIGTERM on Linux, removes the containers and returns without waiting for the
  worker threads; the session is recorded as interrupted. `scripts/run.py`'s `main()`: UTF-8 console output, and
  a problem, sandbox or configuration error shown as one message with exit code 1, without a traceback (D79).
- **From.** v1's Ctrl+C handling and its tests (`my-alphaevolve/src/my_alphaevolve/loop.py`), without Part D's v1
  items 1 and 2.
- **Check.** One Ctrl+C saves the iterations in flight; a second exits within seconds while an LLM call is still
  waiting; SIGTERM does the same.

### Step 4.6. Continuing a run
- **Builds.** D49: the same command with the same `--output` continues the run. `Program.from_dict`; the saved
  programs added again in order (`Database.replay`); completed iterations counted from `history.csv`, with
  `--iterations` a total; the initial program not evaluated again; a last line cut off by a crash dropped; the
  generator reseeded from the seed and the number of programs (D39). See P3.
- **Check.** An interrupted run is finished by the same command; a larger `--iterations` extends it; the draws
  after resuming are not the run's first draws again (Part D, v1 item 9).

### Step 4.7. Refusing to continue a changed problem
- **Builds.** D50: fingerprints in `run.json` of the initial program, the evaluation file, the problem file
  without its `llm` section (`fingerprint_without_llm`) and the image; a changed one stops the run, saying which;
  the `llm` section and the flags may change. Each session's record: its times, the git commit, the command line,
  the `llm` section, the flags, the system message, how it ended.
- **Check.** A changed evaluation file or description stops the run; a changed `llm` section does not.

### Step 4.8. Target score and patience
- **Builds.** `--target-score` and `--patience` in `should_stop` (D37), with `Database.best_changed_at`. See P4.
- **Check.** The run stops once the target is reached, and after that many completed iterations without a better
  best, skipped ones included; patience still counts correctly after a resume.

### Step 4.9. The report: progress and drawings
- **Builds.** `report.py` and `scripts/report.py RUN_FOLDER` (D51, D79): `load_run`; `plot_progress`, the best
  score so far against completed iterations, with every `ok` child's score as a dot. `output_data` in
  `StageResult` and `Result` (D6): circle packing's stage 1 returns the centres and radii, and its evaluation file
  defines `visualize(output_data, path)`; `draw_outputs` draws the best program's packing at every snapshot.
- **Check.** The report runs on a run folder written by the end-to-end test and writes its files.

### Step 4.10. The report: grids
- **Builds.** `grid_snapshots` (the run replayed, its snapshots placed by the history's counts, after skipped
  iterations too); `colour_scale`; `draw_grids` (1D, 2D, and 3D as one square per bin of the third feature);
  `animate`, a GIF of the grids over the run.
- **Check.** Snapshots at the right counts; a 3D grid drawn.

### Milestone 4. The whole design
Runs of both problems with several workers, one of them interrupted and continued, and their reports.

---

## Phase 5: the experiments

### Step 5.1. Function minimization
A cheap check of the whole system before the long runs: runs should find the region of the global minimum (scores
near 1.5), as openevolve's do.

### Step 5.2. Baselines with the same models
openevolve's published circle-packing results came from other models (its configs name Gemini 2.0 Flash with
Claude 3.7 Sonnet), so only runs with the same models compare like with like (D3). Run openevolve (the checkout,
at `da3d701`) on circle packing with batch 1's and batch 2's ensembles and openevolve's phase-1 settings
otherwise, for as many iterations as my-evolve's runs; ShinkaEvolve too, if wanted (its circle-packing presets run
200 generations, with 2 islands and λ = 10). These runs need only the reference checkouts, so they can start at
any time, even during Phase 0.

### Step 5.3. Circle packing
- **Runs.** Batch 1 first (local, so only time counts), then batch 2 (paid; its cost per iteration is known from
  the token counts of earlier runs, D35). The milestones' timings set the run lengths. For scale, openevolve's
  README reports a sum of 2.634 "in about 800 generations", and 2.635977 at iteration 206 of a 450-iteration run
  in three sessions (see P1).
- **Comparison.** The best score against completed iterations, which counts LLM calls in all three systems (D3);
  several seeds per configuration, since one run of an LLM search proves little.
- **Ablations**, which need no new code, since each is a setting of the problem file: the weighted rule against
  openevolve's (`parents.strategy`); λ = 1 against ShinkaEvolve's 10; the 1D grid against a 2D one with
  `radii_spread`; two example programs against none; three islands against one.

---

## Points the design leaves open

Carried over from the first plan, each with a proposed answer and the step where it is settled. That plan's P5
(results that cannot be saved) is now part of step 1.11, and its P6 (the problems' descriptions) part of step 0.2.

**P1. Circle packing's two phases** (before 5.3). openevolve's best results switch from `config_phase_1.yaml` to
`config_phase_2.yaml`, whose system message differs, after 100 iterations, keeping the population. my-evolve
refuses to continue a run whose description changed (D50). Proposed: compare single-phase runs, with phase 1's
description, first. If a second phase proves worth having, let the description change between sessions as the
`llm` section may: it changes the prompts, not the scores, and each session's description is recorded in
`run.json`.

**P2. Identical children in flight** (step 4.3). With several workers, the duplicate check (D13) sees only stored
programs, so two identical children in flight at the same time are both evaluated. Proposed: the main thread also
holds the fingerprints of the children being evaluated, and lets one go if its child ends as `error`.

**P3. A child saved without its history row** (step 4.6). A crash between the child's line in `programs.jsonl`
and its row in `history.csv` leaves a stored child whose iteration is done again on resume (two children with one
iteration number), and which the report cannot place. Proposed: on resume, programs at the end of
`programs.jsonl` whose iteration has no row in `history.csv` are dropped with their LLM-call lines, as a cut-off
line is, and `best_program.py` is rewritten from the rebuilt database.

**P4. Patience after a resume** (step 4.8). `replay` adds the saved programs without the completed count at which
each was added (D63), so `best_changed_at` is lost and `--patience` could stop a resumed run at once. Proposed:
`replay` takes each child's completed count from `history.csv`, as the report's `grid_snapshots` does (D79).

---

## Where each decision is built

| Decisions | Steps |
|---|---|
| D1 (a small core first) | Phase 0 |
| D2 (Python only), D14 (no repair), D24 (exact duplicates only), D28 (no run-level advice) | nothing to build |
| D3 (comparability with openevolve) | 0.2, 1.12, 1.13, Phase 5 |
| D4 (the description) | 0.2, 0.3 |
| D5 (the namespace) | 0.4 (a dictionary), 1.3 (the stand-in) |
| D6, D73 (results) | 0.3, 1.1, 1.10, 1.11, 3.5, 4.9 |
| D7 (statuses) | 1.1, 1.3, 1.4, 2.4 |
| D8 (where the program and the evaluator run) | 1.2, 1.3, 1.6, 1.11, 1.13 |
| D9 (the cascade) | 1.11, 1.12, 3.5 |
| D10 (feedback) | 1.5, 1.10, 1.12 |
| D11 (full rewrites) | 0.7 |
| D12, D13, D74 (evolve blocks and the checks) | 2.4, 2.5, 2.6, 3.4 |
| D15 (descriptions) | 2.3 |
| D16–D18, D61 (MAP-Elites) | 3.4, 3.5 |
| D19, D75 (choosing a parent) | 0.5, 3.1, 3.7 |
| D20 (the initial program must work) | 0.8, 2.4, 2.5 |
| D21 (the archive) | 3.7 |
| D22 (every program kept) | 0.5 |
| D23, D62 (islands) | 3.3, 3.4, 3.6 |
| D25–D27, D29, D30, D67 (the prompt) | 0.6, 1.10, 2.3, 2.7, 3.2 |
| D31, D66 (models and the ensemble) | 0.7, 2.1, 2.9 |
| D32, D33, D46 (client, generation settings, keys) | 0.7, 2.8 |
| D34 (retries and LLM failures) | 0.7, 0.8, 2.9, 4.4 |
| D35 (cost accounting) | 2.1, 4.1 |
| D36, D70 (the loop and its threads) | 0.8, 4.3, 4.4, 4.5 |
| D37 (when a run stops) | 0.8, 2.9, 4.4, 4.8 |
| D38 (errors inside an iteration) | 4.4 |
| D39 (randomness) | 0.5, 4.6 |
| D40–D42, D64 (the sandbox) | 1.3, 1.4, 1.5, 1.8, 1.9 |
| D71 (packages) | 1.7 |
| D43, D44, D72 (the problem file) | 0.3, then every step that adds a setting |
| D45 (the command line) | 0.8, 1.8, 4.2, 4.3, 4.8 |
| D47, D48, D69 (the run folder) | 0.8, 2.1, 4.2 |
| D49 (continuing a run) | 4.6 |
| D50 (run information and safety checks) | 2.1, 4.2, 4.7 |
| D51, D79 (outputs, the scripts and the report) | 0.8, 4.1, 4.5, 4.9, 4.10 |
| D52, D78 (logging) | 4.1 |
| D53, D54 (Ctrl+C and SIGTERM) | 4.3, 4.5 |
| D55–D58 (platforms, layout, tools, style) | 0.1, and every step |
| D59 (how the plan is carried out) | this plan |
| D60 (`Program`) | 0.3, 2.1, 2.3, 2.6, 3.2, 3.3, 3.4, 4.2, 4.6 |
| D63 (`Database`) | 0.5, 2.6, 3.1–3.7, 4.6, 4.8 |
| D65 (`Evaluator`) | 0.4, 1.1, 1.3, 1.10, 1.11 |
| D68 (reply parsing) | 0.7, 2.2, 2.3 |
| D76 (the evaluation API) | 1.1, 1.3, 1.4, 1.10, 1.13, 3.5 |
| D77 (the sandbox protocol and worker) | 1.2, 1.6 |
