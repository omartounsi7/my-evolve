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
- **Decision**: Runs must stay comparable to openevolve's, on function minimization and circle packing. The initial programs are openevolve's code, unchanged, EVOLVE-BLOCK markers included (D12). Evaluators take a namespace (D5) but must score every program exactly as openevolve's evaluators do, with the same cascades (D9). Reference: the openevolve checkout `da3d701`, whose function-minimization evaluator recomputes the value from (x, y) instead of trusting the program (Part D, v1 item 4). Comparable means: every program that works gets the same score as in openevolve, so best-score curves can be compared. Programs that fail or are invalid differ: openevolve scores them 0 and lets them into its grid, here they have no score and stay out (D7), so average scores and failure counts are not comparable.

---

## 2. The problem and its evaluation

### D4. Where the problem description lives [later]
- **v1**: required docstring of the initial program (A1).
- **OE**: `prompt.system_message` in the YAML.
- **SE**: `task_sys_msg` in the config, used as the system message.
- **Options**: docstring · a field of a problem config file · a separate `description.md` in the problem folder.
- **Lean**: a separate file: descriptions grow long (circle packing's lists geometric insights), and it
  keeps the initial program a plain program.
- **Decision**: The description is a field of the problem file (YAML), as in openevolve (D43, D44). It states the contract the program must keep (the entry functions, their arguments and return values); the evolve blocks already protect the code outside them (D12), but the LLM should still know what that code expects.

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
- **Decision**: A result object holding: `score` (a number; only `ok` programs have one, D7); `status` and `error` (whether the program failed, how, and why, D7); `metrics` (named numbers about the run); `features` (named numbers describing the program's output, for the MAP-Elites grid, D17; kept apart from `metrics` so they never affect the score); `feedback` (text for the LLM, D10); `output_data` (plain data the program returned that the evaluator chooses to keep, such as a packing's centres and radii, saved for the report's drawings, D48, D51); the evaluation's duration; the cascade stage reached (D9). There is no separate correctness flag: a program is correct when its `status` is `ok`, which is computed from the status, so the two can never disagree. Implemented as the `Result` dataclass (D60 holds it in `Program.result`); a program's output features live in `result.features`.

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
  - `rejected`: before evaluation, on the host. The child failed a check of D13 and was never run (a syntax error, which includes a reply with no code; a change outside the evolve blocks, or to their markers; a required entry function missing; or the same program as one already in the database).
  - `failed`: during evaluation. The program raised an exception while loading or while one of its functions ran (`ImportError`, `IndexError` in `run_packing`, a wrong return type). An entry function missing only at run time (defined, then deleted) is `failed` too, never `invalid`.
  - `timeout`: during evaluation. A cascade stage exceeded its time limit (60 s per stage for our two problems, as openevolve gives each stage its own limit), or a call exceeded its own limit (D8) and the evaluator did not handle it; the container was killed. A slow call that the evaluator handles is up to the evaluator: function minimization's stage 2 skips a trial over 5 s and scores the others (status `ok`), its stage 1 reports `timeout`, since its only call gave no answer.
  - `invalid`: after evaluation. The program returned an answer that the evaluator judged illegal (overlapping circles, a negative radius, a circle outside the square). openevolve scores such programs 0; here the evaluator says so, with the reason in its feedback.
  - `error`: not the program's fault. The infrastructure failed (Docker did not start, the evaluator itself raised, the disk is full). Such programs do not count as children of their parent (D19), are never shown as negative example programs (D10), and count toward the "errors in a row" stop (D38).

  With the cascade (D9), a program that passes stage 1 and fails or times out in a later stage keeps its stage 1 result: its status is `ok`, with the stage reached recorded. A failed program has an `error` message and no score (`score: None`). Failed programs are stored and saved: they are shown in prompts as negative example programs, with their error (D10, D26), they count in the children count of the parent rule (D19), and they serve analysis and resuming. They are never chosen as parents. Those that have a syntax tree count in duplicate detection (D13), so the same failing program is not evaluated twice; `error` programs do not.

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
- **Decision**: Each program runs in its own sandboxed container (v1's limits). The evaluator runs on the host, in the trusted process: the `namespace` it receives is a stand-in whose functions, when called, run the program's function inside the container and return its result. Results cross the boundary as plain data only (JSON, or numpy arrays without pickle), so the program can choose what its functions return but cannot touch how the score is computed. A time limit can be given for each call made through the namespace, as openevolve's evaluators give `run_search` 5 s: a call that exceeds it raises a timeout error in the evaluator, the container is killed, and the next call starts a fresh container with the program reloaded. Each cascade stage also starts from a freshly loaded program, as openevolve re-imports the program for each stage (D9). Each cascade stage has its own limit as well (D7, D41).

### D9. Cascade evaluation and repeated runs [later]
- **v1**: written inside the user's `evaluate`.
- **OE**: framework-level `evaluate_stage1/2/3` with thresholds in the config.
- **SE**: no cascade; the evaluator helper repeats runs and can stop them early when statistics
  show the program cannot beat a threshold.
- **Options**: inside `evaluate` · framework stages · a helper for repeated runs with early stopping.
- **Lean**: inside `evaluate`: nothing for the framework to know.
- **Decision**: openevolve's cascade. The evaluation file defines `evaluate_stage1(namespace)`, `evaluate_stage2(namespace)`, … (a file with only `evaluate(namespace)` is a one-stage cascade), and the problem file lists the thresholds. A program goes to the next stage only if the previous stage's score reaches its threshold; metrics of later stages overwrite earlier ones; a later stage that fails or times out keeps the earlier stages' result, as in openevolve, while a later stage that finds the answer illegal makes the whole program `invalid`, as openevolve's score of 0 for it overwrites the earlier ones (D65). The result object records the stage reached. Each stage starts from a freshly loaded program (D8). Features always come from stage 1, so every program's features are measured the same way, whichever stage it reached (D17). Cascades of our two problems, copied from openevolve (60 s per stage in both): function minimization: stage 1 = one call of `run_search` (5 s limit), threshold 1.3, stage 2 = 10 calls (5 s each), whose score replaces stage 1's; circle packing: stage 1 = one call of `run_packing`, scored as the sum of the radii divided by 2.635 if the packing is valid, threshold 0.5, stage 2 = openevolve's full evaluation (a second call, scored the same way). openevolve's second circle-packing threshold, 0.75, never applies, since there is no third stage.

### D10. Feedback from the evaluation to the LLM [now]
- **v1**: none; the LLM sees only the parent's score.
- **OE**: artifacts (any text the evaluator returns, or a traceback) shown in the next prompt that
  uses the program as parent.
- **SE**: `text_feedback` from the evaluator (off by default); stdout and stderr shown when fixing a program.
- **Options**: none · `feedback` text from the evaluator (D6) · that, plus the tail of the
  program's stderr captured automatically.
- **Lean**: evaluator feedback plus a captured error for failures, truncated to a size limit.
- **Decision**: An evaluator writes feedback text into the result object (D6) as it checks a program, in the style of openevolve's artifacts (e.g. "Circles 3 and 7 overlap (distance 0.112, radii sum 0.130)", "run_search timed out on trial 4 of 10"); our two examples' evaluators do so for every check they make. The framework adds the error message and the end of the error output when a program crashes or times out. The prompt shows the feedback of the parent and of every example program, and the error of every failed example program, each truncated to a size limit. Example programs are both working programs (positive) and failed ones (negative), D26; the parent is always a working program (D7), so it has feedback but no error, except for an error in a later cascade stage it did not pass (D9), which is shown too.

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
- **Decision**: Full rewrite: the LLM returns the whole file. Inside the evolve blocks it changes as much or as little as it decides, from a single line to everything (D12).

### D12. Which part of the program may change [now]
- **v1**: the whole file.
- **OE**: the whole file, with advisory EVOLVE-BLOCK markers, enforced only on request.
- **SE**: markers required and enforced: diffs outside them are rejected, rewrites replace only
  the blocks' contents, a candidate that lost a marker is rejected.
- **Options**: whole file · markers, advisory · markers, enforced (edits outside are reverted, or
  the child is rejected) · markers, and only the blocks are shown to the LLM.
- **Lean**: markers optional: if the initial program has them, they are enforced as SE does and
  the prompt explains them; otherwise the whole file may change.
- **Decision**: Only the code between `# EVOLVE-BLOCK-START` and `# EVOLVE-BLOCK-END` may change. The initial programs keep openevolve's markers (D3). The prompt tells the LLM explicitly that only the code inside the blocks may change and that the markers must stay where they are. A child that changes anything outside the blocks, or moves, removes, adds or alters a marker, is rejected before evaluation (D13). Unlike openevolve's `enforce_evolve_blocks`, which silently reverts edits made outside the blocks, the child is rejected, so the mistake is recorded and can be shown to the LLM as a negative example program (D7, D10).

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
- **Decision**: Four checks before evaluation, all on the host and without running the program. They apply only to children the LLM writes, never to copies the framework makes (the initial program in each island, migrants, D23). The child must compile (`ast.parse`; a reply with no code fails here); it must keep the evolve blocks exactly where the initial program has them (D12): the same markers, in the same order, with the same code between them outside the blocks. That code is compared line by line after ignoring whitespace that changes nothing: blank lines added or removed, and spaces at the ends of lines (spaces at the start of a line still count, since Python indentation has meaning), so extra whitespace around the blocks is never a reason to reject; its syntax tree must define, at the top level, every entry function the problem file requires (`run_packing`, `run_search`), so the LLM cannot rename or remove them unnoticed (redundant when the entry functions sit outside the blocks, as in our two problems, but kept for problems where they do not); and it must not be a duplicate of any program already in the database (its parent, a grandparent, a sibling, any island). Duplicate means AST-identical: both programs have the same syntax tree, so differences in comments and spacing are ignored; each program's tree is stored as a short fingerprint (a hash), so the check stays instant. The comparison is always between syntax trees, never raw text: it covers every earlier program that has a tree (`ok`, `failed`, `timeout`, `invalid`), and leaves out programs rejected for not compiling (they have no tree) and programs with status `error` (their failure was not theirs, so the same code deserves a new evaluation). Whether a program runs is checked by the evaluation itself: loading it is the first thing the container does, and a program that fails to load is marked failed before any cascade stage. A rejected child is stored with status `rejected` and its reason, and is not evaluated (D7). No diff checks while changes are full rewrites (D11). The checks are plain functions, not a class.

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
- **Decision**: The LLM's reply includes, besides the code, a short description of how the program solves the task (its approach, its main ideas), written so that it stands on its own: it never refers to the parent or to any other program (no "compared to the previous version", no "now uses"), because when the program is later shown as a parent or an example program, the program it came from is usually not in the prompt. The prompt asks for it in these terms (Appendix A). The reply may contain anything else as well (reasoning, comments): only the description and the code are kept (D68). A reply without a description is still accepted if its code is usable. This description is available to prompts (D26) and outputs (D51).

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
- **Decision**: One built-in "code" feature: the number of nodes of the program's syntax tree (`ast.parse`, then `ast.walk`) that lie inside the evolve blocks, found from each node's line numbers, so the fixed code outside the blocks does not dilute the measure (D12); normalized as described in D18; possibly extended later with other measures such as cyclomatic complexity. Plus zero or more "output" features specific to the problem (no upper limit), computed by its evaluator from what the program returns and put in the result's `features` (D6); they are computed from stage 1 of the cascade, even for programs that reach later stages (D9). The problem file names the features a run uses; the default grid is one-dimensional, on the code feature alone. Circle packing, the main experiment, implements two output features, so a run can use either in 2D or both in 3D: the spread of the radii, std(radii) / mean(radii) (0 = all circles the same size; 0 when the mean is 0, which means every radius is 0), and the Pearson correlation (`numpy.corrcoef`) between each circle's radius and the distance from its centre to the centre of the square, (0.5, 0.5) (−1 = big circles in the middle, +1 = big circles at the edges; 0 when the radii or the distances are all equal, since the correlation is then undefined). Both are computed only for `ok` programs (D7). Function minimization: a one-dimensional grid for now; output features to be chosen later. Failed programs have no features and never enter a grid (D7).

### D18. Binning features into cells [later, if D16 uses a grid]
- **v1** (`aeaf384`): grid rebuilt from all programs at each sample, so bins always span the values seen.
- **OE**: running min/max at insertion; bins drift and old placements are never recomputed.
- **Options**: rebuild at each sample · running min/max (OE) · fixed ranges declared by the problem.
- **Lean**: rebuild at each sample: always consistent, and cheap for thousands of programs.
- **Decision**: A fixed grid, known when the run starts and never changed: the problem file gives each feature a range and a number of bins, all modifiable; a value outside the range goes to the nearest end bin. The code feature is normalized against the initial program: log2(nodes inside the blocks / nodes inside the initial program's blocks), default range −1 to +3 (half to eight times the initial size), the same for every problem. Circle packing defaults: radii spread 0 to 1, correlation −1 to +1. Grids stay small, since runs last hundreds of iterations, not thousands. Default bins: 10 for a 1D grid, 5 × 5 for 2D, 3 × 3 × 3 for 3D. To revisit if CVT MAP-Elites is adopted (D16).

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
- **Decision**: ShinkaEvolve's weighted rule as the primary strategy: pick an island, then a parent among the island's grid elites (the best program of each occupied cell) with weight sigmoid(λ × (score − median) / spread) × 1 / (1 + number of children), where the median and the spread are those of the island's elites. The spread is their median absolute deviation, as in ShinkaEvolve, or their standard deviation if that is 0; if both are 0, every elite's score term is 0.5. (ShinkaEvolve only floors the spread at 1e-6: with few elites, two of them tied, the others' weights then jump to almost 0 or 1 whatever λ is.) λ is set in the problem file, and experiments will use values lower than ShinkaEvolve's 10, so that one niche does not take every draw; default λ = 1. "Number of children" counts every child the program has had, whatever its outcome (`failed`, `timeout`, `invalid` and `rejected` children included, since each cost an LLM call), except children with status `error`, which were not the parent's fault (D7); a migrated copy starts at 0 in its new island, a moved program keeps its count (D23). Counting only successful children as a separate productivity term is a possible later experiment. openevolve's rule, adapted to grids, as a secondary strategy: 20% a uniform draw among the island's grid elites, 70% a random member of the archive (the global top k, D21), preferring this island's, 10% a draw among the island's grid elites weighted by score. It sits behind the same interface, chosen in the problem file. Failed programs are never candidates (D7).

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
- **Decision**: An island's population is its grid's elites (the best program of each occupied cell): every program stays in the database with the island it was made on (D22), but a program that loses its cell leaves the island's population. Defaults: 3 islands; the initial program copied into every island; a child lives on its iteration's island, which is its parent's island (only openevolve's archive branch can draw a parent from elsewhere, D75); the island for each iteration drawn uniformly; every 25 iterations, 10% of each island's elites (at least one), drawn at random from all its elites except its best, are copied to every other island, where a copy takes its cell only if the cell is empty or holds a worse elite; copies are not re-evaluated and do not count as iterations; no new islands. Modifiable in the problem file: the number of islands, the migration interval N (in iterations), the share of elites that migrate, which ones (best, random, or random non-best), where they go, and whether they are copied or moved (a moved program goes to the first destination only, since it can be in one place).

### D24. Duplicates and near-duplicates [later]
- **v1**: none.
- **OE**: optional embeddings plus an LLM "novel or not" judge, *after* evaluation.
- **SE**: optional, *before* evaluation: a proposal too similar (by embedding) to its island's
  programs is judged by an LLM and, if rejected, regenerated; no evaluation is spent on it.
- **Options**: none · reject exact or AST-identical code anywhere in the database (D13) ·
  embeddings with a similarity threshold, before evaluation · plus an LLM judge.
- **Lean**: AST-identical rejection from the start; SE-style embedding rejection as a later
  optional step (Ollama serves embedding models too), without the LLM judge at first.
- **Decision**: The check of D13: a child AST-identical to any program already in the database is rejected; no embeddings.

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
- **Decision**: System message plus user message. The system message holds everything that stays the same for a whole run: the instruction, the problem description, the rules (evolve blocks, allowed packages, higher is better) and the reply format; providers cache a repeated prompt start, so it is paid for fully only once, and the model reads it as standing instructions. The user message holds what changes each iteration: the example programs, then the parent, then the request. One call per iteration, no multi-turn conversation (no repair, D14). The templates are in Appendix A.

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
- **Decision**: Besides the parent, the prompt shows a number of other programs, called example programs ("inspirations" in openevolve and ShinkaEvolve), set in the problem file, 2 by default. They are working programs and failed ones alike, presented without any "positive" or "negative" label: the prompt calls them previous attempts, and the LLM judges from each one's score or status, description, feedback and, for a failed one, its error (D10) whether to follow it. They are drawn at random from every program made on the parent's island (each program records its island, D60, D22): not only its grid's elites, which never include failed programs (D23), but also its failed programs and the working ones that lost their cell. The parent itself, programs with status `error` (D7) and children rejected for having no code are never drawn. They are shown in the order they were drawn.

### D27. What the prompt says about scores [later]
- **v1**: the parent's score.
- **OE**: fitness, feature coordinates, metrics, "fitness improved / declined" hints.
- **SE**: score and public metrics for the parent and every program shown; private metrics withheld.
- **Options**: parent score · plus best score so far · plus metrics · plus feedback (D10) · plus hints.
- **Lean**: score, best score so far, metrics and feedback; no canned hints.
- **Decision**: That higher scores are better; for the parent and every working example program, its score; for the parent, also the best score reached so far in the run; for a failed example program, its status instead of a score. Metrics are not shown (feedback carries what the evaluator wants the LLM to know, D10); no canned hints. The time limit and the sandbox's memory and CPU are not mentioned.

### D28. Advice drawn from the whole run [later] *(new with SE)*
- **v1**, **OE**: none: each prompt knows only the programs it shows.
- **SE**: "meta recommendations": every 10 generations an LLM summarises recent programs, keeps a
  running list of insights, and writes recommendations, one of which goes into every system
  prompt. Off unless a model is set for it.
- **Options**: none · periodic summary and recommendations by an LLM · the same, written by hand
  into the description (D4) between runs.
- **Lean**: none at first; a good later step once lineages and change descriptions (D15) are
  stored, since the summary is built from them.
- **Decision**: None.

### D29. Where templates live [later]
- **v1**: one string in `prompt_sampler.py`.
- **OE**: text files, overridable by the user, random wording variations.
- **SE**: Python strings, one module per change format; the system prompt can be evolved (section 15).
- **Options**: Python constants · text files in the package · user-overridable per problem.
- **Lean**: Python constants in one module; no random wording variations (SE's rewrite strategies
  are a different thing, covered by D11).
- **Decision**: Python constants in one module, filled with `str.format`; their text is Appendix A. No random wording variations.

### D30. Prompt size [later]
- **v1**: unbounded (Ollama silently truncates long prompts).
- **OE**: artifacts truncated to 20 KB; nothing else bounded.
- **SE**: logs shown in fix prompts can be truncated (`max_stdout_log_chars`); nothing else bounded.
- **Options**: no limit · a character budget, dropping context programs first · a token count.
- **Lean**: a character budget with a warning.
- **Decision**: Character budget with a warning in the logs.

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
- **Decision**: Like openevolve: a weighted ensemble, one model drawn per call with fixed weights, using the run's own random generator (D39). The models are listed in the `llm` section of the problem file (D43).

### D32. Client and providers [later]
- **v1**: synchronous `openai` client; any OpenAI-compatible server.
- **OE**: async `openai` client, plus CLI-based providers.
- **SE**: each provider's own SDK, local OpenAI-compatible servers, and coding agents through a CLI.
- **Options**: OpenAI-compatible only · plus the native Anthropic SDK · plus others.
- **Lean**: OpenAI-compatible, synchronous (threads suffice, D36), behind the `LLM` interface.
- **Decision**: OpenAI-compatible, synchronous (threads suffice, D36), behind the `LLM` interface. Each model has its own server address, so models of several providers can be mixed through their OpenAI-compatible endpoints. OpenAI's reasoning models are supported: they refuse `max_tokens` and temperature, and need `max_completion_tokens` instead. Each model has a `reasoning` setting; unset, it is guessed from the name with openevolve's list of prefixes (`o1`, `o3`, `o4`, `gpt-5`, `gpt-oss`); set, it overrides the guess for names the list does not know. For a reasoning model the token limit is sent as `max_completion_tokens`, and a configured temperature is an error at start-up rather than a failure at every call.

### D33. Generation settings [later]
- **v1**: `max_tokens` only.
- **OE**: temperature, top_p, max_tokens, seed, reasoning_effort; omits temperature when unset
  because some models reject it.
- **SE**: a temperature drawn per call from a list (`[0.0, 0.5, 1.0]`), a reasoning effort drawn from
  a list, per-model rules.
- **Options**: which to expose · whether unset means "not sent" · a fixed value or a list drawn per call.
- **Lean**: `max_tokens`, plus optional temperature and reasoning effort, not sent when unset; a
  temperature may be a list drawn per call (cheap diversity).
- **Decision**: `max_tokens` (default 16,384, so a reasoning model's hidden thinking does not use up the whole reply), plus an optional `temperature` and an optional `reasoning_effort` (reasoning models only), each sent only when set (some models reject a temperature). All three can be set for the whole `llm` section or per model, as in openevolve. One name, `max_tokens`, replaces v1's `--max-reply-tokens`.

### D34. Retries, timeouts, LLM failures [later]
- **v1**: the `openai` package's 2 retries, 300 s; 3 failed iterations in a row stop the run.
- **OE**: its own 3 retries on top of the package's, 60 s; never stops for failures.
- **SE**: exponential backoff up to 20 tries, 1,200 s, the SDKs' own retries off; a "stuck" detector.
- **Lean**: keep v1's behaviour: one layer of retries, and a stop after N failures in a row.
- **Decision**: One layer of retries (the `openai` package's own, 2 by default) and a per-model timeout (default 300 s, longer for slow local or reasoning models). Before the first iteration, a start-up check sends a one-line request to every model with its own settings; any failure (wrong name, key or address) stops the run at once. During the run, failures are counted per model: a model that fails 3 times in a row (the default, settable) is dropped for the rest of the run, with a warning, and the others' weights are renormalized; the run stops when no model is left. An iteration whose LLM call failed is skipped but still counts toward the iteration total, and is recorded in the run's log. These LLM failures have their own counter, separate from D38's counter of infrastructure errors.

### D35. Cost accounting and budget [later] *(new with SE)*
- **v1**: nothing recorded; iterations and `--max-reply-tokens` bound the cost.
- **OE**: tokens recorded per call and summed.
- **SE**: the dollar cost of every call (LLM, embeddings, judges), priced from a catalog refreshed
  online at start-up; `max_api_costs` stops new proposals at a dollar budget.
- **Options**: nothing · tokens recorded · tokens plus prices per model given in the config ·
  online price catalog · a budget in tokens or dollars.
- **Lean**: record tokens per call from the start (they cost nothing to store); prices per model in
  the config and a dollar budget as a later step; no online catalog.
- **Decision**: Record the tokens of every call from the start (they cost nothing to store), with each program (D60). Optional prices per model in the `llm` section (per million input and output tokens) are used only to report the cost of each program and the run's total; there is no budget: the iteration count and `max_tokens` bound the cost.

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
- **Decision**: Threads, as in v1, with at most `workers` iterations at once (a CLI flag, default 1). Each iteration has two parts run in a worker thread, with the main thread in between: the main thread picks the island, the parent and the example programs and builds the prompt (D19, D26, D67); a worker asks the LLM and parses the reply (D68); back in the main thread, the checks of D13 run, so the duplicate check always sees every program stored so far, even with several workers; a worker then evaluates the child (D65); the main thread stores it, places it on its island's grid and migrates when due (D23). Only the main thread touches the `Database` and the `Storage`. Separate limits for LLM calls and evaluations: not needed now, and easy to add later, since the two parts are already separate.

### D37. When a run stops [later]
- **v1**: iteration count, Ctrl+C, 3 LLM failures in a row.
- **OE**: plus target score and early stopping (patience).
- **SE**: a total number of generations, a dollar budget, a stuck detector.
- **Options**, any combination: iterations · target score · no improvement for N iterations ·
  wall-clock time · token or dollar budget (D35).
- **Lean**: iterations, target score, patience; a budget once D35 records costs.
- **Decision**: The run stops when the iteration total is reached (failed and skipped iterations included, D34, D49); when a program reaches an optional target score (`--target-score`, as openevolve's); after an optional number of iterations without a better best score (`--patience`, off by default); when no LLM model is left (D34); after too many infrastructure errors in a row (D38); or on Ctrl+C (D53). No budget (D35). The reason is recorded in the run's log and summary.

### D38. Errors inside an iteration [later]
- **v1**: only `LLMError` is handled; any other exception ends the run (Part D, v1 item 7).
- **OE**: every error is recorded and the run continues.
- **SE**: every failure is recorded (with its stage and reason) and the run continues.
- **Options**: crash · record and continue · record, and stop after N infrastructure errors in a row.
- **Lean**: record and continue; N errors of any kind in a row stop the run.
- **Decision**: Record and continue. Inside an iteration, any unexpected exception that is not the program's fault (the sandbox, the evaluator, the checks) gives the child status `error` with the exception as its error (D7), and the run goes on; 3 errors in a row (the default, settable) stop the run. This counter is separate from D34's per-model LLM counter, so neither kind of problem hides the other. An exception in the main thread itself (for example the disk refusing a write) stops the run at once, since its results could no longer be saved.

### D39. Randomness [later]
- **v1**: own `random.Random`, no default seed; re-seeded identically on resume (Part D, v1 item 9).
- **OE**: global `random` and `numpy`, default seed 42.
- **SE**: no seed at all.
- **Options**: default seed or none · on resume, restore the generator's state or derive a new seed
  from the seed and the number of programs.
- **Lean**: own generator, no default seed; derive the seed on resume. Every random draw (parent,
  island, change format, temperature) goes through that one generator.
- **Decision**: The run's own `random.Random`, through which every draw goes: island, parent, example programs, migrants, model (D31). `--seed` sets it; without it a seed is drawn at random, and either way it is saved with the run (D50), so a run can be repeated as far as the LLMs and the number of workers allow (with several workers, results arrive in no fixed order). On resume, the generator is seeded from the run's seed and the number of programs already stored, so the draws continue instead of repeating (Part D, v1 item 9). Randomness inside the programs themselves (function minimization's unseeded search) is theirs, as in openevolve.

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
- **Decision**: A `Sandbox` interface (D64) with two implementations sharing the same namespace stand-in and protocol: Docker, the default, with a fresh container for each cascade stage (about 1 s each) and after a call over its time limit; and a local subprocess with no isolation, for the tests and for problems you trust, used only when asked for explicitly (`--unsafe-local-sandbox`) and announced at start-up. No cluster backend.

### D41. Limits [later]
- **v1**: no network, read-only, 1 GB, 1 CPU, 64 processes, 30 s, fixed in the code except the timeout.
- **SE**: none locally, apart from optional caps on the threads of numeric libraries
  (`OMP_NUM_THREADS` and similar); the time limit adapts to the average evaluation time.
- **Options**: which are settings, and whether per problem or per run · thread caps for numpy and
  friends · fixed or adaptive time limit.
- **Lean**: v1's values, as problem settings, plus SE's thread caps set to the container's CPU
  count (numpy otherwise starts as many threads as the host has cores); a fixed time limit.
- **Decision**: v1's limits, as settings of the problem file: no network, read-only file system except a temporary `/tmp`, 1 GB of memory and no swap, 1 CPU, 64 processes, all capabilities dropped, user `nobody`. A time limit per cascade stage (60 s for our two problems, as in openevolve) and optional limits per call set by the evaluator (D8). The thread counts of numeric libraries (`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and similar) are set to the container's CPU count, since numpy otherwise starts one thread per core of the host. The evaluator on the host has no limit: it is your code, and trusted.

### D42. Containers that outlive the run [later]
- **v1**: possible (Part D, v1 item 2).
- **SE**: the clean-up does not stop running evaluations either (Part D, SE item 4).
- **Options**: label containers with the run's id and remove them on exit and on the next start ·
  a time limit inside the container too · both.
- **Lean**: both.
- **Decision**: Both. Every container is labelled with the run's id (`docker run --label`) and started with `--rm`; the sandbox removes its containers when a stage ends, when the run stops, and on Ctrl+C; at start-up, containers left by an earlier session of the same run are removed. Inside the container, the worker runs under a time limit of its own, slightly longer than the stage's, so a container stops even if the host process dies.

### D71. Packages programs may import [now] *(added after D70)*
- **v1**: a `requirements.txt` next to the evaluation file, with exact versions; the packages are installed
  once, when the evaluation image is built, and every prompt names them; containers have no network, so
  nothing else can be installed; pip options such as `--index-url` are refused.
- **OE**: whatever is installed where openevolve runs; the LLM is never told.
- **SE**: whatever is installed in the evaluation environment; the LLM is never told.
- **Decision**: The problem file lists the packages programs may import, with exact versions
  (`numpy==2.5.4`), besides Python's standard library. They are installed into the evaluation image when it
  is built, which is the only moment with network access: the image is built from the Dockerfile and that
  list, tagged with a hash of both, built on first use and rebuilt automatically when either changes; the
  containers themselves have no network (D8), so nothing is ever installed because the LLM asks for it. Every
  prompt names the allowed packages (D67), and a program importing anything else fails with `No module named`
  (status `failed`, D7). Only package names and versions may be listed, no pip options. For comparability
  (D3), the two problems list openevolve's packages: numpy and scipy for function minimization, numpy, scipy
  and matplotlib for circle packing, at the versions v1 pinned. The evaluator runs on the host (D8), so the
  packages the evaluation file itself imports (numpy for both problems) must also be installed in the host's
  environment, as a development dependency.

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
- **Decision**: A YAML problem file for the problem's own facts (description, evaluation settings, limits, packages, cascade thresholds, required entry functions, MAP-Elites features and grid, island and parent-selection settings, D17–D23; the `llm` section, with the models, their weights, addresses, key variables, prices and generation settings, laid out as in openevolve's config files, D31–D35, D46; and k, the interval between best-program snapshots, D47) plus CLI flags for the run's choices. The problem file is loaded into the `Problem` dataclass.

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
- **Decision**: v1's form: `python scripts/run.py INITIAL_PROGRAM EVALUATION_FILE --config PROBLEM_FILE [flags]`. Everything about the problem and the LLMs is in the problem file (D43); the flags are the run's choices: `--config` (the problem file, required); `--iterations` (the total, D49; default 100, as openevolve's circle-packing phases); `--output` (the run folder; default `runs/<problem>_<date and time>`; an existing run folder is continued, D49); `--workers` (D36, default 1); `--seed` (D39); `--target-score` and `--patience` (optional stops, D37); `--unsafe-local-sandbox` (D40); `--verbose` (more detail on the console, D52). Every value is checked, with clear errors, as in v1.

### D46. API key [later]
- **v1**: read from the variable named by `--api-key-env`.
- **OE**: in the YAML, through `${VAR}`, or `OPENAI_API_KEY`.
- **SE**: each provider's usual variable, also read from `.env` files; a start-up check that every
  model has credentials.
- **Lean**: keep v1's way; never in a file; check at start-up that the variable is set when the
  server is not local.
- **Decision**: Each model names the environment variable holding its key, with openevolve's `${VAR}` syntax (`api_key: ${ANTHROPIC_API_KEY}`); a key written directly in the file is refused, so the file can be shared. A model on a local server needs no key.

---

## 10. Saving and continuing runs

### D47. Storage format [now]
- **v1**: append-only `programs.jsonl`.
- **OE**: a JSON file per program, full snapshot every N iterations.
- **SE**: a SQLite file written as programs arrive, plus a folder per generation.
- **Options**: JSONL · per-program files and snapshots · SQLite · a folder per program alongside any of them.
- **Lean**: JSONL: nothing evaluated is ever lost, and it is readable with any tool. SQLite is the
  strong alternative if you want to query runs or serve a viewer from them.
- **Decision**: v1's append-only files, in the run folder (`--output`, D45):
  - `programs.jsonl`: one line per program (D48), appended the moment it is stored: children of every status, the initial program's island copies and the migrants.
  - `llm_calls.jsonl`: one line per LLM call: the prompt, the full reply, the model and its token counts, linked to the program it produced, or marked as a skipped iteration when the call failed (D34).
  - `history.csv`: one line per completed iteration: iteration number, child status and score, the best score so far and the best program's id; the data for the progress plot (D51).
  - `best_program.py`: the best program so far, rewritten whenever it changes, with a header comment (score, iteration, id, description).
  - `best/iteration_0010.py`, `best/iteration_0020.py`, …: the best program as it stood after every k iterations (k in the problem file, default 10), with the same header.
  - `run.json` and `problem.yaml` (D50), and `log.txt` (D52).
  With several workers, iterations finish in no fixed order: "after iteration 20" means after 20 iterations have completed. Nothing evaluated is ever lost: a line is written before the next iteration starts, and a line cut off by a crash is detected and dropped on resume, as in v1.

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
- **Decision**: Each line of `programs.jsonl` is a `Program` (D60) with its `Result` (D6), as JSON: failed programs have `score: null` and their status, never `-Infinity`; the evaluator's `output_data` (the plain data a program returned that the evaluator chose to keep, such as a packing's centres and radii, D6) is saved with it, so outputs can be drawn later without running the program again (D51). Prompts and replies are not repeated in it: they are in `llm_calls.jsonl`, failed calls included (D47).

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
- **Decision**: Run the same command with the same `--output` folder. The `Database` is rebuilt by replaying `programs.jsonl` in order (D63): grids, islands, migrants, fingerprints and children counts all come back as they were, since each migration is stored as its copies. `--iterations` is the total, not "that many more": completed iterations are counted from `history.csv` (skipped ones included, D34), so rerunning the same command after a crash finishes the original run instead of extending it, and a larger value extends it. Iterations in progress at a crash were never written and are simply done again. The random generator is reseeded as D39 says. The initial program is not evaluated again.

### D50. Run information and safety checks [later]
- **v1**: nothing; a different problem in the same folder goes unnoticed.
- **SE**: saves the price catalog and the bandit state with the run; does not notice a changed problem either.
- **Options**: save the settings and a fingerprint of the problem files in `run.json`; on resume,
  refuse (or warn) if the problem changed, allow changing the model and iteration count.
- **Lean**: save them; refuse on a changed problem.
- **Decision**: `run.json` records the start of each session (date, my-evolve's git commit, the command line, the seed, D39) and fingerprints (hashes) of the initial program, the evaluation file, the problem file and the evaluation image; a copy of the problem file is saved as `problem.yaml`. On resume, a changed initial program, evaluation file, image, or any problem-file section other than `llm` stops the run with a clear message: scores saved for one problem mean nothing for another. The `llm` section and the flags (`--iterations`, `--workers`, `--target-score`, `--patience`, `--verbose`) may change between sessions; each session's values are recorded.

### D51. Outputs for people [later]
- **v1**: `best_program.py` with a header.
- **OE**: best program and its info file, logs, web visualizer.
- **SE**: a `best/` folder, a WebUI over the SQLite file, plotting functions (lineage tree, costs,
  Pareto front), optional W&B.
- **Options**: best program · a summary at the end · a score-over-time table or plot · a lineage view.
- **Lean**: best program and end summary now; a small report script later.
- **Decision**: During the run: the console line of every iteration shows the best score so far (D52); `best_program.py` and the snapshots in `best/` (D47). At the end: a summary on the console and in `log.txt` (iterations done, why the run stopped, best score and where it was found, failures by status, tokens and cost per model, D35). After the run, a report script, `python scripts/report.py RUN_FOLDER`, rebuilds the database from `programs.jsonl` iteration by iteration and draws, with matplotlib, into `RUN_FOLDER/report/`:
  - **Progress**: the best score so far against the iteration (from `history.csv`), with every child's score as a dot.
  - **Islands and grids**: for every k iterations and the end, each island's grid side by side, each cell coloured by its elite's score: white when empty, light blue for a weak score, deep blue for a strong one, on one colour scale for the whole run (lowest to highest score ever reached), so images can be compared; the series is also saved as an animation. A 1D grid is a row of cells, a 2D grid a square, a 3D grid one square per value of its third feature.
  - **Problem outputs**: when the evaluation file defines a `visualize` function, the best program's output at every snapshot, drawn from its saved `output_data` (D48). Circle packing defines one, drawing the circles in the unit square as openevolve's example does; function minimization does not.
  matplotlib is needed on the host for the report only.

---

## 11. Logging and console

### D52. Logging [later]
- **v1**: `print()`, one line per iteration.
- **OE**: `logging`, many lines per iteration, a log file per run.
- **SE**: `logging` with Rich tables on the console and a log file in the results folder.
- **Options**: `print` · `logging` with a short console format and a detailed log file in the output folder.
- **Lean**: `logging`: one line per iteration on the console, details in the file.
- **Decision**: The `logging` module. The console shows one line per iteration (iteration, island, model, the child's status and score, the best score so far), plus the start and the end summary (D51); `--verbose` adds the details (parents drawn, checks, migrations, timings). `log.txt` in the run folder always gets everything, with timestamps. Secrets never appear in either (D46).

---

## 12. Stopping

### D53. First Ctrl+C [later]
- **v1**: nothing new starts; iterations in progress finish and are saved.
- **OE**: iterations in progress are abandoned; nothing since the last checkpoint is saved.
- **SE**: not handled: work in progress is abandoned; everything finished is already in SQLite.
- **Lean**: keep v1's behaviour.
- **Decision**: v1's behaviour: nothing new starts; iterations in progress finish and are stored; the run then ends with its summary. The console says so, and that a second Ctrl+C stops at once. On Windows, the main thread waits in short steps so that Ctrl+C reaches it, as in v1 (D55).

### D54. Second Ctrl+C and SIGTERM [later]
- **v1**: the second Ctrl+C still waits for running threads (Part D, v1 item 1); SIGTERM not handled.
- **OE**: `sys.exit(0)`; SIGTERM handled like the first Ctrl+C.
- **SE**: neither handled.
- **Options**: what each one does · how running containers and threads are stopped.
- **Lean**: both exit within seconds: running containers are killed, threads not waited for,
  everything already finished is already on disk.
- **Decision**: A second Ctrl+C, or a termination signal (SIGTERM on Linux; there is none on Windows), stops the run within seconds: the sandbox kills the running containers (D42), the worker threads are not waited for, so the process does not hang on an LLM call (unlike v1, Part D, v1 item 1), and the session is recorded as interrupted. Iterations in progress are lost and done again on resume (D49); everything finished is already on disk (D47).

### D55. Platforms [now]
- **v1**: Windows first (PowerShell docs, UTF-8 output, Ctrl+C wake-up), Linux and macOS too.
- **OE**, **SE**: Linux and macOS (SE also Slurm clusters).
- **Options**: Linux only · Linux and macOS · all three, with Windows docs.
- **Lean**: depends on where you will run it; this machine is Linux. Keeping the code portable costs little;
  Windows-specific docs and tests cost more.
- **Decision**: Linux and windows compatible.

---

## 13. The project itself

### D56. Name, layout, Python version [now]
- **v1**: `src/my_alphaevolve/`, Python 3.10+.
- **OE**, **SE**: flat package folders, Python 3.10+.
- **Options**: `src/my_evolve/` · Python 3.10, 3.11 (for `tomllib`) or 3.12.
- **Lean**: `src/my_evolve/`, Python 3.11+.
- **Decision**: `src/my_evolve/`, Python 3.11+.

### D57. Tools [later]
- **v1**: ruff (lint and format), mypy strict, `unittest`, a fake LLM HTTP server, Docker tests
  skipped without Docker.
- **OE**: black, isort, `unittest` and `pytest`, integration tests against a small local model.
- **SE**: ruff, `pytest`, live-provider tests marked and skipped without secrets.
- **Options**: keep v1's tools · `pytest` instead of `unittest` (shorter tests, fixtures).
- **Lean**: keep ruff and mypy strict; your choice between `unittest` and `pytest`.
- **Decision**: same as v1

### D58. Code style [later]
- **v1**: explanatory plain-English docstrings and comments everywhere.
- **Lean**: keep it; it serves the goal of understanding the code.
- **Decision**: lean

### D59. How we work through the plan [now]
- **Options**: step size (one class or one behaviour per step) · who writes the code (I write and
  explain, or you write and I review) · tests in every step · one commit per step · a run of an
  example at the end of each milestone.
- **Lean**: small steps, each runnable and tested, one commit each; I explain the design of a
  step before writing it.
- **Decision**: lean

---

## 14. Classes and modules *(added after section 13)*

How the decisions above become code: every module, class, attribute and method, with the algorithm of
every function in pseudocode. The pseudocode is Python-like and leaves out logging and type details; it
fixes *what* each function does, so that the plan can build it step by step. Records (`Problem`,
`Result`, `Program`, ...) are plain dataclasses; state derived from them lives in `Database`, never on
the records.

Decisions D60 to D70 keep their numbers; the entries added with this section are numbered from D72, so
the numbers below are not in order. Every entry is [now].

### 14.1 Module map

| Module | Contents | Entry |
|---|---|---|
| `problem.py` | `Problem` and its settings, loaded from the problem file | D72 |
| `program.py` | `Status`, `Result`, `LLMUsage`, `Program` | D73, D60 |
| `checks.py` | Evolve blocks, fingerprints, code complexity, the checks before evaluation | D74 |
| `reply_parser.py` | Extracting the description and the code from a reply | D68 |
| `prompt.py` | The templates of Appendix A and `PromptBuilder` | D67 |
| `llm.py` | `LLMReply`, `LLMError`, `LLM`, `OpenAICompatibleLLM`, `Ensemble` | D66 |
| `grid.py` | `Grid` | D61 |
| `database.py` | `Island`, the parent selectors, `Database` | D62, D75, D63 |
| `evaluation_api.py` | What evaluation files import: `StageResult`, `InvalidProgram`, `ProgramFailure`, `CallTimeout`, `StageTimeout`, `call_with_timeout` | D76 |
| `sandbox_protocol.py` | Plain-data encoding and the messages between host and container | D77 |
| `sandbox_worker.py` | The program run inside the container | D77 |
| `sandbox.py` | `Sandbox`, `SandboxSession`, `ProgramNamespace`, `RemoteFunction`, the Docker and local implementations | D64 |
| `evaluator.py` | `Evaluator` | D65 |
| `storage.py` | `Storage`, `RunInfo` | D69 |
| `logs.py` | Logging set-up | D78 |
| `loop.py` | `RunSettings`, `run` and its helpers | D70 |
| `evaluation.Dockerfile` | The evaluation image | D71 |
| `scripts/run.py`, `scripts/report.py` | The command line and the report | D79 |

`my_evolve/__init__.py` stays empty, so that the container can import `sandbox_worker` and
`sandbox_protocol` without the host's dependencies (`openai`, `yaml`).

### 14.2 One iteration, end to end

```
main thread                                    worker thread
-----------                                    -------------
island  = rng.randrange(number of islands)
parent  = database.sample_parent(island)
examples = database.sample_examples(island, parent)
model   = ensemble.draw()
prompt  = prompt_builder.build(parent, examples, best score)
                                     -- proposal -->  reply = model.complete(prompt)
                                                      parsed = parse_reply(reply.text, parent.code)
outcome = check_child(parsed.code, ...)   <-- reply --
if rejected: child = rejected Program
else:                                -- evaluation -> result = evaluator.evaluate(parsed.code)
child = Program(code, result, ...)        <-- result --
database.add(child); storage.append_program(child); history, best, snapshot, migration
```

---

### D72. The `Problem` class and its settings (`problem.py`) [now]
- **In the references**: v1 has a small `Problem` (initial code, evaluation path, description from the
  docstring, packages from `requirements.txt`); openevolve has `Config` with nested dataclasses loaded by
  `dacite`; ShinkaEvolve has `EvolutionConfig`, `DatabaseConfig` and job configs.
- **Decision**: The problem file (D43, D44) loaded into nested dataclasses, every value checked.

  Layout of a problem file (circle packing; every section but `name`, `description`, `entry_functions`
  and `llm` has the defaults shown):

  ```yaml
  name: circle_packing
  description: |
    Pack 26 circles into the unit square, maximizing the sum of their radii ...
    run_packing() returns (centers, radii, sum_of_radii) ...
  entry_functions: [run_packing]
  packages: [numpy==2.5.4, scipy==1.18.1, matplotlib==3.11.2]

  evaluation:
    stage_time_limit: 60          # seconds, for each cascade stage (D41)
    thresholds: [0.5]             # stage k+1 runs if stage k's score >= thresholds[k-1] (D9)
  sandbox: {memory: 1g, cpus: 1, max_processes: 64}            # D41
  grid:                                                        # D17, D18
    features:
      - {name: code_complexity, low: -1, high: 3, bins: 5}
      - {name: radii_spread, low: 0, high: 1, bins: 5}
  islands:                                                     # D23
    count: 3
    migration_interval: 25
    migration_share: 0.1
    migrants: random_non_best     # best | random | random_non_best
    destinations: all_others      # all_others | ring
    mode: copy                    # copy | move
  parents: {strategy: weighted, lambda: 1.0, archive_size: 10} # D19, D21
  prompt: {example_programs: 2, max_chars: 60000, max_feedback_chars: 2000}  # D26, D30, D10
  snapshot_every: 10              # k of D47
  max_errors_in_a_row: 3          # D38

  llm:                            # D31-D35, D46; section-level values apply to every model
    api_base: http://localhost:11434/v1
    max_tokens: 16384
    timeout: 300
    retries: 2
    max_failures_in_a_row: 3
    models:
      - {name: "qwen3-coder:30b", weight: 0.8}
      - {name: "qwen3:8b", weight: 0.2}
  ```

  **Dataclasses** (one per section; defaults as above):

  | Class | Attributes |
  |---|---|
  | `FeatureSpec` | `name`, `low`, `high`, `bins`: one grid dimension; `code_complexity` is the built-in feature, any other name is an output feature the evaluator must provide |
  | `EvaluationSettings` | `stage_time_limit` (seconds), `thresholds` (list of numbers) |
  | `SandboxSettings` | `memory` (Docker size, e.g. `"1g"`), `cpus`, `max_processes` |
  | `IslandSettings` | `count`, `migration_interval`, `migration_share`, `migrants`, `destinations`, `mode` |
  | `ParentSettings` | `strategy`, `lam` (λ, `lambda` in the file), `archive_size` |
  | `PromptSettings` | `example_programs`, `max_chars`, `max_feedback_chars` |
  | `ModelSettings` | `name`, `weight`, `api_base`, `api_key_env` (the variable named by `${VAR}`, or `None`), `temperature`, `max_tokens`, `reasoning_effort`, `reasoning` (`True`, `False` or `None` for "guess from the name"), `timeout`, `retries`, `price_input`, `price_output` (per million tokens) |
  | `LLMSettings` | `models` (list of `ModelSettings`), `max_failures_in_a_row` |
  | `Problem` | `name`, `description`, `entry_functions`, `packages`, `evaluation`, `sandbox`, `grid_features` (list of `FeatureSpec`), `islands`, `parents`, `prompt`, `snapshot_every`, `max_errors_in_a_row`, `llm` |

  **Methods**:
  - `Problem.load(path) -> Problem`: reads and checks the file.
  - `Problem.from_dict(data) -> Problem`: builds and checks it from a parsed dict (used by `load` and the tests).
  - `Problem.output_feature_names` (property): the names of the grid features other than `code_complexity`.
  - `Problem.fingerprint_without_llm() -> str`: a hash of everything but the `llm` section, for D50.

  ```
  def load(path):
      data = yaml.safe_load(read_text(path))          # plain data only, never Python objects
      if data is not a dict: raise ProblemError(path, "must be a mapping")
      return from_dict(data)

  def from_dict(data):
      check_keys(data, allowed=TOP_LEVEL_KEYS, where="problem file")    # unknown keys are an error (D44)
      require data["name"], data["description"], data["entry_functions"], data["llm"]
      packages = [check_requirement(p) for p in data.get("packages", [])]
          # "name==version" only; anything starting with "-" (a pip option) is refused (D71)
      evaluation = build(EvaluationSettings, data.get("evaluation", {}))
      sandbox    = build(SandboxSettings, data.get("sandbox", {}))
      features   = data.get("grid", {}).get("features",
                       [{"name": "code_complexity", "low": -1, "high": 3}])
      default_bins = {1: 10, 2: 5, 3: 3}.get(len(features), 3)                      # D18
      grid_features = [build(FeatureSpec, {"bins": default_bins, **f}) for f in features]
      check: names unique; low < high; bins >= 1
      islands = build(IslandSettings, data.get("islands", {}))
      check: count >= 1, migration_interval >= 1, 0 < migration_share <= 1, and the choices are known
      parents = build(ParentSettings, rename(data.get("parents", {}), "lambda" -> "lam"))
      check: strategy in {weighted, openevolve}, lam > 0, archive_size >= 1
      prompt = build(PromptSettings, data.get("prompt", {}))
      llm = build_llm(data["llm"])
      return Problem(...)

  def build_llm(section):
      shared = section minus "models" and "max_failures_in_a_row"
      check_keys(shared, allowed=MODEL_KEYS)
      models = []
      for entry in section["models"]:                  # at least one
          check_keys(entry, allowed=MODEL_KEYS)
          merged = {**MODEL_DEFAULTS, **shared, **entry}   # openevolve's rule: a model's own value wins
          merged["api_key_env"] = parse_key(merged.pop("api_key", None))
          if merged["reasoning"] is None: merged["reasoning"] = is_reasoning_model(merged["name"])
          if merged["reasoning"] and merged["temperature"] is not None:
              raise ProblemError(name, "reasoning models do not accept a temperature")     # D32
          check: weight > 0, max_tokens >= 1, timeout > 0, retries >= 0
          models.append(ModelSettings(**merged))
      return LLMSettings(models, section.get("max_failures_in_a_row", 3))

  def parse_key(value):                                 # D46
      if value is None: return None                     # local server: no key
      match = re.fullmatch(r"\$\{(\w+)\}", value)
      if not match: raise ProblemError("api_key", "write ${VARIABLE}, never the key itself")
      return match.group(1)                             # read from the environment only when used

  def fingerprint_without_llm():
      return sha256(canonical_json(asdict(self) minus "llm"))
  ```

### D73. The `Result` class and `Status` (`program.py`) [now]
- **In the references**: v1 has a bare float; openevolve a metrics dict or `EvaluationResult(metrics,
  artifacts)`; ShinkaEvolve `metrics.json` plus `correct.json`.
- **Decision**: D6 and D7 as code.

  `Status`: a string enum with the six values `ok`, `rejected`, `failed`, `timeout`, `invalid`, `error`.

  `Result` attributes:

  | Attribute | Type | For |
  |---|---|---|
  | `status` | `Status` | how the evaluation ended (D7) |
  | `score` | number or `None` | the score; `None` unless `status` is `ok` |
  | `metrics` | dict of names to numbers | numbers about the run, saved and logged, not shown to the LLM (D27) |
  | `features` | dict of names to numbers | the output features for the grid (D17), from stage 1 only |
  | `feedback` | text | what the evaluator wants the LLM to know (D10) |
  | `error` | text or `None` | why the program failed, or the error of a later stage it did not pass (D9) |
  | `output_data` | plain data or `None` | what the evaluator keeps for the report's drawings (D48, D51) |
  | `stage_reached` | integer | the last cascade stage completed; 0 if none |
  | `duration` | seconds | wall-clock time of the evaluation |

  Methods:
  - `is_ok` (property): `status == ok`; the only meaning of "correct" (D6).
  - `Result.rejected(reason) -> Result`: a `rejected` result, with the reason as its error.
  - `Result.failure(status, error, feedback="", duration=0) -> Result`: any other non-`ok` result.
  - `to_dict() -> dict` and `Result.from_dict(data) -> Result`: plain JSON values; the status as its name;
    `score` stays `None` (`null` in JSON), never `-Infinity`.

  ```
  def from_dict(data):
      return Result(status=Status(data["status"]), score=data["score"], metrics=data["metrics"],
                    features=data["features"], feedback=data["feedback"], error=data["error"],
                    output_data=data["output_data"], stage_reached=data["stage_reached"],
                    duration=data["duration"])
  ```

### D60. The `Program` class (`program.py`) [now]
- **v1**: a small class: `id`, `code`, `score`, `parent_id`, `generation`, `iteration`, with `to_dict` / `from_dict`.
- **OE**: a dataclass with the evaluation flattened into it and a free-form `metadata` dict holding the
  island, the diff summary, the parent's metrics, token usage and a migrant flag.
- **SE**: a dataclass mapped onto a SQLite table, also flattened, with database state on it
  (`in_archive`, `children_count`, `migration_history`) and a `metadata` dict.
- **Decision**: A dataclass of facts fixed once the program exists, with no free-form `metadata` dict and
  no database state on it.

  `LLMUsage` attributes: `model` (name), `input_tokens`, `output_tokens`, `duration` (seconds): the call
  that wrote the program (D35).

  `Program` attributes:

  | Attribute | Type | For |
  |---|---|---|
  | `id` | text (UUID) | identifies the program everywhere |
  | `code` | text | the full file |
  | `result` | `Result` | its evaluation (D73) |
  | `origin` | `initial`, `llm`, `copy` or `move` | how it came to exist: the initial program; written by the LLM; a copy placed by the framework (the initial program on each island, or a copied migrant); a moved migrant. D13's checks and D19's children count apply to `llm` programs only |
  | `parent_id` | text or `None` | the parent; for a copy or a move, the program copied; `None` for the initial program |
  | `island` | integer or `None` | the island it was made on (D23); `None` for the initial program itself, which lives on the islands through its copies |
  | `iteration` | integer | the iteration that produced it (0 for the initial program and its copies; a migrant gets the iteration of its migration) |
  | `generation` | integer | its distance from the initial program; a copy keeps the generation of the program it copies |
  | `description` | text or `None` | the LLM's self-contained description (D15) |
  | `fingerprint` | text or `None` | the hash of its syntax tree (D13); `None` if it does not compile |
  | `code_complexity` | integer or `None` | its node count inside the evolve blocks (D17); `None` if it does not compile |
  | `example_ids` | list of ids | the example programs shown in its prompt (D26) |
  | `llm` | `LLMUsage` or `None` | the call that wrote it; `None` for the initial program and copies |
  | `created_at` | text (ISO date and time) | when it was made |

  Methods:
  - `to_dict() -> dict`: every attribute as plain JSON values, `result` and `llm` as nested dicts; one line of `programs.jsonl` (D48).
  - `Program.from_dict(data) -> Program`: the reverse, keeping the id.
  - `Program.new_child(...) -> Program`: builds an `llm` child from its parent (new id, `generation = parent.generation + 1`, `created_at = now`).
  - `copy_to(island, iteration, mode) -> Program`: the copy of a migrant or of the initial program (new id, origin `copy` or `move`, everything else carried over except `island`, `iteration`, `llm`, `example_ids`, `created_at`).

  ```
  def to_dict(self):
      data = asdict(self)                                   # dataclasses.asdict
      data["result"] = self.result.to_dict()
      data["origin"] = self.origin.value
      return data

  def from_dict(data):
      check required keys; raise StorageError naming the missing key otherwise
      return Program(id=data["id"], code=data["code"], result=Result.from_dict(data["result"]),
                     origin=Origin(data["origin"]), parent_id=data["parent_id"], island=data["island"],
                     iteration=data["iteration"], generation=data["generation"],
                     description=data["description"], fingerprint=data["fingerprint"],
                     code_complexity=data["code_complexity"], example_ids=data["example_ids"],
                     llm=LLMUsage(**data["llm"]) if data["llm"] else None, created_at=data["created_at"])

  def copy_to(self, island, iteration, mode):
      return replace(self, id=new_uuid(), origin=mode, parent_id=self.id, island=island,
                     iteration=iteration, llm=None, example_ids=[], created_at=now())
  ```

### D74. The check functions (`checks.py`) [now]
- **In the references**: v1 has none; openevolve has `enforce_evolve_blocks` (reverts) and code-length
  checks; ShinkaEvolve has `validate_evolve_markers` and its patch errors.
- **Decision**: Plain functions (D13), used by the loop's main thread and for the initial program.

  - `split_evolve_blocks(code) -> (outside, blocks)`: the code outside the blocks (one more segment than
    blocks, marker lines included) and the blocks' contents; raises `MarkerError` if markers are missing,
    nested or unmatched.
  - `same_outside_code(child_code, initial_code) -> str or None`: `None` if the child kept the blocks where
    the initial program has them, otherwise what differs.
  - `defined_functions(tree) -> set of names`: top-level `def`s.
  - `fingerprint(tree) -> str`: the hash of a syntax tree.
  - `block_line_ranges(code) -> list of (first, last)`: the line numbers inside each block.
  - `count_block_nodes(tree, code) -> int`: the code feature (D17).
  - `check_child(code, initial_code, entry_functions, known_fingerprints) -> CheckOutcome`: the four
    checks; `CheckOutcome` has `rejection` (reason or `None`), `fingerprint`, `code_complexity`.

  ```
  START, END = "# EVOLVE-BLOCK-START", "# EVOLVE-BLOCK-END"

  def split_evolve_blocks(code):
      outside, blocks, current, inside = [], [], [], False
      for line in code.splitlines():
          marker = line.strip()
          if marker == START:
              if inside: raise MarkerError("an EVOLVE-BLOCK-START inside a block")
              outside.append(current + [line]); current, inside = [], True
          elif marker == END:
              if not inside: raise MarkerError("an EVOLVE-BLOCK-END without a start")
              blocks.append(current); current, inside = [line], False
          else:
              current.append(line)
      if inside: raise MarkerError("an EVOLVE-BLOCK-START without an end")
      if not blocks: raise MarkerError("no evolve block")
      outside.append(current)
      return outside, blocks

  def normalized(lines):                      # whitespace that changes nothing is ignored (D13)
      return [line.rstrip() for line in lines if line.strip() != ""]

  def same_outside_code(child_code, initial_code):
      initial_outside, _ = split_evolve_blocks(initial_code)
      try: child_outside, _ = split_evolve_blocks(child_code)
      except MarkerError as e: return f"the evolve-block markers were changed: {e}"
      if len(child_outside) != len(initial_outside):
          return f"expected {len(initial_outside) - 1} evolve blocks, found {len(child_outside) - 1}"
      for k, (child, initial) in enumerate(zip(child_outside, initial_outside)):
          if normalized(child) != normalized(initial):
              return f"code outside the evolve blocks was changed (part {k + 1})"
      return None

  def defined_functions(tree):
      return {node.name for node in tree.body if isinstance(node, (FunctionDef, AsyncFunctionDef))}

  def fingerprint(tree):
      return sha256(ast.dump(tree, include_attributes=False))   # comments and spacing are not in the tree

  def block_line_ranges(code):
      ranges, start = [], None
      for number, line in enumerate(code.splitlines(), start=1):
          if line.strip() == START: start = number + 1
          elif line.strip() == END: ranges.append((start, number - 1))
      return ranges

  def count_block_nodes(tree, code):
      ranges = block_line_ranges(code)
      count = 0
      for node in ast.walk(tree):
          if not hasattr(node, "lineno"): continue           # contexts and operators carry no position
          if any(first <= node.lineno and node.end_lineno <= last for first, last in ranges):
              count += 1
      return count

  def check_child(code, initial_code, entry_functions, known_fingerprints):
      if code is None: return CheckOutcome("no code in the reply", None, None)
      try: tree = ast.parse(code)
      except SyntaxError as e: return CheckOutcome(f"syntax error: {e}", None, None)
      print_ = fingerprint(tree); complexity = count_block_nodes(tree, code)
      difference = same_outside_code(code, initial_code)
      if difference: return CheckOutcome(difference, print_, complexity)
      missing = set(entry_functions) - defined_functions(tree)
      if missing: return CheckOutcome(f"missing entry function(s): {sorted(missing)}", print_, complexity)
      if print_ in known_fingerprints:                     # a dict: fingerprint -> id of the first program
          return CheckOutcome(f"same program as {known_fingerprints[print_]}", print_, complexity)
      return CheckOutcome(None, print_, complexity)
  ```

### D68. Reply parsing (`reply_parser.py`) [now]
- **v1**: functions in `reply_parser.py`.
- **OE**: functions in `utils/code_utils.py`.
- **SE**: functions in `edit/` (`apply_full_patch`, `apply_diff_patch`).
- **Decision**: Functions, not a class, reusing v1's code-block rules. `ParsedReply` has `code` (or `None`)
  and `description` (or `None`).

  - `parse_reply(reply, parent_code) -> ParsedReply`
  - `extract_description(text) -> (description or None, text without it)`
  - `extract_code(text, parent_code) -> code or None`, with v1's helpers `is_valid_python`,
    `is_same_program` and `choose_code_block`, and v1's four regular expressions (multi-line block,
    one-line block, unclosed block, widest block).

  ```
  def parse_reply(reply, parent_code):
      text = THINKING_PATTERN.sub("", reply)          # <think>...</think> sections are dropped
      description, text = extract_description(text)
      return ParsedReply(extract_code(text, parent_code), description)

  def extract_description(text):
      match = re.search(r"<DESCRIPTION>(.*?)</DESCRIPTION>", text, DOTALL | IGNORECASE)
      if not match: return None, text
      description = match.group(1).strip() or None
      return description, text[:match.start()] + text[match.end():]    # its code fences are not the program

  def extract_code(text, parent_code):                # v1's rules
      blocks = CODE_BLOCK_PATTERN.findall(text) or ONE_LINE_CODE_BLOCK_PATTERN.findall(text)
      if blocks: code = choose_code_block(blocks, text, parent_code)
      else:
          unclosed = UNCLOSED_CODE_BLOCK_PATTERN.search(text)
          code = unclosed.group(1) if unclosed else text  # no fence: the whole text, as in v1
      code = code.strip()
      return code + "\n" if code else None

  def choose_code_block(blocks, text, parent_code):
      candidates = [b for b in blocks if is_valid_python(b)]
      if not candidates:
          widest = WIDEST_CODE_BLOCK_PATTERN.search(text)
          if widest and is_valid_python(widest.group(1)): return widest.group(1)
          candidates = blocks
      new = [b for b in candidates if not is_same_program(b, parent_code)]   # a quoted parent is not the reply
      return max(new or candidates, key=len)
  ```

### D67. The `PromptBuilder` class (`prompt.py`) [now]
- **v1**: `PromptSampler`: one template, filled with the description, the parent and the allowed packages.
- **OE**: `PromptSampler` with a `TemplateManager` over text files.
- **SE**: `PromptSampler`, with one prompt module per change format.
- **Decision**: Builds the two messages of Appendix A (D25, D26, D27, D10). The module also holds the
  templates as constants (D29): `SYSTEM_TEMPLATE`, `ATTEMPT_TEMPLATE`, `PARENT_TEMPLATE`, `REQUEST`.

  `Prompt` attributes: `system`, `user` (texts).

  `PromptBuilder` attributes: `system_message` (built once, the same for the whole run), `settings`
  (`PromptSettings`).

  Methods:
  - `__init__(problem)`: fills `SYSTEM_TEMPLATE` once.
  - `build(parent, examples, best_score) -> Prompt`: the prompt of one iteration.
  - `program_section(program, heading) -> str`: one program's block (description, feedback, error, code).
  - `truncated(text, limit) -> str`: a text cut to the size limit (D10).

  ```
  def __init__(self, problem):
      packages = ", ".join(package_name(p) for p in problem.packages) or "nothing else"
      self.system_message = SYSTEM_TEMPLATE.format(description=problem.description.strip(),
                                                   packages=packages)
      self.settings = problem.prompt

  def build(self, parent, examples, best_score):
      examples = list(examples)
      while True:
          parts = []
          if examples:
              parts.append("# Previous attempts")
              for n, example in enumerate(examples, start=1):
                  label = f"score {example.result.score:.6g}" if example.result.is_ok \
                          else example.result.status.value
                  parts.append(self.program_section(example, f"## Attempt {n}: {label}"))
          parts.append(self.program_section(parent,
              f"# Program to improve (the parent): score {parent.result.score:.6g}; "
              f"best score so far in this run: {best_score:.6g}"))
          parts.append(REQUEST)
          user = "\n\n".join(parts)
          if len(self.system_message) + len(user) <= self.settings.max_chars or not examples:
              break
          examples.pop()                                   # D30: drop example programs, last first
          log.warning("prompt over budget: one example program dropped")
      if len(self.system_message) + len(user) > self.settings.max_chars:
          log.warning("prompt over budget even without example programs")
      return Prompt(self.system_message, user)

  def program_section(self, program, heading):
      lines = [heading]
      if program.description: lines.append(f"Description: {program.description}")
      if program.result.feedback:
          lines.append(f"Feedback: {self.truncated(program.result.feedback)}")
      if program.result.error: lines.append(f"Error: {self.truncated(program.result.error)}")
      lines.append(f"```python\n{program.code.rstrip()}\n```")
      return "\n".join(lines)

  def truncated(self, text):
      limit = self.settings.max_feedback_chars
      return text if len(text) <= limit else text[:limit] + "\n... (truncated)"
  ```

### D66. The `LLM` classes (`llm.py`) [now]
- **v1**: an `LLM` base class with one method, `generate`, and an `OpenAICompatibleLLM` implementation.
- **OE**: `LLMInterface`, implemented per provider, and `LLMEnsemble` on top.
- **SE**: `LLMClient` and `AsyncLLMClient`, over one module per provider.
- **Decision**: An abstract `LLM`, one implementation per model, and an `Ensemble` that the loop always
  uses (with one model or several). Models are drawn, and their failures counted, in the main thread
  only, so the run's random generator and the counters are never shared between threads (D36, D39).

  - `LLMReply`: `text`, `model`, `input_tokens`, `output_tokens`, `duration`.
  - `LLMError`: raised when no reply could be obtained; carries the model's name.
  - `NoModelLeft`: raised by the ensemble when every model has been dropped (D34).
  - `REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5", "gpt-oss")` and `is_reasoning_model(name)` (D32).

  `LLM` (abstract): `name` attribute; `complete(prompt) -> LLMReply` (raises `LLMError`); `check()`: the
  start-up check (D34).

  `OpenAICompatibleLLM(LLM)` attributes: `settings` (`ModelSettings`), `client` (`openai.OpenAI`, the only
  holder of the key).

  `Ensemble` attributes: `models` (list of `LLM`), `weights`, `active` (names still in use),
  `failures_in_a_row` (per name), `max_failures`, `rng`.
  Methods: `draw() -> LLM`; `record_success(name)`; `record_failure(name)`; `check_all()`.

  ```
  def is_reasoning_model(name):
      base = name.lower().split("/")[-1]              # "openai/gpt-5" -> "gpt-5"
      return base.startswith(REASONING_PREFIXES)

  class OpenAICompatibleLLM:
      def __init__(self, settings):
          key = os.environ.get(settings.api_key_env) if settings.api_key_env else None
          if settings.api_key_env and not key:
              raise ConfigurationError(f"{settings.api_key_env} is not set")
          self.client = openai.OpenAI(base_url=settings.api_base, api_key=key or "no-key-needed",
                                      timeout=settings.timeout, max_retries=settings.retries)  # one layer (D34)

      def complete(self, prompt):
          params = {"model": s.name, "messages": [{"role": "system", "content": prompt.system},
                                                  {"role": "user", "content": prompt.user}]}
          if s.reasoning:
              params["max_completion_tokens"] = s.max_tokens
              if s.reasoning_effort: params["reasoning_effort"] = s.reasoning_effort
          else:
              params["max_tokens"] = s.max_tokens
              if s.temperature is not None: params["temperature"] = s.temperature
          start = now()
          try: response = self.client.chat.completions.create(**params)
          except openai.OpenAIError as e: raise LLMError(s.name, f"{type(e).__name__}: {e}")
          text = response.choices[0].message.content if response.choices else None
          if not text: raise LLMError(s.name, "empty reply")
          usage = response.usage
          return LLMReply(text, s.name, usage.prompt_tokens if usage else 0,
                          usage.completion_tokens if usage else 0, now() - start)

      def check(self):
          self.complete(Prompt("Reply with the word OK.", "OK?"))   # raises LLMError on any problem

  class Ensemble:
      def draw(self):
          if not self.active: raise NoModelLeft()
          names = [m.name for m in self.models if m.name in self.active]
          return self.by_name[self.rng.choices(names, weights=[self.weight[n] for n in names])[0]]
          # rng.choices rescales the remaining weights itself: dropping a model renormalizes them (D34)

      def record_success(self, name): self.failures_in_a_row[name] = 0

      def record_failure(self, name):
          self.failures_in_a_row[name] += 1
          if self.failures_in_a_row[name] >= self.max_failures and name in self.active:
              self.active.remove(name)
              log.warning(f"{name} failed {self.max_failures} times in a row; dropped")

      def check_all(self):
          for model in self.models: model.check()   # any LLMError stops the run before iteration 1
  ```

### D61. The `Grid` class (`grid.py`) [now]
- **v1**: none on `main` (`aeaf384` rebuilt a grid from all programs at each sample).
- **OE**: a dict per island from a cell key to a program id, inside `ProgramDatabase`.
- **SE**: no grid.
- **Decision**: One fixed MAP-Elites grid (D17, D18).

  Attributes: `features` (list of `FeatureSpec`), `reference_nodes` (the initial program's
  `code_complexity`, for normalizing), `elites` (dict from a cell, a tuple of bin indices, to a `Program`).

  Methods:
  - `feature_values(program) -> list of numbers`: the program's value on each dimension.
  - `cell_of(program) -> tuple`: its cell.
  - `place(program) -> Placement`: puts an `ok` program in its cell if the cell is empty or its elite
    scores strictly lower; `Placement` says whether it took the cell and which elite it displaced.
  - `remove(program_id)`: takes a program out of its cell (used when a migrant moves away, D23).
  - `elite_list() -> list of Program`: the elites, in cell order (so draws are repeatable).
  - `best() -> Program or None`: the highest-scoring elite (the earliest placed, on a tie).

  ```
  def feature_values(self, program):
      values = []
      for f in self.features:
          if f.name == "code_complexity":
              nodes = max(program.code_complexity, 1)        # an empty block counts as one node
              values.append(log2(nodes / max(self.reference_nodes, 1)))      # D18
          else:
              values.append(program.result.features[f.name])
      return values

  def bin_of(value, f):
      position = (value - f.low) / (f.high - f.low)
      return min(f.bins - 1, max(0, floor(position * f.bins)))   # out of range: nearest end bin

  def cell_of(self, program):
      return tuple(bin_of(v, f) for v, f in zip(self.feature_values(program), self.features))

  def place(self, program):
      assert program.result.is_ok                       # failed programs never enter a grid (D7)
      cell = self.cell_of(program)
      incumbent = self.elites.get(cell)
      if incumbent is None or program.result.score > incumbent.result.score:
          self.elites[cell] = program
          return Placement(took_cell=True, cell=cell, displaced=incumbent)
      return Placement(took_cell=False, cell=cell, displaced=None)

  def remove(self, program_id):
      for cell, elite in list(self.elites.items()):
          if elite.id == program_id: del self.elites[cell]

  def elite_list(self): return [self.elites[c] for c in sorted(self.elites)]
  def best(self): return max(self.elite_list(), key=score, default=None)   # first maximum wins
  ```

### D62. The `Island` class (`database.py`) [now]
- **OE**: sets of program ids, alongside the grids, inside `ProgramDatabase`.
- **SE**: an `island_idx` column, managed by an `IslandManager` and migration strategy classes.
- **Decision**: An island's number, its grid and the list of every program made on it.

  Attributes: `index`, `grid` (`Grid`), `program_ids` (every program made on the island, in order; for
  example programs, D26).
  Methods: `elites() -> list of Program` (the island's population, D23); `best() -> Program`.

  ```
  def elites(self): return self.grid.elite_list()
  def best(self):   return self.grid.best()
  ```

### D75. The parent selectors (`database.py`) [now]
- **In the references**: v1's rule inside `Database.sample`; openevolve's inside
  `ProgramDatabase.sample_from_island`; ShinkaEvolve's `CombinedParentSelector` and strategy classes.
- **Decision**: An abstract `ParentSelector` with one method, `choose(island, database, rng) ->
  Program`, and the two strategies of D19, chosen by `parents.strategy`.

  `WeightedSelector` (primary) attributes: `lam` (λ). `OpenEvolveSelector` (secondary) attributes:
  `archive_size`.

  ```
  class WeightedSelector:
      def choose(self, island, database, rng):
          elites = island.elites()                      # never empty: every island starts with a copy
          scores = [e.result.score for e in elites]
          middle = median(scores)
          spread = median(abs(s - middle) for s in scores)       # median absolute deviation
          if spread == 0: spread = pstdev(scores)                # D19's fallbacks
          weights = []
          for elite, s in zip(elites, scores):
              performance = 0.5 if spread == 0 else sigmoid(self.lam * (s - middle) / spread)
              novelty = 1 / (1 + database.children_count(elite.id))
              weights.append(performance * novelty)
          return rng.choices(elites, weights=weights)[0]

  class OpenEvolveSelector:
      def choose(self, island, database, rng):
          elites = island.elites()
          draw = rng.random()
          if draw < 0.2: return rng.choice(elites)                          # uniform
          if draw < 0.9:                                                    # archive, D21
              archive = database.archive(self.archive_size)
              own = [p for p in archive if p.island == island.index]
              return rng.choice(own or archive)
          weights = [max(e.result.score, 0.001) for e in elites]           # fitness-weighted
          return rng.choices(elites, weights=weights)[0]
  ```

  The child of an iteration always lives on the iteration's island. With the weighted rule that is its
  parent's island; with openevolve's archive branch it may not be, as in openevolve itself.

### D63. The `Database` class (`database.py`) [now]
- **v1**: `Database`: a flat dict of programs and the 70/30 parent choice.
- **OE**: `ProgramDatabase`, 2,800 lines: islands, grids, archive, migration, sampling, saving, artifacts.
- **SE**: `ProgramDatabase` over SQLite, with separate classes for parents, islands and inspirations.
- **Decision**: All of the run's state that is derived from its programs. Only the main thread uses it
  (D36). Adding the saved programs again, in order, rebuilds it exactly (D49), so nothing here is saved
  on its own.

  Attributes:

  | Attribute | For |
  |---|---|
  | `problem` | grid, island and parent settings |
  | `programs` | dict from id to `Program`, every program of the run, in the order added (D22) |
  | `islands` | list of `Island` |
  | `fingerprints` | dict from fingerprint to the id of the first program with it (D13) |
  | `children` | count of `llm` children per parent id, `error` ones excluded (D19) |
  | `best_id` | the best `ok` program so far (the first one, on a tie) |
  | `best_changed_at` | the completed-iteration count when the best last improved (for `--patience`) |
  | `selector` | the `ParentSelector` |
  | `rng` | the run's random generator (D39) |

  Methods:
  - `add(program, completed=None)`: records a program and updates everything derived from it.
  - `seed_islands(initial_program) -> list of Program`: the initial program's copies, one per island.
  - `children_count(id) -> int`.
  - `best() -> Program`.
  - `archive(k) -> list of Program`: the k best `ok` programs, one per fingerprint (D21).
  - `sample_island() -> Island`: uniform (D23).
  - `sample_parent(island) -> Program`: through the selector.
  - `sample_examples(island, parent, count) -> list of Program` (D26).
  - `migrate(iteration) -> list of Program`: the copies (or moves) of one migration (D23).
  - `replay(programs)`: `add` for each saved program, in order (D49).

  ```
  def __init__(self, problem, initial_program, rng):
      self.islands = [Island(i, Grid(problem.grid_features, initial_program.code_complexity), [])
                      for i in range(problem.islands.count)]
      self.selector = WeightedSelector(problem.parents.lam) if problem.parents.strategy == "weighted" \
                      else OpenEvolveSelector(problem.parents.archive_size)
      ...

  def add(self, program, completed=None):
      self.programs[program.id] = program
      if program.island is not None: self.islands[program.island].program_ids.append(program.id)
      if program.fingerprint and program.result.status in {ok, failed, timeout, invalid}:
          self.fingerprints.setdefault(program.fingerprint, program.id)
      if program.origin == llm and program.parent_id and program.result.status != error:
          self.children[program.parent_id] += 1
      if program.origin == move:                                      # D23 "move": leaves its island
          moved = self.programs[program.parent_id]
          self.islands[moved.island].grid.remove(moved.id)
          self.children[program.id] = self.children[moved.id]          # a moved program keeps its count
      if program.result.is_ok and program.island is not None:
          self.islands[program.island].grid.place(program)
      if program.result.is_ok and (self.best_id is None
                                   or program.result.score > self.best().result.score):
          self.best_id = program.id
          if completed is not None: self.best_changed_at = completed

  def seed_islands(self, initial_program):
      return [initial_program.copy_to(island=i, iteration=0, mode=copy) for i in range(len(self.islands))]

  def archive(self, k):
      ranked = sorted((p for p in self.programs.values() if p.result.is_ok),
                      key=lambda p: p.result.score, reverse=True)       # stable: earlier first on ties
      unique, seen = [], set()
      for p in ranked:                                   # copies of one program count once
          if p.fingerprint not in seen: unique.append(p); seen.add(p.fingerprint)
      return unique[:k]

  def best(self):                    return self.programs[self.best_id]
  def children_count(self, id):      return self.children[id]
  def sample_island(self):           return self.rng.choice(self.islands)
  def sample_parent(self, island):   return self.selector.choose(island, self, self.rng)

  def sample_examples(self, island, parent, count):
      pool = [self.programs[i] for i in island.program_ids
              if i != parent.id and self.programs[i].result.status != error
              and self.programs[i].code.strip()]            # a reply without code shows nothing
      return self.rng.sample(pool, min(count, len(pool)))        # shown in the order drawn

  def migrate(self, iteration):
      s = self.problem.islands
      plan = []                                          # chosen first, so copies never migrate twice
      for island in self.islands:
          elites, best = island.elites(), island.best()
          if s.migrants == "best": chosen = [best]
          else:
              pool = elites if s.migrants == "random" else [e for e in elites if e is not best]
              n = min(len(pool), max(1, floor(s.migration_share * len(elites))))
              chosen = self.rng.sample(pool, n)
          destinations = [(island.index + 1) % len(self.islands)] if s.destinations == "ring" \
                         else [j for j in range(len(self.islands)) if j != island.index]
          if s.mode == "move": destinations = destinations[:1]     # a program can only be in one place
          plan += [(program, d) for program in chosen for d in destinations]
      arrivals = [program.copy_to(d, iteration, mode=s.mode) for program, d in plan]
      for arrival in arrivals: self.add(arrival)        # takes its cell only if empty or better (Grid.place)
      return arrivals                                    # stored by the loop, so replay repeats them

  def replay(self, programs):
      for program in programs: self.add(program)
  ```

  With `mode: move` and several destinations, a program moves to the first destination only.

### D76. The evaluation API (`evaluation_api.py`) [now]
- **In the references**: v1's `evaluate(namespace)` returns a float; openevolve's evaluators return a
  dict or an `EvaluationResult` and call `run_with_timeout`; ShinkaEvolve's call `run_shinka_eval`.
- **Decision**: What an evaluation file imports, and the contract of its stage functions.

  An evaluation file defines either `evaluate(namespace)` or `evaluate_stage1(namespace)`,
  `evaluate_stage2(namespace)`, … (D9), and optionally `visualize(output_data, path)` (D51). Each stage
  function receives the program's namespace (D8) and:
  - returns a `StageResult`: `score` (a finite number, higher is better), `metrics` (dict), `features`
    (dict, required from stage 1 for the problem's output features), `feedback` (text), `output_data`
    (plain data or `None`);
  - or raises `InvalidProgram(reason, feedback="")` when the answer breaks the problem's rules (D7);
  - and lets `ProgramFailure` and `CallTimeout` through, unless it handles them itself (function
    minimization's stage 2 catches them per trial).

  Exceptions (raised by the namespace, D64):
  - `ProgramFailure`: the program raised, or its process ended; carries the exception's type, message,
    traceback and the end of the program's error output.
  - `CallTimeout`: one call exceeded its own limit; the evaluator may catch it.
  - `StageTimeout`: the stage's own limit (D41) ran out; deliberately not a subclass of `CallTimeout`, so
    catching a trial's timeout never hides it.

  ```
  def call_with_timeout(function, seconds, *args, **kwargs):     # openevolve's run_with_timeout, ported
      return function.with_timeout(seconds)(*args, **kwargs)
  ```

  Stage functions run in worker threads, several at once when `workers > 1` (D36): they must not keep
  state between calls.

### D77. The sandbox protocol and worker (`sandbox_protocol.py`, `sandbox_worker.py`) [now]
- **In the references**: v1 passes the code on stdin and reads one JSON result line from stdout
  (`container_worker.py`); openevolve and ShinkaEvolve have nothing similar.
- **Decision**: One JSON message per line between the host and the worker in the container. The worker
  answers calls for as long as the stage lasts (D8).

  Messages, host to worker: `{"type": "load", "code": ...}`; `{"type": "call", "id": n, "name": ...,
  "args": [...], "kwargs": {...}}`; `{"type": "get", "id": n, "name": ...}`.
  Worker to host: `{"type": "loaded", "names": {name: "function" | "data" | "other"}}`;
  `{"type": "load_failed", "error": ..., "traceback": ...}`; `{"type": "return", "id": n, "value": ...}`;
  `{"type": "raised", "id": n, "error": ..., "traceback": ...}`.

  Functions of `sandbox_protocol.py` (imported on both sides; numpy is optional):
  - `encode(value) -> JSON value`: plain data only: `None`, booleans, integers, floats, strings, lists,
    dicts with string keys, tuples (tagged, so `run_search`'s `(x, y, value)` stays a tuple), numpy
    arrays of numbers (tagged: dtype, shape, base64 bytes), numpy numbers (as Python numbers). Anything
    else raises `NotPlainData`.
  - `decode(JSON value) -> value`: the reverse; numpy arrays are rebuilt with `numpy.frombuffer` from a
    numeric dtype only, never with pickle (D8).
  - `send(stream, message)` and `receive(stream) -> message`: one line of JSON each.

  ```
  def encode(v):
      if v is None or isinstance(v, (bool, str)): return v
      if isinstance(v, int): return v
      if isinstance(v, float): return v if isfinite(v) else {"__float__": repr(v)}   # nan and inf survive
      if numpy and isinstance(v, numpy.generic): return encode(v.item())
      if numpy and isinstance(v, numpy.ndarray):
          if v.dtype.kind not in "biuf": raise NotPlainData(f"array of {v.dtype}")
          return {"__ndarray__": {"dtype": v.dtype.str, "shape": v.shape, "data": b64(v.tobytes())}}
      if isinstance(v, tuple): return {"__tuple__": [encode(x) for x in v]}
      if isinstance(v, list):  return [encode(x) for x in v]
      if isinstance(v, dict) and all(isinstance(k, str) for k in v):
          return {"__dict__": {k: encode(x) for k, x in v.items()}}   # tagged, so a user key never collides
      raise NotPlainData(type(v).__name__)
  ```

  The worker (`python -m my_evolve.sandbox_worker`), run under a time limit of its own, slightly longer
  than the stage's (D42):

  ```
  def main():
      protocol_out = fdopen(dup(stdout_fd))   # the protocol keeps its own copy of stdout
      dup2(stderr_fd, stdout_fd)               # the program's prints go to stderr, captured by the host
      message = receive(stdin)                 # {"type": "load"}
      namespace = {"__name__": "program"}      # so the program's `if __name__ == "__main__":` never runs
      try: exec(compile(message["code"], "program.py", "exec"), namespace)
      except BaseException as e:               # SystemExit included
          send(protocol_out, {"type": "load_failed", "error": describe(e), "traceback": format_exc()})
          return
      send(protocol_out, {"type": "loaded", "names": {n: kind(v) for n, v in namespace.items()
                                                      if not n.startswith("__")}})
      for message in messages(stdin):
          try:
              if message["type"] == "get": value = namespace[message["name"]]
              else: value = namespace[message["name"]](*decode(message["args"]), **decode(message["kwargs"]))
              send(protocol_out, {"type": "return", "id": message["id"], "value": encode(value)})
          except BaseException as e:
              send(protocol_out, {"type": "raised", "id": message["id"],
                                  "error": describe(e), "traceback": format_exc()})
  ```

  A program can write to the protocol's stream too, but it gains nothing: it already chooses what its
  functions return, and the host ignores any message whose `id` it is not waiting for.

### D64. The `Sandbox` classes (`sandbox.py`) [now]
- **v1**: `DockerEvaluator`, plus the `container_worker` module that runs inside the container.
- **OE**: none.
- **SE**: `JobScheduler` and the `launch` modules (local processes, Slurm).
- **Decision**: A sandbox starts one session per cascade stage (D40); a session is one worker process,
  in a container or not, holding one loaded program, with the namespace stand-in in front of it.

  - `Sandbox` (abstract): `start(code, stage_limit) -> SandboxSession` (shared by both); `command(name,
    stage_limit) -> list` (how to start the worker); `stop(session)` (kill its process);
    `remove_leftovers()`.
  - `DockerSandbox(Sandbox)` attributes: `image` (tag), `settings` (`SandboxSettings`), `run_id`; plus
    `ensure_image(packages)` (D71). `stop` runs `docker kill`; `remove_leftovers` removes the run's containers.
  - `LocalSandbox(Sandbox)`: the same worker as a plain subprocess, no isolation (`--unsafe-local-sandbox`):
    `command` is `[python, -m, my_evolve.sandbox_worker]` with the thread variables set; `stop` kills the
    process; `remove_leftovers` does nothing.
  - `SandboxSession` attributes: `process`, `reader` (a thread putting the worker's messages in a queue),
    `stderr_file`, `deadline` (when the stage ends), `names` (from the `loaded` message), `code`, `alive`.
    `stage_limit`. Methods: `call(name, args, kwargs, timeout) -> value`, `get(name) -> value`, `restart()`, `kill()`,
    `close()`, `error_tail() -> str` (the end of the program's error output, D10).
  - `ProgramNamespace` (what `evaluate` receives): `__getitem__(name)`, `__contains__(name)`, `get(name,
    default)`, `keys()`. A function name gives a `RemoteFunction`; a plain-data global gives its value; a
    missing name raises `ProgramFailure("the program does not define <name>")`, which is `failed` (D7).
  - `RemoteFunction`: `__call__(*args, **kwargs)` (limited by the stage only) and `with_timeout(seconds)`.
  - `SandboxError`: the sandbox itself failed (Docker missing or not running, image build failed, a
    container that cannot start); the program gets status `error`.

  ```
  def ensure_image(packages):                            # D71
      tag = "my-evolve-evaluation:" + sha256(read(DOCKERFILE) + "\n".join(packages))[:12]
      if `docker image inspect tag` fails:
          build from a temporary folder holding the Dockerfile and requirements.txt (the packages)
      return tag

  def command(self, name, stage_limit):                   # DockerSandbox; D41, D42
      s = self.settings
      return ["docker", "run", "--rm", "--interactive", "--name", name,
              "--label", f"my-evolve.run={self.run_id}",
              "--network", "none", "--read-only", "--tmpfs", "/tmp",
              "--memory", s.memory, "--memory-swap", s.memory, "--cpus", str(s.cpus),
              "--pids-limit", str(s.max_processes), "--cap-drop", "ALL",
              "--security-opt", "no-new-privileges", "--user", "65534:65534",
              *[f"--env={v}={max(1, floor(s.cpus))}" for v in THREAD_VARIABLES],   # OMP_NUM_THREADS, ...
              "--mount", f"type=bind,source={PACKAGE_FOLDER},target=/app/my_evolve,readonly",
              self.image, "timeout", "--signal=KILL", str(ceil(stage_limit) + 10),
              "python", "-m", "my_evolve.sandbox_worker"]

  def start(self, code, stage_limit):
      session = SandboxSession(self, code, stage_limit, deadline=now() + stage_limit)
      session.restart()                  # starts the process and loads the program
      return session

  def restart(self):                     # SandboxSession: a fresh process with the program reloaded
      self.kill()
      try: self.process = popen(self.sandbox.command(new_container_name(), self.stage_limit), stdin=PIPE, stdout=PIPE,
                                stderr=self.stderr_file)
      except OSError as e: raise SandboxError(f"cannot start a container: {e}")
      start the reader thread
      send(self.process.stdin, {"type": "load", "code": self.code})
      answer = self.wait_for(lambda m: m["type"] in ("loaded", "load_failed"), self.deadline)
      if answer["type"] == "load_failed":
          raise ProgramFailure(answer["error"], answer["traceback"], self.error_tail())
      self.names, self.alive = answer["names"], True

  def call(self, name, args, kwargs, timeout=None):
      if not self.alive: self.restart()  # after a call timeout, the next call starts afresh (D8)
      if now() >= self.deadline: self.kill(); raise StageTimeout()
      request_id = next id
      send(self.process.stdin, {"type": "call", "id": request_id, "name": name,
                                "args": encode(list(args)), "kwargs": encode(kwargs)})
      call_end = now() + timeout if timeout else infinity
      try: answer = self.wait_for(lambda m: m.get("id") == request_id, min(call_end, self.deadline))
      except WaitTimedOut:
          self.kill()
          if call_end < self.deadline: raise CallTimeout(name, timeout)
          raise StageTimeout()
      except WorkerEnded as e:                   # the process died: exit(), memory, os._exit
          self.alive = False
          raise ProgramFailure(describe_end(e.exit_code), "", self.error_tail())
             # exit code 137: "stopped, most likely for using too much memory" (as v1)
      if answer["type"] == "raised": raise ProgramFailure(answer["error"], answer["traceback"], self.error_tail())
      return decode(answer["value"])

  def wait_for(self, matches, until):            # messages arrive on the reader thread's queue
      while True:
          message = self.queue.get(timeout=max(0, until - now()))   # Empty -> WaitTimedOut
          if message is END_OF_STREAM: raise WorkerEnded(self.process.wait())
          if matches(message): return message    # anything else (forged or stale) is ignored

  def kill(self):                                # SandboxSession
      if self.process and self.process.poll() is None:
          self.sandbox.stop(self); self.process.wait()
      self.alive = False

  def close(self): self.kill(); close the stderr file

  def remove_leftovers(self):                    # DockerSandbox: at start-up, at the end, on a second Ctrl+C (D42)
      ids = `docker ps -aq --filter label=my-evolve.run=<run_id>`
      if ids: `docker rm -f <ids>`
  ```

  `ProgramNamespace.__getitem__(name)`: `"function"` gives `RemoteFunction(session, name)`, `"data"` gives
  `session.get(name)`, `"other"` raises `ProgramFailure` (a class or a module cannot cross the boundary),
  a missing name raises `ProgramFailure`.

### D65. The `Evaluator` class (`evaluator.py`) [now]
- **v1**: the `Evaluator` base class, implemented by `DockerEvaluator`.
- **OE**: `Evaluator`: cascade, artifacts, retries, LLM feedback.
- **SE**: the evaluation script itself, helped by `run_shinka_eval`.
- **Decision**: Runs the cascade (D9) on the host, each stage in a fresh sandbox session, and turns
  whatever happens into a `Result` (D73). It never raises for a program's sake.

  Attributes: `stages` (the stage functions, in order), `thresholds`, `stage_limit`, `output_features`
  (names, D17), `sandbox`, `visualize` (the evaluation file's function, or `None`).

  Methods:
  - `__init__(evaluation_path, problem, sandbox)`: loads the evaluation file (with v1's
    `load_score_function` approach: helper files next to it importable, then forgotten) and finds its stages.
  - `evaluate(code) -> Result`: the cascade.
  - `run_stage(stage, code) -> StageResult`: one stage in one session.
  - `checked(outcome, stage_number) -> StageResult`: validates what a stage returned.

  ```
  def __init__(self, evaluation_path, problem, sandbox):
      module_names = load_python_file(evaluation_path)          # v1's loader
      numbered = [module_names[f"evaluate_stage{k}"] for k in 1, 2, ... while it exists]
      self.stages = numbered or [module_names["evaluate"]]       # neither: ProblemError
      if len(problem.evaluation.thresholds) < len(self.stages) - 1:
          raise ProblemError("evaluation.thresholds needs one value per stage after the first")
      self.visualize = module_names.get("visualize")
      self.thresholds = problem.evaluation.thresholds
      self.stage_limit = problem.evaluation.stage_time_limit
      self.output_features = problem.output_feature_names
      self.sandbox = sandbox

  def evaluate(self, code):
      start, merged, feedback, error = now(), None, [], None
      for k, stage in enumerate(self.stages, start=1):
          try:
              outcome = self.checked(self.run_stage(stage, code), k)
          except InvalidProgram as e:                # any stage: openevolve scores it 0, here invalid
              return Result.failure(invalid, error=e.reason, feedback=join(feedback + [e.feedback]),
                                    duration=now() - start)
          except (ProgramFailure, CallTimeout, StageTimeout) as e:
              status = timeout if isinstance(e, (CallTimeout, StageTimeout)) else failed
              if merged is None:                     # stage 1: the program failed (D7)
                  return Result.failure(status, error=describe(e), feedback=join(feedback),
                                        duration=now() - start)
              error = f"stage {k}: {describe(e)}"    # a later stage: keep what earlier stages gave (D9)
              break
          except SandboxError as e:
              return Result.failure(error, error=f"sandbox: {e}", duration=now() - start)
          except Exception:                          # the evaluation file itself raised: not the program's fault
              return Result.failure(error, error=f"evaluator: {format_exc()}", duration=now() - start)
          merged = merge(merged, outcome, k)
          if outcome.feedback: feedback.append(outcome.feedback)
          if k < len(self.stages) and outcome.score < self.thresholds[k - 1]: break
      return Result(ok, score=merged.score, metrics=merged.metrics, features=merged.features,
                    feedback=join(feedback), error=error, output_data=merged.output_data,
                    stage_reached=merged.stage, duration=now() - start)

  def run_stage(self, stage, code):
      session = self.sandbox.start(code, self.stage_limit)     # ProgramFailure if loading fails
      try: return stage(ProgramNamespace(session))
      finally: session.close()

  def checked(self, outcome, k):
      if not isinstance(outcome, StageResult): raise EvaluatorBug("a stage must return StageResult")
      if isinstance(outcome.score, bool) or not isfinite(outcome.score): raise EvaluatorBug("score")
      if k == 1:
          for name in self.output_features:
              if not isfinite(outcome.features.get(name, nan)): raise EvaluatorBug(f"feature {name}")
      return outcome

  def merge(previous, outcome, k):               # D9
      if previous is None: return Merged(outcome.score, dict(outcome.metrics), dict(outcome.features),
                                         outcome.output_data, stage=1)
      return Merged(score=outcome.score, metrics={**previous.metrics, **outcome.metrics},
                    features=previous.features,                     # stage 1's only (D17)
                    output_data=outcome.output_data if outcome.output_data is not None
                                else previous.output_data, stage=k)
  ```

  `EvaluatorBug` is an ordinary exception, so it reaches the `except Exception` branch: status `error`.
  A `describe(e)` for `ProgramFailure` is its type and message, then the end of its traceback and of the
  program's error output, each cut to the prompt's size limit later (D67).

### D69. The `Storage` class (`storage.py`) [now]
- **v1**: `RunStorage`: appends to `programs.jsonl`, writes `best_program.py`, reads a run back.
- **OE**: `save` and `load` methods of `ProgramDatabase`, plus checkpoint folders.
- **SE**: the SQLite file itself, plus the generation folders written by the runner.
- **Decision**: Owns the run folder (D47). Only the main thread uses it (D36).

  `RunInfo` (the content of `run.json`, D50) attributes: `run_id`, `seed`, `fingerprints` (initial
  program, evaluation file, problem without `llm`, image), and `sessions` (a list: start and end time,
  git commit, command line, `llm` section, flags, system message, how it ended). Methods: `to_dict`,
  `from_dict`.

  `HistoryRow` (one line of `history.csv`): `iteration`, `completed` (the count of completed iterations),
  `program_id` (or empty), `status` (a `Status`, or `skipped` when the LLM call failed, or `error` when the
  iteration failed before having a child), `score`, `best_score`, `best_id`, `model`.

  `Storage` attributes: `folder` and the path of each file. Methods:
  - `is_new() -> bool`: no `programs.jsonl` yet.
  - `append_program(program)`; `append_llm_call(record)`; `append_history(row)`: one line each, flushed.
  - `write_best(program)`: rewrites `best_program.py`.
  - `write_snapshot(program, completed)`: `best/iteration_<completed, 4 digits>.py`.
  - `save_problem(path)`: copies the problem file to `problem.yaml`.
  - `read_run_info() -> RunInfo or None`; `write_run_info(info)`: `run.json`, rewritten whole, via a
    temporary file and a rename, so a crash never leaves half a file.
  - `load_programs() -> list of Program`; `load_history() -> list of HistoryRow`.

  ```
  def append_line(path, text):
      with open(path, "a", encoding="utf-8") as f: f.write(text + "\n"); f.flush(); fsync(f)

  def append_program(self, program): append_line(self.programs_path, json.dumps(program.to_dict()))

  def write_best(self, program):
      atomic_write(self.best_path, header(program) + program.code)

  def header(program):                    # D47: a comment that keeps the file a valid program
      return (f"# Best program: score {program.result.score}, iteration {program.iteration}\n"
              f"# Program id: {program.id}\n" +
              "".join(f"# {line}\n" for line in wrap(program.description or "")) + "\n")

  def load_jsonl(path, parse):            # v1's rule for a cut-off last line
      lines = read_text(path).splitlines() if exists(path) else []
      items = []
      for number, line in enumerate(lines, start=1):
          try: items.append(parse(json.loads(line)))
          except (JSONDecodeError, KeyError, TypeError):
              if number == len(lines): rewrite(path, lines[:-1]); break      # cut off by a crash
              raise StorageError(f"{path}, line {number}: cannot be read")
      return items

  def load_programs(self): return load_jsonl(self.programs_path, Program.from_dict)
  def load_history(self):  return load the CSV the same way (a cut-off last row is dropped)
  ```

  `llm_calls.jsonl` records: `iteration`, `program_id` (or `None` when skipped), `model`, `user` (the user
  message; the system message is saved once per session in `run.json`), `reply` (or `None`), the token
  counts, `duration`, `error` (or `None`).

### D78. Logging (`logs.py`) [now]
- **In the references**: v1 uses `print`; openevolve and ShinkaEvolve the `logging` module, with a file per run.
- **Decision**: One function, `setup_logging(folder, verbose)`, and module loggers
  (`logging.getLogger(__name__)`) everywhere else (D52).

  ```
  def setup_logging(folder, verbose):
      root = logging.getLogger("my_evolve"); root.setLevel(DEBUG)
      console = StreamHandler(stdout with UTF-8)            # D55: any character prints on Windows too
      console.setLevel(DEBUG if verbose else INFO)
      console.setFormatter("%(message)s")
      file = FileHandler(folder / "log.txt", mode="a", encoding="utf-8")
      file.setLevel(DEBUG); file.setFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
      root.addHandler(console); root.addHandler(file)
  ```

  The one line per iteration, at INFO: `iteration 42/100 · island 1 · qwen3-coder:30b · ok 0.912 · best
  0.951`. Details at DEBUG. No secret is ever passed to a logger (D46): keys are only read inside
  `OpenAICompatibleLLM`.

### D70. The loop (`loop.py`) [now]
- **v1**: the function `run_my_alphaevolve`.
- **OE**: the `OpenEvolve` controller and `ProcessParallelController`.
- **SE**: `ShinkaEvolveRunner`.
- **Decision**: A function, `run`, with the main thread doing all the bookkeeping and a small pool of
  daemon worker threads doing the waiting (LLM calls and evaluations, D36).

  `RunSettings` attributes (the flags, D45): `initial_program`, `evaluation_file`, `problem_file`,
  `iterations`, `output`, `workers`, `seed`, `target_score`, `patience`, `unsafe_local_sandbox`, `verbose`.

  `WorkerPool`: `workers` daemon threads reading tasks from one queue and putting results on another, so
  a second Ctrl+C never waits for them (fixing Part D, v1 item 1). Methods: `submit(kind, iteration,
  function, *args)`; `next_result(timeout) -> TaskResult or None` (`kind`, `iteration`, `value` or
  `exception`).

  `IterationState` attributes: `number`, `island`, `parent`, `examples`, `model`, `prompt`,
  `parsed` (after the proposal), `checks` (`CheckOutcome`).

  Functions of `loop.py`:
  - `run(settings) -> Database`: the whole run.
  - `prepare(settings, problem, storage) -> Context`: everything before the first iteration.
  - `start_iteration(context, number) -> IterationState`: the main thread's first part.
  - `propose(model, prompt, parent_code) -> (LLMReply, ParsedReply)`: in a worker.
  - `after_proposal(context, state, result)`: back in the main thread.
  - `finish(context, state, child)`: stores a child and does everything that follows.
  - `skip(context, state, error)`: an iteration without a child.
  - `should_stop(context) -> reason or None` (D37).
  - `summary(context)`: the end summary (D51).

  ```
  def run(settings):
      problem = Problem.load(settings.problem_file)
      storage = Storage(settings.output)
      setup_logging(storage.folder, settings.verbose)
      context = prepare(settings, problem, storage)
      pool = WorkerPool(settings.workers)
      in_flight = {}                          # iteration number -> IterationState
      stopping, reason = False, None
      install a SIGTERM handler (Linux) that raises Terminate
      try:
          while True:
              while not stopping and len(in_flight) < settings.workers \
                      and context.started < settings.iterations:
                  context.started += 1
                  try: state = start_iteration(context, context.started)
                  except NoModelLeft: stopping, reason = True, "no LLM model left"; break
                  in_flight[state.number] = state
                  pool.submit("proposal", state.number, propose, state.model, state.prompt,
                              state.parent.code)
              if not in_flight: break
              task = pool.next_result(timeout=0.2)    # short waits, so Ctrl+C reaches the main thread (D53)
              if task is None: continue
              state = in_flight[task.iteration]
              if task.kind == "proposal":
                  if after_proposal(context, state, task) == "evaluating":
                      pool.submit("evaluation", state.number, context.evaluator.evaluate, state.parsed.code)
                      continue
              else:
                  child = child_program(state, result=task.value) if task.exception is None \
                          else child_program(state, Result.failure(error, error=describe(task.exception)))
                  finish(context, state, child)
              del in_flight[task.iteration]
              if not stopping and (reason := should_stop(context)): stopping = True
      except KeyboardInterrupt:                   # first Ctrl+C: finish what is in flight (D53)
          log.info("Stopping: finishing the iterations in progress (Ctrl+C again to stop now)")
          reason = "Ctrl+C"
          try: drain(pool, in_flight, context)    # the same handling as above, starting nothing new
          except (KeyboardInterrupt, Terminate):  # second Ctrl+C or SIGTERM: stop now (D54)
              context.sandbox.remove_leftovers(); reason = "interrupted"
      except Terminate:
          context.sandbox.remove_leftovers(); reason = "interrupted"
      finally:
          context.sandbox.remove_leftovers()
          record the session's end and reason in run.json
      summary(context, reason)
      return context.database                     # daemon worker threads are not waited for

  def prepare(settings, problem, storage):
      info = storage.read_run_info()
      fingerprints = {initial program, evaluation file, problem.fingerprint_without_llm(), image tag}
      if info is None:
          info = RunInfo(run_id=new_uuid(), seed=settings.seed if settings.seed is not None
                         else random_seed(), fingerprints=fingerprints, sessions=[])
          storage.save_problem(settings.problem_file)
      elif info.fingerprints != fingerprints:
          raise RunError("this folder holds a run of a different problem: " + what changed)   # D50
      sandbox = LocalSandbox(info.run_id) if settings.unsafe_local_sandbox \
                else DockerSandbox(info.run_id, problem.sandbox, ensure_image(problem.packages))
      if settings.unsafe_local_sandbox: log.warning("programs run WITHOUT isolation")
      sandbox.remove_leftovers()                                          # D42
      evaluator = Evaluator(settings.evaluation_file, problem, sandbox)
      models = [OpenAICompatibleLLM(m) for m in problem.llm.models]
      initial_code = read_text(settings.initial_program)
      if storage.is_new():
          initial = evaluate_initial(initial_code, problem, evaluator)   # refuses to start unless ok (D20)
          rng = Random(info.seed)
          database = Database(problem, initial, rng)
          for p in [initial] + database.seed_islands(initial):
              database.add(p); storage.append_program(p)
          storage.write_best(initial); storage.write_snapshot(initial, 0)
          completed = 0
      else:
          programs, history = storage.load_programs(), storage.load_history()
          rng = Random(hash_seed(info.seed, len(programs)))               # D39
          database = Database(problem, programs[0], rng); database.replay(programs)
          completed = len(history)
      ensemble = Ensemble(models, rng, problem.llm.max_failures_in_a_row)
      ensemble.check_all()                       # D34: any failure stops the run here
      builder = PromptBuilder(problem)
      info.sessions.append(Session(start=now(), commit=git_commit(), command=argv, llm=problem.llm,
                                   flags=settings, system=builder.system_message))
      storage.write_run_info(info)
      return Context(settings, problem, storage, database, evaluator, sandbox, ensemble, builder, initial_code,
                     completed=completed, started=completed, errors_in_a_row=0)

  def evaluate_initial(code, problem, evaluator):
      try: split_evolve_blocks(code)
      except MarkerError as e: raise RunError(f"the initial program's evolve blocks are not valid: {e}")
      outcome = check_child(code, code, problem.entry_functions, {})
      if outcome.rejection: raise RunError(f"the initial program is not usable: {outcome.rejection}")
      result = evaluator.evaluate(code)
      if not result.is_ok: raise RunError(f"the initial program got status {result.status}: {result.error}")
      return Program(id=new_uuid(), code=code, result=result, origin=initial, parent_id=None, island=None,
                     iteration=0, generation=0, description=None, fingerprint=outcome.fingerprint,
                     code_complexity=outcome.code_complexity, example_ids=[], llm=None, created_at=now())

  def start_iteration(context, number):
      db = context.database
      island = db.sample_island()
      parent = db.sample_parent(island)
      examples = db.sample_examples(island, parent, context.problem.prompt.example_programs)
      model = context.ensemble.draw()            # NoModelLeft if every model was dropped
      prompt = context.builder.build(parent, examples, db.best().result.score)
      return IterationState(number, island.index, parent, examples, model, prompt)

  def propose(model, prompt, parent_code):        # in a worker thread
      reply = model.complete(prompt)              # LLMError if no reply
      return reply, parse_reply(reply.text, parent_code)

  def after_proposal(context, state, task):
      if isinstance(task.exception, LLMError):
          context.ensemble.record_failure(state.model.name)
          context.storage.append_llm_call(call_record(state, None, task.exception))
          skip(context, state, status="skipped", error=str(task.exception))     # still counts (D34)
          return "done"
      if task.exception is not None:              # anything else: an infrastructure error (D38)
          skip(context, state, status="error", error=describe(task.exception))
          return "done"
      reply, state.parsed = task.value
      context.ensemble.record_success(state.model.name)
      state.checks = check_child(state.parsed.code, context.initial_code,
                                 context.problem.entry_functions, context.database.fingerprints)
      state.reply = reply
      if state.checks.rejection:
          finish(context, state, child_program(state, Result.rejected(state.checks.rejection)))
          return "done"
      return "evaluating"

  def child_program(state, result):
      return Program.new_child(state.parent, code=state.parsed.code or "", result=result,
                               island=state.island, iteration=state.number,
                               description=state.parsed.description,
                               fingerprint=state.checks.fingerprint if state.checks else None,
                               code_complexity=state.checks.code_complexity if state.checks else None,
                               example_ids=[e.id for e in state.examples],
                               llm=LLMUsage(state.reply.model, state.reply.input_tokens,
                                            state.reply.output_tokens, state.reply.duration))

  def finish(context, state, child):
      db, storage = context.database, context.storage
      context.completed += 1
      best_before = db.best_id
      db.add(child, completed=context.completed)
      storage.append_program(child)
      storage.append_llm_call(call_record(state, child, None))
      context.errors_in_a_row = context.errors_in_a_row + 1 if child.result.status == error else 0
      if db.best_id != best_before: storage.write_best(db.best())
      storage.append_history(HistoryRow(state.number, context.completed, child.id, child.result.status,
                                        child.result.score, db.best().result.score, db.best_id,
                                        state.model.name))
      log.info(iteration line)
      after_completion(context)

  def skip(context, state, status, error):
      context.completed += 1
      if status == "error": context.errors_in_a_row += 1
      context.storage.append_history(HistoryRow(state.number, context.completed, None, status, None,
                                                context.database.best().result.score,
                                                context.database.best_id, state.model.name))
      log.info(iteration line with the error)
      after_completion(context)

  def after_completion(context):
      p, n = context.problem, context.completed
      if n % p.snapshot_every == 0: context.storage.write_snapshot(context.database.best(), n)
      if n % p.islands.migration_interval == 0:
          for arrival in context.database.migrate(iteration=n): context.storage.append_program(arrival)

  def should_stop(context):                                  # D37 (the iteration total is the loop's own test)
      s, db = context.settings, context.database
      if s.target_score is not None and db.best().result.score >= s.target_score: return "target score reached"
      if s.patience is not None and context.completed - db.best_changed_at >= s.patience: return "patience ran out"
      if context.errors_in_a_row >= context.problem.max_errors_in_a_row: return "too many errors in a row"
      if not context.ensemble.active: return "no LLM model left"
      return None
  ```

  `drain` runs the same handling as the main loop (`after_proposal`, evaluation, `finish`) for the
  iterations in flight, without starting new ones. `summary` writes the end summary of D51 to the console
  and `log.txt`: iterations done, the reason, the best score and its iteration, counts by status, tokens
  and cost per model (D35, from the `llm` fields of the programs and the prices of the `llm` section).

### D79. The command line and the report (`scripts/run.py`, `scripts/report.py`) [now]
- **In the references**: v1's `scripts/run.py`; openevolve's `cli.py` and Flask visualizer;
  ShinkaEvolve's `shinka_run` and WebUI.
- **Decision**: Two scripts; neither holds logic that a test would need, which lives in the package.

  `scripts/run.py`:
  - `parse_arguments(argv) -> RunSettings`: argparse with the positional `INITIAL_PROGRAM` and
    `EVALUATION_FILE` and the flags of D45; every value checked (`--iterations >= 1`, `--workers >= 1`,
    `--patience >= 1`, files exist), `parser.error` otherwise.
  - `main()`: reconfigures stdout and stderr to UTF-8 (D55), builds `RunSettings`, calls `run`, and turns
    `ProblemError`, `RunError`, `SandboxError` and `ConfigurationError` into one clear message and exit
    code 1, without a traceback.
  - `default_output(problem_name) -> Path`: `runs/<name>_<YYYYmmdd_HHMMSS>` (D45).

  `scripts/report.py RUN_FOLDER` (D51), functions of `my_evolve/report.py`:
  - `load_run(folder) -> (Problem, programs, history, evaluation file)`: from `problem.yaml`,
    `programs.jsonl`, `history.csv`, and the evaluation file's path recorded in `run.json` (D50).
  - `plot_progress(history, programs, path)`: the best score so far against the completed-iteration count
    as a step line, every `ok` child's score as a dot.
  - `grid_snapshots(problem, programs, history) -> list of (completed, list of grids)`: replays the run
    and keeps a copy of every island's grid after every k completed iterations and at the end.
  - `colour_scale(programs) -> (low, high)`: the lowest and highest `ok` scores of the whole run.
  - `draw_grids(snapshot, scale, path)`: one panel per island; empty cells white, others coloured on the
    `Blues` colour map from light (low) to deep (high).
  - `animate(snapshot images, path)`: the snapshots as one animated GIF.
  - `draw_outputs(evaluation_file, snapshots, path)`: calls the evaluation file's `visualize(output_data,
    path)` for the best program of every snapshot, when it defines one (circle packing does).

  ```
  def grid_snapshots(problem, programs, history):
      database = Database(problem, programs[0], Random(0))     # a replay draws nothing
      completed_at = {row.program_id: row.completed for row in history if row.program_id}
      due = sorted(row.completed for row in history if row.completed % problem.snapshot_every == 0)
      grids = lambda: [deepcopy(island.grid) for island in database.islands]
      snapshots = []
      for program in programs:
          n = completed_at.get(program.id)              # None for the initial program, copies, migrants
          while n is not None and due and due[0] < n:   # due after a skipped iteration: nothing changed since
              snapshots.append((due.pop(0), grids()))
          database.add(program)
          if n is not None and due and due[0] == n: snapshots.append((due.pop(0), grids()))
      snapshots += [(n, grids()) for n in due]           # skipped iterations at the very end
      snapshots.append(("end", grids()))
      return snapshots

  def draw_grids(snapshot, scale, path):
      completed, grids = snapshot
      figure with one panel per island, titled "island i"
      for each grid: shape = [f.bins for f in grid.features]
          values = full(shape, nan); for cell, elite in grid.elites.items(): values[cell] = elite.result.score
          1D: one row of cells; 2D: a square (first feature across, second up);
          3D: one square per bin of the third feature, side by side
          imshow with the Blues colour map, normalized to scale, nan cells drawn white, a colour bar
      title "after iteration {completed}"; save to path

  def draw_outputs(evaluation_file, snapshots, folder):
      visualize = load_python_file(evaluation_file).get("visualize")   # loaded on the host, trusted
      if visualize is None: return
      for completed, best in best program of each snapshot:
          if best.result.output_data is not None:
              visualize(best.result.output_data, folder / f"output_{completed:04d}.png")
  ```

  Circle packing's `visualize(output_data, path)` draws the unit square and each circle (centre, radius,
  number) with matplotlib and the title "n=26, sum of radii=…", as openevolve's `visualize` does, but
  saves to `path` instead of showing a window.

---

## 15. Smaller features: yes or no

Each one is a self-contained step that can be added late. [later] for all; decided in the last column.

| Feature | v1 | OE | SE | Lean | Decision |
|---|---|---|---|---|---|
| Target score stop (D37) | no | yes | no | yes | yes, `--target-score` (D37) |
| Early stopping on no improvement (D37) | no | yes | no | yes | yes, `--patience` (D37) |
| Token usage recorded and summed (D35) | no | yes | yes | yes | yes (D35) |
| Token or dollar budget stop (D35) | no | no | yes (dollars) | later | no (D35) |
| Code-length limit (D13) | no | yes | no | yes | no: D13's four checks only |
| Arguments passed to the evaluator from the config | no | yes | yes | no | no: constants live in the evaluation file |
| LLM-as-judge scores | no | yes | no | no | no |
| Embedding-based novelty filter (D24) | no | yes | yes | later | no (D24) |
| Random wording variations in prompts | no | yes | no | no | no (D29) |
| Per-island system messages | no | yes | no | no | no |
| "Changes description" mode for large codebases | no | yes | no | no | no |
| Several LLM providers besides OpenAI-compatible | no | yes | yes | no | no (D32) |
| Human-in-the-loop "manual mode" | no | yes | no | no | no |
| Library API usable from a notebook | partly | yes | yes | yes, a single `run(...)` | yes: the `run(...)` function (D70) |
| Evolution trace for RL training | no | yes | no | no (D48 covers analysis) | no: `programs.jsonl` and `llm_calls.jsonl` hold the same data (D47) |
| Web visualizer | no | yes | yes | later, maybe | no: the report script instead (D51) |
| Crossover of two programs (D11) | no | no | yes | later | no for now; a possible later experiment |
| Several full-rewrite strategies drawn at random (D11) | no | no | yes | later | no for now; a possible later experiment |
| LLM writes the initial program | no | no | yes | no | no: the initial program must work (D20) |
| Evolving the system prompt itself | no | no | yes | no | no |
| New islands when the search stagnates (D23) | no | no | yes | no | no (D23) |
| Public and private metrics (D6) | no | no | yes | no | no |
| Repeated runs with statistical early stop in the evaluator (D9) | no | no | yes | no | no: openevolve's cascade (D9) |
| Plots saved per program by the evaluator | no | no | yes | no | no: the report draws from `output_data` (D51) |
| Slurm cluster backends (D40) | no | no | yes | no | no (D40) |
| Weights & Biases logging | no | no | yes | no | no |
| Hydra presets (D43) | no | no | yes | no | no (D43, D44) |
| Skills that teach a coding agent to set up and run tasks | no | no | yes | no | no |

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
