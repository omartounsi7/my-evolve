# my-alphaevolve vs openevolve: the differences

What was compared:

- **my-alphaevolve** at `4a1e438` (branch `main`).
- **openevolve** at `da3d701`, the checkout next to it. It includes your two local commits
  (Claude models for function minimization). Your examples were adapted from openevolve
  `30d9752`, which is older than this checkout.

Part A covers the evolution algorithm itself; Part B covers the engineering around it.
Part C lists what exists in only one of the two. Part D lists bugs and surprising behaviours
found while reading; they matter because a redesign should not copy them by accident.

File references point into each repository: `src/my_alphaevolve/...` for yours,
`openevolve/...` for openevolve.

---

## Part A: the evolution algorithm

### A1. Defining a problem

| | my-alphaevolve | openevolve |
|---|---|---|
| Files the user writes | `initial_program.py`, `evaluation.py`, optional `requirements.txt` | `initial_program.<any ext>`, `evaluator.py`, `config.yaml` |
| Problem description for the LLM | Required docstring at the top of the initial program; the run refuses to start without it (`problem.py`) | `prompt.system_message` in the YAML; a generic "expert software developer" message otherwise |
| Part of the program the LLM may change | The whole file | The whole file is shown. `# EVOLVE-BLOCK-START` / `END` markers delimit what *should* change, but no default prompt mentions them; they are enforced only with `enforce_evolve_blocks: true` (default `false`), which reverts edits made outside them |
| Languages | Python only: programs are `exec`'d | Any: the evaluator decides how to run the file; the language is guessed from the code (`extract_code_language`) and the file extension is kept |
| Packages programs may import | Those in `requirements.txt`, installed in the evaluation image and named in every prompt | Whatever is installed where openevolve runs; the LLM is never told |
| Is the initial program checked? | Yes: a failing initial program stops the run | No: it is added whatever its score |

So "whole files vs evolve blocks" is really two separate things: **how the LLM expresses a change**
(full rewrite vs SEARCH/REPLACE diff, see A5) and **which region it may change** (advisory markers,
optionally enforced).

### A2. What an evaluation returns

| | my-alphaevolve | openevolve |
|---|---|---|
| Evaluator signature | `evaluate(namespace)`: receives the dict of names the program defined; the framework ran the code | `evaluate(program_path)`: receives a file path; the evaluator imports or runs the program itself |
| Return value | One number, higher is better; must be finite and not a bool (`evaluator.py:37`) | A `dict` of metrics, or an `EvaluationResult(metrics, artifacts)` |
| The score used for selection | That number | `combined_score` if present, otherwise the average of the numeric metrics that are not MAP-Elites feature dimensions (`utils/metrics_utils.py:get_fitness_score`); a warning is logged when `combined_score` is missing |
| A failed program | Score `-inf`; kept, never a parent | Metrics `{"error": 0.0}` (plus `"timeout": True` on timeouts): fitness 0, stored like any other program, can occupy a MAP-Elites cell and be picked as a parent |
| Feedback to the LLM ("artifacts") | None | Any text or bytes in `artifacts` (stderr, tracebacks, hints written by the evaluator) is stored and shown in the next prompt that uses this program as parent |
| Cascade evaluation (cheap test first) | Written by the user inside `evaluate` (your two examples do this) | Framework feature: `evaluate_stage1/2/3` with `cascade_thresholds` (default `[0.5, 0.75, 0.9]`, on by default); stage metrics are merged |
| Extra arguments to the evaluator | None | `evaluator_args` from YAML or `--evaluator-args`, checked against the signature at start-up |
| LLM-as-judge | None | Optional `use_llm_feedback`: a second LLM ensemble scores readability etc.; `combined_score` becomes 70% evaluator + 30% LLM |
| Retries | None | An evaluation that raises is retried `max_retries` (3) times |
| Time limit | Hard: the container is killed after `--timeout` (30 s), including about 1 s of container start | Soft: `asyncio.wait_for` (300 s) stops *waiting*, but the thread running `evaluate` keeps going in the worker process (Part D) |
| Evaluation file loading | Loaded once on the host to check it, then again in every container | Loaded once per worker process; in cascade mode, re-imported on every evaluation |

### A3. The database

| | my-alphaevolve | openevolve |
|---|---|---|
| Structure | A flat `dict` of every program (`database.py`) | 5 islands, each a set of programs plus its own MAP-Elites grid; a global elite archive (100); the global best and each island's best tracked separately (`database.py`, 2,800 lines) |
| What `Program` holds | id, code, score, parent_id, generation, iteration | id, code, language, parent_id, generation, iteration_found, timestamp, metrics dict, complexity, diversity, metadata (island, diff summary, parent metrics, token usage, migrant flag), prompts, artifacts, embedding, changes_description |
| Parent selection | 70%: random among the 10 best working programs; 30%: random among all working programs | Per island (`sample_from_island`): 20%: uniform from the island; 70%: random archive elite, preferring this island; 10%: fitness-weighted from the island |
| Other programs given to the LLM | None | Inspirations (island best, top programs, programs from nearby grid cells, random ones) plus the island's top programs and some "diverse" ones (A4) |
| MAP-Elites | None on `main`. Tried in `aeaf384` (complexity × diversity, 10 bins each, grid rebuilt from all programs at every sample, parent = random elite) and reverted in `4a1e438` | Feature dimensions `complexity` (code length), `diversity` (cheap distance to a reference set of 20 programs), `score`, or any metric the evaluator returns; 10 bins by default; values scaled with a running min/max, so bin edges move as the run goes |
| Cell replacement | n/a | A program takes a cell only if strictly fitter; the displaced program is deleted unless it is still referenced elsewhere |
| Population limit | None: every program is kept forever | `population_size` (1000): the least fit programs that own no cell are deleted first |
| Migration | n/a | Once the busiest island has gained 50 programs since the last migration, the top 10% of each island is copied to its two neighbours (ring), skipping duplicate code; copies are never migrated again |
| Novelty filter | None | Optional: embedding similarity ≥ 0.99 to an island program triggers an LLM "NOVEL / NOT NOVEL" judgement; non-novel programs are kept but not placed in the grid |
| Duplicates of the parent | Evaluated and stored like any child | Rejected before evaluation ("identical to the parent") |
| Code-length limit | None | `max_code_length` (10,000 characters): longer children are rejected |
| Hooks for custom policies | None | `PopulationStrategy` (admit, replace_cell, archive, evict, migration_due, migrate) and `island_selector` |

### A4. The prompt

| | my-alphaevolve | openevolve |
|---|---|---|
| Messages | A single user message | A system message plus a user message |
| Where templates live | One Python string (`prompt_sampler.py`) | Text files in `openevolve/prompts/defaults/`, overridable with `template_dir`; small phrases in `fragments.json` |
| Contents | Problem description, parent score, parent code, allowed packages, "reply with only the complete program" | Fitness, feature coordinates, "focus areas" (fitness improved / declined, code too long), the parent's artifacts, "previous attempts", top programs, diverse programs, inspirations, the parent code, task instructions (diff format with an example, or full rewrite) |
| Randomness in the wording | None | `use_template_stochasticity`: placeholders replaced by a random variation |
| Per-island system messages | n/a | `island_system_messages` |
| Large-codebase mode | n/a | `programs_as_changes_description`: other programs are shown as short descriptions the LLM maintains, not as code |

The "previous attempts" section is not the parent's history: it is the last three of the island's
top programs, in reverse order.

### A5. How the LLM expresses a change, and how its reply is read

| | my-alphaevolve | openevolve |
|---|---|---|
| Change format | Full rewrite of the file | SEARCH/REPLACE diffs by default (`diff_based_evolution: true`); full rewrite as an option (the circle-packing config uses it) |
| Reply parsing | Robust (`reply_parser.py`): drops `<think>` blocks; among the code blocks keeps those that are valid Python, then those that do not repeat the parent (compared by AST), then the longest; handles unclosed blocks, one-line blocks and nested backticks; falls back to the whole reply | Diffs: strict, whole-line markers; a malformed sequence rejects the reply; each SEARCH is matched exactly, then ignoring trailing spaces; first match only. Rewrite: first fenced block in the right language, else any block, else the whole reply |
| Rejected before evaluation | Nothing | No diff found, no SEARCH matched, diff changed nothing, rewrite identical to the parent, edits only outside the evolve blocks, code too long |
| Record of the change | None | A text summary of the diff, stored in the child's metadata and shown in later prompts |

### A6. The LLM

| | my-alphaevolve | openevolve |
|---|---|---|
| Models | One | A weighted ensemble, one model drawn per call (seeded); a second ensemble for LLM feedback; the evolution ensemble is also the novelty judge |
| Client | Synchronous `openai.OpenAI` | `openai.AsyncOpenAI`, run with `asyncio.run` inside each worker |
| Providers | Any OpenAI-compatible server | OpenAI-compatible, plus Claude Code CLI, Copilot CLI, Codex app-server, "manual mode" (a human answers through a file queue), or a custom `init_client` |
| Parameters sent | `max_tokens` (4096, or none) | temperature (0.7), top_p, max_tokens (4096), seed, reasoning_effort; reasoning models are detected by name and get `max_completion_tokens` |
| Timeout and retries | 300 s; the `openai` package's own 2 retries | 60 s; its own loop of 3 retries 5 s apart, *on top of* the `openai` package's retries (Part D) |
| Token usage | Not recorded | Per call and totals, logged and stored |
| A failed call | `LLMError`: the iteration is skipped; 3 in a row stop the run | The iteration fails and the run carries on; if no iteration at all produced a candidate, the run ends with `EvolutionFailedError` |

### A7. The loop

| | my-alphaevolve | openevolve |
|---|---|---|
| Parallelism | Threads (`ThreadPoolExecutor`), `--workers` (1) | Processes (`ProcessPoolExecutor`), `parallel_evaluations` (1 without a config file, 4 in `default_config.yaml`) |
| One iteration, in the worker | Ask the LLM, extract the code, evaluate | Rebuild the programs from a snapshot, build the prompt, ask the LLM, parse, evaluate |
| Shared state | Only the main thread touches the database and the files | The main process owns the database; each submitted iteration receives a pickled snapshot of *every* program (plus up to 100 artifact sets) |
| When the parent is chosen | When the iteration starts, in the main thread | The same, in the main process; the target island is chosen round-robin (or by `island_selector`) |
| How many iterations are in flight | Exactly `workers` | `2 × workers` at the start, spread over the islands, then one new per completion |
| Waiting for results | `wait(FIRST_COMPLETED)` in 0.2 s steps (for Ctrl+C on Windows) | Polls every future every 10 ms in an asyncio loop. A guard meant to give up after `evaluator.timeout + 30` s never fires (Part D) |
| Stop conditions | Iteration count, Ctrl+C, 3 LLM failures in a row | Iteration count, `--target-score` on `combined_score`, early stopping (patience, minimum improvement, chosen metric; negative patience = stop when the metric *equals* a value), SIGINT / SIGTERM |
| Do failed iterations count? | Yes | Yes |
| After each result | Store, append to disk, update the best file, print a line | Store, store artifacts, trace, log the prompt, increment the island's generation, migrate if due, log, checkpoint if due, check target score and early stopping |

### A8. Randomness and repeatability

| | my-alphaevolve | openevolve |
|---|---|---|
| Default seed | None (random runs) | 42 |
| What the seed controls | Only parent choice, through the database's own `random.Random`, so programs that call `random.seed` do not disturb it | Python's global `random` and `numpy.random`, a seed derived for the LLM (sent to the API), the ensemble's model choice |
| Claimed repeatability | Parents only, and only with one worker | "Fully deterministic" in the README; in practice not with several workers, nor with an LLM that ignores `seed` |

---

## Part B: the engineering around it

### B1. Running untrusted programs

| | my-alphaevolve | openevolve |
|---|---|---|
| Mechanism | A fresh Docker container per evaluation, removed afterwards (`DockerEvaluator`) | None of its own: `evaluate` runs in a thread of a pool worker process. The program runs wherever the evaluator runs it: in the worker itself (function minimization imports it), or in a subprocess the evaluator starts (circle packing) |
| Network | None (`--network none`) | Full |
| File system | Read-only, except a temporary `/tmp`; sees only the package and the problem folder, read-only | Everything the user can access |
| Limits | 1 GB memory (no swap), 1 CPU, 64 processes, all capabilities dropped, user `nobody` | None (`memory_limit_mb` and `cpu_limit` exist in the config but are marked "not implemented") |
| Secrets | The container gets no environment variables from the host | Each worker copies the whole parent environment, API keys included, and LLM-written code can read it |
| How the program is passed / the result returned | Code on stdin; result as the last JSON line of stdout (`container_worker.py`) | A temporary file with the program's extension; the return value of `evaluate` |
| Image | Built on first use from `evaluation.Dockerfile` plus the requirements; tag = hash of both, so it rebuilds when they change | n/a. openevolve's `Dockerfile` runs openevolve itself, not the programs |
| Cost | About 1 s per evaluation for container start | Negligible |
| Without Docker | Refuses to run; tests use an `InProcessEvaluator` stand-in | n/a |

### B2. Configuring a run

| | my-alphaevolve | openevolve |
|---|---|---|
| Mechanism | CLI flags only (`scripts/run.py`, argparse) | A YAML file loaded into dataclasses (`config.py`, via `dacite`), plus a few CLI overrides |
| CLI options | `initial_program evaluation_file --model --llm-url --api-key-env --max-reply-tokens --iterations --output --timeout --workers --seed` | `initial_program evaluation_file --config --output --iterations --target-score --log-level --logger-prefix --checkpoint --api-base --evaluator-args --primary-model --secondary-model` |
| Number of settings | 10 | About 100, in sections `llm`, `prompt`, `database`, `evaluator`, `evolution_trace` and top-level |
| Validation | Every value checked, clear errors | Mostly unchecked; **unknown keys are silently dropped** (the circle-packing config sets `allow_full_rewrites: true`, which does not exist); only `llm.model` gets a dedicated error |
| API key | Read from the environment variable named by `--api-key-env` (default `OPENAI_API_KEY`); never written anywhere | `api_key` in the YAML, `${VAR}` to read a variable, or `OPENAI_API_KEY`; serialized to every worker |
| Defaults | One set, in the code | Two sets that disagree: the dataclasses (e.g. 10,000 iterations, checkpoint every 100, 1 worker) apply without a config file, `configs/default_config.yaml` documents others (100, 10, 4) |
| Use from Python | `run_my_alphaevolve(problem, llm, evaluator, ...)` | `run_evolution`, `evolve_function`, `evolve_algorithm`, `evolve_code` (`api.py`), accepting code strings and evaluator callables |

### B3. Results on disk, and continuing a run

| | my-alphaevolve | openevolve |
|---|---|---|
| Where | `--output FOLDER`; nothing is saved without it | `--output`, by default `openevolve_output/` next to the initial program; always saved |
| Program records | `programs.jsonl`: one line per program, appended the moment it is evaluated | `checkpoints/checkpoint_N/programs/<id>.json`, one file per program (with its prompts and reply when `log_prompts`), written every `checkpoint_interval` iterations; each checkpoint is a full copy |
| Other state | None needed: the database is rebuilt from the programs | `metadata.json` per checkpoint: islands, grids, archive, best ids, generations, feature statistics |
| Best program | `best_program.py`, rewritten whenever the best changes, with a header comment (score, iteration, id) | `checkpoints/checkpoint_N/best_program.<ext>` + `best_program_info.json`, and `best/` at the end of the run |
| Prompts and LLM replies | Not saved | Saved in the program files; also in the optional evolution trace |
| Evolution trace | n/a | Optional `evolution_trace.jsonl` (or JSON, HDF5): parent, child, metrics, prompt, reply, diff, for analysis or RL training |
| Artifacts | n/a | Small ones in the program JSON, those over 32 KB in an `artifacts/` folder, cleaned after 30 days |
| Programs that were removed | None are removed | Deleted programs (population limit, displaced cell owners) are absent from later checkpoints: the history is incomplete |
| Continuing | Run the same command with the same `--output`; `--iterations` = that many more; the initial program is not re-evaluated | `--checkpoint checkpoints/checkpoint_N`; `--iterations` = that many more |
| What is lost on an abrupt stop | Nothing already evaluated; a cut-off last line is detected and dropped | Everything since the last checkpoint (up to `checkpoint_interval − 1` iterations) |
| Different problem in the same folder | Not detected (the README warns) | Not detected |
| Viewing a run | Reading `programs.jsonl` | A Flask web visualizer of the program tree (`scripts/visualizer.py`) |

### B4. Logging and console output

| | my-alphaevolve | openevolve |
|---|---|---|
| Mechanism | `print()` | The `logging` module: the root logger gets a console handler and a file handler, `logs/openevolve_<timestamp>.log` |
| Per iteration | One line: iteration, child score, generation, best score | Several lines per iteration and per component (sampled model, token usage, MAP-Elites cell events, metrics, island status), with timestamps and emoji |
| Levels | None | `log_level`, `--log-level`; `logger_prefix` to tell concurrent runs apart |

### B5. Ctrl+C and other ways of stopping

| | my-alphaevolve | openevolve |
|---|---|---|
| First Ctrl+C | `KeyboardInterrupt` caught in the main thread: nothing new starts; iterations in progress finish and are saved | SIGINT handler sets a shutdown event; the loop stops at its next check; pending futures are cancelled and the worker processes terminated, so iterations in progress are lost |
| Second Ctrl+C | Stops waiting for them, prints "skipped"… but the process still waits for them before exiting (Part D) | `sys.exit(0)` from the signal handler |
| Checkpoint on stop | Not needed (already appended) | None: the run ends without a final checkpoint; only `best/` is written |
| SIGTERM | Not handled: Python's default kills the process | Same handler as SIGINT |
| Leftover processes | Containers of interrupted evaluations can outlive the run (Part D) | Worker processes are terminated, then killed after 1 s; subprocesses started by an evaluator are not tracked |

### B6. Platform, packaging and tooling

| | my-alphaevolve | openevolve |
|---|---|---|
| Platforms targeted | Windows first (PowerShell commands, UTF-8 output, Ctrl+C wake-up), Linux and macOS | Mostly Linux and macOS; Windows is mentioned only for multiprocessing caveats, and some providers do not support it |
| Layout | `src/my_alphaevolve/`, entry point `scripts/run.py` | Flat `openevolve/` package, console script `openevolve-run`, `openevolve-run.py` |
| Dependencies | `openai` only | `openai`, `pyyaml`, `numpy`, `tqdm`, `flask`, `dacite`, `cloudpickle` |
| Code style | ruff (lint + format), mypy `strict`, plain-English docstrings and comments throughout | black, isort, partial typing |
| Tests | `unittest`, 193 tests; a fake OpenAI-compatible HTTP server; Docker tests skipped when Docker is missing | `unittest` and `pytest`, 95 test files; integration tests against a small local model served by optillm; CI workflows |
| Size of the core | About 1,300 lines (`src/` and `scripts/run.py`) | About 11,700 lines in `openevolve/`, plus 1,800 in `compat/` |

---

## Part C: what exists in only one of them

### Only in openevolve

- Islands, migration, MAP-Elites, elite archive, population limit (A3).
- Inspirations and top/diverse programs in the prompt (A3, A4).
- SEARCH/REPLACE diffs, evolve-block enforcement, code-length limit (A5).
- LLM ensembles, other providers, manual (human) mode, token accounting (A6).
- Metrics dictionaries, artifacts, framework-level cascade, LLM-as-judge, evaluator arguments (A2).
- Novelty filtering with embeddings and an LLM judge (A3).
- Target score and early stopping (A7).
- YAML configuration, template directories, template stochasticity, per-island system messages, changes-description mode (A4, B2).
- Periodic checkpoints, evolution traces, prompt logging, visualizer (B3).
- Library API; `PopulationStrategy` and `island_selector` hooks; co-evolution of two populations (`coevolution.py`); compatibility layer with Google's AlphaEvolve evaluators and bundles (`compat/`).
- Any programming language (Rust, R, Metal examples).

### Only in my-alphaevolve

- A sandbox: network-less, read-only, resource-limited container per evaluation (B1).
- Allowed packages, installed in the image and announced to the LLM (A1).
- Problem description in the initial program's docstring, checked at start (A1).
- A reply parser that copes with thinking models, quoted parents, unclosed and nested blocks (A5).
- Append-only saving: an interrupted run loses nothing that was evaluated (B3).
- First Ctrl+C finishes the iterations in progress (B5).
- A stop after 3 LLM failures in a row (A6).
- Score validation (finite number, not a bool) (A2).
- Clean loading of the evaluation file: helper modules next to it are imported and then forgotten, so two problems can each have a `utils.py` (`problem.py:load_score_function`).
- Windows support (B6).
- Strict typing and validation of every user input (B2, B6).

---

## Part D: bugs and surprising behaviours found while reading

### In my-alphaevolve

1. **The second Ctrl+C does not make the process exit sooner.** `pool.shutdown(wait=False, cancel_futures=True)` stops *waiting* for the threads, but Python joins thread-pool threads when the interpreter exits, so the process still waits for the in-flight LLM calls (up to 300 s) and evaluations. Verified with a three-line script: `shutdown(wait=False)` on a pool running `time.sleep(3)` still took 3 s to exit.
2. **Containers can outlive the run.** The container is killed only by the `finally` of the thread that started it. After a second Ctrl+C, a SIGTERM or a crash, nothing kills the containers still running; with no time limit inside the container itself, a program that never ends keeps running.
3. **A program can forge its score.** The program runs in the same interpreter as `container_worker`, before the result is printed. `os.write(1, b'{"status": "ok", "score": 1e9}\n'); os._exit(0)` bypasses the stdout redirection and becomes the last line of stdout. It can also monkeypatch what `evaluate` uses (e.g. `numpy`). An LLM is unlikely to do this on purpose, but reward hacking is a known AlphaEvolve-style risk.
4. **The function-minimization example trusts the value the program reports** when it returns `(x, y, value)`. openevolve now recomputes it from `(x, y)` for that reason (issue #514, in `examples/function_minimization/evaluator.py`).
5. **Failed programs are saved as `-Infinity`**, which Python's `json` writes and reads, but which is not valid JSON for other tools (`jq`, JavaScript).
6. **A child identical to its parent is evaluated and stored again**, costing an evaluation (often seconds) for nothing.
7. **Any exception other than `LLMError` in a worker ends the run**, for example Docker failing to start a container: `record` only catches `LLMError`.
8. **Prompts and replies are thrown away**, so a strange child cannot be traced back to what the LLM was asked and answered.
9. **A continued run restarts the random sequence**: the database is re-seeded with the same seed, so the first parents chosen after resuming follow the same random draws as at the start of the run.

### In openevolve

1. **Ctrl+C loses everything since the last checkpoint**, and the iterations in progress. With the dataclass default (`checkpoint_interval: 100`), up to 99 iterations.
2. **Evaluation timeouts do not stop the evaluation.** `asyncio.wait_for` gives up waiting, but the thread running `evaluate` carries on in the worker process, which is reused for the next iterations.
3. **LLM-written code runs with your API keys and the network**, in function minimization directly inside the worker process.
4. **Failed programs (fitness 0) enter the MAP-Elites grid and can be chosen as parents.**
5. **Retries multiply**: the `openai` client retries `retries` times inside each of the `retries + 1` attempts of openevolve's own loop, so up to 16 attempts with the defaults.
6. **Grid cells drift**: bins come from a running min/max, so the same feature value lands in different cells as the run goes, and earlier cell assignments are never recomputed.
7. **Every iteration pickles the whole population** to send it to a worker.
8. **"Previous attempts" in the prompt are the island's top programs**, not the parent's actual history.
9. **Unknown YAML keys are silently ignored** (see B2).
10. **The two sets of defaults disagree** (see B2).
11. **The end of a run is not checkpointed** unless the last iteration is a multiple of `checkpoint_interval`: resuming from the last checkpoint loses the iterations after it, possibly the best program (which is then only in `best/`).
12. **The guard against stuck iterations is dead code**: the main loop reads a result only once its future is done, so `future.result(timeout=evaluator.timeout + 30)` returns at once and never times out.
