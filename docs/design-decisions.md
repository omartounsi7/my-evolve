# Design decisions for my-evolve

Every difference in [differences.md](differences.md) is a choice to make again. This file lists
those choices, grouped by topic, with:

- **v1**: what my-alphaevolve does;
- **OE**: what openevolve does;
- **Options**: the realistic alternatives, including ones neither repository uses;
- **Lean**: my suggestion, as a starting point for discussion;
- **Decision**: left blank for you.

Each decision is tagged:

- **[now]**: it shapes the architecture; better decided before the plan is written.
- **[later]**: it can wait for the step of the plan that needs it; the plan will note a default.

Section references such as (A3) point to differences.md.

---

## 1. Scope

### D1. How far to go [now]
- **v1**: a minimal core, about 1,300 lines.
- **OE**: most features of the AlphaEvolve paper (evolve blocks, diffs, ensembles, MAP-Elites with
  islands, cascades, LLM feedback, several metrics) plus many of its own; about 13,500 lines.
- **Options**: a small core, adding OE features one by one only when chosen below · feature parity with OE.
- **Lean**: a small core with clear places where features plug in; each feature chosen below
  becomes its own step of the plan.
- **Decision**:

### D2. Languages of the evolved programs [now]
- **v1**: Python only; programs are `exec`'d.
- **OE**: any language; the evaluator runs the file.
- **Options**: Python only · any language, which forces the evaluator to receive a file path (D5)
  and the sandbox image to hold compilers.
- **Lean**: Python only.
- **Decision**:

### D3. Compatibility with openevolve [later]
- **v1**: the examples are adapted so that their scores equal OE's.
- **Options**: none · same scores on adapted examples (as now) · run OE evaluators unchanged
  (`evaluate(program_path)` returning a dict).
- **Lean**: same scores on adapted examples, so runs stay comparable.
- **Decision**:

---

## 2. The problem and its evaluation

### D4. Where the problem description lives [later]
- **v1**: required docstring of the initial program (A1).
- **OE**: `prompt.system_message` in the YAML.
- **Options**: docstring · a field of a problem config file · a separate `description.md` in the problem folder.
- **Lean**: a separate file: descriptions grow long (circle packing's lists geometric insights), and it
  keeps the initial program a plain program.
- **Decision**:

### D5. What the evaluator receives [now]
- **v1**: `evaluate(namespace)`, the names the program defined, after the framework ran it.
- **OE**: `evaluate(program_path)`; the evaluator loads or runs the program itself.
- **Options**: namespace · file path · the code as a string.
- **Lean**: namespace, if D2 is Python only: evaluators stay short and cannot get loading wrong.
  Linked to D8.
- **Decision**:

### D6. What the evaluator returns [now]
- **v1**: one finite number.
- **OE**: a dict of metrics with a `combined_score` convention (and a fallback average), or metrics + artifacts.
- **Options**: one number · a dict with a designated main score · a small result object:
  `score` (required), `metrics` (optional numbers, for display and MAP-Elites features),
  `feedback` (optional text for the LLM).
- **Lean**: the result object, still accepting a bare number. No averaging fallback: the main score is explicit.
- **Decision**:

### D7. Failed programs [now]
- **v1**: score `-inf`, stored, never a parent, saved as `-Infinity`.
- **OE**: metrics `{"error": 0.0}`, fitness 0, can enter the grid and be a parent.
- **Options**: a sentinel score (`-inf`, `0`) · an explicit status (`ok`, `failed`, `timeout`,
  `rejected`) with no score and an error message.
  And separately: are failures stored? shown to the LLM? ever parents?
- **Lean**: explicit status + error message; stored and saved; never parents; their error shown to
  the LLM when the prompt mentions recent failed attempts (D23).
- **Decision**:

### D8. Where the evaluator runs relative to the program [later]
- **v1**: in the same Python process, inside the container; the program can forge its result or
  patch what `evaluate` uses (Part D, item 3).
- **OE**: the same, or the evaluator's own subprocess.
- **Options**: same process (as now) · same process, with a result channel the program cannot
  write to · the program runs in the container and returns the value of an entry function
  (e.g. `run_packing()`), which the evaluator scores on the host.
- **Lean**: same process for now, with the risk documented; revisit if reward hacking shows up.
- **Decision**:

### D9. Cascade evaluation [later]
- **v1**: written inside the user's `evaluate`.
- **OE**: framework-level `evaluate_stage1/2/3` with thresholds in the config.
- **Options**: inside `evaluate` · framework stages.
- **Lean**: inside `evaluate`: nothing for the framework to know.
- **Decision**:

### D10. Feedback from the evaluation to the LLM [now]
- **v1**: none; the LLM sees only the parent's score.
- **OE**: artifacts (any text the evaluator returns, or a traceback) shown in the next prompt that
  uses the program as parent.
- **Options**: none · `feedback` text from the evaluator (D6) · that, plus the tail of the
  program's stderr captured automatically.
- **Lean**: evaluator feedback plus a captured error for failures, truncated to a size limit.
- **Decision**:

---

## 3. How the LLM changes a program

### D11. Format of a change [now]
- **v1**: full rewrite of the file.
- **OE**: SEARCH/REPLACE diffs by default; full rewrite optional.
- **Options**: full rewrite · diffs · both, chosen per run · both, chosen per iteration (e.g. by
  program length, or at random).
- **Lean**: both, chosen per run; full rewrite first in the plan, diffs as a later step.
- **Decision**:

### D12. Which part of the program may change [now]
- **v1**: the whole file.
- **OE**: the whole file, with advisory EVOLVE-BLOCK markers, enforced only on request.
- **Options**: whole file · markers, advisory · markers, enforced (edits outside are reverted, or
  the child is rejected) · markers, and only the blocks are shown to the LLM.
- **Lean**: markers optional: if the initial program has them, they are enforced and the prompt
  explains them; otherwise the whole file may change.
- **Decision**:

### D13. Checks before a child is evaluated [later]
- **v1**: none; even a copy of the parent is evaluated.
- **OE**: rejects unparsable diffs, unchanged code, code over 10,000 characters.
- **Options**, any combination: not valid Python (`ast.parse`) · same program as the parent (AST
  comparison, as v1's parser already does) · same as any program in the database · too long ·
  diff that does not apply.
  And: is a rejected child stored (with its reason) or only counted?
- **Lean**: all of them; rejected children stored with status `rejected` and their reason, not evaluated.
- **Decision**:

### D14. Record of what changed [later]
- **v1**: none.
- **OE**: a text summary of the diff, shown in later prompts.
- **Options**: none · the diff itself (computed with `difflib` even for rewrites) · a one-line
  explanation asked of the LLM in a fixed place of its reply.
- **Lean**: store a computed diff for every child; ask for an explanation only if D23 shows history.
- **Decision**:

---

## 4. The database and the choice of parents

### D15. Population structure [now]
- **v1**: a flat list; MAP-Elites tried and reverted (`aeaf384`, `4a1e438`).
- **OE**: islands, each with its own MAP-Elites grid, plus a global archive.
- **Options**: flat · one MAP-Elites grid · islands of flat populations · islands with a grid each.
- **Lean**: islands with a grid each as the target, built in three plan steps (flat, then grid,
  then islands) behind one `Database` interface, so each step can be run and compared.
- **Decision**:

### D16. MAP-Elites features [later, if D15 uses a grid]
- **v1** (`aeaf384`): complexity = code length, diversity = OE's quick estimate against the first 20 programs.
- **OE**: the same two, `score`, or any evaluator metric.
- **Options**: code length · lines of code · a diversity measure (OE's estimate, edit distance,
  AST difference) · metrics returned by the evaluator (D6).
- **Lean**: default code length × diversity; let a problem name evaluator metrics instead.
- **Decision**:

### D17. Binning features into cells [later, if D15 uses a grid]
- **v1** (`aeaf384`): grid rebuilt from all programs at each sample, so bins always span the values seen.
- **OE**: running min/max at insertion; bins drift and old placements are never recomputed.
- **Options**: rebuild at each sample · running min/max (OE) · fixed ranges declared by the problem.
- **Lean**: rebuild at each sample: always consistent, and cheap for thousands of programs.
- **Decision**:

### D18. Choosing a parent [now]
- **v1**: 70% a random one of the 10 best working programs, 30% a random working program.
- **OE**: per island, 20% uniform, 70% a random archive elite, 10% fitness-weighted.
- **Options**: v1's rule · OE's rule · a uniform random grid elite (`aeaf384`) · tournament (best
  of k random programs) · rank-based (probability falling with rank).
- **Lean**: v1's exploit/explore rule, applied within the chosen island and among grid elites, with
  the ratio and the 10 configurable.
- **Decision**:

### D19. Forgetting programs [later]
- **v1**: every program kept forever, in memory and on disk.
- **OE**: a population limit deletes the worst programs that own no cell; displaced cell owners
  are deleted; checkpoints lose them.
- **Options**: keep all · cap what selection sees, keep all on disk · delete.
- **Lean**: keep all on disk; let selection ignore what it does not need (a grid already does).
- **Decision**:

### D20. Islands [later, if D15 uses islands]
- **OE**: 5 islands; the initial program only in island 0, others filled by its descendants;
  children go to the island the iteration was scheduled for; ring migration of the top 10% every
  50 programs, as copies.
- **Options to settle**: number of islands · seeding (initial program copied to every island, or
  not) · scheduling (round-robin, least busy) · migration (topology, interval in iterations or
  generations, how many, copy or move).
- **Lean**: initial program in every island; round-robin; ring migration of each island's best
  every N iterations, as copies.
- **Decision**:

### D21. Duplicates and near-duplicates [later]
- **v1**: none.
- **OE**: optional embeddings plus an LLM "novel or not" judge.
- **Options**: none · reject exact or AST-identical code anywhere in the database (D13) · embeddings.
- **Lean**: AST-identical rejection only; no embeddings.
- **Decision**:

---

## 5. The prompt

### D22. Message structure [later]
- **v1**: one user message.
- **OE**: system message (role) plus user message.
- **Options**: one message · system message for the fixed rules (role, reply format, allowed
  packages), user message for the problem and the programs.
- **Lean**: system + user.
- **Decision**:

### D23. Programs shown besides the parent [now]
- **v1**: none.
- **OE**: top programs of the island, "diverse" ones, inspirations from nearby cells, "previous
  attempts" (which are really top programs).
- **Options**, any combination: top k by score · programs from other cells or islands · the
  parent's ancestors with their scores and changes · the parent's recent failed children with their errors.
- **Lean**: top k plus a few from other cells; the parent's lineage as a short list; numbers configurable.
- **Decision**:

### D24. What the prompt says about scores [later]
- **v1**: the parent's score.
- **OE**: fitness, feature coordinates, metrics, "fitness improved / declined" hints.
- **Options**: parent score · plus best score so far · plus metrics · plus feedback (D10) · plus hints.
- **Lean**: parent score, best score so far, metrics and feedback; no canned hints.
- **Decision**:

### D25. Where templates live [later]
- **v1**: one string in `prompt_sampler.py`.
- **OE**: text files, overridable by the user, random wording variations.
- **Options**: Python constants · text files in the package · user-overridable per problem.
- **Lean**: Python constants in one module; no random variations.
- **Decision**:

### D26. Prompt size [later]
- **v1**: unbounded (Ollama silently truncates long prompts).
- **OE**: artifacts truncated to 20 KB; nothing else bounded.
- **Options**: no limit · a character budget, dropping context programs first · a token count.
- **Lean**: a character budget with a warning.
- **Decision**:

---

## 6. The LLM

### D27. One model or an ensemble [now]
- **v1**: one model.
- **OE**: weighted ensemble, one model drawn per call.
- **Options**: one · ensemble.
- **Lean**: one model; an ensemble is later a small wrapper behind the same `LLM` interface.
- **Decision**:

### D28. Client and providers [later]
- **v1**: synchronous `openai` client; any OpenAI-compatible server.
- **OE**: async `openai` client, plus CLI-based providers.
- **Options**: OpenAI-compatible only · plus the native Anthropic SDK · plus others.
- **Lean**: OpenAI-compatible, synchronous (threads suffice, D31), behind the `LLM` interface.
- **Decision**:

### D29. Generation settings [later]
- **v1**: `max_tokens` only.
- **OE**: temperature, top_p, max_tokens, seed, reasoning_effort; omits temperature when unset
  because some models reject it.
- **Options**: which to expose, and whether unset means "not sent".
- **Lean**: `max_tokens`, plus optional temperature and reasoning effort, not sent when unset.
- **Decision**:

### D30. Retries, timeouts, LLM failures [later]
- **v1**: the `openai` package's 2 retries, 300 s; 3 failed iterations in a row stop the run.
- **OE**: its own 3 retries on top of the package's, 60 s; never stops for failures.
- **Lean**: keep v1's behaviour.
- **Decision**:

---

## 7. The loop

### D31. Iterations in parallel [now]
- **v1**: threads; parent chosen in the main thread when an iteration starts.
- **OE**: processes, a snapshot of the whole population pickled per iteration.
- **Options**: threads · processes · asyncio · two pools (many LLM calls, fewer containers).
- **Lean**: threads, one pool, as in v1: the work is waiting on the LLM and on containers.
- **Decision**:

### D32. When a run stops [later]
- **v1**: iteration count, Ctrl+C, 3 LLM failures in a row.
- **OE**: plus target score and early stopping (patience).
- **Options**, any combination: iterations · target score · no improvement for N iterations ·
  wall-clock time · token budget (section 14).
- **Lean**: iterations, target score, patience.
- **Decision**:

### D33. Errors inside an iteration [later]
- **v1**: only `LLMError` is handled; any other exception ends the run (Part D, item 7).
- **OE**: every error is recorded and the run continues.
- **Options**: crash · record and continue · record, and stop after N infrastructure errors in a row.
- **Lean**: record and continue; N errors of any kind in a row stop the run.
- **Decision**:

### D34. Randomness [later]
- **v1**: own `random.Random`, no default seed; re-seeded identically on resume (Part D, item 9).
- **OE**: global `random` and `numpy`, default seed 42.
- **Options**: default seed or none · on resume, restore the generator's state or derive a new seed
  from the seed and the number of programs.
- **Lean**: own generator, no default seed; derive the seed on resume.
- **Decision**:

---

## 8. Running programs safely

### D35. Isolation [now]
- **v1**: a new Docker container per evaluation (about 1 s each); no way to run without Docker.
- **OE**: none of its own.
- **Options**: container per evaluation · one long-lived container per worker, a fresh process per
  evaluation inside it · local subprocess with OS limits (no Docker) · a backend interface with
  several of these.
- **Lean**: a backend interface; Docker per evaluation as the default; a local subprocess backend
  marked unsafe, for tests and trusted problems.
- **Decision**:

### D36. Limits [later]
- **v1**: no network, read-only, 1 GB, 1 CPU, 64 processes, 30 s, fixed in the code except the timeout.
- **Options**: which are settings, and whether per problem or per run.
- **Lean**: the same values, as problem settings.
- **Decision**:

### D37. Containers that outlive the run [later]
- **v1**: possible (Part D, item 2).
- **Options**: label containers with the run's id and remove them on exit and on the next start ·
  a time limit inside the container too · both.
- **Lean**: both.
- **Decision**:

---

## 9. Configuration and interface

### D38. How a run is configured [now]
- **v1**: CLI flags only.
- **OE**: a YAML file plus CLI overrides; unknown keys silently ignored.
- **Options**: CLI only · config file only · config file plus CLI overrides · a problem file for
  the problem's own facts (description, timeout, limits, packages, features) plus CLI flags for
  the run's choices (model, iterations, workers, output, seed).
- **Lean**: the last one: a problem folder is complete on its own, and a run is one command line.
- **Decision**:

### D39. Config file format and validation [later, if D38 uses a file]
- **Options**: YAML (needs `pyyaml`) · TOML (`tomllib`, built into Python 3.11+) · JSON.
  Unknown keys: ignored · error.
- **Lean**: TOML; unknown keys are an error; loaded into dataclasses by hand.
- **Decision**:

### D40. Command line [later]
- **v1**: `python scripts/run.py INITIAL_PROGRAM EVALUATION_FILE --model ...`.
- **OE**: `openevolve-run INITIAL_PROGRAM EVALUATOR --config ...`.
- **Options**: two file paths · a problem folder · a script · a console command (`my-evolve run
  examples/circle_packing`) · `python -m my_evolve`.
- **Lean**: a problem folder; a console command and `python -m`.
- **Decision**:

### D41. API key [later]
- **v1**: read from the variable named by `--api-key-env`.
- **OE**: in the YAML, through `${VAR}`, or `OPENAI_API_KEY`.
- **Lean**: keep v1's way; never in a file.
- **Decision**:

---

## 10. Saving and continuing runs

### D42. Storage format [now]
- **v1**: append-only `programs.jsonl`.
- **OE**: a JSON file per program, full snapshot every N iterations.
- **Options**: JSONL · per-program files and snapshots · SQLite.
- **Lean**: JSONL: nothing evaluated is ever lost, and it is readable with any tool.
- **Decision**:

### D43. What is saved for each program [later]
- **v1**: id, parent, generation, iteration, score, code.
- **OE**: also metrics, artifacts, prompts and reply, diff summary, island, token usage, timestamp.
- **Options**: which fields · prompts and replies in the same file or a separate one.
- **Lean**: everything above plus status, error and timings; prompts and replies in a separate
  `llm_calls.jsonl` so `programs.jsonl` stays readable. Failures as `score: null` + status, never `-Infinity`.
- **Decision**:

### D44. Continuing a run [now]
- **v1**: same `--output`; the database is rebuilt by re-adding the saved programs.
- **OE**: `--checkpoint DIR`; the database state is reloaded from the snapshot.
- **Options**: replay the saved programs · load a snapshot.
  With islands and grids, replay needs every decision that is not recomputable (island of each
  program, migrations) to be saved too.
- **Lean**: replay, with island and migration events in the log.
- **Decision**:

### D45. Run information and safety checks [later]
- **v1**: nothing; a different problem in the same folder goes unnoticed.
- **Options**: save the settings and a fingerprint of the problem files in `run.json`; on resume,
  refuse (or warn) if the problem changed, allow changing the model and iteration count.
- **Lean**: save them; refuse on a changed problem.
- **Decision**:

### D46. Outputs for people [later]
- **v1**: `best_program.py` with a header.
- **OE**: best program and its info file, logs, web visualizer.
- **Options**: best program · a summary at the end · a score-over-time table or plot · a lineage view.
- **Lean**: best program and end summary now; a small report script later.
- **Decision**:

---

## 11. Logging and console

### D47. Logging [later]
- **v1**: `print()`, one line per iteration.
- **OE**: `logging`, many lines per iteration, a log file per run.
- **Options**: `print` · `logging` with a short console format and a detailed log file in the output folder.
- **Lean**: `logging`: one line per iteration on the console, details in the file.
- **Decision**:

---

## 12. Stopping

### D48. First Ctrl+C [later]
- **v1**: nothing new starts; iterations in progress finish and are saved.
- **OE**: iterations in progress are abandoned; nothing since the last checkpoint is saved.
- **Lean**: keep v1's behaviour.
- **Decision**:

### D49. Second Ctrl+C and SIGTERM [later]
- **v1**: the second Ctrl+C still waits for running threads (Part D, item 1); SIGTERM not handled.
- **OE**: `sys.exit(0)`; SIGTERM handled like the first Ctrl+C.
- **Options**: what each one does · how running containers and threads are stopped.
- **Lean**: both exit within seconds: running containers are killed, threads not waited for,
  everything already finished is already on disk.
- **Decision**:

### D50. Platforms [now]
- **v1**: Windows first (PowerShell docs, UTF-8 output, Ctrl+C wake-up), Linux and macOS too.
- **Options**: Linux only · Linux and macOS · all three, with Windows docs.
- **Lean**: depends on where you will run it; this machine is Linux. Keeping the code portable costs little;
  Windows-specific docs and tests cost more.
- **Decision**:

---

## 13. The project itself

### D51. Name, layout, Python version [now]
- **v1**: `src/my_alphaevolve/`, Python 3.10+.
- **Options**: `src/my_evolve/` · Python 3.10, 3.11 (for `tomllib`) or 3.12.
- **Lean**: `src/my_evolve/`, Python 3.11+.
- **Decision**:

### D52. Tools [later]
- **v1**: ruff (lint and format), mypy strict, `unittest`, a fake LLM HTTP server, Docker tests
  skipped without Docker.
- **OE**: black, isort, `unittest` and `pytest`, integration tests against a small local model.
- **Options**: keep v1's tools · `pytest` instead of `unittest` (shorter tests, fixtures).
- **Lean**: keep ruff and mypy strict; your choice between `unittest` and `pytest`.
- **Decision**:

### D53. Code style [later]
- **v1**: explanatory plain-English docstrings and comments everywhere.
- **Lean**: keep it; it serves the goal of understanding the code.
- **Decision**:

### D54. How we work through the plan [now]
- **Options**: step size (one class or one behaviour per step) · who writes the code (I write and
  explain, or you write and I review) · tests in every step · one commit per step · a run of an
  example at the end of each milestone.
- **Lean**: small steps, each runnable and tested, one commit each; I explain the design of a
  step before writing it.
- **Decision**:

---

## 14. Smaller features: yes or no

Each one is a self-contained step that can be added late. [later] for all.

| Feature | v1 | OE | Lean |
|---|---|---|---|
| Target score stop (D32) | no | yes | yes |
| Early stopping on no improvement (D32) | no | yes | yes |
| Token usage recorded and summed | no | yes | yes |
| Token budget stop | no | no | maybe |
| Code-length limit (D13) | no | yes | yes |
| Arguments passed to the evaluator from the config | no | yes | no |
| LLM-as-judge scores | no | yes | no |
| Embedding-based novelty filter (D21) | no | yes | no |
| Random wording variations in prompts | no | yes | no |
| Per-island system messages | no | yes | no |
| "Changes description" mode for large codebases | no | yes | no |
| Several LLM providers besides OpenAI-compatible | no | yes | no |
| Human-in-the-loop "manual mode" | no | yes | no |
| Library API usable from a notebook | partly | yes | yes, a single `run(...)` |
| Evolution trace for RL training | no | yes | no (D43 covers analysis) |
| Web visualizer | no | yes | later, maybe |
