# Design decisions for my-evolve

my-evolve is a from-scratch rewrite of **my-alphaevolve** ("v1"), an AlphaEvolve re-implementation, taking
selected ideas from **openevolve** ("OE") and **ShinkaEvolve** ("SE"). The three reference repositories are
`my-alphaevolve/`, `openevolve/` and `ShinkaEvolve/`; how they differ is described in
[differences.md](differences.md), whose section names (A1 to B6) and Part D items are cited here.

Each entry states what my-evolve does (**Decision**), sometimes followed by where the idea comes from in the
references. Numbers (D1 to D79) are stable identifiers, not an order: D71 and D72 to D79 were added later.
Sections 1 to 13 and 15 say *what* the system does; section 14 says *how*, class by class.

## Terms

| Term | Meaning |
|---|---|
| problem | a task to solve, defined by an initial program, an evaluation file and a problem file |
| initial program | the program evolution starts from; openevolve's, unchanged (D3) |
| evaluation file | Python code, run on the host, that scores programs through stage functions (D9, D76) |
| problem file | a YAML file holding the problem's description and every setting of the problem and its runs (D43, D72) |
| run | one evolution of one problem, saved in a run folder; it may span several sessions (resumes, D49) |
| iteration | one attempt to produce a child: choose a parent, ask the LLM, check and evaluate the child |
| completed iterations | iterations finished so far, whatever their outcome; counts like "every 25 iterations" refer to them |
| child | the program an LLM writes in an iteration; it may be rejected before evaluation (D13) |
| status | how a program's evaluation ended: `ok`, `rejected`, `failed`, `timeout`, `invalid` or `error` (D7) |
| stage | one step of the evaluation cascade; later stages run only for programs good enough at earlier ones (D9) |
| island | a sub-population with its own MAP-Elites grid (D16, D23) |
| elite | the best program of one grid cell; an island's population is its elites (D23) |
| example programs | other programs shown in the prompt as previous attempts, working or failed (D26) |
| evolve blocks | the regions between `# EVOLVE-BLOCK-START` and `# EVOLVE-BLOCK-END`, the only code the LLM may change (D12) |
| sandbox | the Docker container a program runs in, isolated from the host (D8, D40) |

---

## 1. Scope

### D1. How far to go
**Decision.** Build a small core that works end to end first; add selected openevolve and ShinkaEvolve
components afterwards, each as its own step.

### D2. Languages of the evolved programs
**Decision.** Python only.

### D3. Comparability with openevolve
**Decision.** Runs must be comparable to openevolve's on function minimization and circle packing, the two
test problems (circle packing is the main experiment).
- The initial programs are openevolve's (`examples/function_minimization/initial_program.py`,
  `examples/circle_packing/initial_program.py`), unchanged, EVOLVE-BLOCK markers included.
- The evaluation files are ports of openevolve's evaluators (`evaluator.py` in the same folders, at commit
  `da3d701`): they receive a namespace (D5) but give every working program exactly the score openevolve
  gives it, with the same cascades (D9). As in that commit, function minimization recomputes the function's
  value from the returned (x, y) instead of trusting the program (Part D, v1 item 4).
- Comparable means best-score curves can be compared. Average scores and failure counts cannot: openevolve
  scores failing and invalid programs 0 and keeps them in its grid; here they have no score and stay out (D7).

---

## 2. The problem and its evaluation

### D4. Where the problem description lives
**Decision.** In the `description` field of the problem file, as openevolve keeps it in its config. It
states the task and the contract the program must keep: its entry functions (e.g. `run_packing()`), their
arguments and their return values.

### D5. What the evaluator receives
**Decision.** Each stage function of the evaluation file is called as `evaluate(namespace)`: `namespace`
gives access to the names the program defines (its functions, and plain-data constants), not a file path.
The namespace is a stand-in: calling one of its functions runs that function in the sandbox (D8).
*References:* v1's `evaluate(namespace)`; openevolve's `evaluate(program_path)`.

### D6. What the evaluator returns
**Decision.** A `Result` object (D73) with: `status` and `error` (D7); `score`, a number, only for `ok`
programs; `metrics`, named numbers about the run; `features`, named numbers describing the program's output,
used only for the MAP-Elites grid (D17); `feedback`, text for the LLM (D10); `output_data`, plain data kept
for the report's drawings (D51); the cascade stage reached (D9); the duration. A program is "correct" when its
status is `ok`; there is no separate correctness flag. A stage function itself returns a `StageResult` or
raises `InvalidProgram` (D76); the framework builds the `Result`.

### D7. Failed programs
**Decision.** Every program has a status. `ok`: evaluated, and its answer is legal; only `ok` programs have a
score. The other five, by when the program stopped and whose fault it was:
- `rejected`: refused before evaluation by a check of D13 (no code or a syntax error, a change outside the
  evolve blocks or to their markers, a missing entry function, or a duplicate of an earlier program); never run.
- `failed`: raised an exception while loading or while one of its functions ran, or its process died
  (`ImportError`, `IndexError`, a wrong return type, an entry function missing at run time, too much memory).
- `timeout`: a cascade stage ran out of time (60 s per stage for both problems, D41), or a call ran over its
  own limit and the evaluator did not handle it (D8). When the evaluator handles a slow call, the outcome is
  up to it: function minimization's stage 2 skips a trial over 5 s and scores the others (`ok`); its stage 1
  reports `timeout`, since its only call gave no answer.
- `invalid`: returned an answer the evaluator judged illegal (overlapping circles, a negative radius, a circle
  outside the square), with the reason. openevolve scores such programs 0.
- `error`: not the program's fault: the infrastructure failed (Docker, the evaluation file itself raised, a
  full disk). Such programs do not count as their parent's children (D19), are never shown as example
  programs (D26), and count toward the "errors in a row" stop (D38).

A program that passes stage 1 and fails or times out in a later stage keeps its earlier result: status `ok`,
with the later stage's error recorded (D9). A failed program has no score (`null` in JSON, never
`-Infinity`) and an error message. Failed programs are stored and saved, shown as example programs (D26),
counted as children (D19), used for duplicate detection (D13), and never chosen as parents.

### D8. Where the program and the evaluator run
**Decision.** The program runs in a sandboxed Docker container (D40, D41); the evaluation file runs on the host,
in the trusted process, and reaches the program only through the namespace (D5). A call of a namespace
function runs that function in the container and returns its result as plain data (JSON values, or numpy
arrays of numbers, never pickle). So the program chooses what its functions return, but cannot touch how the
score is computed (in v1 it could, Part D, v1 item 3).
- An evaluator may give a call its own time limit (function minimization gives `run_search` 5 s): a call over
  it raises a timeout error in the evaluator, the container is killed, and the next call starts a fresh
  container with the program loaded again.
- Each cascade stage starts with a freshly loaded program in a new container, as openevolve re-imports the
  program for each stage, and has its own time limit (D41).

### D9. Cascade evaluation
**Decision.** openevolve's cascade. The evaluation file defines `evaluate_stage1(namespace)`,
`evaluate_stage2(namespace)`, … in order (a file defining only `evaluate(namespace)` has one stage), and the
problem file lists one threshold per stage after the first. Stage k+1 runs only if stage k's score reaches
the k-th threshold.
- A later stage's score replaces the earlier one; its metrics are added to the earlier ones, replacing those
  with the same name; its output data, if any, replaces the earlier one.
- Features come from stage 1 only, so every program's features are measured the same way (D17).
- A later stage that fails or times out keeps the earlier result (status `ok`, D7). A stage that judges the
  answer illegal makes the whole program `invalid`, at any stage (openevolve gives it a score of 0, which
  overwrites the earlier stages' score).
- The two problems' cascades, ported from openevolve (60 s per stage):
  - function minimization: stage 1 calls `run_search` once (5 s limit); threshold 1.3; stage 2 calls it 10
    times (5 s each) and scores reliability too.
  - circle packing: stage 1 calls `run_packing` once and scores the sum of the radii divided by 2.635 if the
    packing is valid; threshold 0.5; stage 2 is openevolve's full evaluation, a second call scored the same
    way. openevolve's second threshold, 0.75, has no stage to gate and is not used.

### D10. Feedback to the LLM
**Decision.** Evaluators write feedback text as they check a program, like openevolve's artifacts ("Circles 3
and 7 overlap (distance 0.112, radii sum 0.130)", "run_search timed out on trial 4 of 10"); both problems'
evaluators do so for every check. When a program crashes or times out, the framework records the error and
the end of its error output. The prompt shows the feedback of the parent and of every example program, and
the error of every failed example program and of a parent's failed later stage, each cut to a size limit
(D30). No LLM writes feedback.

---

## 3. How the LLM changes a program

### D11. Format of a change
**Decision.** Full rewrite: the LLM returns the whole file. Inside the evolve blocks it changes as much or as
little as it wants (D12). No SEARCH/REPLACE diffs.

### D12. Which code may change
**Decision.** Only the code inside the evolve blocks (`# EVOLVE-BLOCK-START` … `# EVOLVE-BLOCK-END`), which the
initial programs keep (D3). The prompt says so, and that the markers must stay as they are (Appendix A). A
child that changes code outside the blocks, or moves, removes, adds or alters a marker, is rejected before
evaluation (D13), so the mistake is recorded and can be shown to the LLM (D26); openevolve's
`enforce_evolve_blocks` reverts such edits silently instead.

### D13. Checks before a child is evaluated
**Decision.** Four checks, on the host, without running the program, in this order. They apply to children
the LLM writes, never to copies the framework makes (the initial program's copies, migrants, D23). A child
that fails one is stored with status `rejected` and the reason, and is not evaluated.
1. It compiles (`ast.parse`); a reply without code fails here.
2. It keeps the evolve blocks exactly where the initial program has them: the same markers in the same order,
   and the same code outside them, compared line by line ignoring blank lines and spaces at the ends of lines
   (spaces at the start of lines count, since indentation has meaning in Python).
3. It defines, at the top level, every entry function the problem file lists (`run_packing`, `run_search`).
4. It is not a duplicate of any program already in the database: no earlier program has the same syntax tree
   (comments and spacing do not count). Each program's tree is stored as a hash (its fingerprint), so the check
   is instant. Earlier programs count if they have a tree and a status of `ok`, `failed`, `timeout` or
   `invalid`; `rejected` and `error` programs do not.

Whether a program runs is checked by the evaluation itself: loading it is the container's first step (D8).

### D14. Repairing a rejected change
**Decision.** None: a rejected child ends its iteration. No second request in the same conversation.
*Reference:* ShinkaEvolve asks again with the error (`max_patch_attempts`).

### D15. Description of a program
**Decision.** The LLM's reply contains, besides the code, a description of how the program solves the task
(its approach and main ideas), between `<DESCRIPTION>` and `</DESCRIPTION>`. It must stand on its own: it never
refers to the parent or any other program ("compared to the previous version", "now uses"), because when the
program is later shown in a prompt, its parent is usually absent. The reply may contain anything else
(reasoning, comments); only the description and the code are kept (D68). A reply without a description is
accepted if its code is usable. The description is shown in prompts (D26) and saved (D48).

---

## 4. The database and the choice of parents

### D16. Population structure
**Decision.** Islands, each with its own MAP-Elites grid, as in openevolve, plus an archive of the best
programs (D21). Every program is kept (D22). CVT MAP-Elites may replace the fixed grids later.

### D17. MAP-Elites features
**Decision.** A grid has one built-in "code" feature and zero or more "output" features.
- `code_complexity`, built in: the number of syntax-tree nodes (`ast.parse`, then `ast.walk`) inside the
  evolve blocks, found from each node's line numbers; normalized as in D18. It may later include other
  measures, such as cyclomatic complexity.
- Output features, specific to a problem: computed by its evaluator from what the program returns, at stage 1
  (D9), and put in the result's `features`; only `ok` programs have them, and only `ok` programs enter a grid.
- The problem file names the features a run uses. The default grid is one-dimensional, on `code_complexity`.
- Circle packing defines two output features, so a run can use either (2D) or both (3D):
  - `radii_spread`: std(radii) / mean(radii); 0 means all circles have the same size; 0 when the mean is 0.
  - `radius_centre_correlation`: the Pearson correlation (`numpy.corrcoef`) between each circle's radius and the
    distance from its centre to (0.5, 0.5); −1 means big circles in the middle, +1 big circles at the edges;
    0 when the radii or the distances are all equal (the correlation is then undefined).
- Function minimization: a one-dimensional grid for now; output features may come later.

### D18. Binning features into cells
**Decision.** A fixed grid, known when the run starts and never changed. The problem file gives each feature
a range (`low`, `high`) and a number of bins; a value outside the range goes to the nearest end bin.
- `code_complexity` is normalized against the initial program: log2(nodes inside the blocks ÷ nodes inside
  the initial program's blocks); default range 0 to 2.5 (the initial size to about 5.7 times it; 10 bins of
  about 19% each). It was −1 to +3, but children only grew in the first plan's milestones (a log2 ratio of
  0 to 1.31 for circle packing, 0.34 to 2.2 for function minimization), so the bins below 0 stayed empty
  and each island used 2 or 3 of its 10 cells. A smaller child goes to the first bin.
- Circle packing ranges: `radii_spread` 0 to 1, `radius_centre_correlation` −1 to +1.
- Default bins per feature: 10 for a 1D grid, 5 for 2D, 3 for 3D, so grids stay small for runs of hundreds
  of iterations.

### D19. Choosing a parent
**Decision.** Two strategies, chosen in the problem file; failed programs are never candidates.
- **Weighted (default)**, ShinkaEvolve's rule adapted to grids: draw an island uniformly (D23), then one of its
  elites with probability proportional to sigmoid(λ × (score − median) / spread) × 1 / (1 + children).
  - The median and the spread are those of the island's elites' scores. The spread is their median absolute
    deviation, or their standard deviation if that is 0; if both are 0, every elite's sigmoid term is 0.5.
  - λ is set in the problem file, default 1 (ShinkaEvolve's 10 makes almost every draw go to the elites above
    the median, defeating the grid's diversity).
  - "Children" counts every child the program has had, whatever its status (each cost an LLM call), except
    `error` ones. A copied migrant starts at 0 on its new island; a moved one keeps its count (D23).
- **openevolve's rule**, adapted to grids: 20% of the time a uniform draw among the island's elites, 70% a
  uniform draw among the archive's programs made on this island (or the whole archive if none, D21), 10% a
  draw among the island's elites in proportion to their scores (each at least 0.001).

The child lives on the iteration's island. With the weighted rule that is its parent's island; openevolve's
rule can draw an archive program from another island, as openevolve itself does.

### D20. When no program works
**Decision.** Impossible by construction: the initial program must evaluate as `ok`, or the run refuses to
start (as in v1). No "fix mode" (ShinkaEvolve's repair of broken programs).

### D21. The archive
**Decision.** The k best `ok` programs of the whole run (default 10, set in the problem file), computed when
needed, never stored, counting copies of one program once (by fingerprint). Used only by openevolve's rule (D19).

### D22. Forgetting programs
**Decision.** Never: every program, failed ones included, stays in memory and on disk.

### D23. Islands
**Decision.** An island's population is its grid's elites; every program also records the island it was made
on, so programs that lost their cell still count for example programs (D26). Defaults, all settable in the
problem file:
- 3 islands. The initial program itself belongs to no island: each island starts with a copy of it.
- Each iteration's island is drawn uniformly; its child lives on that island (D19).
- Every 25 completed iterations, a migration: on each island, 10% of its elites (at least one), drawn at
  random among its elites except its best, are copied to every other island. A copy takes its cell only if
  the cell is empty or holds a lower-scoring elite. Copies are not evaluated again and are not iterations.
- No new islands during a run.

Settable: the number of islands; the interval; the share that migrates; which programs (`best`, `random`,
`random_non_best`); where they go (`all_others`, or `ring`: the next island); copy or move (a moved program
leaves its grid and goes to the first destination only).

### D24. Duplicates and near-duplicates
**Decision.** Only exact duplicates of syntax trees are rejected (D13). No embeddings, no LLM judge.

---

## 5. The prompt

### D25. Message structure
**Decision.** One call per iteration, with a system message and a user message (Appendix A). The system message
holds what stays the same for a whole run: the instruction, the problem description, the rules (evolve blocks,
allowed packages, higher scores are better) and the reply format; providers can cache it. The user message
holds what changes: the example programs, then the parent, then the request.

### D26. Example programs
**Decision.** Besides the parent, the prompt shows example programs ("inspirations" in openevolve and
ShinkaEvolve), 2 by default (set in the problem file).
- They are drawn at random among every program made on the iteration's island (not only its elites: also its
  failed programs and the working ones that lost their cell), except the parent, `error` programs, and
  children without code. They are shown in the order drawn.
- They are not labelled good or bad: the prompt calls them previous attempts, and shows for each its score
  (or its status if it failed), description, feedback and, if it failed, its error (D10, D27).

### D27. Scores in the prompt
**Decision.** The prompt says higher scores are better, and shows the score of the parent and of every working
example program, the status of every failed one, and the best score reached so far in the run. It shows no
metrics, no hints such as "fitness improved", and no limits of the sandbox.

### D28. Advice drawn from the whole run
**Decision.** None. *Reference:* ShinkaEvolve's meta recommendations.

### D29. Where templates live
**Decision.** Python constants in `prompt.py`, filled with `str.format`; their text is Appendix A. No random
wording variations.

### D30. Prompt size
**Decision.** A character budget for the whole prompt (default 60,000, in the problem file): over it, example
programs are dropped, last first, with a warning in the log. Feedback and errors are each cut to 2,000
characters (also in the problem file).

A model may give its `context_length`, the tokens its server holds. A server such as Ollama silently cuts
a prompt that does not fit, the system message first, so the budget plus the model's `max_tokens` must fit
in it: counted at 3.5 characters per token (the fewest seen in the first plan's milestones, 3.55 to 4.49),
a problem file that does not is refused. A prompt whose reported tokens, plus `max_tokens`, still exceed the
context is reported in the log. Batch 1's problem files set 32,768 and a budget of 40,000 characters.

---

## 6. The LLM

### D31. Models
**Decision.** A weighted ensemble, as in openevolve: the problem file lists the models and their weights, and
each iteration draws one model with the run's random generator (D39). Models are drawn in the main thread.

### D32. Client and providers
**Decision.** Every model is reached through an OpenAI-compatible endpoint with the synchronous `openai` client
(threads suffice, D36); each model has its own address, so providers can be mixed (Appendix B). OpenAI's
reasoning models are supported: they refuse `max_tokens` and `temperature` and need `max_completion_tokens`.
A model's `reasoning` setting says whether it is one; unset, it is guessed from the name (prefixes `o1`, `o3`,
`o4`, `gpt-5`, `gpt-oss`, as in openevolve). For a reasoning model the token limit is sent as
`max_completion_tokens`; a temperature configured for one is an error when the problem file is loaded.

### D33. Generation settings
**Decision.** `max_tokens` (default 16,384, enough for a reasoning model's hidden thinking plus the reply), an
optional `temperature`, and an optional `reasoning_effort` (reasoning models only). Settings left unset are not
sent. Each can be set for all models or per model, as in openevolve's `llm` section.

### D34. Retries, timeouts and LLM failures
**Decision.**
- One layer of retries: the `openai` package's own (2 by default); a timeout per model (default 300 s).
- Before the first iteration, each model gets a one-line test request with its own settings; any failure
  stops the run.
- During the run, failures are counted per model: 3 failures in a row (settable) drop that model for the rest
  of the run, with a warning, and the others' weights are rescaled; the run stops when no model is left.
- An iteration whose LLM call failed is skipped, but counts as completed (D37, D49) and is logged.

### D35. Cost accounting
**Decision.** Every call's input and output tokens are saved with the program (D60). Optional prices per model
(per million tokens) are used only to report costs. No budget: the iteration count and `max_tokens` bound the
cost.

---

## 7. The loop

### D36. Iterations in parallel
**Decision.** Threads, as in v1: at most `--workers` iterations at once (default 1). Each iteration alternates
between the main thread and a worker thread:
1. main: draw the island, the parent, the example programs and the model; build the prompt;
2. worker: ask the LLM, parse the reply;
3. main: run the checks of D13, so the duplicate check sees every stored program even with several workers;
4. worker: evaluate the child;
5. main: store the child, update the grid, migrate when due.

Only the main thread uses the database and the run folder.

### D37. When a run stops
**Decision.** When the number of completed iterations reaches `--iterations` (failed and skipped iterations
included); when the best score reaches `--target-score`, if given; after `--patience` completed iterations
without a better best score, if given; when no model is left (D34); after too many infrastructure errors in a
row (D38); on Ctrl+C (D53). The reason is logged and saved.

### D38. Errors inside an iteration
**Decision.** Record and continue. An unexpected exception that is not the program's fault (in the sandbox, the
evaluation file or the checks) gives the child status `error`, or, before any child exists, records the
iteration as an error. 3 such errors in a row (settable in the problem file) stop the run; this counter is
separate from the LLM's (D34). An exception in the main thread itself (e.g. the disk refusing a write) stops the
run at once.

### D39. Randomness
**Decision.** One `random.Random` per run makes every draw: island, parent, example programs, migrants, model.
`--seed` sets it; without it a seed is drawn at random; either way it is saved (D50). On resume, the generator
is seeded from the run's seed and the number of programs already stored, so draws continue instead of repeating
(Part D, v1 item 9). A run repeats exactly only with one worker and deterministic LLMs. Randomness inside
programs (function minimization's search) is their own.

---

## 8. Running programs safely

### D40. Isolation
**Decision.** Two sandboxes behind one interface (D64), sharing the same worker and protocol (D77):
- Docker, the default: a fresh container for each cascade stage of each program (about 1 s each), and after a
  call that ran over its time limit.
- A local subprocess without any isolation, for the tests and trusted code, only with `--unsafe-local-sandbox`,
  announced with a warning at start-up.

### D41. Limits
**Decision.** v1's container limits, settable in the problem file: no network; a read-only file system except
a temporary `/tmp`; 1 GB of memory and no swap; 1 CPU; 64 processes; no capabilities; user `nobody`. The
thread counts of numeric libraries (`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, …) are set to the CPU count. Each
cascade stage has a time limit (60 s for both problems, as in openevolve), and evaluators may limit single calls
(D8). The evaluation file, on the host, has no limits: it is trusted code.

### D42. Containers that outlive a run
**Decision.** Every container is started with `--rm` and labelled with the run's id; the run removes its
containers when a stage ends, when the run stops, on Ctrl+C, and, at start-up, those left by an earlier session.
Inside the container, the worker runs under its own time limit, 10 s longer than the stage's, so a container
stops even if the host process dies.

### D71. Packages programs may import
**Decision.** The problem file lists them with exact versions (`numpy==2.5.4`); Python's standard library is
always available. They are installed in the evaluation image when it is built, the only moment with network
access; containers have no network, so nothing is ever installed because the LLM asks. The image is built on
first use from `evaluation.Dockerfile` and the list, and tagged with a hash of both, so it is rebuilt when
either changes. Only `name==version` entries are allowed, no pip options. Every prompt names the allowed
packages; importing another fails (`failed`). For comparability (D3): numpy and scipy for function
minimization; numpy, scipy and matplotlib for circle packing, at v1's versions. Packages the evaluation file
imports (numpy for both) must also be installed on the host, since it runs there (D8).

---

## 9. Configuration and interface

### D43. How a run is configured
**Decision.** A YAML problem file for everything about the problem and its runs (layout in D72): description,
entry functions, packages, cascade and time limits, sandbox limits, grid features, islands, parent selection,
prompt settings, snapshot interval, error limit, and the `llm` section (models, weights, addresses, key
variables, prices, generation settings), laid out like openevolve's `llm` section. Command-line flags only for
choices about one run (D45).

### D44. Problem file format
**Decision.** YAML, read as plain data, loaded into dataclasses (D72). Every value is checked; an unknown key
is an error (openevolve silently ignores them).

### D45. Command line
**Decision.** `python scripts/run.py INITIAL_PROGRAM EVALUATION_FILE --config PROBLEM_FILE [flags]`, as in v1.
Flags: `--config` (required); `--iterations` (total completed iterations, default 100, D49); `--output` (the run
folder, default `runs/<problem name>_<date>_<time>`; an existing run folder is continued, D49); `--workers`
(default 1); `--seed`; `--target-score`; `--patience`; `--unsafe-local-sandbox`; `--verbose`. Every value is
checked, with a clear message.

### D46. API keys
**Decision.** A model names the environment variable holding its key with openevolve's syntax,
`api_key: ${ANTHROPIC_API_KEY}`; a key written in the file is refused, so problem files can be shared. A model
on a local server needs no key.

---

## 10. Saving and continuing runs

### D47. The run folder
**Decision.** v1's append-only files, extended. Each line is written as soon as its program or iteration is
done, so nothing finished is lost; on resume, a last line cut off by a crash is dropped, as in v1.
- `programs.jsonl`: one line per program (D48): the initial program, its island copies, every child (any
  status), every migrant.
- `llm_calls.jsonl`: one line per LLM call: the user message, the full reply, the model, tokens, duration,
  error; linked to its program, or marked skipped (the system message is saved once per session in `run.json`).
- `history.csv`: one line per completed iteration: iteration, completed count, child id, status (or `skipped`,
  or `error` when no child exists), score, best score so far, best program's id, model. The data for the
  progress plot.
- `best_program.py`: the best program so far, rewritten when it changes, with a comment header (score,
  iteration, id, description).
- `best/iteration_0000.py` (the initial program), then one file every k completed iterations (k =
  `snapshot_every`, default 10): the best program at that point, with the same header.
- `run.json`, `problem.yaml` (D50), `log.txt` (D52).

### D48. What is saved for each program
**Decision.** Each line of `programs.jsonl` is a `Program` (D60) as JSON, with its `Result` (D73) nested, its
`output_data` included (for the report, D51). Prompts and replies are in `llm_calls.jsonl`, not here.

### D49. Continuing a run
**Decision.** Run the same command with the same `--output` folder. The database is rebuilt by adding the saved
programs again, in order (migrations are saved as their copies, so they replay too). `--iterations` is a total:
the iterations already completed are the rows of `history.csv`, so rerunning the same command after a crash
finishes the run, and a larger value extends it. Iterations in progress at the crash are lost and done again.
The initial program is not evaluated again. The random generator is reseeded as D39 says.

### D50. Run information and safety checks
**Decision.** `run.json` holds the run's id, its seed, fingerprints (hashes) of the initial program, the
evaluation file, the problem file without its `llm` section, and the image, and one record per session (times,
git commit, command line, `llm` section, flags, system message, how it ended). `problem.yaml` is a copy of the
problem file. On resume, any changed fingerprint stops the run with a message saying what changed; the `llm`
section and the flags may change between sessions.

### D51. Outputs for people
**Decision.**
- During the run: one console line per iteration with the best score so far (D52); `best_program.py` and the
  snapshots in `best/`.
- At the end: a summary on the console and in `log.txt`: iterations completed, why the run stopped, the best
  score and its iteration, counts by status, tokens and cost per model.
- After the run, `python scripts/report.py RUN_FOLDER` replays the run and draws, with matplotlib, into
  `RUN_FOLDER/report/`:
  - progress: the best score so far against completed iterations, with every `ok` child's score as a dot;
  - grids: at every snapshot and at the end, each island's grid side by side; an empty cell is white, an
    occupied one blue, from light (lowest score of the run) to deep (highest), on one scale for all images;
    also as an animated GIF; a 3D grid is drawn as one square per bin of its third feature;
  - outputs: if the evaluation file defines `visualize(output_data, path)`, the best program's output at every
    snapshot. Circle packing's draws the circles in the unit square, as openevolve's `visualize` does; function
    minimization defines none.

---

## 11. Logging

### D52. Logging
**Decision.** The `logging` module. The console shows one line per iteration (iteration, island, model, the
child's status and score, the best score so far) and the start and end of the run; `--verbose` adds details
(parents drawn, checks, migrations, timings). `log.txt` in the run folder gets everything, with timestamps.
Secrets are never logged.

---

## 12. Stopping

### D53. First Ctrl+C
**Decision.** As in v1: nothing new starts; iterations in progress finish and are saved; the run ends with its
summary. The console says so, and that a second Ctrl+C stops at once. The main thread waits in short steps, so
Ctrl+C reaches it on Windows too.

### D54. Second Ctrl+C, and SIGTERM
**Decision.** Either stops the run within seconds: running containers are killed, worker threads are not
waited for (v1 waited for them, Part D, v1 item 1), and the session is recorded as interrupted. Iterations in
progress are lost and redone on resume; everything finished is already saved. SIGTERM exists on Linux only.

### D55. Platforms
**Decision.** Linux and Windows: the code avoids anything specific to one system.

---

## 13. The project

### D56. Name, layout, Python version
**Decision.** The package is `src/my_evolve/`; Python 3.11 or later.

### D57. Tools
**Decision.** As in v1: ruff (lint and format), mypy in strict mode, `unittest`, a fake OpenAI-compatible
HTTP server for tests, and Docker tests skipped when Docker is missing.

### D58. Code style
**Decision.** As in v1: plain-English docstrings and comments throughout, since understanding the code is a goal
of the project.

### D59. How the plan is carried out
**Decision.** Small steps, each runnable and tested, one commit each; each step's design is explained before
it is written.

---

## 14. Classes and modules

How the decisions above become code: every module, class, attribute and method, and the algorithm of
every function as numbered steps in plain language. Records (`Problem`, `Result`, `Program`, ...) are
plain dataclasses; state derived from them lives in `Database`, never on the records.

The entries are numbered D60 to D70 and D72 to D79, in the order of the modules, not of their numbers.

### 14.1 Module map

| Module | Contents | Entry |
|---|---|---|
| `problem.py` | `Problem` and its settings, loaded from the problem file | D72 |
| `program.py` | `Status`, `Result`, `LLMUsage`, `Program` | D73, D60 |
| `checks.py` | Evolve blocks, fingerprints, code complexity, the checks before evaluation | D74 |
| `reply_parser.py` | Extracting the description and the code from a reply | D68 |
| `prompt.py` | The templates of Appendix A and `PromptBuilder` | D67 |
| `llm.py` | `LLMReply`, `LLMError`, `NoModelLeft`, `LLM`, `OpenAICompatibleLLM`, `Ensemble` | D66 |
| `grid.py` | `Grid` | D61 |
| `database.py` | `Island`, the parent selectors, `Database` | D62, D75, D63 |
| `evaluation_api.py` | What evaluation files import: `StageResult`, `InvalidProgram`, `ProgramFailure`, `CallTimeout`, `StageTimeout`, `call_with_timeout` | D76 |
| `sandbox_protocol.py` | Plain-data encoding and the messages between host and container | D77 |
| `sandbox_worker.py` | The program run inside the container | D77 |
| `sandbox.py` | `Sandbox`, `SandboxSession`, `ProgramNamespace`, `RemoteFunction`, the Docker and local sandboxes | D64 |
| `evaluator.py` | `Evaluator` | D65 |
| `storage.py` | `Storage`, `RunInfo`, `HistoryRow` | D69 |
| `logs.py` | Logging set-up | D78 |
| `loop.py` | `RunSettings`, `run` and its helpers | D70 |
| `report.py` | The report's drawings | D79 |
| `evaluation.Dockerfile` | The evaluation image | D71 |
| `scripts/run.py`, `scripts/report.py` | The command line and the report | D79 |

`my_evolve/__init__.py` stays empty, so that the container can use `sandbox_worker` and
`sandbox_protocol` without the host's dependencies (`openai`, `yaml`).

### 14.2 One iteration, end to end

| Step | Thread | What happens |
|---|---|---|
| 1 | main | Draw an island, a parent among its elites, example programs from the island, and a model; build the prompt. |
| 2 | worker | Ask the model; extract the description and the code from its reply. |
| 3 | main | Run the four checks; a rejected child is stored and the iteration ends. |
| 4 | worker | Evaluate the child through the cascade, each stage in a fresh sandbox session. |
| 5 | main | Store the child; update the grid, the best program, the history; write a snapshot or migrate when due. |

---

### D72. The `Problem` class and its settings (`problem.py`)
**Decision.** The problem file (D43, D44) loaded into nested dataclasses, every value checked.

**Sections of the problem file**, with their defaults:

| Section | Keys (default) |
|---|---|
| top level | `name` (required), `description` (required; includes the entry functions' contract, D4), `entry_functions` (required, e.g. `[run_packing]`), `packages` (list of `name==version`, empty), `snapshot_every` (10, D47), `max_errors_in_a_row` (3, D38) |
| `evaluation` | `stage_time_limit` (60 s, D41), `thresholds` (list: stage k+1 runs if stage k's score reaches the k-th value, D9) |
| `sandbox` | `memory` (`1g`), `cpus` (1), `max_processes` (64), D41 |
| `grid` | `features`: a list of `name`, `low`, `high`, `bins`; default one feature, `code_complexity` from 0 to 2.5; default bins 10, 5 or 3 for one, two or three features (D17, D18) |
| `islands` | `count` (3), `migration_interval` (25), `migration_share` (0.1), `migrants` (`random_non_best`, or `best`, `random`), `destinations` (`all_others`, or `ring`), `mode` (`copy`, or `move`), D23 |
| `parents` | `strategy` (`weighted`, or `openevolve`), `lambda` (1.0), `archive_size` (10), D19, D21 |
| `prompt` | `example_programs` (2, D26), `max_chars` (60,000, D30), `max_feedback_chars` (2,000, D10) |
| `llm` | values shared by every model (`api_base`, `max_tokens` 16,384, `temperature`, `reasoning_effort`, `timeout` 300 s, `retries` 2, prices, `context_length`, D30), `max_failures_in_a_row` (3), and `models`: a list of `name`, `weight` and any of the shared keys, which override them for that model (D31–D35, D46) |

**Dataclasses**:

| Class | Attributes |
|---|---|
| `FeatureSpec` | `name`, `low`, `high`, `bins`: one grid dimension; `code_complexity` is the built-in feature, any other name is an output feature the evaluator must provide |
| `EvaluationSettings` | `stage_time_limit`, `thresholds` |
| `SandboxSettings` | `memory`, `cpus`, `max_processes` |
| `IslandSettings` | `count`, `migration_interval`, `migration_share`, `migrants`, `destinations`, `mode` |
| `ParentSettings` | `strategy`, `lam` (λ), `archive_size` |
| `PromptSettings` | `example_programs`, `max_chars`, `max_feedback_chars` |
| `ModelSettings` | `name`, `weight`, `api_base`, `api_key_env` (the variable named by `${VAR}`, or none), `temperature`, `max_tokens`, `reasoning_effort`, `reasoning` (yes, no, or guessed from the name), `timeout`, `retries`, `price_input`, `price_output` (per million tokens) |
| `LLMSettings` | `models` (list of `ModelSettings`), `max_failures_in_a_row` |
| `Problem` | `name`, `description`, `entry_functions`, `packages`, `evaluation`, `sandbox`, `grid_features`, `islands`, `parents`, `prompt`, `snapshot_every`, `max_errors_in_a_row`, `llm` |

**Methods**:
- `Problem.load(path)`: reads the file and returns the `Problem`.
- `Problem.from_dict(data)`: builds and checks it from parsed data (used by `load` and by the tests).
- `output_feature_names`: the grid features other than `code_complexity`.
- `fingerprint_without_llm()`: a hash of every setting except the `llm` section, for D50.

**`load(path)`**:
1. Read the file as YAML, plain data only (never Python objects).
2. If it is not a mapping, stop with an error naming the file.
3. Return `from_dict` of it.

**`from_dict(data)`**:
1. Refuse any unknown key, at every level, with its location (D44).
2. Require `name`, `description`, `entry_functions` and `llm`.
3. Check each package is `name==version`; refuse anything starting with `-`, a pip option (D71).
4. Build each section's settings from its keys and the defaults above.
5. For the grid: if no features are given, use `code_complexity` alone; give each feature without `bins`
   the default for the number of features; check names are unique, `low < high`, `bins ≥ 1`.
6. Check the island, parent and prompt settings are in range and their choices are known.
7. Build the LLM settings with `build_llm`.
8. Return the `Problem`.

**`build_llm(section)`**:
1. Take the section's values other than `models` and `max_failures_in_a_row`: they apply to every model.
2. Require at least one model. For each model, merge: the defaults, then the shared values, then the
   model's own values (a model's own value wins, as in openevolve).
3. Turn its `api_key` into the name of an environment variable with `parse_key`.
4. If `reasoning` is not set, guess it from the name (`is_reasoning_model`, D66).
5. If it is a reasoning model with a temperature, stop with an error: these models refuse one (D32).
6. Check weight > 0, max_tokens ≥ 1, timeout > 0, retries ≥ 0.
7. Return the models and the failure limit.

**`parse_key(value)`** (D46):
1. No value: no key (a local server).
2. A value of the form `${NAME}`: the key will be read from the variable `NAME` when the model is built.
3. Anything else: stop with an error saying to write `${VARIABLE}`, never the key itself.

**`fingerprint_without_llm()`**: hash the settings, minus the `llm` section, written in a fixed order.

### D73. The `Result` class and `Status` (`program.py`)
**Decision.** D6 and D7 as classes.

`Status`: an enumeration of `ok`, `rejected`, `failed`, `timeout`, `invalid`, `error` (D7).

`Result` attributes:

| Attribute | For |
|---|---|
| `status` | how the evaluation ended (D7) |
| `score` | the score; none unless `status` is `ok` |
| `metrics` | named numbers about the run, saved and logged, not shown to the LLM (D27) |
| `features` | the output features for the grid (D17), from stage 1 only |
| `feedback` | what the evaluator wants the LLM to know (D10) |
| `error` | why the program failed, or the error of a later stage it did not pass (D9); none otherwise |
| `output_data` | plain data the evaluator keeps for the report's drawings (D48, D51); may be none |
| `stage_reached` | the last cascade stage completed; 0 if none |
| `duration` | wall-clock time of the evaluation, in seconds |

Methods:
- `is_ok`: true when the status is `ok`; the only meaning of "correct" (D6).
- `Result.rejected(reason)`: a `rejected` result, with the reason as its error.
- `Result.failure(status, error, feedback, duration)`: any other result without a score.
- `to_dict()`: every attribute as plain JSON values, the status as its name, a missing score as `null`
  (never `-Infinity`).
- `Result.from_dict(data)`: the reverse.

### D60. The `Program` class (`program.py`)
**Decision.** A dataclass of facts fixed once the program exists, with no free-form `metadata` dict and
no database state on it.

`LLMUsage` attributes: `model`, `input_tokens`, `output_tokens`, `duration`: the call that wrote the
program (D35).

`Program` attributes:

| Attribute | For |
|---|---|
| `id` | a UUID, identifying the program everywhere |
| `code` | the full file |
| `result` | its `Result` (D73) |
| `origin` | `initial` (the initial program), `llm` (written by the LLM), `copy` (placed by the framework: the initial program on each island, or a copied migrant) or `move` (a moved migrant). D13's checks and D19's children count apply to `llm` programs only |
| `parent_id` | the parent; for a copy or a move, the program copied; none for the initial program |
| `island` | the island it was made on (D23); none for the initial program itself, which lives on the islands through its copies |
| `iteration` | the iteration that produced it: 0 for the initial program and its copies; for a migrant, the number of completed iterations at its migration |
| `generation` | its distance from the initial program; a copy keeps the generation of the program it copies |
| `description` | the LLM's self-contained description (D15); may be none |
| `fingerprint` | the hash of its syntax tree (D13); none if it does not compile |
| `code_complexity` | its node count inside the evolve blocks (D17); none if it does not compile |
| `example_ids` | the example programs shown in its prompt (D26) |
| `llm` | its `LLMUsage`; none for the initial program and copies |
| `created_at` | when it was made |

Methods:
- `to_dict()`: every attribute as plain JSON values, with `result` and `llm` nested; one line of
  `programs.jsonl` (D48).
- `Program.from_dict(data)`: the reverse, keeping the id; a missing key is an error that names it.
- `Program.new_child(parent, ...)`: an `llm` child: a new id, the parent's id, `generation` = the
  parent's + 1, the time of creation, and the given code, result, island, iteration, description,
  fingerprint, code complexity, example ids and LLM usage.
- `copy_to(island, iteration, mode)`: a copy or a move of this program: a new id, origin `copy` or
  `move`, this program as parent, the given island and iteration, no LLM usage and no example ids;
  code, result, generation, description, fingerprint and code complexity are carried over.

### D74. The check functions (`checks.py`)
**Decision.** Plain functions (D13), used by the loop's main thread and for the initial program. A
marker line is one whose text, without surrounding spaces, is exactly `# EVOLVE-BLOCK-START` or
`# EVOLVE-BLOCK-END`.

**`split_evolve_blocks(code)`**: returns the code outside the blocks (one segment more than there are
blocks, marker lines included) and the blocks' contents.
1. Go through the lines, keeping a current segment and whether we are inside a block.
2. A START line: if already inside, error "a start inside a block"; otherwise close the outside segment
   (with the START line) and begin a block.
3. An END line: if not inside, error "an end without a start"; otherwise close the block and begin an
   outside segment with the END line.
4. Any other line: add it to the current segment.
5. At the end: if still inside, error "a start without an end"; if there was no block, error "no evolve
   block"; otherwise close the last outside segment and return both lists.

**`same_outside_code(child_code, initial_code)`**: none if the child kept the blocks where the initial
program has them, otherwise what differs.
1. Split both programs; if the child's markers are broken, return "the markers were changed" with why.
2. If the numbers of blocks differ, return the expected and the found numbers.
3. For each pair of outside segments, compare them after dropping blank lines and the spaces at the ends
   of lines (spaces at the start still count); return the first segment that differs.
4. Otherwise return none.

**`defined_functions(tree)`**: the names of the functions defined at the top level of the syntax tree.

**`fingerprint(tree)`**: the SHA-256 hash of the syntax tree written out without line numbers; comments
and spacing are not part of the tree, so they do not change it.

**`count_block_nodes(tree, code)`**: the code feature (D17).
1. Find the line numbers inside each block, from the positions of the marker lines.
2. Go through every node of the tree; skip nodes without a position (contexts, operators).
3. Count the nodes whose first and last lines both fall inside one block.

**`check_child(code, initial_code, entry_functions, known_fingerprints)`**: the four checks of D13;
returns the reason for a rejection (or none), the fingerprint and the code complexity.
1. No code: rejected, "no code in the reply".
2. Parse the code; a syntax error: rejected, with the error.
3. Compute the fingerprint and the code complexity.
4. `same_outside_code` against the initial program; a difference: rejected, with it.
5. A required entry function missing from `defined_functions`: rejected, naming it.
6. The fingerprint already known: rejected, "same program as" the id of the program that has it.
7. Otherwise: accepted.

### D68. Reply parsing (`reply_parser.py`)
**Decision.** Functions, not a class, reusing v1's rules. `ParsedReply` holds `code` and `description`,
either of which may be none.

**`parse_reply(reply, parent_code)`**:
1. Remove the thinking sections (`<think>` … `</think>`).
2. Take out the description with `extract_description`.
3. Find the code in what remains with `extract_code`.
4. Return both.

**`extract_description(text)`**:
1. Find the first text between `<DESCRIPTION>` and `</DESCRIPTION>`, in any letter case.
2. None found: return no description and the text unchanged.
3. Otherwise return the description, stripped (none if empty), and the text without that section, so
   that code quoted inside the description is never taken for the program.

**`extract_code(text, parent_code)`** (v1's rules):
1. Find the fenced code blocks (opening and closing fences on their own lines); if none, the one-line
   blocks.
2. Some found: choose one with `choose_code_block`.
3. None found: a block opened but never closed gives everything after its opening; no fence at all gives
   the whole text (rejected later if it is not Python).
4. Strip it; return none if it is empty, otherwise the code ending with one newline.

**`choose_code_block(blocks, text, parent_code)`**:
1. Keep the blocks that are valid Python. If none is, try the widest block (from the first opening fence
   to the last closing one): if it is valid Python, return it; otherwise keep all the blocks.
2. Drop the blocks that are the same program as the parent (same syntax tree), unless that drops them all.
3. Return the longest.

### D67. The `PromptBuilder` class (`prompt.py`)
**Decision.** Builds the two messages of Appendix A (D25, D26, D27, D10). The module also holds the
templates of Appendix A as constants (D29).

`Prompt` attributes: `system` and `user`, the two messages.

`PromptBuilder` attributes: `system_message` (built once, the same for the whole run), `settings` (the
prompt settings).

Methods:
- `PromptBuilder(problem)`: builds the system message.
- `build(parent, examples, best_score)`: the prompt of one iteration.
- `program_section(program, heading)`: one program's part of the user message.
- `truncated(text)`: a text cut to the size limit (D10).

**`PromptBuilder(problem)`**:
1. Write the allowed packages as a list of names (without versions), or "nothing else" when there is none.
2. Fill the system template with the problem's description and that list; keep it.

**`build(parent, examples, best_score)`**:
1. If there are example programs, start with "# Previous attempts", then one section per example, in the
   order drawn, headed "Attempt n:" followed by its score for a working one, or its status otherwise.
2. Add the parent's section, headed with its score and the best score so far in the run.
3. Add the request, "Write the improved program."
4. If the two messages together exceed `max_chars` and examples are left, drop the last example, log a
   warning and start again (D30).
5. If they still exceed it without examples, log a warning and keep them.
6. Return the system message and the user message.

**`program_section(program, heading)`**:
1. The heading.
2. "Description:" and the description, if there is one.
3. "Feedback:" and the feedback, truncated, if there is any.
4. "Error:" and the error, truncated, if there is one.
5. The code in a Python fence.

**`truncated(text)`**: the text itself if it fits in `max_feedback_chars`, otherwise its beginning
followed by "… (truncated)".

### D66. The `LLM` classes (`llm.py`)
**Decision.** An abstract `LLM`, one implementation per model, and an `Ensemble` that the loop always
uses, with one model or several. Models are drawn, and their failures counted, in the main thread only,
so the run's random generator and the counters are never shared between threads (D36, D39).

- `LLMReply`: `text`, `model`, `input_tokens`, `output_tokens`, `duration`.
- `LLMError`: no reply could be obtained; it names the model.
- `NoModelLeft`: every model has been dropped (D34).
- `is_reasoning_model(name)` (D32): true when the name, without any provider prefix such as `openai/`,
  starts with `o1`, `o3`, `o4`, `gpt-5` or `gpt-oss`.

`LLM` (abstract): attribute `name`; methods `complete(prompt)` (returns an `LLMReply` or raises
`LLMError`) and `check()` (the start-up check, D34).

`OpenAICompatibleLLM(LLM)` attributes: `settings` (its `ModelSettings`) and `client` (the `openai`
client, the only holder of the key).

**`OpenAICompatibleLLM(settings)`**:
1. If the model names a key variable, read it from the environment; if it is not set, stop with an error
   naming the variable.
2. Create the client with the model's address, the key (or a placeholder for a local server), its
   timeout and its number of retries (one layer of retries, D34).

**`complete(prompt)`**:
1. Send the system and user messages with the model's name.
2. For a reasoning model, send the token limit as `max_completion_tokens`, and the reasoning effort if
   set; for any other, send it as `max_tokens`, and the temperature if set (D32, D33).
3. Any error from the `openai` package: raise `LLMError` with its type and message.
4. An empty reply: raise `LLMError`, "empty reply".
5. Return the text, the model's name, the token counts (0 when the server gives none) and the duration.

**`check()`**: send a one-line request ("Reply with the word OK.") with the model's own settings; any
`LLMError` reaches the caller.

`Ensemble` attributes: `models`, their `weights`, `active` (the names still in use),
`failures_in_a_row` (per model), `max_failures`, `rng` (the run's random generator).

**`draw()`**:
1. If no model is active, raise `NoModelLeft`.
2. Draw one active model at random, in proportion to the weights of the active models (dropping a model
   thus rescales the others', D34).

**`record_success(name)`**: set the model's failures in a row to 0.

**`record_failure(name)`**: add 1 to its failures in a row; when they reach `max_failures`, remove it from
the active models and log a warning.

**`check_all()`**: `check()` every model; the first failure stops the run before its first iteration.

### D61. The `Grid` class (`grid.py`)
**Decision.** One fixed MAP-Elites grid (D17, D18).

Attributes: `features` (the `FeatureSpec`s), `reference_nodes` (the initial program's code complexity,
for normalizing), `elites` (for each occupied cell, given by one bin number per feature, its elite).

**`feature_values(program)`**: for each feature, `code_complexity` gives log2 of the program's node count
over `reference_nodes` (each taken as at least 1, D18); any other feature gives the value the evaluator
put in the result's features.

**`cell_of(program)`**: for each feature, the bin of its value: its position between `low` and `high`,
times the number of bins, rounded down, and moved into the first or the last bin when out of range.

**`place(program)`**: for an `ok` program only (D7).
1. Find its cell.
2. If the cell is empty, or its elite scores strictly lower, the program becomes the cell's elite.
3. Return whether it took the cell, the cell, and the elite it displaced, if any.

**`remove(program_id)`**: empty the cell this program holds, if any (a migrant moving away, D23).

**`elite_list()`**: the elites, in the order of their cells, so that draws can be repeated.

**`best()`**: the elite with the highest score; the first in cell order, on a tie.

### D62. The `Island` class (`database.py`)
**Decision.** An island's number, its grid and the list of every program made on it.

Attributes: `index`, `grid` (its `Grid`), `program_ids` (every program made on the island, in order;
where example programs are drawn from, D26).

Methods: `elites()`, the island's population (D23): its grid's elites; `best()`: its grid's best.

### D75. The parent selectors (`database.py`)
**Decision.** An abstract `ParentSelector` with one method, `choose(island, database, rng)`, and the two
strategies of D19, chosen by `parents.strategy`. The child of an iteration always lives on the
iteration's island: with the weighted rule that is its parent's island; with openevolve's archive branch
it may not be, as in openevolve itself.

`WeightedSelector` (primary), attribute `lam` (λ). **`choose`**:
1. Take the island's elites (never empty: every island starts with a copy of the initial program) and
   their scores.
2. Compute the median score and the spread: the median absolute deviation from the median; if that is 0,
   the standard deviation (D19).
3. For each elite, the performance term is 0.5 if the spread is 0, otherwise the sigmoid of λ × (score −
   median) / spread; the novelty term is 1 / (1 + its number of children).
4. Draw one elite at random in proportion to performance × novelty.

`OpenEvolveSelector` (secondary), attribute `archive_size`. **`choose`**:
1. Draw a number between 0 and 1.
2. Below 0.2: a uniform draw among the island's elites.
3. Below 0.9: a uniform draw among the archive's programs made on this island, or among the whole
   archive if none was (D21).
4. Otherwise: a draw among the island's elites in proportion to their scores (each at least 0.001, as in
   openevolve).

### D63. The `Database` class (`database.py`)
**Decision.** All of the run's state that is derived from its programs. Only the main thread uses it
(D36). Adding the saved programs again, in order, rebuilds it exactly (D49), so none of it is saved on
its own.

Attributes:

| Attribute | For |
|---|---|
| `problem` | the grid, island and parent settings |
| `programs` | every program of the run, by id, in the order added (D22) |
| `islands` | the `Island`s |
| `fingerprints` | for each fingerprint, the id of the first program that had it (D13) |
| `children` | for each program, its number of `llm` children, `error` ones excluded (D19) |
| `best_id` | the best `ok` program so far; the earliest, on a tie |
| `best_changed_at` | the number of completed iterations when the best last improved (for `--patience`, D37) |
| `selector` | the parent selector (D75) |
| `rng` | the run's random generator (D39) |

**`Database(problem, initial_program, rng)`**: create one island per `islands.count`, each with a grid
whose reference is the initial program's code complexity; create the selector named by
`parents.strategy`.

**`add(program, completed)`**:
1. Record the program; if it was made on an island, add it to that island's list.
2. If it has a fingerprint and its status is `ok`, `failed`, `timeout` or `invalid`, record the
   fingerprint, unless already known (D13).
3. If it is an `llm` child whose status is not `error`, add 1 to its parent's children (D19).
4. If it is a `move`: take the moved program out of its island's grid, and give the new record the moved
   program's children count (D19, D23).
5. If it is `ok` and on an island, place it in that island's grid.
6. If it is `ok` and scores strictly higher than the best, it becomes the best; record the number of
   completed iterations, when given.

**`seed_islands(initial_program)`**: one copy of the initial program per island, iteration 0.

**`best()`**: the program of `best_id`. **`children_count(id)`**: its children, 0 if none.

**`archive(k)`** (D21):
1. Sort the `ok` programs by score, highest first; the earlier one first on a tie.
2. Keep one program per fingerprint, so that copies count once.
3. Return the first k.

**`sample_island()`**: a uniform draw among the islands (D23).

**`sample_parent(island)`**: the selector's choice on that island.

**`sample_examples(island, parent, count)`** (D26):
1. Take every program made on the island (the iteration's island) except the parent, programs with status
   `error` and children without code.
2. Draw `count` of them at random without replacement (fewer if there are fewer), and keep the order drawn.

**`migrate(iteration)`** (D23):
1. For each island, choose its migrants: its best for `best`; otherwise draw at random among its elites
   (`random`) or its elites except its best (`random_non_best`), `migration_share` × the number of elites,
   rounded down, at least 1, at most as many as there are.
2. Its destinations: the next island for `ring`, every other island for `all_others`; with `move`, only
   the first destination, since a program can be in one place only.
3. Choose every island's migrants first, then create them, so that an arrival never migrates in the same
   round.
4. Create a copy (or move) of each migrant for each destination, with this iteration, and `add` each:
   it takes its cell only if the cell is empty or holds a worse elite.
5. Return the new records, for the loop to store, so that a replay repeats the migration exactly.

**`replay(programs)`**: `add` every saved program, in order (D49).

### D76. The evaluation API (`evaluation_api.py`)
**Decision.** What an evaluation file imports, and the contract of its functions.

An evaluation file defines either `evaluate(namespace)` or `evaluate_stage1(namespace)`,
`evaluate_stage2(namespace)`, … (D9), and optionally `visualize(output_data, path)` (D51). Each stage
function receives the program's namespace (D8) and:
- returns a `StageResult`: `score` (a finite number, higher is better), `metrics`, `features` (from
  stage 1: every output feature of the problem), `feedback`, `output_data`;
- or raises `InvalidProgram(reason, feedback)` when the answer breaks the problem's rules (D7);
- and lets `ProgramFailure`, `CallTimeout` and `StageTimeout` through, unless it handles them itself
  (function minimization's stage 2 catches the first two for each trial).

Exceptions raised by the namespace (D64):
- `ProgramFailure`: the program raised, or its process ended; it carries the exception's type and
  message, its traceback, and the end of the program's error output.
- `CallTimeout`: one call exceeded its own limit; the evaluator may catch it.
- `StageTimeout`: the stage's own limit ran out (D41); deliberately not a kind of `CallTimeout`, so that
  catching a trial's timeout never hides it.

**`call_with_timeout(function, seconds, arguments)`**: openevolve's `run_with_timeout`, ported: call the
namespace function with that time limit.

Stage functions run in worker threads, several at once when `workers` > 1 (D36), so they must not keep
state between calls.

### D77. The sandbox protocol and worker (`sandbox_protocol.py`, `sandbox_worker.py`)
**Decision.** One JSON message per line between the host and the worker, which answers calls for as
long as the stage lasts (D8).

Messages:

| From | Message | Contents |
|---|---|---|
| host | `load` | the program's code |
| host | `call` | an id, a function name, its arguments |
| host | `get` | an id, the name of a plain-data global |
| worker | `loaded` | the program's top-level names, each marked `function`, `data` or `other` |
| worker | `load_failed` | the error and its traceback |
| worker | `return` | the id, the value |
| worker | `raised` | the id, the error and its traceback |

**`encode(value)`**: turns plain data into JSON values; anything else raises `NotPlainData`.
- Kept as they are: none, booleans, integers, strings, finite floats.
- Tagged, so that they come back unchanged: floats that are not finite; tuples (so that `run_search`'s
  `(x, y, value)` stays a tuple); dictionaries with text keys; numpy arrays of numbers (their type, shape
  and bytes in base64).
- Converted: numpy numbers become Python numbers; lists are encoded item by item.
- Refused: arrays of anything but numbers, and every other type.

**`decode(value)`**: the reverse; numpy arrays are rebuilt from their bytes for a number type only,
never through pickle (D8). numpy is optional on both sides.

**`send(stream, message)`** and **`receive(stream)`**: one line of JSON each way.

**The worker** (`python -m my_evolve.sandbox_worker`), under a time limit of its own, slightly longer
than the stage's (D42):
1. Keep a private copy of standard output for the protocol, then point standard output at standard
   error, so that what the program prints goes to the error output the host captures.
2. Read the `load` message.
3. Run the code in a fresh namespace whose `__name__` is `program`, so the program's
   `if __name__ == "__main__":` part never runs.
4. Anything raised, exit requests included: send `load_failed` and stop.
5. Send `loaded` with the program's top-level names and their kinds.
6. For each following message: look the name up in the namespace; for `get`, take its value; for `call`,
   decode the arguments and call it; send `return` with the encoded value, or `raised` with the error
   and the traceback if anything was raised (a value that is not plain data included).

A program can write to the protocol's stream too, but gains nothing: it already chooses what its
functions return, and the host ignores any message whose id it is not waiting for.

### D64. The `Sandbox` classes (`sandbox.py`)
**Decision.** A sandbox starts one session per cascade stage (D40). A session is one worker process,
in a container or not, holding one loaded program; the namespace stands in front of it.

Classes:
- `Sandbox` (abstract): `start(code, stage_limit)`, shared; `command(name, stage_limit)`, how to start
  the worker; `stop(session)`, how to kill it; `remove_leftovers()`.
- `DockerSandbox` attributes: `image`, `settings` (the sandbox settings), `run_id`; plus
  `ensure_image(packages)`.
- `LocalSandbox`: the same worker as a plain subprocess, without any isolation (`--unsafe-local-sandbox`).
- `SandboxSession` attributes: `process`, `reader` (a thread collecting the worker's messages in a
  queue), `stderr_file`, `code`, `stage_limit`, `deadline` (when the stage ends), `names` (from
  `loaded`), `alive`. Methods: `restart()`, `call(name, args, kwargs, timeout)`, `get(name)`, `kill()`,
  `close()`, `error_tail()` (the end of the program's error output, D10).
- `ProgramNamespace`, what `evaluate` receives: looking a name up gives a `RemoteFunction` for a
  function, the value for a plain-data global, and raises `ProgramFailure` for anything else or a
  missing name (`failed`, D7); it also tells whether a name exists and lists the names.
- `RemoteFunction`: calling it calls the program's function, limited by the stage only;
  `with_timeout(seconds)` gives the same function with a time limit of its own.
- `SandboxError`: the sandbox itself failed (Docker missing or stopped, the image build failed, a
  container that cannot start); the program then gets status `error`.

**`ensure_image(packages)`** (D71):
1. The tag: `my-evolve-evaluation:` and the start of a hash of the Dockerfile and the package list.
2. If Docker has no image with that tag, build it from a temporary folder holding only the Dockerfile
   and the package list.
3. Return the tag.

**`command(name, stage_limit)`**, Docker (D41, D42): `docker run`, removed when it ends, with: the
container's name; the run's label; no network; a read-only file system with a temporary `/tmp`; the
memory limit and no swap; the CPU and process limits; all capabilities dropped and no new privileges;
the user `nobody`; the thread variables (`OMP_NUM_THREADS` and similar) set to the CPU count; the package
folder mounted read-only; and, as the command, the worker under `timeout`, killed 10 s after the
stage's limit. Local: the same worker, run by the host's Python, with the thread variables set.

**`start(code, stage_limit)`**: create a session with the stage's deadline, `restart` it, return it.

**`restart()`** (a fresh process with the program reloaded):
1. `kill` any process still running.
2. Start the worker with `command`; failing to start raises `SandboxError`.
3. Start the reader thread; send `load` with the code.
4. Wait, until the deadline, for `loaded` or `load_failed`.
5. `load_failed` raises `ProgramFailure` with the error, the traceback and the error output.
6. Keep the names; the session is alive.

**`call(name, args, kwargs, timeout)`**:
1. If the session is not alive (a previous call ran out of time), `restart` it (D8).
2. If the stage's deadline has passed, `kill` and raise `StageTimeout`.
3. Send `call` with a new id and the encoded arguments.
4. Wait for the answer with that id until the call's own limit or the deadline, whichever comes first;
   any other message is ignored.
5. Time ran out: `kill`, then raise `CallTimeout` if it was the call's own limit, `StageTimeout` if it
   was the stage's.
6. The worker ended: the session is no longer alive; raise `ProgramFailure` explaining how it ended
   (exit code 137: "stopped, most likely for using too much memory", as in v1) with the error output.
7. `raised`: raise `ProgramFailure` with the error, the traceback and the error output.
8. `return`: return the decoded value.

**`get(name)`**: the same as `call`, with a `get` message.

**`kill()`**: if the process is running, `stop` it (`docker kill`, or killing the process) and wait for
it; the session is no longer alive. **`close()`**: `kill`, then close the error-output file.

**`remove_leftovers()`**, Docker (D42): remove every container labelled with the run's id. Called at
start-up, when the run stops, and on a second Ctrl+C. Local: nothing to do.

### D65. The `Evaluator` class (`evaluator.py`)
**Decision.** Runs the cascade (D9) on the host, each stage in a fresh sandbox session, and turns
whatever happens into a `Result` (D73). It never raises because of a program.

Attributes: `stages` (the stage functions, in order), `thresholds`, `stage_limit`, `output_features`
(their names, D17), `sandbox`, `visualize` (the evaluation file's function, or none).

**`Evaluator(evaluation_path, problem, sandbox)`**:
1. Load the evaluation file on the host with v1's loader (helper files next to it can be imported, and
   are forgotten afterwards).
2. Its stages: `evaluate_stage1`, `evaluate_stage2`, … as long as they exist; otherwise `evaluate`
   alone; neither is an error.
3. If there are fewer thresholds than stages after the first, stop with an error.
4. Keep the thresholds, the stage limit, the output feature names, the sandbox and `visualize`.

**`evaluate(code)`**:
1. Start a clock; nothing merged yet.
2. For each stage, in order, run it with `run_stage` and validate what it returned with `checked`.
   - It raised `InvalidProgram`, at any stage: return `invalid`, with the reason as the error and the
     feedback gathered so far plus its own (openevolve scores such programs 0, D9).
   - It raised `ProgramFailure`, `CallTimeout` or `StageTimeout`: at stage 1, return `failed` (or
     `timeout` for the last two) with the failure described; at a later stage, keep the earlier stages'
     result, note "stage k:" and the failure as its error, and stop going through stages (D9).
   - It raised `SandboxError`: return `error`, "sandbox:" and the message.
   - Anything else (the evaluation file itself raised, or `checked` refused its result): return `error`,
     "evaluator:" and the traceback; not the program's fault.
3. Merge the stage's result into the result so far with `merge`, and gather its feedback.
4. If another stage follows and this stage's score is below its threshold, stop going through stages.
5. Return `ok` with the merged score, metrics, features and output data, the gathered feedback, the
   error of a later stage if any, the stage reached and the duration.

**`run_stage(stage, code)`**: start a sandbox session (loading the program; `ProgramFailure` if that
fails), call the stage function with a `ProgramNamespace` over the session, and always close the
session afterwards.

**`checked(outcome, stage_number)`**: refuse anything that is not a `StageResult`, a score that is a
boolean or not a finite number, and, at stage 1, any output feature missing or not finite.

**`merge(previous, outcome, stage_number)`**: at stage 1, the stage's own values; later, the new score,
the earlier metrics updated with the new ones, stage 1's features (D17), the new output data if the stage
gave any (otherwise the earlier one), and the new stage number.

Describing a `ProgramFailure`: its type and message, then the end of its traceback and of the program's
error output; the prompt cuts them to its size limit later (D67).

### D69. The `Storage` class (`storage.py`)
**Decision.** Owns the run folder (D47). Only the main thread uses it (D36).

`RunInfo` (the content of `run.json`, D50) attributes: `run_id`, `seed`, `fingerprints` (of the initial
program, the evaluation file, the problem without its `llm` section, and the image), `sessions` (for
each: start and end time, git commit, command line, `llm` section, flags, system message, how it ended).
Methods: `to_dict`, `from_dict`.

`HistoryRow` (one line of `history.csv`) attributes: `iteration`, `completed` (the number of completed
iterations), `program_id` (empty when there is no child), `status` (the child's status, `skipped` when
the LLM call failed, `error` when the iteration failed before having a child), `score`, `best_score`,
`best_id`, `model`.

`Storage` attributes: `folder` and the path of each file. Methods:
- `is_new()`: true while there is no `programs.jsonl`.
- `append_program(program)`, `append_llm_call(record)`, `append_history(row)`: add one line, and make sure
  it reaches the disk before returning.
- `write_best(program)`: rewrite `best_program.py`: a comment header (score, iteration, id, and the
  description as comment lines), then the code.
- `write_snapshot(program, completed)`: the same, as `best/iteration_` and the number on four digits.
- `save_problem(path)`: copy the problem file to `problem.yaml`.
- `read_run_info()`, `write_run_info(info)`: `run.json`, written whole to a temporary file then renamed,
  so that a crash never leaves half a file.
- `load_programs()`, `load_history()`: read the files back.

**Reading a line-based file back** (`load_programs`, `load_history`, as in v1):
1. No file: nothing saved yet.
2. Read each line.
3. A line that cannot be read: if it is the last one, it was cut off by a crash; rewrite the file without
   it and stop there; otherwise stop with an error naming the file and the line.

`llm_calls.jsonl` records: iteration, program id (none when skipped), model, the user message (the system
message is saved once per session in `run.json`), the reply (none when the call failed), the token
counts, the duration, the error (none when the call succeeded).

### D78. Logging (`logs.py`)
**Decision.** One function, `setup_logging(folder, verbose)`, and a logger per module everywhere else (D52).

**`setup_logging(folder, verbose)`**:
1. The package's logger lets everything through.
2. A console handler, writing UTF-8 (D55), shows the message alone; it shows the details too only with
   `verbose`.
3. A file handler appends everything to `log.txt` in the run folder, with the time, the level and the
   module.

The one line per iteration on the console: iteration and total, island, model, the child's status and
score, the best score so far. No secret is ever logged (D46): keys are only read inside
`OpenAICompatibleLLM`.

### D70. The loop (`loop.py`)
**Decision.** A function, `run`, with the main thread doing all the bookkeeping and a small pool of
daemon worker threads doing the waiting (LLM calls and evaluations, D36).

`RunSettings` attributes (the flags, D45): `initial_program`, `evaluation_file`, `problem_file`,
`iterations`, `output`, `workers`, `seed`, `target_score`, `patience`, `unsafe_local_sandbox`, `verbose`.

`WorkerPool`: `workers` daemon threads taking tasks from one queue and putting their results on another;
being daemon threads, they are never waited for when the program ends, so a second Ctrl+C cannot hang
on them (Part D, v1 item 1). Methods: `submit(kind, iteration, function, arguments)`;
`next_result(timeout)`, the next finished task (its kind, iteration, and value or exception), or none.

`IterationState` attributes: `number`, `island`, `parent`, `examples`, `model`, `prompt`, and, once the
reply is back, `reply`, `parsed`, `checks`.

`Context` attributes: the settings, the problem, the storage, the database, the evaluator, the sandbox,
the ensemble, the prompt builder, the initial code, `started` and `completed` (iteration counts),
`errors_in_a_row`.

**`run(settings)`**:
1. Load the problem; open the storage; set up logging.
2. `prepare` everything else.
3. Start the worker pool; on Linux, make SIGTERM interrupt the main thread as a second Ctrl+C would.
4. Repeat until nothing is in flight and nothing more may start:
   1. While fewer than `workers` iterations are in flight, fewer than `iterations` have started, and the
      run is not stopping: `start_iteration` and submit its proposal (`propose`) to the pool. If no model
      is left, the run is stopping.
   2. Wait for a finished task in steps of 0.2 s, so that Ctrl+C reaches the main thread (D53).
   3. A finished proposal: `after_proposal`; if the child passed the checks, submit its evaluation.
   4. A finished evaluation: build the child with its result (an exception gives status `error`) and
      `finish` it.
   5. When an iteration is done, check `should_stop`; a reason means the run is stopping.
5. First Ctrl+C: log that the iterations in progress will be finished and that a second Ctrl+C stops at
   once; finish them as above without starting new ones (D53).
6. Second Ctrl+C, or SIGTERM: remove the containers and stop at once; the session ends "interrupted" (D54).
7. In every case: remove the run's containers, record the end of the session and its reason in
   `run.json`, print the `summary`, and return the database.

**`prepare(settings, problem, storage)`**:
1. Compute the fingerprints of the initial program, the evaluation file, the problem without `llm`, and
   the image tag.
2. No `run.json` yet: create the run's information (a new run id; the seed given, or one drawn at random)
   and copy the problem file. A `run.json` with other fingerprints: stop, saying what changed (D50).
3. Create the sandbox: the local one with `--unsafe-local-sandbox`, announced with a warning; otherwise
   Docker, after `ensure_image`. Remove leftover containers (D42).
4. Create the evaluator and one `OpenAICompatibleLLM` per model.
5. A new run: `evaluate_initial`; create the random generator from the seed and the database; add the
   initial program and its island copies, storing each; write the best program and snapshot 0; no
   iteration completed yet.
6. A resumed run: load the programs and the history; create the random generator from the seed and the
   number of programs stored (D39); create the database from the first program and `replay` the rest;
   the completed iterations are the history's rows.
7. Create the ensemble and `check_all` the models (D34).
8. Create the prompt builder; record the session (time, commit, command, `llm` section, flags, system
   message) in `run.json`.
9. Return the context, with `started` equal to `completed`.

**`evaluate_initial(code, problem, evaluator)`** (D20):
1. Its evolve blocks must split without error; otherwise stop, saying why.
2. Check it against itself (it must compile and define its entry functions); a rejection stops the run.
3. Evaluate it; anything but `ok` stops the run with its status and error.
4. Return it as the `initial` program, on no island, iteration 0, generation 0.

**`start_iteration(context, number)`**: draw the island, then the parent, then the example programs,
then the model (`NoModelLeft` if none is left); build the prompt with the best score so far.

**`propose(model, prompt, parent_code)`**, in a worker: ask the model (`LLMError` if no reply) and parse
its reply.

**`after_proposal(context, state, task)`**:
1. An `LLMError`: record the model's failure in the ensemble, store the failed call, and `skip` the
   iteration as `skipped` (it still counts, D34).
2. Any other exception: `skip` the iteration as `error` (D38).
3. Otherwise: record the model's success; keep the reply and the parsed reply; run `check_child` against
   the initial program, the entry functions and the known fingerprints.
4. Rejected: `finish` with a `rejected` child. Accepted: the evaluation can start.

**The child** (`child_program`): `Program.new_child` of the parent, with the parsed code (empty if none),
the result, the iteration's island and number, the description, the fingerprint and code complexity
from the checks, the example ids, and the model's usage.

**`finish(context, state, child)`**:
1. One more completed iteration.
2. `add` the child to the database with that count; store it; store its LLM call.
3. Errors in a row: one more if its status is `error`, otherwise back to 0.
4. If the best changed, rewrite `best_program.py`.
5. Store its history row; log its line.
6. `after_completion`.

**`skip(context, state, status, error)`**: one more completed iteration; one more error in a row for
`error`; store a history row without a child; log the line with the error; `after_completion`.

**`after_completion(context)`**: every `snapshot_every` completed iterations, write the best program's
snapshot; every `migration_interval` completed iterations, `migrate` and store the arrivals.

**`should_stop(context)`** (D37), the iteration total being the loop's own test:
1. The target score is set and the best score reaches it: "target score reached".
2. Patience is set and that many iterations have completed since the best last improved: "patience ran out".
3. Errors in a row reach `max_errors_in_a_row`: "too many errors in a row".
4. No model is active: "no LLM model left".
5. Otherwise none.

**`summary(context, reason)`** (D51), to the console and `log.txt`: iterations done, the reason, the best
score and its iteration, the counts by status, the tokens and cost per model (from the programs' LLM
usage and the prices of the `llm` section, D35).

### D79. The command line and the report (`scripts/run.py`, `scripts/report.py`, `report.py`)
**Decision.** Two scripts; any logic a test would need lives in the package.

`scripts/run.py`:
- **`parse_arguments(argv)`**: the two positional files and the flags of D45; check every value
  (`--iterations`, `--workers` and `--patience` at least 1, the files exist) and report a wrong one as a
  usage error.
- **`default_output(problem_name)`**: `runs/`, the problem's name, and the date and time (D45).
- **`main()`**: switch the console's output to UTF-8 (D55); parse the arguments; call `run`; turn a
  problem, run, sandbox or configuration error into one clear message and exit code 1, without a
  traceback.

`scripts/report.py RUN_FOLDER` calls the functions of `report.py` (D51):

**`load_run(folder)`**: the problem from `problem.yaml`, the programs, the history, and the evaluation
file's path recorded in `run.json`.

**`plot_progress(history, programs, path)`**: the best score so far against the number of completed
iterations, as a step line, with every `ok` child's score as a dot.

**`grid_snapshots(problem, programs, history)`**:
1. Create a database from the first program; a replay draws nothing at random.
2. Find, from the history, the completed count of each child and the counts at which a snapshot is due
   (multiples of `snapshot_every`).
3. Go through the programs in order. Before adding a child, take the snapshots due earlier than its count
   (they followed skipped iterations, which changed nothing). Add it. If a snapshot is due at its count,
   take it.
4. A snapshot is a copy of every island's grid, with its count.
5. At the end, take the snapshots still due, then a final one.

**`colour_scale(programs)`**: the lowest and the highest `ok` score of the whole run.

**`draw_grids(snapshot, scale, path)`**: one panel per island, titled with its number; each cell white
when empty, otherwise coloured on the `Blues` colour map, from light for the scale's lowest score to deep
for its highest; a 1D grid as a row of cells, a 2D grid as a square (first feature across, second up),
a 3D grid as one square per bin of its third feature; a colour bar; the title says after which iteration.

**`animate(images, path)`**: the grid images, in order, as one animated GIF.

**`draw_outputs(evaluation_file, snapshots, folder)`**: if the evaluation file defines `visualize`
(loaded on the host: it is your code), call it with the saved output data of the best program at each
snapshot, writing `output_` and the count on four digits.

Circle packing's `visualize(output_data, path)` draws the unit square and each circle with its number,
titled with n and the sum of the radii, as openevolve's `visualize` does, but saves the image to `path`
instead of opening a window.

---

## 15. Smaller features

Features of the references, and whether my-evolve has them.

| Feature | v1 | OE | SE | my-evolve |
|---|---|---|---|---|
| Target score stop | no | yes | no | yes, `--target-score` (D37) |
| Early stopping on no improvement | no | yes | no | yes, `--patience` (D37) |
| Token usage recorded and summed | no | yes | yes | yes (D35) |
| Token or dollar budget stop | no | no | yes (dollars) | no (D35) |
| Code-length limit | no | yes | no | no: only the checks of D13 |
| Arguments passed to the evaluator from the config | no | yes | yes | no: constants live in the evaluation file |
| LLM-as-judge scores | no | yes | no | no |
| Embedding-based novelty filter | no | yes | yes | no (D24) |
| Random wording variations in prompts | no | yes | no | no (D29) |
| Per-island system messages | no | yes | no | no |
| "Changes description" mode for large codebases | no | yes | no | no |
| Providers other than OpenAI-compatible endpoints | no | yes | yes | no (D32) |
| Human-in-the-loop "manual mode" | no | yes | no | no |
| Library API usable from a notebook | partly | yes | yes | yes: the `run` function (D70) |
| Evolution trace for RL training | no | yes | no | no: `programs.jsonl` and `llm_calls.jsonl` hold the same data (D47) |
| Web visualizer | no | yes | yes | no: the report script instead (D51) |
| Crossover of two programs | no | no | yes | no for now; a possible later experiment (D11) |
| Several full-rewrite strategies drawn at random | no | no | yes | no for now; a possible later experiment (D11) |
| LLM writes the initial program | no | no | yes | no: the initial program must work (D20) |
| Evolving the system prompt itself | no | no | yes | no |
| New islands when the search stagnates | no | no | yes | no (D23) |
| Public and private metrics | no | no | yes | no |
| Repeated runs with statistical early stop in the evaluator | no | no | yes | no: openevolve's cascade (D9) |
| Plots saved per program by the evaluator | no | no | yes | no: the report draws from `output_data` (D51) |
| Slurm cluster backends | no | no | yes | no (D40) |
| Weights & Biases logging | no | no | yes | no |
| Hydra presets | no | no | yes | no (D43, D44) |
| Skills that teach a coding agent to set up and run tasks | no | no | yes | no |

---

## Appendix A. The prompt

The text of the two messages, as decided in D25 to D27, D12, D15 and D71. Words in braces are filled in
for each problem or iteration. Templates are Python constants (D29), so this is their content, not their
final code.

### System message (the same for a whole run)

````text
You are an expert software engineer tasked with improving a program. You will see
a program to improve, the parent, and other programs tried before, with their
results. Write a new version of the parent that solves the problem below better
than it does, using what the previous attempts show.

# Problem
{description from the problem file, including the contract of the entry functions}

# Rules
- Change only the code between `# EVOLVE-BLOCK-START` and `# EVOLVE-BLOCK-END`.
  Leave everything else, the markers included, exactly as it is. Return the whole file.
- You may import Python's standard library and: {allowed packages}. Nothing else is installed.
- Higher scores are better.

# Reply format
Your reply must contain these two parts. You may write anything else around them.
<DESCRIPTION>
How this program solves the problem: its approach and main ideas. Describe the
program on its own; do not mention any other program.
</DESCRIPTION>
```python
the complete program
```
````

### User message (new for each iteration)

````text
# Previous attempts

## Attempt 1: score {score}
Description: {description}
Feedback: {feedback}
```python
{code}
```

## Attempt 2: {status, e.g. invalid}
Description: {description}
Feedback: {feedback}
Error: {error, e.g. Circles 3 and 7 overlap (distance 0.112, radii sum 0.130)}
```python
{code}
```

# Program to improve (the parent): score {score}; best score so far in this run: {best score}
Description: {description}
Feedback: {feedback}
```python
{code}
```

Write the improved program.
````

Notes:
- A failed attempt shows its status in place of a score, and its error; a working one has no error line.
  An empty field (no description, no feedback) is left out with its label.
- The parent comes last, just before the request: it is what the LLM must work on, and models attend most
  to the end of a prompt.
- Feedback and errors are truncated to a size limit (D10, D30).
- The previous attempts are shown in the order they were drawn, which is random (D26).

---

## Appendix B. Models for the experiments

Two batches, each an ensemble of two models with fixed weights (D31), set in the `llm` section of the
problem file (D43).

| Batch | Models | Weights | Reached through |
|---|---|---|---|
| 1 | `qwen3-coder:30b` (main), `qwen3:8b` | 0.8 / 0.2 | Local Ollama server, `http://localhost:11434/v1`; no key |
| 2 | Claude Haiku 5.5 (`claude-haiku-5-5`, main), Claude Sonnet 5.5 (`claude-sonnet-5-5`) | 0.8 / 0.2 | Anthropic's OpenAI-compatible endpoint, `https://api.anthropic.com/v1/`; key in `${ANTHROPIC_API_KEY}` (D46) |

Notes:
- Batch 1: the two models (about 18 GB and 5 GB) fit together in the RTX 5090's 32 GB, so Ollama keeps
  both loaded. Start the server with a context length that holds the whole prompt
  (`OLLAMA_CONTEXT_LENGTH=32768`), since Ollama silently cuts longer prompts.
- Batch 2: no `temperature`, since these Claude models reject it (D33), as openevolve's
  function-minimization config already does. The weights mirror that config (Haiku 0.8, Sonnet 0.2).
- The weights are proposals; any model and weight can be changed in the problem file.
