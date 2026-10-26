# Design decisions for my-evolve

Every difference in [differences.md](differences.md) is a choice to make again. This file lists
those choices, grouped by topic, with:

- **v1**: what my-alphaevolve does;
- **OE**: what openevolve does;
- **SE**: what ShinkaEvolve does;
- **Options**: the realistic alternatives, including ones none of the three uses;
- **Lean**: my suggestion, as a starting point for discussion;
- **Decision**: left blank for you.

Each decision is tagged:

- **[now]**: it shapes the architecture; better decided before the plan is written.
- **[later]**: it can wait for the step of the plan that needs it; the plan will note a default.

Decisions marked *(new with SE)* exist because ShinkaEvolve does something the other two do not.
Section references such as (A3) point to differences.md; "Part D, v1 item 3" means item 3 of
the my-alphaevolve list in its Part D.

---

## 1. Scope

### D1. How far to go [now]
- **v1**: a minimal core, about 1,300 lines.
- **OE**: most features of the AlphaEvolve paper (evolve blocks, diffs, ensembles, MAP-Elites with
  islands, cascades, LLM feedback, several metrics) plus many of its own; about 13,500 lines.
- **SE**: a research platform built for sample efficiency, with many optional mechanisms
  (bandit model choice, novelty rejection, meta recommendations, prompt evolution, cluster
  backends); about 41,800 lines.
- **Options**: a small core, adding features one by one only when chosen below · feature parity
  with OE or SE.
- **Lean**: a small core with clear places where features plug in; each feature chosen below
  becomes its own step of the plan. Several of SE's sample-efficiency ideas are small on their own
  (D14, D19, D24), so they fit this approach well.
- **Decision**: Start with a small core that works end to end, then add selected openevolve and ShinkaEvolve components, each as its own step.

### D2. Languages of the evolved programs [now]
- **v1**: Python only; programs are `exec`'d.
- **OE**: any language; the evaluator runs the file.
- **SE**: a dozen languages, each with its own EVOLVE-BLOCK comment syntax and file extension.
- **Options**: Python only · any language, which forces the evaluator to receive a file path (D5),
  the sandbox image to hold compilers, and the parser to know each language's comments.
- **Lean**: Python only.
- **Decision**: Python only.

### D3. Compatibility with openevolve or ShinkaEvolve [later]
- **v1**: the examples are adapted so that their scores equal OE's.
- **SE**: its circle-packing score is the raw sum of the radii (OE and v1 divide it by 2.635), so
  SE results are comparable to OE's only after that conversion.
- **Options**: none · same scores on adapted examples (as now) · run OE or SE evaluators unchanged.
- **Lean**: same scores as OE on adapted examples, so runs stay comparable; note SE's raw scale
  when comparing with its published numbers.
- **Decision**: Runs must stay comparable to openevolve's, on function minimization and circle packing. The initial programs are openevolve's code, with the EVOLVE-BLOCK markers removed, since the whole file may change (D12). Evaluators take a namespace (D5) but must score every program exactly as openevolve's evaluators do, with the same cascades (D9). Reference: the openevolve checkout `da3d701`, whose function-minimization evaluator recomputes the value from (x, y) instead of trusting the program (Part D, v1 item 4).

---

## 2. The problem and its evaluation

### D4. Where the problem description lives [later]
- **v1**: required docstring of the initial program (A1).
- **OE**: `prompt.system_message` in the YAML.
- **SE**: `task_sys_msg` in the config, used as the system message.
- **Options**: docstring · a field of a problem config file · a separate `description.md` in the problem folder.
- **Lean**: a separate file: descriptions grow long (circle packing's lists geometric insights), and it
  keeps the initial program a plain program.
- **Decision**: The description is a field of the problem file (YAML), as in openevolve (D43, D44).

### D5. What the evaluator receives [now]
- **v1**: `evaluate(namespace)`, the names the program defined, after the framework ran it.
- **OE**: `evaluate(program_path)`; the evaluator loads or runs the program itself.
- **SE**: the evaluator is a script given a file path; its helper imports the program and calls a
  named entry function several times, then hands the return values to the user's `validate` and
  `aggregate` functions.
- **Options**: namespace · file path · the code as a string · the return values of a named entry
  function, called by the framework (SE's helper, but built into the framework).
- **Lean**: namespace, if D2 is Python only: evaluators stay short and cannot get loading wrong.
  The entry-function variant is the one to pick if D8 moves the evaluator out of the program's process.
- **Decision**: `evaluate(namespace)`.

### D6. What the evaluator returns [now]
- **v1**: one finite number.
- **OE**: a dict of metrics with a `combined_score` convention (and a fallback average), or metrics + artifacts.
- **SE**: `combined_score`, a separate `correct` flag with an error message, `public` metrics (shown to
  the LLM), `private` metrics (hidden), `text_feedback`, `extra_data`.
- **Options**: one number · a dict with a designated main score · a small result object:
  `score` (required), `metrics` (optional numbers, for display and MAP-Elites features),
  `feedback` (optional text for the LLM) · plus a way to say "this program is invalid, because …"
  instead of returning a score of 0 (SE's `correct`).
- **Lean**: the result object, still accepting a bare number, with an explicit "invalid, because …"
  outcome. No averaging fallback: the main score is explicit. No private metrics until a problem needs them.
- **Decision**: A result object holding: `score` (a number; only `ok` programs have one, D7); `status` and `error` (whether the program failed, how, and why, D7); `metrics` (named numbers about the run); `features` (named numbers describing the program's output, for the MAP-Elites grid, D17; kept apart from `metrics` so they never affect the score); `feedback` (text for the LLM, D10); the evaluation's duration; the cascade stage reached (D9). There is no separate correctness flag: a program is correct when its `status` is `ok`, which is computed from the status, so the two can never disagree.

### D7. Failed programs [now]
- **v1**: score `-inf`, stored, never a parent, saved as `-Infinity`.
- **OE**: metrics `{"error": 0.0}`, fitness 0, can enter the grid and be a parent.
- **SE**: `correct: false`, score 0, stored; never a parent while a correct program exists (D20).
- **Options**: a sentinel score (`-inf`, `0`) · an explicit status (`ok`, `failed`, `invalid`,
  `timeout`, `rejected`) with no score and an error message.
  And separately: are failures stored? shown to the LLM? ever parents?
- **Lean**: explicit status + error message; stored and saved; never parents (see D20 for the
  "nothing works" case); their error shown to the LLM when the prompt mentions recent failed attempts (D26).
- **Decision**: Every program has a `status`. `ok` means it was evaluated and its answer is legal; only `ok` programs have a score. The five failure statuses, by when the program stopped and whose fault it was:
  - `rejected`: before evaluation, on the host. The child failed a check of D13 and was never run (a syntax error, which includes a reply with no code, or the same program as its parent).
  - `failed`: during evaluation. The program raised an exception while loading or while one of its functions ran (`ImportError`, `IndexError` in `run_packing`, a wrong return type).
  - `timeout`: during evaluation. The program ran out of time and its container was killed.
  - `invalid`: after evaluation. The program returned an answer that the evaluator judged illegal (overlapping circles, a negative radius, a circle outside the square). openevolve scores such programs 0; here the evaluator says so, with the reason in its feedback.
  - `error`: not the program's fault. The infrastructure failed (Docker did not start, the evaluator itself raised, the disk is full). Such programs do not count as children of their parent (D19), are never shown as negative inspirations (D10), and count toward the "errors in a row" stop (D38).

  With the cascade (D9), a program that passes stage 1 and fails or times out in a later stage keeps its stage 1 result: its status is `ok`, with the stage reached recorded. A failed program has an `error` message and no score (`score: None`). Failed programs are stored and saved: they are shown in prompts as negative inspirations, with their error (D10, D26), they count in the children count of the parent rule (D19), and they serve analysis and resuming. They are never chosen as parents, and play no part in duplicate detection (D13).

### D8. Where the evaluator runs relative to the program [later]
- **v1**: in the same Python process, inside the container; the program can forge its result or
  patch what `evaluate` uses (Part D, v1 item 3).
- **OE**: the same, or the evaluator's own subprocess.
- **SE**: the same: the program is imported by the evaluator script and could write the result
  files itself (Part D, SE item 5).
- **Options**: same process (as now) · same process, with a result channel the program cannot
  write to · the program runs in the container and returns the value of an entry function
  (e.g. `run_packing()`), which the evaluator scores on the host.
- **Lean**: same process for now, with the risk documented; revisit if reward hacking shows up.
- **Decision**: Each program runs in its own sandboxed container (v1's limits). The evaluator runs on the host, in the trusted process: the `namespace` it receives is a stand-in whose functions, when called, run the program's function inside the container and return its result. Results cross the boundary as plain data only (JSON, or numpy arrays without pickle), so the program can choose what its functions return but cannot touch how the score is computed.

### D9. Cascade evaluation and repeated runs [later]
- **v1**: written inside the user's `evaluate`.
- **OE**: framework-level `evaluate_stage1/2/3` with thresholds in the config.
- **SE**: no cascade; the evaluator helper repeats runs and can stop them early when statistics
  show the program cannot beat a threshold.
- **Options**: inside `evaluate` · framework stages · a helper for repeated runs with early stopping.
- **Lean**: inside `evaluate`: nothing for the framework to know.
- **Decision**: openevolve's cascade. The evaluation file defines `evaluate_stage1(namespace)`, `evaluate_stage2(namespace)`, … (a file with only `evaluate(namespace)` is a one-stage cascade), and the problem file lists the thresholds. A program goes to the next stage only if the previous stage's score reaches its threshold; metrics of later stages overwrite earlier ones; a later stage that fails keeps the earlier stages' result, as in openevolve. The result object records the stage reached. Cascades of our two problems, copied from openevolve (60 s per evaluation in both): function minimization: stage 1 = one call of `run_search` (5 s limit), threshold 1.3, stage 2 = 10 calls (5 s each), whose score replaces stage 1's; circle packing: stage 1 = one call of `run_packing`, scored as the sum of the radii divided by 2.635 if the packing is valid, threshold 0.5, stage 2 = openevolve's full evaluation (a second call, scored the same way). openevolve's second circle-packing threshold, 0.75, never applies, since there is no third stage.

### D10. Feedback from the evaluation to the LLM [now]
- **v1**: none; the LLM sees only the parent's score.
- **OE**: artifacts (any text the evaluator returns, or a traceback) shown in the next prompt that
  uses the program as parent.
- **SE**: `text_feedback` from the evaluator (off by default); stdout and stderr shown when fixing a program.
- **Options**: none · `feedback` text from the evaluator (D6) · that, plus the tail of the
  program's stderr captured automatically.
- **Lean**: evaluator feedback plus a captured error for failures, truncated to a size limit.
- **Decision**: An evaluator writes feedback text into the result object (D6) as it checks a program, in the style of openevolve's artifacts (e.g. "Circles 3 and 7 overlap (distance 0.112, radii sum 0.130)", "run_search timed out on trial 4 of 10"); our two examples' evaluators do so for every check they make. The framework adds the error message and the end of the error output when a program crashes or times out. When a program is used as an inspiration, the prompt shows its feedback and, if it failed, its error, truncated to a size limit: inspirations are both working programs (positive) and failed ones (negative), D26.

---

## 3. How the LLM changes a program

### D11. Format of a change [now]
- **v1**: full rewrite of the file.
- **OE**: SEARCH/REPLACE diffs by default; full rewrite optional.
- **SE**: drawn per proposal: diff 60%, full rewrite 30%, crossover of two programs 10%; a full
  rewrite also draws one of 5 strategies ("completely different algorithm", "different parameters", …).
- **Options**: full rewrite · diffs · both, chosen per run · several formats drawn per proposal with
  set probabilities (SE) · crossover as an extra format · rewrite strategies as an extra layer.
- **Lean**: formats drawn per proposal with configurable probabilities, which also covers "one
  format only". Full rewrite first in the plan, diffs next; crossover and rewrite strategies as later steps.
- **Decision**: Full rewrite.

### D12. Which part of the program may change [now]
- **v1**: the whole file.
- **OE**: the whole file, with advisory EVOLVE-BLOCK markers, enforced only on request.
- **SE**: markers required and enforced: diffs outside them are rejected, rewrites replace only
  the blocks' contents, a candidate that lost a marker is rejected.
- **Options**: whole file · markers, advisory · markers, enforced (edits outside are reverted, or
  the child is rejected) · markers, and only the blocks are shown to the LLM.
- **Lean**: markers optional: if the initial program has them, they are enforced as SE does and
  the prompt explains them; otherwise the whole file may change.
- **Decision**: The whole file may change: no EVOLVE-BLOCK markers (the initial programs have them removed, D3).

### D13. Checks before a child is evaluated [later]
- **v1**: none; even a copy of the parent is evaluated.
- **OE**: rejects unparsable diffs, unchanged code, code over 10,000 characters.
- **SE**: rejects patches that fail to apply, edits outside the blocks, broken markers; then the
  novelty filter (D24).
- **Options**, any combination: not valid Python (`ast.parse`) · same program as the parent (AST
  comparison, as v1's parser already does) · same as any program in the database · too long ·
  diff that does not apply · markers broken.
  And: is a rejected child stored (with its reason) or only counted?
- **Lean**: all of them; rejected children stored with status `rejected` and their reason, not evaluated.
- **Decision**: Two checks before evaluation, both on the host and without running the program. They apply only to children the LLM writes, never to copies the framework makes (the initial program in each island, migrants, D23). The child must compile (`ast.parse`; a reply with no code fails here), and it must not be a duplicate of its parent. Duplicate means AST-identical: both programs have the same syntax tree, so differences in comments and spacing are ignored. The comparison is always between syntax trees, never raw text, so failed programs play no part in it: the parent, being `ok`, always has a tree, and a child that does not compile is rejected for that reason instead. Whether a program runs is checked by the evaluation itself: loading it is the first thing the container does, and a program that fails to load is marked failed before any cascade stage. A rejected child is stored with status `rejected` and its reason, and is not evaluated (D7). No diff checks while changes are full rewrites (D11).

### D14. Repairing a rejected change [later] *(new with SE)*
- **v1**, **OE**: none; a reply that cannot be used is a lost iteration.
- **SE**: the LLM is told what went wrong (for a missing SEARCH, with the most similar lines of the
  file) and asked again in the same conversation (`max_patch_attempts`); after that, a new parent
  is drawn (`max_patch_resamples`).
- **Options**: no repair · ask again with the error, up to N times · also draw a new parent after N failures.
- **Lean**: ask again with the error once or twice: far cheaper than a new proposal, and the
  conversation already holds the context. Counts as one iteration.
- **Decision**: None.

### D15. Record of what changed [later]
- **v1**: none.
- **OE**: a text summary of the diff, shown in later prompts.
- **SE**: the LLM names and describes its change in tagged sections (`<NAME>`, `<DESCRIPTION>`);
  a unified diff is stored too.
- **Options**: none · the diff itself (computed with `difflib` even for rewrites) · a name and
  description asked of the LLM in tagged sections.
- **Lean**: store a computed diff for every child, and ask for SE's name and description: they cost
  a few tokens and make lineages readable, in prompts (D26) and in the outputs (D51).
- **Decision**: The LLM's reply includes, besides the code, a short description of how the child differs from its parent and why it should score better. A reply without a description is still accepted if its code is usable. This description is available to prompts (D26) and outputs (D51).

---

## 4. The database and the choice of parents

### D16. Population structure [now]
- **v1**: a flat list; MAP-Elites tried and reverted (`aeaf384`, `4a1e438`).
- **OE**: islands, each with its own MAP-Elites grid, plus a global archive.
- **SE**: 2 islands and a global archive of correct programs; no grid.
- **Options**: flat · one MAP-Elites grid · islands of flat populations (SE) · islands with a grid each (OE).
- **Lean**: built in steps behind one `Database` interface, each runnable and comparable: flat,
  then islands (SE-style), then a MAP-Elites grid per island as an optional step. SE shows that
  islands plus a good parent rule go a long way without a grid.
- **Decision**: Islands, each with its own MAP-Elites grid, plus a global archive. Tentatively later, CVT MAP-Elites.

### D17. MAP-Elites features [later, if D16 uses a grid]
- **v1** (`aeaf384`): complexity = code length, diversity = OE's quick estimate against the first 20 programs.
- **OE**: the same two, `score`, or any evaluator metric.
- **SE**: no grid; it does compute code metrics (`radon`: lines, cyclomatic complexity, nesting) and
  embeddings, which could serve as features.
- **Options**: code length · lines of code · cyclomatic complexity · a diversity measure (OE's
  estimate, edit distance, AST difference, embedding position) · metrics returned by the evaluator (D6).
- **Lean**: default code length × diversity; let a problem name evaluator metrics instead.
- **Decision**: One built-in "code" feature: the number of nodes of the program's syntax tree (`ast.parse`, then `ast.walk`), normalized as described in D18; possibly extended later with other measures such as cyclomatic complexity. Plus zero or more "output" features specific to the problem (no upper limit), computed by its evaluator from what the program returns and put in the result's `features` (D6); they must be computable from stage 1 of the cascade (D9). The problem file names the features a run uses; the default grid is one-dimensional, on the code feature alone. Circle packing, the main experiment, implements two output features, so a run can use either in 2D or both in 3D: the spread of the radii, std(radii) / mean(radii) (0 = all circles the same size; 0 when the mean is 0, which means every radius is 0), and the Pearson correlation (`numpy.corrcoef`) between each circle's radius and the distance from its centre to the centre of the square, (0.5, 0.5) (−1 = big circles in the middle, +1 = big circles at the edges; 0 when the radii or the distances are all equal, since the correlation is then undefined). Both are computed only for `ok` programs (D7). Function minimization: a one-dimensional grid for now; output features to be chosen later. Failed programs have no features and never enter a grid (D7).

### D18. Binning features into cells [later, if D16 uses a grid]
- **v1** (`aeaf384`): grid rebuilt from all programs at each sample, so bins always span the values seen.
- **OE**: running min/max at insertion; bins drift and old placements are never recomputed.
- **Options**: rebuild at each sample · running min/max (OE) · fixed ranges declared by the problem.
- **Lean**: rebuild at each sample: always consistent, and cheap for thousands of programs.
- **Decision**: A fixed grid, known when the run starts and never changed: the problem file gives each feature a range and a number of bins, all modifiable; a value outside the range goes to the nearest end bin. The code feature is normalized against the initial program: log2(nodes / nodes of the initial program), default range −1 to +3 (half to eight times the initial size), the same for every problem. Circle packing defaults: radii spread 0 to 1, correlation −1 to +1. Grids stay small, since runs last hundreds of iterations, not thousands. Default bins: 10 for a 1D grid, 5 × 5 for 2D, 3 × 3 × 3 for 3D. To revisit if CVT MAP-Elites is adopted (D16).

### D19. Choosing a parent [now]
- **v1**: 70% a random one of the 10 best working programs, 30% a random working program.
- **OE**: per island, 20% uniform, 70% a random archive elite, 10% fitness-weighted.
- **SE**: an island is drawn, then a parent among its archive members, weighted by
  sigmoid(λ × (score − median) / spread) × 1 / (1 + number of children): good programs are
  favoured, and programs already tried often are tried less. Alternatives: power law over rank,
  beam search, best-of-n.
- **Options**: v1's rule · OE's rule · SE's weighted rule · a uniform random grid elite (`aeaf384`) ·
  tournament (best of k random programs) · rank-based (probability falling with rank).
- **Lean**: SE's weighted rule: it is the main sample-efficiency idea of its paper, it does not
  depend on the score's scale, and the children factor gives exploration without a separate
  "explore" branch. Keep v1's rule as a second strategy behind the same interface, to compare.
- **Decision**: ShinkaEvolve's weighted rule as the primary strategy: pick an island, then a parent among the island's grid elites (the best program of each occupied cell) with weight sigmoid(λ × (score − median) / spread) × 1 / (1 + number of children), where the median and spread are those of the island's elites. λ is set in the problem file, and experiments will use values lower than ShinkaEvolve's 10, so that one niche does not take every draw; default λ = 1. "Number of children" counts every child the program has had, whatever its outcome (`failed`, `timeout`, `invalid` and `rejected` children included, since each cost an LLM call), except children with status `error`, which were not the parent's fault (D7); a migrated copy starts at 0 in its new island. Counting only successful children as a separate productivity term is a possible later experiment. openevolve's rule (20% uniform from the island, 70% archive elite, 10% fitness-weighted) as a secondary strategy behind the same interface, chosen in the problem file. Failed programs are never candidates (D7).

### D20. When no program works [later] *(new with SE)*
- **v1**: cannot happen: the initial program must work.
- **OE**: selection carries on among failed programs (fitness 0).
- **SE**: "fix mode": a random incorrect program becomes the parent, its ancestors are shown, and
  the prompt asks the LLM to fix it from its stdout and stderr.
- **Options**: refuse to start, and treat "nothing works" as impossible (v1) · a fix mode (SE).
- **Lean**: refuse to start, as v1 does: the initial program must work, so a working parent always
  exists. Revisit if you want runs that start from a broken or LLM-written program.
- **Decision**: No fix mode: failed programs are never parents (D7), so the initial program must work and the run refuses to start otherwise, as in v1.

### D21. The elite archive [later] *(new with SE)*
- **v1**: none stored; the 10 best are computed when needed.
- **OE**: a set of up to 100 elites, updated as programs arrive; MAP-Elites displacement swaps members.
- **SE**: up to 40 correct programs; a better newcomer replaces the worst member (`fitness`) or
  the member most similar to it by embedding (`crowding`); ranking can weigh several criteria.
- **Options**: computed on demand (top k by score) · stored and updated on arrival · crowding
  replacement · several criteria.
- **Lean**: computed on demand, top k by score, k configurable: always correct, and nothing to
  keep consistent on resume. Crowding only if embeddings are adopted (D24).
- **Decision**: Computed on demand (top k by score, default k=10).

### D22. Forgetting programs [later]
- **v1**: every program kept forever, in memory and on disk.
- **OE**: a population limit deletes the worst programs that own no cell; displaced cell owners
  are deleted; checkpoints lose them.
- **SE**: every program kept forever.
- **Options**: keep all · cap what selection sees, keep all on disk · delete.
- **Lean**: keep all on disk; let selection ignore what it does not need (the archive and the
  parent rule already do).
- **Decision**: Keep all on disk.

### D23. Islands [later, if D16 uses islands]
- **OE**: 5 islands; the initial program only in island 0, others filled by its descendants;
  children go to the island the iteration was scheduled for; ring migration of the top 10% every
  50 programs, as copies.
- **SE**: 2 islands; the initial program copied into every island; children stay on their parent's
  island; an island drawn uniformly per proposal; every 10 generations, random non-best programs
  *move* to a random island (off by default); optionally a new island when the search stagnates.
- **Options to settle**: number of islands · seeding (initial program copied to every island, or
  not) · scheduling (round-robin, uniform, least busy) · migration (topology, interval, how many,
  copy or move, which programs) · new islands on stagnation.
- **Lean**: initial program in every island; island drawn uniformly; ring migration of each
  island's best every N iterations, as copies; no new islands for now.
- **Decision**: An island's population is its grid's elites (the best program of each occupied cell): every program stays in the database with the island it was made on (D22), but a program that loses its cell leaves the island's population. Defaults: 3 islands; the initial program copied into every island; children stay on their parent's island; the island for each iteration drawn uniformly; every 25 iterations, 10% of each island's elites (at least one), drawn at random from all its elites except its best, are copied to every other island, where a copy takes its cell only if the cell is empty or holds a worse elite; copies are not re-evaluated and do not count as iterations; no new islands. Modifiable in the problem file: the number of islands, the migration interval N (in iterations), the share of elites that migrate, which ones (best, random, or random non-best), where they go, and whether they are copied or moved.

### D24. Duplicates and near-duplicates [later]
- **v1**: none.
- **OE**: optional embeddings plus an LLM "novel or not" judge, *after* evaluation.
- **SE**: optional, *before* evaluation: a proposal too similar (by embedding) to its island's
  programs is judged by an LLM and, if rejected, regenerated; no evaluation is spent on it.
- **Options**: none · reject exact or AST-identical code anywhere in the database (D13) ·
  embeddings with a similarity threshold, before evaluation · plus an LLM judge.
- **Lean**: AST-identical rejection from the start; SE-style embedding rejection as a later
  optional step (Ollama serves embedding models too), without the LLM judge at first.
- **Decision**: Only the parent check of D13 (a child AST-identical to its parent is rejected); no check against the rest of the database, no embeddings.

---

## 5. The prompt

### D25. Message structure [later]
- **v1**: one user message.
- **OE**: system message (role) plus user message.
- **SE**: system message (task, recommendations, reply format) plus user message; repairs continue
  the conversation (D14).
- **Options**: one message · system message for the fixed rules (role, reply format, allowed
  packages), user message for the problem and the programs · multi-turn for repairs.
- **Lean**: system + user, multi-turn only for repairs.
- **Decision**:

### D26. Programs shown besides the parent [now]
- **v1**: none.
- **OE**: top programs of the island, "diverse" ones, inspirations from nearby cells, "previous
  attempts" (which are really top programs).
- **SE**: one archive program and one of the island's top programs by default, with code and
  metrics, ordered worst to best so the best sits closest to the task; ancestors in fix mode.
- **Options**, any combination: top k by score · archive members · programs from other cells or
  islands · the parent's ancestors with their scores and changes · the parent's recent failed
  children with their errors. And their order.
- **Lean**: a few programs (2 to 4, configurable) from the archive and the parent's island, worst
  to best as SE does; the parent's lineage as a short list of names and scores (D15).
- **Decision**: Partly decided: inspirations include both working programs (positive) and failed ones (negative), each shown with its feedback and, for a failed one, its error (D10). Which programs, how many, and in what order: to be decided.

### D27. What the prompt says about scores [later]
- **v1**: the parent's score.
- **OE**: fitness, feature coordinates, metrics, "fitness improved / declined" hints.
- **SE**: score and public metrics for the parent and every program shown; private metrics withheld.
- **Options**: parent score · plus best score so far · plus metrics · plus feedback (D10) · plus hints.
- **Lean**: score, best score so far, metrics and feedback; no canned hints.
- **Decision**:

### D28. Advice drawn from the whole run [later] *(new with SE)*
- **v1**, **OE**: none: each prompt knows only the programs it shows.
- **SE**: "meta recommendations": every 10 generations an LLM summarises recent programs, keeps a
  running list of insights, and writes recommendations, one of which goes into every system
  prompt. Off unless a model is set for it.
- **Options**: none · periodic summary and recommendations by an LLM · the same, written by hand
  into the description (D4) between runs.
- **Lean**: none at first; a good later step once lineages and change descriptions (D15) are
  stored, since the summary is built from them.
- **Decision**:

### D29. Where templates live [later]
- **v1**: one string in `prompt_sampler.py`.
- **OE**: text files, overridable by the user, random wording variations.
- **SE**: Python strings, one module per change format; the system prompt can be evolved (section 14).
- **Options**: Python constants · text files in the package · user-overridable per problem.
- **Lean**: Python constants in one module; no random wording variations (SE's rewrite strategies
  are a different thing, covered by D11).
- **Decision**:

### D30. Prompt size [later]
- **v1**: unbounded (Ollama silently truncates long prompts).
- **OE**: artifacts truncated to 20 KB; nothing else bounded.
- **SE**: logs shown in fix prompts can be truncated (`max_stdout_log_chars`); nothing else bounded.
- **Options**: no limit · a character budget, dropping context programs first · a token count.
- **Lean**: a character budget with a warning.
- **Decision**:

---

## 6. The LLM

### D31. One model or several [now]
- **v1**: one model.
- **OE**: weighted ensemble, one model drawn per call with fixed weights.
- **SE**: a pool, with a bandit (UCB) choosing the model per proposal from how much its children
  improved on their parents, optionally weighed against cost.
- **Options**: one · several with fixed weights (OE) · several chosen by a bandit (SE).
- **Lean**: one model, behind an `LLM` interface that a pool can implement later; if several
  models come, SE's bandit rather than fixed weights, since it learns which model is worth its price.
- **Decision**:

### D32. Client and providers [later]
- **v1**: synchronous `openai` client; any OpenAI-compatible server.
- **OE**: async `openai` client, plus CLI-based providers.
- **SE**: each provider's own SDK, local OpenAI-compatible servers, and coding agents through a CLI.
- **Options**: OpenAI-compatible only · plus the native Anthropic SDK · plus others.
- **Lean**: OpenAI-compatible, synchronous (threads suffice, D36), behind the `LLM` interface.
- **Decision**:

### D33. Generation settings [later]
- **v1**: `max_tokens` only.
- **OE**: temperature, top_p, max_tokens, seed, reasoning_effort; omits temperature when unset
  because some models reject it.
- **SE**: a temperature drawn per call from a list (`[0.0, 0.5, 1.0]`), a reasoning effort drawn from
  a list, per-model rules.
- **Options**: which to expose · whether unset means "not sent" · a fixed value or a list drawn per call.
- **Lean**: `max_tokens`, plus optional temperature and reasoning effort, not sent when unset; a
  temperature may be a list drawn per call (cheap diversity).
- **Decision**:

### D34. Retries, timeouts, LLM failures [later]
- **v1**: the `openai` package's 2 retries, 300 s; 3 failed iterations in a row stop the run.
- **OE**: its own 3 retries on top of the package's, 60 s; never stops for failures.
- **SE**: exponential backoff up to 20 tries, 1,200 s, the SDKs' own retries off; a "stuck" detector.
- **Lean**: keep v1's behaviour: one layer of retries, and a stop after N failures in a row.
- **Decision**:

### D35. Cost accounting and budget [later] *(new with SE)*
- **v1**: nothing recorded; iterations and `--max-reply-tokens` bound the cost.
- **OE**: tokens recorded per call and summed.
- **SE**: the dollar cost of every call (LLM, embeddings, judges), priced from a catalog refreshed
  online at start-up; `max_api_costs` stops new proposals at a dollar budget.
- **Options**: nothing · tokens recorded · tokens plus prices per model given in the config ·
  online price catalog · a budget in tokens or dollars.
- **Lean**: record tokens per call from the start (they cost nothing to store); prices per model in
  the config and a dollar budget as a later step; no online catalog.
- **Decision**:

---

## 7. The loop

### D36. Iterations in parallel [now]
- **v1**: threads; parent chosen in the main thread when an iteration starts.
- **OE**: processes, a snapshot of the whole population pickled per iteration.
- **SE**: asyncio, with separate limits for proposals, evaluations and database work, and an
  optional controller that keeps extra proposals ready when the LLM is the bottleneck.
- **Options**: threads · processes · asyncio · one pool · separate limits for LLM calls and for evaluations.
- **Lean**: threads, as in v1: the work is waiting on the LLM and on containers. One pool first;
  separate limits as a later step if evaluations and LLM calls turn out to need different numbers.
- **Decision**:

### D37. When a run stops [later]
- **v1**: iteration count, Ctrl+C, 3 LLM failures in a row.
- **OE**: plus target score and early stopping (patience).
- **SE**: a total number of generations, a dollar budget, a stuck detector.
- **Options**, any combination: iterations · target score · no improvement for N iterations ·
  wall-clock time · token or dollar budget (D35).
- **Lean**: iterations, target score, patience; a budget once D35 records costs.
- **Decision**:

### D38. Errors inside an iteration [later]
- **v1**: only `LLMError` is handled; any other exception ends the run (Part D, v1 item 7).
- **OE**: every error is recorded and the run continues.
- **SE**: every failure is recorded (with its stage and reason) and the run continues.
- **Options**: crash · record and continue · record, and stop after N infrastructure errors in a row.
- **Lean**: record and continue; N errors of any kind in a row stop the run.
- **Decision**:

### D39. Randomness [later]
- **v1**: own `random.Random`, no default seed; re-seeded identically on resume (Part D, v1 item 9).
- **OE**: global `random` and `numpy`, default seed 42.
- **SE**: no seed at all.
- **Options**: default seed or none · on resume, restore the generator's state or derive a new seed
  from the seed and the number of programs.
- **Lean**: own generator, no default seed; derive the seed on resume. Every random draw (parent,
  island, change format, temperature) goes through that one generator.
- **Decision**:

---

## 8. Running programs safely

### D40. Isolation [now]
- **v1**: a new Docker container per evaluation (about 1 s each); no way to run without Docker.
- **OE**: none of its own.
- **SE**: a new process per evaluation, locally (no isolation) or as a Slurm cluster job (in a
  conda environment or in Docker).
- **Options**: container per evaluation · one long-lived container per worker, a fresh process per
  evaluation inside it · local subprocess with OS limits (no Docker) · a backend interface with
  several of these · cluster backends.
- **Lean**: a backend interface; Docker per evaluation as the default; a local subprocess backend
  marked unsafe, for tests and trusted problems. No cluster backend.
- **Decision**:

### D41. Limits [later]
- **v1**: no network, read-only, 1 GB, 1 CPU, 64 processes, 30 s, fixed in the code except the timeout.
- **SE**: none locally, apart from optional caps on the threads of numeric libraries
  (`OMP_NUM_THREADS` and similar); the time limit adapts to the average evaluation time.
- **Options**: which are settings, and whether per problem or per run · thread caps for numpy and
  friends · fixed or adaptive time limit.
- **Lean**: v1's values, as problem settings, plus SE's thread caps set to the container's CPU
  count (numpy otherwise starts as many threads as the host has cores); a fixed time limit.
- **Decision**:

### D42. Containers that outlive the run [later]
- **v1**: possible (Part D, v1 item 2).
- **SE**: the clean-up does not stop running evaluations either (Part D, SE item 4).
- **Options**: label containers with the run's id and remove them on exit and on the next start ·
  a time limit inside the container too · both.
- **Lean**: both.
- **Decision**:

---

## 9. Configuration and interface

### D43. How a run is configured [now]
- **v1**: CLI flags only.
- **OE**: a YAML file plus CLI overrides; unknown keys silently ignored.
- **SE**: the same dataclasses reached three ways: the Python API, Hydra presets, or a task-folder
  CLI with an optional YAML and `--set key=value` overrides.
- **Options**: CLI only · config file only · config file plus CLI overrides · a problem file for
  the problem's own facts (description, timeout, limits, packages, features) plus CLI flags for
  the run's choices (model, iterations, workers, output, seed) · generic `--set` overrides (SE).
- **Lean**: a problem file plus CLI flags: a problem folder is complete on its own, and a run is
  one command line. No presets.
- **Decision**: A YAML problem file for the problem's own facts (description, evaluation settings, limits, packages, cascade thresholds) plus CLI flags for the run's choices.

### D44. Config file format and validation [later, if D43 uses a file]
- **OE**, **SE**: YAML. OE ignores unknown keys; SE's CLI rejects them.
- **Options**: YAML (needs `pyyaml`) · TOML (`tomllib`, built into Python 3.11+) · JSON.
  Unknown keys: ignored · error.
- **Lean**: TOML; unknown keys are an error; loaded into dataclasses by hand.
- **Decision**: YAML; unknown keys are an error; loaded into dataclasses.

### D45. Command line [later]
- **v1**: `python scripts/run.py INITIAL_PROGRAM EVALUATION_FILE --model ...`.
- **OE**: `openevolve-run INITIAL_PROGRAM EVALUATOR --config ...`.
- **SE**: `shinka_run --task-dir FOLDER --results_dir ... --num_generations ...`.
- **Options**: two file paths · a problem folder · a script · a console command (`my-evolve run
  examples/circle_packing`) · `python -m my_evolve`.
- **Lean**: a problem folder, as SE does; a console command and `python -m`.
- **Decision**:

### D46. API key [later]
- **v1**: read from the variable named by `--api-key-env`.
- **OE**: in the YAML, through `${VAR}`, or `OPENAI_API_KEY`.
- **SE**: each provider's usual variable, also read from `.env` files; a start-up check that every
  model has credentials.
- **Lean**: keep v1's way; never in a file; check at start-up that the variable is set when the
  server is not local.
- **Decision**:

---

## 10. Saving and continuing runs

### D47. Storage format [now]
- **v1**: append-only `programs.jsonl`.
- **OE**: a JSON file per program, full snapshot every N iterations.
- **SE**: a SQLite file written as programs arrive, plus a folder per generation.
- **Options**: JSONL · per-program files and snapshots · SQLite · a folder per program alongside any of them.
- **Lean**: JSONL: nothing evaluated is ever lost, and it is readable with any tool. SQLite is the
  strong alternative if you want to query runs or serve a viewer from them.
- **Decision**:

### D48. What is saved for each program [later]
- **v1**: id, parent, generation, iteration, score, code.
- **OE**: also metrics, artifacts, prompts and reply, diff summary, island, token usage, timestamp.
- **SE**: also correctness, public and private metrics, feedback, the change's name and description,
  the inspirations used, model and costs, timings, logs, and every attempt's reply in the generation's folder.
- **Options**: which fields · prompts and replies in the same file or a separate one · failed
  attempts (D14) kept or not.
- **Lean**: everything above plus status, error, timings and tokens; prompts and replies (failed
  attempts included) in a separate `llm_calls.jsonl` so `programs.jsonl` stays readable. Failures as
  `score: null` + status, never `-Infinity`.
- **Decision**:

### D49. Continuing a run [now]
- **v1**: same `--output`; the database is rebuilt by re-adding the saved programs; `--iterations`
  means that many *more*.
- **OE**: `--checkpoint DIR`; the database state is reloaded from the snapshot; also "more".
- **SE**: same results folder; state is in SQLite; `num_generations` is the *total*, so rerunning
  the same command finishes the original target.
- **Options**: replay the saved programs · load a snapshot. And: is the iteration count a total or
  "that many more"?
  With islands, replay needs every decision that is not recomputable (island of each
  program, migrations) to be saved too.
- **Lean**: replay, with island and migration events in the log; the count is a total, as in SE,
  so that rerunning the same command after a crash does not extend the run.
- **Decision**:

### D50. Run information and safety checks [later]
- **v1**: nothing; a different problem in the same folder goes unnoticed.
- **SE**: saves the price catalog and the bandit state with the run; does not notice a changed problem either.
- **Options**: save the settings and a fingerprint of the problem files in `run.json`; on resume,
  refuse (or warn) if the problem changed, allow changing the model and iteration count.
- **Lean**: save them; refuse on a changed problem.
- **Decision**:

### D51. Outputs for people [later]
- **v1**: `best_program.py` with a header.
- **OE**: best program and its info file, logs, web visualizer.
- **SE**: a `best/` folder, a WebUI over the SQLite file, plotting functions (lineage tree, costs,
  Pareto front), optional W&B.
- **Options**: best program · a summary at the end · a score-over-time table or plot · a lineage view.
- **Lean**: best program and end summary now; a small report script later.
- **Decision**:

---

## 11. Logging and console

### D52. Logging [later]
- **v1**: `print()`, one line per iteration.
- **OE**: `logging`, many lines per iteration, a log file per run.
- **SE**: `logging` with Rich tables on the console and a log file in the results folder.
- **Options**: `print` · `logging` with a short console format and a detailed log file in the output folder.
- **Lean**: `logging`: one line per iteration on the console, details in the file.
- **Decision**:

---

## 12. Stopping

### D53. First Ctrl+C [later]
- **v1**: nothing new starts; iterations in progress finish and are saved.
- **OE**: iterations in progress are abandoned; nothing since the last checkpoint is saved.
- **SE**: not handled: work in progress is abandoned; everything finished is already in SQLite.
- **Lean**: keep v1's behaviour.
- **Decision**:

### D54. Second Ctrl+C and SIGTERM [later]
- **v1**: the second Ctrl+C still waits for running threads (Part D, v1 item 1); SIGTERM not handled.
- **OE**: `sys.exit(0)`; SIGTERM handled like the first Ctrl+C.
- **SE**: neither handled.
- **Options**: what each one does · how running containers and threads are stopped.
- **Lean**: both exit within seconds: running containers are killed, threads not waited for,
  everything already finished is already on disk.
- **Decision**:

### D55. Platforms [now]
- **v1**: Windows first (PowerShell docs, UTF-8 output, Ctrl+C wake-up), Linux and macOS too.
- **OE**, **SE**: Linux and macOS (SE also Slurm clusters).
- **Options**: Linux only · Linux and macOS · all three, with Windows docs.
- **Lean**: depends on where you will run it; this machine is Linux. Keeping the code portable costs little;
  Windows-specific docs and tests cost more.
- **Decision**:

---

## 13. The project itself

### D56. Name, layout, Python version [now]
- **v1**: `src/my_alphaevolve/`, Python 3.10+.
- **OE**, **SE**: flat package folders, Python 3.10+.
- **Options**: `src/my_evolve/` · Python 3.10, 3.11 (for `tomllib`) or 3.12.
- **Lean**: `src/my_evolve/`, Python 3.11+.
- **Decision**:

### D57. Tools [later]
- **v1**: ruff (lint and format), mypy strict, `unittest`, a fake LLM HTTP server, Docker tests
  skipped without Docker.
- **OE**: black, isort, `unittest` and `pytest`, integration tests against a small local model.
- **SE**: ruff, `pytest`, live-provider tests marked and skipped without secrets.
- **Options**: keep v1's tools · `pytest` instead of `unittest` (shorter tests, fixtures).
- **Lean**: keep ruff and mypy strict; your choice between `unittest` and `pytest`.
- **Decision**:

### D58. Code style [later]
- **v1**: explanatory plain-English docstrings and comments everywhere.
- **Lean**: keep it; it serves the goal of understanding the code.
- **Decision**:

### D59. How we work through the plan [now]
- **Options**: step size (one class or one behaviour per step) · who writes the code (I write and
  explain, or you write and I review) · tests in every step · one commit per step · a run of an
  example at the end of each milestone.
- **Lean**: small steps, each runnable and tested, one commit each; I explain the design of a
  step before writing it.
- **Decision**:

---

## 14. Smaller features: yes or no

Each one is a self-contained step that can be added late. [later] for all.

| Feature | v1 | OE | SE | Lean |
|---|---|---|---|---|
| Target score stop (D37) | no | yes | no | yes |
| Early stopping on no improvement (D37) | no | yes | no | yes |
| Token usage recorded and summed (D35) | no | yes | yes | yes |
| Token or dollar budget stop (D35) | no | no | yes (dollars) | later |
| Code-length limit (D13) | no | yes | no | yes |
| Arguments passed to the evaluator from the config | no | yes | yes | no |
| LLM-as-judge scores | no | yes | no | no |
| Embedding-based novelty filter (D24) | no | yes | yes | later |
| Random wording variations in prompts | no | yes | no | no |
| Per-island system messages | no | yes | no | no |
| "Changes description" mode for large codebases | no | yes | no | no |
| Several LLM providers besides OpenAI-compatible | no | yes | yes | no |
| Human-in-the-loop "manual mode" | no | yes | no | no |
| Library API usable from a notebook | partly | yes | yes | yes, a single `run(...)` |
| Evolution trace for RL training | no | yes | no | no (D48 covers analysis) |
| Web visualizer | no | yes | yes | later, maybe |
| Crossover of two programs (D11) | no | no | yes | later |
| Several full-rewrite strategies drawn at random (D11) | no | no | yes | later |
| LLM writes the initial program | no | no | yes | no |
| Evolving the system prompt itself | no | no | yes | no |
| New islands when the search stagnates (D23) | no | no | yes | no |
| Public and private metrics (D6) | no | no | yes | no |
| Repeated runs with statistical early stop in the evaluator (D9) | no | no | yes | no |
| Plots saved per program by the evaluator | no | no | yes | no |
| Slurm cluster backends (D40) | no | no | yes | no |
| Weights & Biases logging | no | no | yes | no |
| Hydra presets (D43) | no | no | yes | no |
| Skills that teach a coding agent to set up and run tasks | no | no | yes | no |
