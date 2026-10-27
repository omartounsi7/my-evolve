# my-alphaevolve vs my-evolve vs openevolve vs ShinkaEvolve: the differences

What was compared:

- **my-alphaevolve** at `4a1e438` (branch `main`).
- **my-evolve**, the planned rewrite of my-alphaevolve, as specified in
  [design-decisions.md](design-decisions.md). It is not written yet: its column describes the design, and the
  decision numbers there (D1 to D79) give the details.
- **openevolve** at `da3d701`, the checkout next to it. It includes your two local commits
  (Claude models for function minimization). Your examples were adapted from openevolve
  `30d9752`, which is older than this checkout.
- **ShinkaEvolve** at `8adc053`, Sakana AI's framework ("towards open-ended and sample-efficient
  program evolution", ICLR 2026). Its paper names three ideas for sample efficiency: a parent
  selection that balances exploration and exploitation, novelty rejection sampling of code, and a
  bandit that picks among several LLMs. All three are covered below (A3, A6).

Part A covers the evolution algorithm itself; Part B covers the engineering around it.
Part C lists what exists in only some of them, my-evolve's choices included. Part D lists bugs and surprising behaviours
found while reading; they matter because a redesign should not copy them by accident.

File references point into each repository: `src/my_alphaevolve/...` for yours,
`openevolve/...` for openevolve, `shinka/...` for ShinkaEvolve; my-evolve's files are planned as `src/my_evolve/...`.

A ShinkaEvolve word to keep in mind: its **generation** is the sequence number of a proposal
(the 37th proposal is generation 37), not the distance from the initial program, which is what
"generation" means in the others.

---

## Part A: the evolution algorithm

### A1. Defining a problem

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Files the user writes | `initial_program.py`, `evaluation.py`, optional `requirements.txt` | `initial_program.py`, `evaluation.py`, and a YAML problem file | `initial_program.<any ext>`, `evaluator.py`, `config.yaml` | `evaluate.py` (a script) and `initial.<ext>`; a YAML config or a Python launch script is optional |
| No initial program? | Not possible | Not possible: it must evaluate `ok`, or the run refuses to start | Not possible | An LLM writes one from the task description (`prompts_init.py`) |
| Problem description for the LLM | Required docstring at the top of the initial program; the run refuses to start without it (`problem.py`) | `description` in the problem file, including the entry functions' contract | `prompt.system_message` in the YAML; a generic "expert software developer" message otherwise | `task_sys_msg` in the config, used as the system message; a generic message otherwise |
| Part of the program the LLM may change | The whole file | Only the code inside EVOLVE-BLOCK markers, kept from openevolve's initial programs; the LLM returns the whole file, and a child that changes code outside the blocks or a marker is rejected | The whole file is shown. `# EVOLVE-BLOCK-START` / `END` markers delimit what *should* change, but no default prompt mentions them; they are enforced only with `enforce_evolve_blocks: true` (default `false`), which reverts edits made outside them | Only inside EVOLVE-BLOCK markers, which are required: prompts say so, a diff that touches code outside them is rejected, a full rewrite only replaces the blocks' contents, and a candidate that lost a marker is rejected (`shinka/edit/`) |
| Languages | Python only: programs are `exec`'d | Python only | Any: the evaluator decides how to run the file; the language is guessed from the code (`extract_code_language`) and the file extension is kept | Many, each with its marker syntax: Python, Julia, Go, Rust, C++, CUDA, Swift, Fortran, Verilog, Wolfram, Markdown, JSON (`utils/languages.py`) |
| Packages programs may import | Those in `requirements.txt`, installed in the evaluation image and named in every prompt | Listed with exact versions in the problem file, installed in the evaluation image and named in every prompt | Whatever is installed where openevolve runs; the LLM is never told | Whatever is installed in the evaluation environment (the current interpreter, a sourced venv, a conda env, or a cluster image); the LLM is never told |
| Is the initial program checked? | Yes: a failing initial program stops the run | Yes: it must pass the checks before evaluation and evaluate `ok`, or the run refuses to start | No: it is added whatever its score | It is evaluated; if it is incorrect, the run starts in "fix mode" (A3) |

So "whole files vs evolve blocks" is really two separate things: **how the LLM expresses a change**
(full rewrite vs SEARCH/REPLACE diff, see A5) and **which region it may change** (advisory markers
in openevolve, mandatory and enforced markers in ShinkaEvolve).

### A2. What an evaluation returns

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Evaluator signature | `evaluate(namespace)`: receives the dict of names the program defined; the framework ran the code | Stage functions `evaluate_stage1(namespace)`, … (or `evaluate(namespace)`), run on the host; calling a function of the namespace runs the program's function in its container | `evaluate(program_path)`: receives a file path; the evaluator imports or runs the program itself | A script run as `python evaluate.py --program_path ... --results_dir ...`. It usually calls the helper `run_shinka_eval`, which imports the program, calls an entry function (`run_packing`) `num_runs` times with arguments the evaluator chooses, validates each result and aggregates them (`core/wrap_eval.py`) |
| Return value | One number, higher is better; must be finite and not a bool (`evaluator.py:37`) | A `StageResult` (score, metrics, features, feedback, output data), or `InvalidProgram` raised; the framework turns it into a `Result` with a status | A `dict` of metrics, or an `EvaluationResult(metrics, artifacts)` | Two files in the results folder: `metrics.json` (`combined_score`, `public` and `private` metrics, `text_feedback`, `extra_data`) and `correct.json` (`correct`, `error`) |
| The score used for selection | That number | The stage's `score`; no averaging fallback | `combined_score` if present, otherwise the average of the numeric metrics that are not MAP-Elites feature dimensions (`utils/metrics_utils.py:get_fitness_score`); a warning is logged when `combined_score` is missing | `combined_score`, with a separate yes/no **correctness** that always comes first; the archive can also rank by several weighted criteria (score, lines of code, cyclomatic complexity, nesting) using ranks |
| A failed program | Score `-inf`; kept, never a parent | One of five statuses (`rejected`, `failed`, `timeout`, `invalid`, `error`), an error message and no score; stored, shown to the LLM as a previous attempt, never a parent | Metrics `{"error": 0.0}` (plus `"timeout": True` on timeouts): fitness 0, stored like any other program, can occupy a MAP-Elites cell and be picked as a parent | `correct: false`, score 0 by default (a NaN or infinite score also makes it incorrect); stored; never a parent while a correct program exists |
| Feedback to the LLM ("artifacts") | None | Feedback text from the evaluator, plus the error and end of the error output the framework captures; shown for the parent and every example program | Any text or bytes in `artifacts` (stderr, tracebacks, hints written by the evaluator) is stored and shown in the next prompt that uses this program as parent | `text_feedback` from the evaluator, shown when `use_text_feedback` is on (off by default); `public` metrics are shown to the LLM, `private` ones are not; stdout and stderr are shown in fix prompts |
| Cascade evaluation (cheap test first) | Written by the user inside `evaluate` (your two examples do this) | openevolve's: `evaluate_stage1/2/…` with thresholds in the problem file; the two problems use openevolve's cascades | Framework feature: `evaluate_stage1/2/3` with `cascade_thresholds` (default `[0.5, 0.75, 0.9]`, on by default); stage metrics are merged | None; instead, the helper can stop repeated runs early when statistics show the program cannot beat a threshold (Bayesian, confidence-interval or hybrid tests, `utils/eval_stop.py`) |
| Repeated runs | Written by the user inside `evaluate` | Written by the user inside a stage (function minimization's stage 2 calls `run_search` 10 times) | Written by the user | Built into the helper: `num_runs`, optionally in parallel processes (`run_workers`) |
| Extra arguments to the evaluator | None | None: constants live in the evaluation file | `evaluator_args` from YAML or `--evaluator-args`, checked against the signature at start-up | `extra_cmd_args`, passed as command-line flags to `evaluate.py` |
| LLM-as-judge | None | None | Optional `use_llm_feedback`: a second LLM ensemble scores readability etc.; `combined_score` becomes 70% evaluator + 30% LLM | Not for scores (an LLM judges novelty, A3); an evaluator may call LLMs itself, as the novelty-generator example does |
| Plots and extra data | None | `output_data`, saved with each program and drawn after the run by the evaluation file's `visualize` | None | The evaluator can return `extra_data` (saved as `extra.pkl`) and plotting functions (figures saved per program) |
| Retries | None | None | An evaluation that raises is retried `max_retries` (3) times | None |
| Time limit | Hard: the container is killed after `--timeout` (30 s), including about 1 s of container start | Hard: 60 s per cascade stage, and optional limits on single calls set by the evaluator; the container is killed | Soft: `asyncio.wait_for` (300 s) stops *waiting*, but the thread running `evaluate` keeps going in the worker process (Part D) | None by default (`job_config.time` unset). A hung-job detector kills a local evaluation after max(60 s, 5 × the average evaluation time + 60 s) |
| Evaluation file loading | Loaded once on the host to check it, then again in every container | Once, on the host, where it runs; the program is loaded afresh in a new container for each stage | Loaded once per worker process; in cascade mode, re-imported on every evaluation | A new Python process per evaluation, so it is loaded every time |
| Who computes the score | `evaluate`, in the same Python process as the program, inside the container | The evaluation file, on the host; the program, in its container, only answers calls | The evaluator, in the same process as the program unless it starts a subprocess | The evaluation script, which imports the program |
| Kinds of failure told apart | One: score `-inf` | Five statuses: `rejected`, `failed`, `timeout`, `invalid` (an illegal answer), `error` (not the program's fault) | None: `{"error": 0.0}`, plus a `timeout` flag | Two: `correct` or not |

### A3. The database

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Structure | A flat `dict` of every program (`database.py`) | 3 islands, each with a fixed MAP-Elites grid; every program kept in memory and in `programs.jsonl`; an archive of the 10 best computed when needed | 5 islands, each a set of programs plus its own MAP-Elites grid; a global elite archive (100); the global best and each island's best tracked separately (`database.py`, 2,800 lines) | A SQLite file holding every program; 2 islands; a global archive of 40 correct programs; the best program tracked (`database/dbase.py`) |
| What `Program` holds | id, code, score, parent_id, generation, iteration | id, code, origin (initial, LLM, copy, move), parent_id, island, iteration, generation, description, fingerprint, code complexity, example ids, LLM usage, creation time, and its `Result` (status, score, metrics, features, feedback, error, output data, stage reached, duration); no database state | id, code, language, parent_id, generation, iteration_found, timestamp, metrics dict, complexity, diversity, metadata (island, diff summary, parent metrics, token usage, migrant flag), prompts, artifacts, embedding, changes_description | id, code, language, parent_id, ids of the inspirations used, island, generation (proposal number), timestamp, diff, combined_score, public and private metrics, text feedback, correct, number of children, complexity (from `radon`), embedding with 2D/3D projections and cluster, migration history, archive flag, id of the system prompt used, metadata (patch name and description, model, costs, logs, timings) |
| Parent selection | 70%: random among the 10 best working programs; 30%: random among all working programs | ShinkaEvolve's weighted rule over the island's grid elites, with λ = 1 by default and fallbacks when the spread is 0; openevolve's rule, adapted to grids, as an option | Per island (`sample_from_island`): 20%: uniform from the island; 70%: random archive elite, preferring this island; 10%: fitness-weighted from the island | An island is drawn (uniformly by default), then a parent among that island's archive members. Default `weighted`: weight = sigmoid(λ × (score − median) / spread) × 1 / (1 + number of children), so good programs are favoured *and* programs already tried often are tried less (`database/parents.py`). Alternatives: power law over rank, beam search (keep the best as parent until it has k children), best-of-n, sequential |
| No working program yet | Impossible: the initial program must work | Cannot happen: the initial program must work | Selection proceeds on failed programs (fitness 0) | "Fix mode": a random incorrect program becomes the parent, its ancestors are shown, and the prompt asks to fix it using its stdout and stderr (`prompts_fix.py`) |
| Other programs given to the LLM | None | 2 example programs drawn at random among everything made on the island, working or failed, shown unlabelled as previous attempts | Inspirations (island best, top programs, programs from nearby grid cells, random ones) plus the island's top programs and some "diverse" ones (A4) | Archive inspirations (global best, island elites, random archive members) and the island's top programs: 1 + 1 by default, shown with code and metrics, worst first (`database/inspirations.py`) |
| MAP-Elites | None on `main`. Tried in `aeaf384` (complexity × diversity, 10 bins each, grid rebuilt from all programs at every sample, parent = random elite) and reverted in `4a1e438` | A built-in feature (syntax-tree nodes inside the evolve blocks, as log2 of the ratio to the initial program) and any output features the evaluator computes (circle packing: spread of the radii, correlation of radius and distance to the centre); fixed ranges and bins from the problem file; 1D by default | Feature dimensions `complexity` (code length), `diversity` (cheap distance to a reference set of 20 programs), `score`, or any metric the evaluator returns; 10 bins by default; values scaled with a running min/max, so bin edges move as the run goes | None. Diversity comes from islands, the children-count factor in parent selection, the novelty filter, and optionally a "crowding" archive |
| Archive | n/a (the 10 best are computed when needed) | The 10 best `ok` programs of the run, computed when needed, copies counted once; used only by openevolve's rule | Bounded set of elites, updated at insertion; MAP-Elites displacement swaps archive members | Only correct programs; when full, a better program replaces the worst member (`fitness`) or the member most similar to it by embedding (`crowding`) |
| Cell replacement | n/a | A program takes a cell if it is empty or if it scores strictly higher; the displaced program stays in the database | A program takes a cell only if strictly fitter; the displaced program is deleted unless it is still referenced elsewhere | n/a |
| Population limit | None: every program is kept forever | None: every program is kept | `population_size` (1000): the least fit programs that own no cell are deleted first | None: every program is kept forever |
| Migration | n/a | Every 25 completed iterations, 10% of each island's elites (at least one, never its best) are copied to every other island; interval, share, choice, destinations and copy or move all settable | Once the busiest island has gained 50 programs since the last migration, the top 10% of each island is copied to its two neighbours (ring), skipping duplicate code; copies are never migrated again | Every 10 generations, random correct programs are *moved* to a random other island; each island's best and the initial programs never move; off by default (`migration_rate: 0.0`), 10% in the presets |
| Seeding the islands | n/a | The initial program is copied into every island | The initial program goes to island 0; other islands fill with descendants | The initial program is copied into every island |
| New islands during the run | n/a | None | n/a | Optional: after 100 generations without improvement, a new island is started from the initial program, the best one or a random archive member |
| Novelty filter | None | None besides the duplicate check | Optional: embedding similarity ≥ 0.99 to an island program triggers an LLM "NOVEL / NOT NOVEL" judgement, *after* evaluation; non-novel programs are kept but not placed in the grid | Optional, *before* evaluation: if a proposal's embedding is more than 0.99 similar to a program of its island, an LLM judges it; a rejected proposal is regenerated (up to 3 times), so no evaluation is spent on it. On only when `novelty_llm_models` is set |
| Duplicates of the parent | Evaluated and stored like any child | Rejected before evaluation, like any child with the same syntax tree as an earlier program | Rejected before evaluation ("identical to the parent") | Caught by the novelty filter when it is on; evaluated otherwise |
| Code-length limit | None | None | `max_code_length` (10,000 characters): longer children are rejected | None |
| Hooks for custom policies | None | Two parent strategies behind one interface, chosen in the problem file | `PopulationStrategy` (admit, replace_cell, archive, evict, migration_due, migrate) and `island_selector` | Strategies chosen by name in the config; a custom bandit object for model choice |
| Failed programs in the prompt | Never shown | Shown as previous attempts, unlabelled, with their status and error | Not chosen as inspirations on purpose, but can be (fitness 0) | Only in fix mode, as ancestors |

### A4. The prompt

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Messages | A single user message | A system message, the same for the whole run (cacheable), and a user message | A system message plus a user message | A system message (task description, recommendations, reply format) plus a user message; a failed patch continues the same conversation (A5) |
| Where templates live | One Python string (`prompt_sampler.py`) | Python constants, whose text is fixed in design-decisions.md (Appendix A) | Text files in `openevolve/prompts/defaults/`, overridable with `template_dir`; small phrases in `fragments.json` | Python strings in `shinka/prompts/` |
| Contents | Problem description, parent score, parent code, allowed packages, "reply with only the complete program" | Instruction, problem description, rules (evolve blocks, allowed packages, higher is better), reply format; previous attempts with score or status, description, feedback and error; the parent with its score and the best score so far | Fitness, feature coordinates, "focus areas" (fitness improved / declined, code too long), the parent's artifacts, "previous attempts", top programs, diverse programs, inspirations, the parent code, task instructions (diff format with an example, or full rewrite) | Inspirations with their code and public metrics; the parent's code, score and public metrics; optional text feedback; the task for the chosen patch type; a reply format with `<NAME>`, `<DESCRIPTION>` and the change |
| Randomness in the wording | None | None | `use_template_stochasticity`: placeholders replaced by a random variation | The patch type is drawn per proposal (A5); a full rewrite also draws one of 5 instructions: default, "completely different algorithm", "motivated by context", "structural redesign", "different parameters" |
| Per-island system messages | n/a | n/a | `island_system_messages` | n/a |
| Run-level advice | None | None | None | Optional "meta recommendations": every 10 generations an LLM summarises each recent program, updates a running list of insights, and writes up to 5 recommendations; one is added to every system prompt. On only when `meta_llm_models` is set (`core/summarizer.py`) |
| Evolving the prompt itself | None | None | None | Optional: system prompts are evolved in their own archive by an LLM, chosen by UCB / epsilon-greedy, and scored by how the programs they produce rank (`core/prompt_evolver.py`) |
| Large-codebase mode | n/a | n/a | `programs_as_changes_description`: other programs are shown as short descriptions the LLM maintains, not as code | n/a |

The "previous attempts" section of openevolve is not the parent's history: it is the last three of
the island's top programs, in reverse order.

### A5. How the LLM expresses a change, and how its reply is read

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Change format | Full rewrite of the file | Full rewrite of the file, changes allowed inside the evolve blocks only | SEARCH/REPLACE diffs by default (`diff_based_evolution: true`); full rewrite as an option (the circle-packing config uses it) | Drawn per proposal: diff (60%), full rewrite (30%), or **crossover** (10%), which shows a second program and asks to combine the two; "fix" when nothing is correct |
| Reply parsing | Robust (`reply_parser.py`): drops `<think>` blocks; among the code blocks keeps those that are valid Python, then those that do not repeat the parent (compared by AST), then the longest; handles unclosed blocks, one-line blocks and nested backticks; falls back to the whole reply | The description from `<DESCRIPTION>` tags; the code with v1's rules; anything else in the reply ignored | Diffs: strict, whole-line markers; a malformed sequence rejects the reply; each SEARCH is matched exactly, then ignoring trailing spaces; first match only. Rewrite: first fenced block in the right language, else any block, else the whole reply | Tagged replies (`<NAME>`, `<DESCRIPTION>`, `<DIFF>` or `<CODE>`). Diffs: SEARCH matched exactly, then with corrected indentation; an empty SEARCH inserts at the end of the last block; markers inside a patch are removed. Rewrites: the fenced code's block contents replace the original's |
| Rejected before evaluation | Nothing | No code or a syntax error, a change outside the blocks or to a marker, a missing entry function, a duplicate of an earlier program; stored as `rejected` | No diff found, no SEARCH matched, diff changed nothing, rewrite identical to the parent, edits only outside the evolve blocks, code too long | Patch errors (SEARCH not found, edit outside the blocks, no code found, broken markers), then the novelty filter (A3) |
| A failed patch | n/a (nothing is rejected) | No repair: the iteration ends | The iteration fails | The LLM is told the error (for a missing SEARCH, with the most similar lines) and asked again in the same conversation (`max_patch_attempts`, 1 by default, 10 in the small preset); then a new parent is drawn (`max_patch_resamples`, 3); then the whole loop restarts (`max_novelty_attempts`, 3) |
| Record of the change | None | The LLM's description of the program itself, written so as never to refer to its parent, saved and shown in later prompts | A text summary of the diff, stored in the child's metadata and shown in later prompts | The LLM's own name and description of the change, a unified diff (`edit.diff`), a summary of it, and every attempt's reply |

### A6. The LLM

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Models | One | A weighted ensemble from the problem file, one model drawn per iteration | A weighted ensemble, one model drawn per call (seeded); a second ensemble for LLM feedback; the evolution ensemble is also the novelty judge | A pool (4 OpenAI and Google models by default). Per proposal, a **UCB bandit** picks the model, rewarded by the child's score relative to its parent's, optionally blended with cost (`cost_aware_coef`, 0.5); or a fixed or Thompson-sampling policy (`llm/prioritization.py`). Separate pools for meta recommendations, novelty judging, prompt evolution and embeddings |
| Client | Synchronous `openai.OpenAI` | Synchronous `openai.OpenAI`, in worker threads | `openai.AsyncOpenAI`, run with `asyncio.run` inside each worker | Each provider's own SDK (OpenAI, Anthropic, Google GenAI, DeepSeek, Azure, Bedrock, OpenRouter), synchronous and asynchronous |
| Providers | Any OpenAI-compatible server | Any OpenAI-compatible endpoint, one address per model (a local Ollama server, Anthropic's compatible endpoint) | OpenAI-compatible, plus Claude Code CLI, Copilot CLI, Codex app-server, "manual mode" (a human answers through a file queue), or a custom `init_client` | Those SDKs, local OpenAI-compatible servers (`local/<model>@<url>`), and coding agents run through the Headless CLI on your subscriptions (`headless/codex`, `headless/claude`) |
| Parameters sent | `max_tokens` (4096, or none) | `max_tokens` (16,384), optional temperature and reasoning effort, unset ones not sent; reasoning models get `max_completion_tokens` | temperature (0.7), top_p, max_tokens (4096), seed, reasoning_effort; reasoning models are detected by name and get `max_completion_tokens` | Drawn per call: a temperature from a list (`[0.0, 0.5, 1.0]`), a reasoning effort from a list; max_tokens 16,384; per-model rules (no temperature for some, thinking budgets for Gemini) |
| Timeout and retries | 300 s; the `openai` package's own 2 retries | 300 s per model by default; one layer of retries, the `openai` package's 2 | 60 s; its own loop of 3 retries 5 s apart, *on top of* the `openai` package's retries (Part D) | 1,200 s; exponential backoff up to 20 tries; the SDKs' own retries turned off |
| Token usage and cost | Not recorded | Tokens of every call saved with the program; optional prices per model, for reporting only | Tokens per call and totals, logged and stored | Tokens and dollar cost of every call (LLM, embedding, novelty, meta), priced from a model catalog refreshed from models.dev at start-up and saved with the run |
| Budget | `--iterations` and `--max-reply-tokens` bound the cost | The iteration count and `max_tokens` only | Iterations only | `max_api_costs` in dollars: no new proposal once committed costs reach it |
| A failed call | `LLMError`: the iteration is skipped; 3 in a row stop the run | The iteration is skipped but counts as completed; see the next rows | The iteration fails and the run carries on; if no iteration at all produced a candidate, the run ends with `EvolutionFailedError` | The attempt fails and is retried as a failed patch would be (A5); a proposal that exhausts its attempts is recorded as failed; a "stuck" detector ends a run that makes no progress |
| Embeddings | None | None | Optional, for the novelty filter | On by default (`text-embedding-3-small`): for the novelty filter, the crowding archive, and the WebUI's similarity views |
| Start-up check | None | A one-line test request to every model; any failure stops the run | None | Checks that every model has credentials |
| A model that keeps failing | 3 failed iterations in a row stop the run | Dropped after 3 failures in a row; the others' weights are rescaled | Keeps being drawn | No rule of its own; the run carries on |

### A7. The loop

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Parallelism | Threads (`ThreadPoolExecutor`), `--workers` (1) | Daemon threads, `--workers` (1) | Processes (`ProcessPoolExecutor`), `parallel_evaluations` (1 without a config file, 4 in `default_config.yaml`) | One asyncio event loop with three separate limits: proposals being generated (`max_proposal_jobs`), evaluations running as subprocesses (`max_evaluation_jobs`), database workers (`max_db_workers`) (`core/async_runner.py`, 6,250 lines) |
| One iteration | In the worker: ask the LLM, extract the code, evaluate | Main thread: island, parent, example programs, model, prompt. Worker: LLM call, parsing. Main: checks. Worker: evaluation. Main: storing, grid, migration | In the worker: rebuild the programs from a snapshot, build the prompt, ask the LLM, parse, evaluate | Proposal: choose a model, sample parent and inspirations, build the prompt, ask the LLM, apply the patch (with retries), embed, novelty check, write `gen_N/main.<ext>`. Then evaluation: run `evaluate.py`, read its files, store, update archive, islands and bandit |
| Shared state | Only the main thread touches the database and the files | Only the main thread touches the database and the files | The main process owns the database; each submitted iteration receives a pickled snapshot of *every* program (plus up to 100 artifact sets) | The SQLite file: samplers read through their own read-only connections, writes go through the database workers |
| When the parent is chosen | When the iteration starts, in the main thread | When the iteration starts, in the main thread; islands drawn uniformly | The same, in the main process; the target island is chosen round-robin (or by `island_selector`) | When the proposal starts |
| How many iterations are in flight | Exactly `workers` | Exactly `workers` | `2 × workers` at the start, spread over the islands, then one new per completion | Up to `max_evaluation_jobs` evaluations, plus proposals; optionally an adaptive controller generates extra proposals when LLM calls are slower than evaluations ("controlled oversubscription") |
| Waiting for results | `wait(FIRST_COMPLETED)` in 0.2 s steps (for Ctrl+C on Windows) | A queue of finished tasks, read in 0.2 s steps (for Ctrl+C on Windows) | Polls every future every 10 ms in an asyncio loop. A guard meant to give up after `evaluator.timeout + 30` s never fires (Part D) | Asynchronous polling of the evaluation processes |
| Stop conditions | Iteration count, Ctrl+C, 3 LLM failures in a row | Completed iterations, `--target-score`, `--patience`, no LLM model left, 3 infrastructure errors in a row, Ctrl+C | Iteration count, `--target-score` on `combined_score`, early stopping (patience, minimum improvement, chosen metric; negative patience = stop when the metric *equals* a value), SIGINT / SIGTERM | `num_generations` (a total, not "more"), the dollar budget, the stuck detector; no target score, no patience |
| Do failed iterations count? | Yes | Yes, skipped ones included | Yes | Yes: a failed proposal uses up its generation number; results beyond the target are discarded |
| After each result | Store, append to disk, update the best file, print a line | Store, update grid and best, append to the history; every 10 completed iterations a snapshot of the best, every 25 a migration | Store, store artifacts, trace, log the prompt, increment the island's generation, migrate if due, log, checkpoint if due, check target score and early stopping | Store, update the archive and best, migrate if due, update the bandit, feed the meta summariser, refresh `best/`, log to the WebUI database and optionally W&B |

### A8. Randomness and repeatability

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Default seed | None (random runs) | None: one is drawn at random and saved | 42 | No seed option at all |
| What the seed controls | Only parent choice, through the database's own `random.Random`, so programs that call `random.seed` do not disturb it | The run's own `random.Random`: island, parent, example programs, migrants, model; reseeded from the seed and the number of programs on resume, so draws do not repeat | Python's global `random` and `numpy.random`, a seed derived for the LLM (sent to the API), the ensemble's model choice | n/a: global `random` and `numpy.random`, unseeded |
| Claimed repeatability | Parents only, and only with one worker | The draws, with one worker; not the LLMs' replies | "Fully deterministic" in the README; in practice not with several workers, nor with an LLM that ignores `seed` | None claimed |

---

## Part B: the engineering around it

### B1. Running untrusted programs

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Mechanism | A fresh Docker container per evaluation, removed afterwards (`DockerEvaluator`) | A fresh Docker container for each cascade stage; the evaluator stays on the host and reaches the program only through its function calls | None of its own: `evaluate` runs in a thread of a pool worker process. The program runs wherever the evaluator runs it: in the worker itself (function minimization imports it), or in a subprocess the evaluator starts (circle packing) | A new process per evaluation running the user's `evaluate.py`, which imports the program. Backends: local (current interpreter, a sourced venv or a conda env), or a Slurm cluster job (in a conda env, or in Docker) (`launch/`) |
| Network | None (`--network none`) | None | Full | Full locally; on Slurm with Docker, whatever `docker_flags` allow (nothing is restricted by default) |
| File system | Read-only, except a temporary `/tmp`; sees only the package and the problem folder, read-only | Read-only except a temporary `/tmp`; sees only the `my_evolve` package, read-only | Everything the user can access | Everything the user can access (locally) |
| Limits | 1 GB memory (no swap), 1 CPU, 64 processes, all capabilities dropped, user `nobody` | v1's, settable in the problem file: 1 GB (no swap), 1 CPU, 64 processes, no capabilities, user `nobody`; numeric libraries' threads capped to the CPU count; 60 s per stage | None (`memory_limit_mb` and `cpu_limit` exist in the config but are marked "not implemented") | None locally, except optional thread caps for numeric libraries (`numeric_threads_per_job` sets `OMP_NUM_THREADS` and similar); on Slurm, the requested CPUs, GPUs, memory and time |
| Secrets | The container gets no environment variables from the host | None reach the container | Each worker copies the whole parent environment, API keys included, and LLM-written code can read it | Local evaluations copy the whole environment, API keys included (and `.env` files are loaded into it at start-up) |
| How the program is passed / the result returned | Code on stdin; result as the last JSON line of stdout (`container_worker.py`) | The code in a `load` message on stdin; calls and their results as JSON messages, one per line; numpy arrays without pickle | A temporary file with the program's extension; the return value of `evaluate` | A file in the generation's folder; results as JSON files written by the evaluator; stdout and stderr captured to `job_log.out` / `job_log.err` |
| Image | Built on first use from `evaluation.Dockerfile` plus the requirements; tag = hash of both, so it rebuilds when they change | Built on first use from `evaluation.Dockerfile` and the problem file's packages, tagged with a hash of both | n/a. openevolve's `Dockerfile` runs openevolve itself, not the programs | On Slurm with Docker, a given image (`ubuntu:latest` by default) or a tarball |
| Cost | About 1 s per evaluation for container start | About 1 s per cascade stage | Negligible | A Python start plus imports per evaluation |
| Without Docker | Refuses to run; tests use an `InProcessEvaluator` stand-in | An unsafe local sandbox (`--unsafe-local-sandbox`), for tests and trusted code, announced with a warning | n/a | The default |

### B2. Configuring a run

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Mechanism | CLI flags only (`scripts/run.py`, argparse) | A YAML problem file (problem, cascade, sandbox, grid, islands, parents, prompt, and an `llm` section laid out like openevolve's), plus a few CLI flags | A YAML file loaded into dataclasses (`config.py`, via `dacite`), plus a few CLI overrides | Three ways over the same dataclasses (`EvolutionConfig`, `DatabaseConfig`, a `JobConfig`): the Python API (`ShinkaEvolveRunner`), Hydra presets composed by `shinka_launch` (task, database, evolution, cluster, variant), or `shinka_run --task-dir` with an optional YAML and `--set key=value` overrides |
| CLI options | `initial_program evaluation_file --model --llm-url --api-key-env --max-reply-tokens --iterations --output --timeout --workers --seed` | `INITIAL_PROGRAM EVALUATION_FILE --config --iterations --output --workers --seed --target-score --patience --unsafe-local-sandbox --verbose` | `initial_program evaluation_file --config --output --iterations --target-score --log-level --logger-prefix --checkpoint --api-base --evaluator-args --primary-model --secondary-model` | `shinka_run --task-dir --results_dir --num_generations --config-fname --set --max-evaluation-jobs --max-proposal-jobs --max-db-workers --verbose --debug` |
| Number of settings | 10 | About 40 | About 100, in sections `llm`, `prompt`, `database`, `evaluator`, `evolution_trace` and top-level | About 100, in `evo`, `db`, `job` and three runner limits |
| Validation | Every value checked, clear errors | Every value checked; unknown keys are an error | Mostly unchecked; **unknown keys are silently dropped** (the circle-packing config sets `allow_full_rewrites: true`, which does not exist); only `llm.model` gets a dedicated error | `shinka_run` rejects unknown keys and namespaces; some values are checked (probabilities sum to 1, exclusive options) |
| API key | Read from the environment variable named by `--api-key-env` (default `OPENAI_API_KEY`); never written anywhere | `${VARIABLE}` in the problem file names the environment variable; a key written in the file is refused | `api_key` in the YAML, `${VAR}` to read a variable, or `OPENAI_API_KEY`; serialized to every worker | Each provider's usual variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, ...), also read from `.env` files; the start-up checks that every configured model has credentials |
| Defaults | One set, in the code | One set, in the code, listed in design-decisions.md | Two sets that disagree: the dataclasses (e.g. 10,000 iterations, checkpoint every 100, 1 worker) apply without a config file, `configs/default_config.yaml` documents others (100, 10, 4) | Layered: dataclass defaults, then presets, then overrides; the documentation lists the order of precedence |
| Use from Python | `run_my_alphaevolve(problem, llm, evaluator, ...)` | `run(settings)` | `run_evolution`, `evolve_function`, `evolve_algorithm`, `evolve_code` (`api.py`), accepting code strings and evaluator callables | The main interface: build the configs, create `ShinkaEvolveRunner`, call `run()` (or `await run_async()`) |

### B3. Results on disk, and continuing a run

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Where | `--output FOLDER`; nothing is saved without it | `--output`, by default `runs/<problem>_<date>_<time>/`; always saved | `--output`, by default `openevolve_output/` next to the initial program; always saved | `results_dir`, by default `results_<timestamp>/`; always saved |
| Program records | `programs.jsonl`: one line per program, appended the moment it is evaluated | `programs.jsonl`, appended as each program is stored: children of every status, island copies, migrants | `checkpoints/checkpoint_N/programs/<id>.json`, one file per program (with its prompts and reply when `log_prompts`), written every `checkpoint_interval` iterations; each checkpoint is a full copy | `programs.sqlite`, written as each program is evaluated; plus a folder per generation, `gen_N/`, with the program, the parent's code, the diff, the raw patch, every LLM attempt (reply, patch, metadata), and `results/` (metrics, correctness, logs, extra data, plots) |
| Other state | None needed: the database is rebuilt from the programs | None needed: the database is rebuilt by replaying the programs; `history.csv` (one line per completed iteration), `run.json` (seed, fingerprints, sessions), `problem.yaml` | `metadata.json` per checkpoint: islands, grids, archive, best ids, generations, feature statistics | In the SQLite file (archive, best, islands, event and attempt logs), plus `bandit_state.pkl`, the meta summariser's memory, `pricing_snapshot.json`, the prompt archive when prompts evolve |
| Best program | `best_program.py`, rewritten whenever the best changes, with a header comment (score, iteration, id) | `best_program.py`, rewritten when the best changes, plus `best/iteration_0010.py`, … every 10 completed iterations | `checkpoints/checkpoint_N/best_program.<ext>` + `best_program_info.json`, and `best/` at the end of the run | `best/`: a copy of the best generation's folder, refreshed whenever the best changes |
| Prompts and LLM replies | Not saved | `llm_calls.jsonl`, failed calls included | Saved in the program files; also in the optional evolution trace | Every attempt's reply saved in its generation folder |
| Evolution trace | n/a | None: the two JSONL files hold the same data | Optional `evolution_trace.jsonl` (or JSON, HDF5): parent, child, metrics, prompt, reply, diff, for analysis or RL training | n/a (optional Weights & Biases logging instead) |
| Artifacts | n/a | `output_data`, inside each program's line | Small ones in the program JSON, those over 32 KB in an `artifacts/` folder, cleaned after 30 days | `extra.pkl` and plots in each generation's folder |
| Programs that were removed | None are removed | None are removed | Deleted programs (population limit, displaced cell owners) are absent from later checkpoints: the history is incomplete | None are removed |
| Continuing | Run the same command with the same `--output`; `--iterations` = that many more; the initial program is not re-evaluated | The same command with the same `--output`; `--iterations` is a total, so the same command finishes an interrupted run | `--checkpoint checkpoints/checkpoint_N`; `--iterations` = that many more | Run again with the same `results_dir`; `num_generations` is the *total*, so the same command finishes the original target; costs, bandit and meta memory are restored |
| What is lost on an abrupt stop | Nothing already evaluated; a cut-off last line is detected and dropped | Only the iterations in progress; a cut-off last line is dropped | Everything since the last checkpoint (up to `checkpoint_interval − 1` iterations) | Proposals and evaluations in progress; everything evaluated is in SQLite |
| Different problem in the same folder | Not detected (the README warns) | Detected by fingerprints of the files and settings: the run refuses to continue | Not detected | Not detected |
| Viewing a run | Reading `programs.jsonl` | `scripts/report.py`: progress plot, grid pictures and their animation, circle-packing drawings | A Flask web visualizer of the program tree (`scripts/visualizer.py`) | A WebUI served from the SQLite file (`shinka_visualize`: tree, metrics, code, diffs, timelines, embeddings), plotting functions (lineage tree, Pareto front, costs, throughput), notebooks, optional W&B |
| Picture of the grids | n/a | Each island's grid at every snapshot, cells coloured by their elite's score, and an animation | None: the visualizer marks MAP-Elites members in the program tree | n/a (no grids) |

### B4. Logging and console output

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Mechanism | `print()` | The `logging` module: the console and `log.txt` in the run folder | The `logging` module: the root logger gets a console handler and a file handler, `logs/openevolve_<timestamp>.log` | The `logging` module with a Rich console handler, and `evolution_run.log` in the results folder |
| Per iteration | One line: iteration, child score, generation, best score | One line: iteration, island, model, the child's status and score, best score | Several lines per iteration and per component (sampled model, token usage, MAP-Elites cell events, metrics, island status), with timestamps and emoji | Many lines and Rich tables per proposal (sampled parent and inspirations, patch metadata, novelty checks, costs, bandit state, island summary) |
| Levels | None | `--verbose` | `log_level`, `--log-level`; `logger_prefix` to tell concurrent runs apart | `--verbose`, `--debug` |

### B5. Ctrl+C and other ways of stopping

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| First Ctrl+C | `KeyboardInterrupt` caught in the main thread: nothing new starts; iterations in progress finish and are saved | As in v1: nothing new starts; iterations in progress finish and are saved | SIGINT handler sets a shutdown event; the loop stops at its next check; pending futures are cancelled and the worker processes terminated, so iterations in progress are lost | Not handled: asyncio cancels the tasks; proposals in progress (LLM calls already paid for) and evaluations in progress are lost |
| Second Ctrl+C | Stops waiting for them, prints "skipped"… but the process still waits for them before exiting (Part D) | Stops within seconds: containers killed, worker threads not waited for | `sys.exit(0)` from the signal handler | n/a |
| Checkpoint on stop | Not needed (already appended) | Not needed (already appended) | None: the run ends without a final checkpoint; only `best/` is written | Not needed (already in SQLite) |
| SIGTERM | Not handled: Python's default kills the process | Handled like a second Ctrl+C (Linux) | Same handler as SIGINT | Not handled |
| Leftover processes | Containers of interrupted evaluations can outlive the run (Part D) | Containers labelled with the run's id and removed when the run stops and at the next start; each also has its own time limit | Worker processes are terminated, then killed after 1 s; subprocesses started by an evaluator are not tracked | The clean-up does not stop running evaluations: local ones usually die from the same terminal SIGINT, Slurm jobs keep running; killing a hung evaluation kills only the evaluator process, not processes it started |

### B6. Platform, packaging and tooling

| | my-alphaevolve | my-evolve (planned) | openevolve | ShinkaEvolve |
|---|---|---|---|---|
| Platforms targeted | Windows first (PowerShell commands, UTF-8 output, Ctrl+C wake-up), Linux and macOS | Linux and Windows | Mostly Linux and macOS; Windows is mentioned only for multiprocessing caveats, and some providers do not support it | Linux and macOS, and Slurm clusters; Windows is mentioned only for activating a virtual environment |
| Layout | `src/my_alphaevolve/`, entry point `scripts/run.py` | `src/my_evolve/`, entry points `scripts/run.py` and `scripts/report.py` | Flat `openevolve/` package, console script `openevolve-run`, `openevolve-run.py` | Flat `shinka/` package, console scripts `shinka_launch`, `shinka_run`, `shinka_visualize`, `shinka_models` |
| Dependencies | `openai` only | `openai`, `pyyaml`; on the host also numpy (evaluation files) and matplotlib (report) | `openai`, `pyyaml`, `numpy`, `tqdm`, `flask`, `dacite`, `cloudpickle` | About 26, among them `openai`, `anthropic`, `google-genai`, `boto3`, `hydra-core`, `pandas`, `scikit-learn`, `radon`, `matplotlib`, `moviepy` |
| Code style | ruff (lint + format), mypy `strict`, plain-English docstrings and comments throughout | v1's: ruff, mypy strict, plain-English docstrings and comments | black, isort, partial typing | ruff, partial typing |
| Tests | `unittest`, 193 tests; a fake OpenAI-compatible HTTP server; Docker tests skipped when Docker is missing | v1's: `unittest`, a fake OpenAI-compatible server, Docker tests skipped without Docker | `unittest` and `pytest`, 95 test files; integration tests against a small local model served by optillm; CI workflows | `pytest`, 79 files and about 615 tests; live-provider tests marked and skipped without secrets; CI workflows |
| Size of the core | About 1,300 lines (`src/` and `scripts/run.py`) | Not written yet; planned as about 19 modules (design-decisions.md, section 14) | About 11,700 lines in `openevolve/`, plus 1,800 in `compat/` | About 41,800 lines in `shinka/` |
| Documentation | README | README, plus `design-decisions.md` (the design) and this file | README, example READMEs | A documentation website, a tutorial notebook, and "skills" that teach coding agents (Claude Code, Codex) to set up, convert, run and inspect tasks |

---

## Part C: what exists in only some of them

### In openevolve and ShinkaEvolve, not in my-alphaevolve

- Islands, migration and an elite archive (A3).
- Programs other than the parent shown in the prompt (A3, A4).
- SEARCH/REPLACE diffs; EVOLVE-BLOCK markers (A1, A5).
- Several LLMs per run; several providers; token accounting (A6).
- Several metrics per program, and feedback text from the evaluator (A2).
- Novelty filtering with embeddings and an LLM judge (A3).
- Any programming language (A1).
- Configuration files (B2), a web viewer of runs (B3), the `logging` module (B4).

### Only in openevolve

- MAP-Elites grids, a population limit (A3).
- Framework-level cascade evaluation, LLM-as-judge scores, retries of evaluations (A2).
- Code-length limit (A5).
- Target score and early stopping (A7).
- Template directories, random wording variations, per-island system messages, changes-description mode (A4).
- Periodic checkpoints, evolution traces (B3).
- `PopulationStrategy` and `island_selector` hooks; co-evolution of two populations (`coevolution.py`); compatibility layer with Google's AlphaEvolve evaluators and bundles (`compat/`).
- Manual (human) mode (A6).
- A default seed (A8).

### Only in ShinkaEvolve

- Parent selection weighted by score and by how few children a program has (A3).
- Novelty rejection *before* evaluation, regenerating rejected proposals (A3).
- A bandit that learns which LLM improves programs most, optionally per dollar (A6).
- Mandatory, enforced EVOLVE-BLOCK markers (A1).
- Three change formats mixed per proposal, including crossover of two programs; five full-rewrite strategies (A4, A5).
- Repairing a failed patch by telling the LLM its error, in the same conversation (A5).
- "Fix mode" when no program is correct; a separate correctness flag (A2, A3).
- An LLM-written initial program (A1).
- Meta recommendations: a running summary of what worked, injected into prompts (A4).
- Evolving the system prompt itself (A4).
- New islands spawned when the search stagnates; crowding and multi-criteria archives (A3).
- Public vs private metrics; repeated runs with statistical early stopping in the evaluator helper; plots per program (A2).
- Separate limits for proposals and evaluations, with adaptive oversubscription (A7).
- Dollar costs from a live price catalog, and a dollar budget (A6).
- SQLite storage; a folder per generation with every LLM attempt (B3).
- Slurm cluster backends (B1).
- Hydra presets (B2); Weights & Biases logging (B3); agent skills and a documentation site (B6).

### Only in my-alphaevolve

- A sandbox: network-less, read-only, resource-limited container per evaluation (B1).
- Allowed packages, installed in the image and announced to the LLM (A1).
- Problem description in the initial program's docstring, checked at start (A1).
- A reply parser that copes with thinking models, quoted parents, unclosed and nested blocks (A5).
- First Ctrl+C finishes the iterations in progress (B5).
- A stop after 3 LLM failures in a row (A6).
- Score validation (finite number, not a bool) (A2).
- Clean loading of the evaluation file: helper modules next to it are imported and then forgotten, so two problems can each have a `utils.py` (`problem.py:load_score_function`).
- Windows support (B6).
- Strict typing and validation of every user input (B2, B6).
- A core small enough to read in an afternoon (B6).

(Append-only saving, which loses nothing on a crash, is shared with ShinkaEvolve's SQLite.)

my-evolve keeps all of these, except two: the problem description moves to the problem file (D4), and the
stop after 3 LLM failures becomes a per-model rule (D34).

### What my-evolve takes from the others

- From openevolve: islands with a MAP-Elites grid each (A3); evolve blocks and its initial programs (A1); the
  cascade with per-stage thresholds (A2); a weighted model ensemble and an `llm` section laid out like its
  config (A6, B2); target score and patience (A7); the YAML configuration file (B2).
- From ShinkaEvolve: the weighted parent selection by score and number of children (A3); rejection of edits
  outside the evolve blocks (A1, A5); a run continued with a total iteration count (B3).

### Only in my-evolve

- The evaluation file runs on the host; the program runs in its container and only answers calls, so it cannot
  touch how its score is computed (A2, B1).
- Five statuses, telling an illegal answer (`invalid`) and an infrastructure failure (`error`) apart from a
  crash or a timeout (A2).
- Failed programs shown to the LLM as unlabelled previous attempts, beside working ones (A3, A4).
- Grid features from the evaluator's view of the output (circle packing's radii spread and radius/centre
  correlation) next to a code feature counted inside the evolve blocks only, on a grid fixed when the run
  starts (A3).
- The weighted parent rule adapted to MAP-Elites: drawn among grid elites, with λ = 1 and fallbacks when the
  spread is 0 (A3).
- Descriptions of programs that never refer to the parent, so they still make sense out of context (A5).
- Duplicates rejected against every earlier program, by syntax tree, before any evaluation (A3).
- A one-line test of every model before the run, and a failing model dropped instead of stopping the run (A6).
- A refusal to continue a run whose problem files or settings changed (B3).
- Snapshots of the best program every 10 completed iterations, and a report drawing the islands' grids over
  time (B3).
- A second Ctrl+C that stops within seconds, killing the containers (B5).

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

How my-evolve's design answers these: 1 and 2 (D42, D54), 3 (D8), 4 (D3, its evaluation files are ports of
openevolve's current ones), 5 (`null` scores, D7), 6 and 7 (the checks of D13, D38), 8 (`llm_calls.jsonl`, D47),
9 (D39).

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

### In ShinkaEvolve

1. **There is no seed anywhere.** Parents, islands, patch types, rewrite strategies, temperatures and models are drawn from unseeded global `random` and `numpy.random`, so no part of a run can be repeated.
2. **LLM-written code runs with your API keys and the network**: local evaluations inherit the whole environment, `.env` files included, with no limits.
3. **No evaluation time limit by default.** Until enough evaluations have finished to compute an average, nothing bounds a program that never ends except the 60 s floor of the hung-job rule; and `process.kill()` reaches only the evaluator process, not processes it started (e.g. with `run_workers > 1`).
4. **Ctrl+C is not handled**, so proposals already paid for are lost, and Slurm jobs keep running after the run stops.
5. **A program can forge its result**: it runs inside the evaluator's process, whose command line names the results folder, so it can write its own `metrics.json` and `correct.json` and exit before the evaluator does.
6. **`exploitation_ratio` does nothing.** It is documented as the "chance to pick parent from archive", but no parent-selection strategy reads it (only a `hasattr` check and the W&B config do).
7. **Embeddings are paid for by default, but the novelty filter is off by default**: it only runs when `novelty_llm_models` is set, so with the defaults the embeddings serve the archive's crowding option and the WebUI only.
8. **"Generation" means proposal number**, not distance from the initial program, which that number is easily mistaken for; the distance itself is not stored.
9. **The defaults assume paid accounts with two providers**: four OpenAI and Google models plus OpenAI embeddings.
