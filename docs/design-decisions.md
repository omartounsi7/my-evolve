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

How the decisions above become code: every module, class, attribute and method, and the algorithm of
every function as numbered steps in plain language. Records (`Problem`, `Result`, `Program`, ...) are
plain dataclasses; state derived from them lives in `Database`, never on the records.

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

### D72. The `Problem` class and its settings (`problem.py`) [now]
- **In the references**: v1 has a small `Problem` (initial code, evaluation path, description from the
  docstring, packages from `requirements.txt`); openevolve has `Config` with nested dataclasses loaded by
  `dacite`; ShinkaEvolve has `EvolutionConfig`, `DatabaseConfig` and job configs.
- **Decision**: The problem file (D43, D44) loaded into nested dataclasses, every value checked.

  **Sections of the problem file**, with their defaults:

  | Section | Keys (default) |
  |---|---|
  | top level | `name` (required), `description` (required; includes the entry functions' contract, D4), `entry_functions` (required, e.g. `[run_packing]`), `packages` (list of `name==version`, empty), `snapshot_every` (10, D47), `max_errors_in_a_row` (3, D38) |
  | `evaluation` | `stage_time_limit` (60 s, D41), `thresholds` (list: stage k+1 runs if stage k's score reaches the k-th value, D9) |
  | `sandbox` | `memory` (`1g`), `cpus` (1), `max_processes` (64), D41 |
  | `grid` | `features`: a list of `name`, `low`, `high`, `bins`; default one feature, `code_complexity` from −1 to +3; default bins 10, 5 or 3 for one, two or three features (D17, D18) |
  | `islands` | `count` (3), `migration_interval` (25), `migration_share` (0.1), `migrants` (`random_non_best`, or `best`, `random`), `destinations` (`all_others`, or `ring`), `mode` (`copy`, or `move`), D23 |
  | `parents` | `strategy` (`weighted`, or `openevolve`), `lambda` (1.0), `archive_size` (10), D19, D21 |
  | `prompt` | `example_programs` (2, D26), `max_chars` (60,000, D30), `max_feedback_chars` (2,000, D10) |
  | `llm` | values shared by every model (`api_base`, `max_tokens` 16,384, `temperature`, `reasoning_effort`, `timeout` 300 s, `retries` 2, prices), `max_failures_in_a_row` (3), and `models`: a list of `name`, `weight` and any of the shared keys, which override them for that model (D31–D35, D46) |

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

### D73. The `Result` class and `Status` (`program.py`) [now]
- **In the references**: v1 has a bare float; openevolve a metrics dict or `EvaluationResult(metrics,
  artifacts)`; ShinkaEvolve `metrics.json` plus `correct.json`.
- **Decision**: D6 and D7 as classes.

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

### D60. The `Program` class (`program.py`) [now]
- **v1**: a small class: `id`, `code`, `score`, `parent_id`, `generation`, `iteration`, with `to_dict` / `from_dict`.
- **OE**: a dataclass with the evaluation flattened into it and a free-form `metadata` dict holding the
  island, the diff summary, the parent's metrics, token usage and a migrant flag.
- **SE**: a dataclass mapped onto a SQLite table, also flattened, with database state on it
  (`in_archive`, `children_count`, `migration_history`) and a `metadata` dict.
- **Decision**: A dataclass of facts fixed once the program exists, with no free-form `metadata` dict and
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
  | `iteration` | the iteration that produced it: 0 for the initial program and its copies; a migrant gets the iteration of its migration |
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

### D74. The check functions (`checks.py`) [now]
- **In the references**: v1 has none; openevolve has `enforce_evolve_blocks` (reverts) and code-length
  checks; ShinkaEvolve has `validate_evolve_markers` and its patch errors.
- **Decision**: Plain functions (D13), used by the loop's main thread and for the initial program. A
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

### D68. Reply parsing (`reply_parser.py`) [now]
- **v1**: functions in `reply_parser.py`.
- **OE**: functions in `utils/code_utils.py`.
- **SE**: functions in `edit/` (`apply_full_patch`, `apply_diff_patch`).
- **Decision**: Functions, not a class, reusing v1's rules. `ParsedReply` holds `code` and `description`,
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

### D67. The `PromptBuilder` class (`prompt.py`) [now]
- **v1**: `PromptSampler`: one template, filled with the description, the parent and the allowed packages.
- **OE**: `PromptSampler` with a `TemplateManager` over text files.
- **SE**: `PromptSampler`, with one prompt module per change format.
- **Decision**: Builds the two messages of Appendix A (D25, D26, D27, D10). The module also holds the
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

### D66. The `LLM` classes (`llm.py`) [now]
- **v1**: an `LLM` base class with one method, `generate`, and an `OpenAICompatibleLLM` implementation.
- **OE**: `LLMInterface`, implemented per provider, and `LLMEnsemble` on top.
- **SE**: `LLMClient` and `AsyncLLMClient`, over one module per provider.
- **Decision**: An abstract `LLM`, one implementation per model, and an `Ensemble` that the loop always
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

### D61. The `Grid` class (`grid.py`) [now]
- **v1**: none on `main` (`aeaf384` rebuilt a grid from all programs at each sample).
- **OE**: a dict per island from a cell key to a program id, inside `ProgramDatabase`.
- **SE**: no grid.
- **Decision**: One fixed MAP-Elites grid (D17, D18).

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

### D62. The `Island` class (`database.py`) [now]
- **OE**: sets of program ids, alongside the grids, inside `ProgramDatabase`.
- **SE**: an `island_idx` column, managed by an `IslandManager` and migration strategy classes.
- **Decision**: An island's number, its grid and the list of every program made on it.

  Attributes: `index`, `grid` (its `Grid`), `program_ids` (every program made on the island, in order;
  where example programs are drawn from, D26).

  Methods: `elites()`, the island's population (D23): its grid's elites; `best()`: its grid's best.

### D75. The parent selectors (`database.py`) [now]
- **In the references**: v1's rule inside `Database.sample`; openevolve's inside
  `ProgramDatabase.sample_from_island`; ShinkaEvolve's `CombinedParentSelector` and strategy classes.
- **Decision**: An abstract `ParentSelector` with one method, `choose(island, database, rng)`, and the two
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

### D63. The `Database` class (`database.py`) [now]
- **v1**: `Database`: a flat dict of programs and the 70/30 parent choice.
- **OE**: `ProgramDatabase`, 2,800 lines: islands, grids, archive, migration, sampling, saving, artifacts.
- **SE**: `ProgramDatabase` over SQLite, with separate classes for parents, islands and inspirations.
- **Decision**: All of the run's state that is derived from its programs. Only the main thread uses it
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
  1. Take every program made on the island except the parent, programs with status `error` and children
     without code.
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

### D76. The evaluation API (`evaluation_api.py`) [now]
- **In the references**: v1's `evaluate(namespace)` returns a float; openevolve's evaluators return a
  dict or an `EvaluationResult` and call `run_with_timeout`; ShinkaEvolve's call `run_shinka_eval`.
- **Decision**: What an evaluation file imports, and the contract of its functions.

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

### D77. The sandbox protocol and worker (`sandbox_protocol.py`, `sandbox_worker.py`) [now]
- **In the references**: v1 passes the code on stdin and reads one JSON result line from stdout
  (`container_worker.py`); openevolve and ShinkaEvolve have nothing similar.
- **Decision**: One JSON message per line between the host and the worker, which answers calls for as
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

### D64. The `Sandbox` classes (`sandbox.py`) [now]
- **v1**: `DockerEvaluator`, plus the `container_worker` module that runs inside the container.
- **OE**: none.
- **SE**: `JobScheduler` and the `launch` modules (local processes, Slurm).
- **Decision**: A sandbox starts one session per cascade stage (D40). A session is one worker process,
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

### D65. The `Evaluator` class (`evaluator.py`) [now]
- **v1**: the `Evaluator` base class, implemented by `DockerEvaluator`.
- **OE**: `Evaluator`: cascade, artifacts, retries, LLM feedback.
- **SE**: the evaluation script itself, helped by `run_shinka_eval`.
- **Decision**: Runs the cascade (D9) on the host, each stage in a fresh sandbox session, and turns
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

### D69. The `Storage` class (`storage.py`) [now]
- **v1**: `RunStorage`: appends to `programs.jsonl`, writes `best_program.py`, reads a run back.
- **OE**: `save` and `load` methods of `ProgramDatabase`, plus checkpoint folders.
- **SE**: the SQLite file itself, plus the generation folders written by the runner.
- **Decision**: Owns the run folder (D47). Only the main thread uses it (D36).

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

### D78. Logging (`logs.py`) [now]
- **In the references**: v1 uses `print`; openevolve and ShinkaEvolve the `logging` module, with a file per run.
- **Decision**: One function, `setup_logging(folder, verbose)`, and a logger per module everywhere else (D52).

  **`setup_logging(folder, verbose)`**:
  1. The package's logger lets everything through.
  2. A console handler, writing UTF-8 (D55), shows the message alone; it shows the details too only with
     `verbose`.
  3. A file handler appends everything to `log.txt` in the run folder, with the time, the level and the
     module.

  The one line per iteration on the console: iteration and total, island, model, the child's status and
  score, the best score so far. No secret is ever logged (D46): keys are only read inside
  `OpenAICompatibleLLM`.

### D70. The loop (`loop.py`) [now]
- **v1**: the function `run_my_alphaevolve`.
- **OE**: the `OpenEvolve` controller and `ProcessParallelController`.
- **SE**: `ShinkaEvolveRunner`.
- **Decision**: A function, `run`, with the main thread doing all the bookkeeping and a small pool of
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

### D79. The command line and the report (`scripts/run.py`, `scripts/report.py`, `report.py`) [now]
- **In the references**: v1's `scripts/run.py`; openevolve's `cli.py` and Flask visualizer;
  ShinkaEvolve's `shinka_run` and WebUI.
- **Decision**: Two scripts; any logic a test would need lives in the package.

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
