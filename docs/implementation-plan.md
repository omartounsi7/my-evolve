# Implementation plan for my-evolve

The order in which my-evolve is built from [design-decisions.md](design-decisions.md). What each step builds is
specified by the decisions it cites (D1 to D79); this plan adds the order, the limits of each step, what each
step takes from the three reference repositories, and the tests that show it works. It changes nothing in the
design, except six points the design leaves open, each with a proposed answer (P1 to P6, at the end).

Read against: design-decisions.md and [differences.md](differences.md) at `bf6b6de`; my-alphaevolve ("v1") at
`4a1e438`; openevolve at `da3d701`; ShinkaEvolve at `8adc053`.

## How the steps are carried out

- **Design first** (D59). Before a step's code is written, its design is posted for review: the functions and
  classes it adds, any detail the decisions leave open, and its tests. The code is written once you agree.
- **Always working.** A step ends with ruff (lint and format), mypy in strict mode and every test passing (D57);
  tests that need Docker are skipped without it, as in v1. The code has v1's plain-English docstrings and
  comments (D58). You review the diff, and the step becomes one commit.
- **The design stays true.** A decision that changes during the build is changed in design-decisions.md in the
  same commit.
- **Settings arrive with their feature.** Step 2 builds the core sections of the problem file at once: every one
  of them is in use by the end of Phase 1, before anything is run. After that, each step adds the settings it
  needs, so a runnable my-evolve never accepts a key it ignores (D44; differences.md Part D, openevolve item 9).
- **Platforms** (D55). The code avoids anything specific to one system. This machine tests Linux; Windows is
  tested at the two milestones, if a Windows machine is at hand.

## Overview

Phase 1 builds a core that runs end to end (D1): v1's features on my-evolve's architecture (the problem file, the
six statuses, the checks before evaluation, the evaluator on the host with its cascade, the sandbox protocol),
with a weighted model ensemble and ShinkaEvolve's parent rule, but one island, no grid and no example programs.
Phase 2 adds those, one component per step. Phase 3 runs the experiments.

| Step | Builds | Decisions |
|---|---|---|
| **Phase 1** | **The core** | |
| 0 | Project skeleton | D55–D58 |
| 1 | `program.py`: statuses, results, programs | D6, D7, D60, D73 |
| 2 | `problem.py`: the problem file's core sections | D4, D43, D44, D46, D71, D72 |
| 3 | `checks.py`, and openevolve's initial programs | D3, D12, D13, D17, D74 |
| 4 | `reply_parser.py` | D11, D15, D68 |
| 5 | `sandbox_protocol.py`, `sandbox_worker.py` | D8, D77 |
| 6 | `sandbox.py` (local), `evaluation_api.py` | D5, D8, D40, D64, D76 |
| 7 | `sandbox.py` (Docker), `evaluation.Dockerfile` | D40–D42, D71 |
| 8 | `evaluator.py`, with the cascade | D7, D9, D10, D65 |
| 9 | The two problems, checked against openevolve's scores | D3, D4, D9, D10, D17, D41 |
| 10 | `prompt.py`, with the parent only | D12, D25, D27, D29, D67 |
| 11 | `llm.py`: the client and the ensemble | D31–D35, D46, D66 |
| 12 | `storage.py`, `logs.py` | D47, D48, D52, D69, D78 |
| 13 | `database.py`: one island, weighted parent choice | D19, D22, D62, D63, D75 |
| 14 | `loop.py` | D20, D34, D36–D39, D70 |
| 15 | `scripts/run.py`; Ctrl+C and SIGTERM | D45, D53–D55, D79 |
| 16 | Continuing a run | D39, D49, D50 |
| M1 | First real runs | |
| **Phase 2** | **The components** | |
| 17 | Example programs in the prompt | D26, D30, D67 |
| 18 | MAP-Elites grids | D16–D18, D23, D61 |
| 19 | Islands and migration | D19, D23, D63 |
| 20 | Target score and patience | D37 |
| 21 | openevolve's parent rule and the archive | D19, D21, D75 |
| 22 | The report | D51, D79 |
| M2 | The whole design, run again | |
| **Phase 3** | **The experiments** | |
| 23 | Function minimization runs | D3 |
| 24 | Baselines: openevolve with the same models | D3 |
| 25 | Circle packing runs | D3, Appendix B |

Two components come in Phase 1 rather than Phase 2, because adding them later would mean rewriting what Phase 1
builds: the cascade (step 8), since the evaluation files of step 9 are written with stages; and the ensemble
(step 11), since the loop always draws its model from one (D66). D2, D14, D24 and D28 decide what my-evolve does
without (other languages, repairs, embeddings, run-level advice) and need no step.

Step 9 is the first point where real programs are scored in the sandbox; after step 16, the whole system runs.

---

## Phase 1: the core

### Step 0. Project skeleton
- **Builds.** `pyproject.toml` (package `my_evolve` in `src/`; Python 3.11 or later; dependencies `openai` and
  `pyyaml`, plus numpy and matplotlib for the host's evaluation files and report; ruff and mypy settings from v1,
  with `py311` as target); an empty `src/my_evolve/__init__.py`; v1's `tests/docker_check.py`; a README with the
  setup and everyday commands for Linux and Windows; `runs/` added to `.gitignore`.
- **Done when** `pip install -e ".[dev]"` works and ruff, mypy and `unittest` pass on the empty package.

### Step 1. Statuses, results and programs (`program.py`)
- **Builds.** D73 and D60 in full: `Status`; `Result` with `rejected`, `failure`, `is_ok`, `to_dict`,
  `from_dict`; `LLMUsage`; `Program` with `to_dict`, `from_dict`, `new_child`, `copy_to`.
- **From v1.** `Program`'s dictionary round trip; UUIDs as ids.
- **Tests.** Every status survives a round trip; a missing score is written `null`, never `-Infinity` (Part D,
  v1 item 5); a missing key is an error that names it; `new_child` and `copy_to` set origin, parent and
  generation as D60 says.

### Step 2. The problem file: core sections (`problem.py`)
- **Builds.** `Problem.load` and `from_dict`, with every section Phase 1 uses: the top level (`name`,
  `description`, `entry_functions`, `packages`, `snapshot_every`, `max_errors_in_a_row`), `evaluation`,
  `sandbox`, `prompt.max_feedback_chars`, `parents` (`strategy`, with only `weighted` for now, and `lambda`), and
  the whole `llm` section (`build_llm`, `parse_key`, and `is_reasoning_model`, which this step creates in
  `llm.py`, D66). Unknown keys refused with their location; `fingerprint_without_llm`.
- **From v1.** The refusal of pip options in the package list, made stricter: `name==version` only (D71).
- **From openevolve.** The layout of the `llm` section; `${VAR}` for keys.
- **Tests.** Each check of `from_dict` and `build_llm`: unknown keys at every level, a key written in the file, a
  reasoning model with a temperature, a model's own value overriding the shared one, the defaults; the
  fingerprint changes with every setting except those of `llm`.

### Step 3. Evolve blocks and the checks (`checks.py`)
- **Builds.** D74 in full: `split_evolve_blocks`, `same_outside_code`, `defined_functions`, `fingerprint`,
  `count_block_nodes`, `check_child`. openevolve's two initial programs are copied unchanged into
  `examples/circle_packing/` and `examples/function_minimization/`, with openevolve's licence and the commit they
  come from (D3).
- **From v1.** Comparing programs by syntax tree (`is_same_program`), now kept as a SHA-256 hash.
- **From ShinkaEvolve.** Rejecting edits outside the blocks; my-evolve also compares the markers.
- **Tests**, on both initial programs. Each way of breaking the markers (moved, removed, added, altered, a start
  inside a block); a change outside the blocks; blank lines and spaces at line ends ignored, spaces at line starts
  not; a missing entry function; comments and spacing leave the fingerprint unchanged; only nodes inside the blocks
  are counted.

### Step 4. Reply parsing (`reply_parser.py`)
- **Builds.** D68: `ParsedReply`, `parse_reply`, `extract_description`, `extract_code`, `choose_code_block`.
- **From v1.** `reply_parser.py` almost whole (its patterns, and the three rules of `choose_code_block`) with its
  tests; `make_child_program` goes, since children are made by `Program.new_child`.
- **Tests.** v1's parser tests; the description found in any letter case; code quoted inside the description never
  taken for the program; a reply without a description still gives its code; an empty description is none.

### Step 5. The sandbox protocol and its worker (`sandbox_protocol.py`, `sandbox_worker.py`)
- **Builds.** D77: `encode`, `decode`, `NotPlainData`, `send`, `receive`, and the worker run as
  `python -m my_evolve.sandbox_worker`. Neither module imports anything but the standard library and, when it is
  installed, numpy (section 14.1).
- **Tests.** Round trips of every kind of value (tuples inside lists, non-finite floats, integer and float arrays of
  any shape) and refusal of the others. Then the worker as a plain subprocess, driven through its pipes: names and
  kinds in `loaded`; `return`, and `raised` with the traceback; a program's `if __name__ == "__main__":` part not
  run; its prints sent to the error output; `sys.exit` while loading gives `load_failed`; a return value that is
  not plain data gives `raised`.

### Step 6. The local sandbox and the evaluation API (`sandbox.py`, `evaluation_api.py`)
- **Builds.** D64 without Docker: `Sandbox`, `LocalSandbox`, `SandboxSession`, `ProgramNamespace`,
  `RemoteFunction`, `SandboxError`. D76: `StageResult`, `InvalidProgram`, `ProgramFailure`, `CallTimeout`,
  `StageTimeout`, `call_with_timeout`.
- **From v1.** The explanation of a process that ends without an answer (exit code 137: "most likely too much
  memory").
- **Tests**, all without Docker. A call's value comes back decoded; an exception in the program becomes a
  `ProgramFailure` with its traceback and the end of the error output; a call over its own limit raises
  `CallTimeout`, and the next call runs in a fresh process with the program loaded again; the stage's deadline
  raises `StageTimeout`, which catching `CallTimeout` does not hide; a worker that dies (`os._exit`) or a missing
  name gives a `ProgramFailure`; a forged `return` line with an unknown id is ignored (the attack of Part D, v1
  item 3); a program that prints without end fills a file, not memory.

### Step 7. The Docker sandbox (`sandbox.py`, `evaluation.Dockerfile`)
- **Builds.** `DockerSandbox` with `ensure_image`, `command`, `stop` and `remove_leftovers` (D64): the limits of
  D41, the thread variables, the run's label, and the worker under its own time limit, 10 s longer than the
  stage's (D42).
- **From v1.** `evaluation.Dockerfile` (the problem's folder is no longer mounted: the evaluation file stays on
  the host); the `docker run` options; the image tag hashed from the Dockerfile and the packages; the check that
  Docker is installed and running.
- **Tests**, skipped without Docker. v1's isolation tests on the new sandbox (no network; nothing writable but
  `/tmp`; the memory limit; a program that never ends stopped with everything it started; text outside plain
  English); the listed packages importable, others not; no environment variable of the host visible; no container
  left after `kill`; `remove_leftovers` removes the run's containers and no others; a container stops on its own
  when the host process that started it is killed.

### Step 8. The evaluator and its cascade (`evaluator.py`)
- **Builds.** D65 in full: loading the evaluation file and its stages; `evaluate(code)`, which turns every outcome
  into a `Result`; `run_stage`, `checked`, `merge`. Output features are checked from step 18 on, once problems name
  some. See P5.
- **From v1.** The loader of evaluation files (helper files next to it importable, then forgotten); the checks on
  the score (a finite number, not a boolean).
- **From openevolve.** The cascade's rules: a stage's score must reach its threshold for the next stage to run; a
  later stage's metrics replace those with the same name; a later stage that fails keeps the earlier result.
- **Tests**, with small evaluation files in `tests/` and the local sandbox. One test per status of D7 and per rule
  of D9 (a later stage failing or timing out keeps `ok` and records "stage k:" with its error; an
  `InvalidProgram` at stage 2 makes the program `invalid`; a score below the threshold ends the cascade; features
  from stage 1 only); the evaluation file raising, or a `SandboxError`, gives `error`; fewer thresholds than stages
  is refused when the evaluator is created.

### Step 9. The two problems (`examples/`)
- **Builds.** The evaluation files: ports of openevolve's two evaluators at `da3d701`, as stage functions that
  receive the namespace, raise `InvalidProgram` with the reason, and write feedback for each check (D10). Function
  minimization's stage 2 limits each of its 10 calls to 5 s with `call_with_timeout`, and always recomputes the
  function's value from (x, y). Circle packing's stage 1 also returns its two features (D17) and its output data
  (centres and radii), used from steps 18 and 22. The problem files: description (P6), entry functions, packages at
  v1's versions, 60 s per stage, thresholds 0.5 (circle packing) and 1.3 (function minimization), and Appendix B's
  batch 1 as `llm` section; batch 2 in a second problem file per problem, differing only in that section.
- **From v1.** The scoring code of its two evaluation files, brought up to `da3d701`.
- **Tests.** A parity test scores a fixed set of programs (both initial programs, openevolve's best circle-packing
  program, programs whose `run_search` returns fixed points, programs breaking each rule) and compares the results
  with what openevolve's own evaluators give them: the same score for every working program, and `invalid` or
  `failed` where openevolve gives 0 (D3). openevolve's results are recorded once by a small script run against the
  openevolve checkout; the tests themselves do not need openevolve. In Docker: both initial programs evaluate `ok`
  (circle packing: 0.364, a sum of about 0.959).
- **To watch.** openevolve's best circle-packing program (a sum of 2.635977) took 22.7 s per evaluation, by
  openevolve's record of it (`best_program_info.json`). It must finish each stage within 60 s on the sandbox's one
  CPU, or D41's limits need changing in the problem file.

### Step 10. The prompt, with the parent only (`prompt.py`)
- **Builds.** D67 without example programs: the system message, the parent's section and the request, as in
  Appendix A; `program_section` and `truncated`.
- **From v1.** The sentence naming the allowed packages; the test that braces in code and descriptions are kept as
  written.
- **Tests.** The exact text of both messages for a fixed problem and parent; empty fields left out with their
  labels; feedback and errors truncated; package names without versions, and "nothing else" when there are none.

### Step 11. The LLM client and the ensemble (`llm.py`)
- **Builds.** D66 in full: `LLMReply`, `LLMError`, `NoModelLeft`, `LLM`, `OpenAICompatibleLLM` (`complete`,
  `check`), `Ensemble` (`draw`, `record_success`, `record_failure`, `check_all`).
- **From v1.** `OpenAICompatibleLLM` (the `openai` package imported only when needed, one layer of retries, an
  empty reply as an `LLMError`), and the fake OpenAI-compatible server of its tests, extended to receive system
  messages, return token counts and record every parameter sent.
- **From openevolve.** The weighted ensemble; the name prefixes of reasoning models.
- **Tests.** v1's LLM tests; a reasoning model gets `max_completion_tokens` and `reasoning_effort`, never a
  temperature; settings left unset are not sent; token counts, 0 when the server sends none; the key read from the
  variable `${VAR}` names, with a clear error when that variable is not set; draws in proportion to the weights,
  with a seeded generator; 3 failures in a row drop a model and rescale the others; `NoModelLeft`; `check_all`
  stops at the first model that fails.
- **Done when**, besides the tests, `check()` succeeds against the local Ollama server, and against Anthropic's
  endpoint if `ANTHROPIC_API_KEY` is set (one request each, run by hand).

### Step 12. The run folder and logging (`storage.py`, `logs.py`)
- **Builds.** D69 and D78: `RunInfo`, `HistoryRow`, `Storage` (appends that reach the disk before returning,
  `best_program.py`, the snapshots in `best/`, the copy of the problem file, `run.json` written whole or not at all,
  `load_programs` and `load_history` dropping a cut-off last line), the records of `llm_calls.jsonl`,
  `setup_logging`.
- **From v1.** `RunStorage`: appending JSON lines, dropping a last line cut off by a crash, the header of
  `best_program.py`.
- **Tests.** v1's storage tests; history rows survive a round trip; `best_program.py`, with a description of several
  lines in its header, has the same fingerprint as the program (the header is comments only); a crash while writing
  `run.json` leaves the previous file; `log.txt` gets the details the console leaves out.

### Step 13. The database, core (`database.py`)
- **Builds.** D63 for one island and no grid: `Island` (until step 18, its population is every `ok` program made
  on it), `WeightedSelector` (D75), and `Database` with `add`, `seed_islands`, `best`, `children_count`,
  `sample_parent` and `replay`.
- **From ShinkaEvolve.** The weighted rule of `database/parents.py`, with my-evolve's λ = 1 and its fallbacks
  when the spread is 0 (D19).
- **Tests.** `add`'s rules (fingerprints recorded for `ok`, `failed`, `timeout` and `invalid` programs only;
  children counted for `llm` children that are not `error`; the best replaced only by a strictly higher score);
  failed programs never drawn; draw frequencies on a made-up population match sigmoid × 1 / (1 + children); both
  spread fallbacks; `replay` of saved programs rebuilds the same state.

### Step 14. The loop (`loop.py`)
- **Builds.** D70 for a new run: `RunSettings`, `WorkerPool`, `IterationState`, `Context`, `run`, `prepare`,
  `evaluate_initial`, `start_iteration`, `propose`, `after_proposal`, `finish`, `skip`, `after_completion` (the
  snapshots; migrations come in step 19), `should_stop` (errors in a row, no model left), `summary`. The largest
  step. See P2.
- **From v1.** The main thread waiting in 0.2 s steps (D53); the structure of its loop tests.
- **Tests**, with the fake LLM server, the local sandbox and a tiny test problem. A run refuses to start unless the
  initial program is `ok`; one child per iteration, each status stored with its reason; a failed LLM call skips its
  iteration, which still counts; an error inside the framework gives `error`, and 3 in a row stop the run; several
  workers run at once while only the main thread writes; one worker and one seed repeat the same draws; the run
  folder holds every file of D47.

### Step 15. The command line, Ctrl+C and SIGTERM (`scripts/run.py`, `loop.py`)
- **Builds.** D79's `parse_arguments`, `default_output` and `main`; in `run`, D53 (the first Ctrl+C finishes the
  iterations in flight) and D54 (a second Ctrl+C, or SIGTERM, removes the containers and returns at once without
  waiting for the worker threads); the end of the session recorded in `run.json`.
- **From v1.** `scripts/run.py` (UTF-8 console output, checked arguments) and its Ctrl+C tests.
- **Tests.** The script runs the test problem end to end; wrong values are usage errors; a problem or configuration
  error is one message and exit code 1, without a traceback; the API key appears in no output and no file; one
  Ctrl+C saves the iterations in flight; a second one exits within seconds while an LLM call is still waiting
  (Part D, v1 item 1); SIGTERM does the same on Linux.

### Step 16. Continuing a run (`loop.py`, `storage.py`)
- **Builds.** D49 and D50: `prepare` for a folder that holds a run (programs and history loaded, the generator
  reseeded from the seed and the number of programs, `replay`); the fingerprints in `run.json`, and the refusal to
  continue when one has changed, saying which; one session record per launch; `--iterations` as a total. See P3.
- **Tests.** An interrupted run is finished by the same command; a larger `--iterations` extends it; the initial
  program is not evaluated again; the draws after resuming are not the first draws again (Part D, v1 item 9); a
  changed evaluation file or description stops the run, a changed `llm` section does not.

### Milestone 1. First real runs
Short runs (20 to 50 iterations) of both problems in Docker with batch 1's models, one of them interrupted and
continued. They are also a baseline for later: my-evolve without example programs, grids or islands. To look at:
- the prompts and replies in `llm_calls.jsonl`, and whether replies keep the `<DESCRIPTION>` tags;
- how many children are `rejected`, and why: with no repair (D14), each change outside the evolve blocks is a lost
  iteration;
- the size of the prompts: the prompt and the reply share Ollama's context, and D30's 60,000 characters (roughly
  15,000 to 20,000 tokens) plus 16,384 reply tokens can exceed `OLLAMA_CONTEXT_LENGTH=32768` (Appendix B). Several
  workers need `OLLAMA_NUM_PARALLEL`, and each request in parallel needs context memory of its own on the GPU,
  beside the 23 GB of the two models;
- the time an iteration takes, split between the LLM, the container starts and the stages: it decides how long the
  experiments' runs can be.

What these runs teach may change prompt wording or defaults; such changes go into design-decisions.md.

---

## Phase 2: the components

### Step 17. Example programs in the prompt (`database.py`, `prompt.py`)
- **Builds.** `Database.sample_examples` (D26); Appendix A's "Previous attempts" in `PromptBuilder.build`; the
  character budget, which drops examples last first (D30); `example_ids` saved with each child. New settings:
  `prompt.example_programs` (0 allowed, for step 25's ablation) and `prompt.max_chars`.
- **From openevolve and ShinkaEvolve.** Inspirations, changed as D26 says: drawn among every program of the
  island, failed ones included, and not labelled good or bad.
- **Tests.** Examples come only from the iteration's island, and are never the parent, an `error` program or a child
  without code; drawn without replacement and shown in the order drawn; a failed example shows its status and
  error, a working one its score; over the budget, the last example goes first, with a warning; the exact text of
  Appendix A.

### Step 18. MAP-Elites grids (`grid.py`, `database.py`, `evaluator.py`)
- **Builds.** `Grid` (D61); an island's population becomes its grid's elites (D23); `ok` programs placed as they
  are added; `code_complexity` measured against the initial program's node count (D18); the evaluator requires the
  problem's output features at stage 1 (D65). New settings: the `grid` section, with D18's default bins; circle
  packing's problem file names its features.
- **From openevolve.** A MAP-Elites grid per island; but bins fixed when the run starts instead of moving with a
  running minimum and maximum (Part D, openevolve item 6), and features from the evaluator's view of the output.
- **Tests.** Bins at the edges and out of range; a cell taken only by a strictly higher score; a displaced elite
  stays in the database and can still be an example program; elites listed in cell order, so draws repeat; a
  missing or infinite feature gives `error`; `replay` rebuilds the same grids.

### Step 19. Islands and migration (`database.py`, `loop.py`)
- **Builds.** Several islands, each starting with a copy of the initial program; the iteration's island drawn
  uniformly; `migrate` every `migration_interval` completed iterations, its records stored so that a replay repeats
  it (D63). New settings: the `islands` section.
- **From openevolve.** Islands, and periodic copies of a share of each island's population to the others. **From
  ShinkaEvolve.** Moving instead of copying; never sending an island's best (`random_non_best`).
- **Tests.** Each choice of `migrants`, `destinations` and `mode`; at least one migrant per island; arrivals do not
  migrate again in the same round; a copy starts with no children, a move keeps its count and leaves its grid; an
  arrival takes a cell only if it is empty or holds a worse elite; replay after migrations rebuilds the same grids.

### Step 20. Target score and patience (`loop.py`, `scripts/run.py`)
- **Builds.** `--target-score` and `--patience` in `should_stop` (D37), using `best_changed_at`. See P4.
- **From openevolve.** The target score and early stopping.
- **Tests.** The run stops when the target is reached, and after that many completed iterations without a better
  best, skipped ones included; patience still counts correctly after a resume.

### Step 21. openevolve's parent rule and the archive (`database.py`)
- **Builds.** `Database.archive` (D21) and `OpenEvolveSelector` (D75). New settings: `parents.strategy:
  openevolve`, `parents.archive_size`.
- **From openevolve.** `sample_from_island` (20% uniform on the island, 70% from the archive preferring the island,
  10% in proportion to fitness), adapted to grid elites.
- **Tests.** The frequencies of the three branches, with a seeded generator; copies of one program count once in the
  archive; the whole archive is used when none of it was made on the island; the child lives on the iteration's
  island even when its parent comes from another.

### Step 22. The report (`report.py`, `scripts/report.py`, circle packing's `visualize`)
- **Builds.** D79's `load_run`, `plot_progress`, `grid_snapshots`, `colour_scale`, `draw_grids` (1D, 2D and 3D),
  `animate`, `draw_outputs`; circle packing's `visualize(output_data, path)`.
- **From openevolve.** Circle packing's drawing of the circles.
- **Tests.** The report runs on a folder written by a loop test and writes every file of D51; snapshots that follow
  skipped iterations are taken at the right counts; a 3D grid is drawn as one square per bin of its third feature.

### Milestone 2. The whole design, run again
Milestone 1's short runs again, now with two example programs, the default grid and three islands; the report shows
the grids filling and the migrations. Then the experiments.

---

## Phase 3: the experiments

### Step 23. Function minimization
A cheap check of the whole system before the long runs: runs should find the region of the global minimum (scores
near 1.5), as openevolve's do.

### Step 24. Baselines with the same models
openevolve's published circle-packing results came from other models (its configs name Gemini 2.0 Flash with Claude
3.7 Sonnet, or Claude Sonnet 4.5 with Opus 4.5), so only runs with the same models compare like with like (D3).
Run openevolve (the checkout, at `da3d701`) on circle packing with batch 1's and batch 2's ensembles and
openevolve's phase-1 settings otherwise, for
as many iterations as my-evolve's runs; ShinkaEvolve too, if wanted (its circle-packing presets run 200 generations,
with 2 islands and λ = 10). These runs need only the reference checkouts, so they can start any time, even while
Phase 1 is being built.

### Step 25. Circle packing
- **Runs.** Batch 1 first (local, so only time counts), then batch 2 (paid; its cost per iteration is known from the
  token counts of earlier runs, D35). Milestone 1's timings set the run lengths. For scale, openevolve's README
  reports a sum of 2.634 "in about 800 generations" with its default configuration (issue #117), and 2.635977 at
  iteration 206 of a 450-iteration run in three sessions, phase 1 × 100, phase 2 × 100 and phase 2 × 250
  (issue #156); P1 is about those phases.
- **Comparison.** The best score against completed iterations, which counts LLM calls in all three systems (D3);
  several seeds per configuration, since one run of an LLM search proves little.
- **Ablations**, which need no new code since each is a setting of the problem file: the weighted rule against
  openevolve's (`parents.strategy`); λ = 1 against ShinkaEvolve's 10; the 1D grid against a 2D one with
  `radii_spread`; two example programs against none; three islands against one.

---

## Points the design leaves open

Each has a proposed answer, to accept or change; the step named is where it is settled.

**P1. Circle packing's two phases** (before step 25). openevolve's best results switch from `config_phase_1.yaml` to
`config_phase_2.yaml`, whose system message differs, after 100 iterations, keeping the population. my-evolve refuses
to continue a run whose description changed (D50). Proposed: compare single-phase runs, with phase 1's description,
first. If a second phase proves worth having, let the description change between sessions as the `llm` section may:
it changes the prompts, not the scores, and each session's description would be recorded in `run.json`.

**P2. Identical children in flight** (step 14). With several workers, the duplicate check (D13) sees only stored
programs, so two identical children in flight at the same time are both evaluated. Proposed: the main thread also
holds the fingerprints of the children being evaluated, and lets one go if its child ends as `error`.

**P3. A child saved without its history row** (step 16). A crash between the child's line in `programs.jsonl` and its
row in `history.csv` leaves a stored child whose iteration is done again on resume (two children with one iteration
number), and which the report cannot place (D79, `grid_snapshots`). Proposed: on resume, programs at the end of
`programs.jsonl` whose iteration has no row in `history.csv` are dropped with their LLM-call lines, as a cut-off line
is, and `best_program.py` is rewritten from the rebuilt database.

**P4. Patience after a resume** (step 20). `replay` adds the saved programs without the completed count at which each
was added (D63), so `best_changed_at` is lost and `--patience` could stop a resumed run at once. Proposed: `replay`
takes each child's completed count from `history.csv`, as the report's `grid_snapshots` already does (D79).

**P5. Results that cannot be saved** (step 8). `checked` (D65) does not look at metrics or output data: a numpy array
left in `output_data` would make saving the program fail in the main thread, which stops the run (D38), and a NaN
metric would be written as invalid JSON (Part D, v1 item 5). Proposed: `checked` also requires metrics and features
to be finite numbers, feedback to be text, and output data to be plain JSON data; anything else gives `error`
("evaluator: …"), since it is the evaluation file's fault, not the program's.

**P6. The problems' descriptions** (step 9). D4 says where the description lives, not what it says. Proposed, for
comparability with openevolve: the system message of openevolve's config for the problem (`config_phase_1.yaml` for
circle packing, which names the 2.635 target as openevolve's does; `config.yaml` for function minimization),
followed by the contract of the entry function: `run_packing()` returns the centres (an array of shape (26, 2)), the
radii (shape (26,)) and their sum; `run_search()` returns `(x, y)` or `(x, y, value)`.
