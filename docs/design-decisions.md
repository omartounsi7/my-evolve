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
- **Decision**: openevolve's cascade. The evaluation file defines `evaluate_stage1(namespace)`, `evaluate_stage2(namespace)`, … (a file with only `evaluate(namespace)` is a one-stage cascade), and the problem file lists the thresholds. A program goes to the next stage only if the previous stage's score reaches its threshold; metrics of later stages overwrite earlier ones; a later stage that fails keeps the earlier stages' result, as in openevolve. The result object records the stage reached. Each stage starts from a freshly loaded program (D8). Features always come from stage 1, so every program's features are measured the same way, whichever stage it reached (D17). Cascades of our two problems, copied from openevolve (60 s per stage in both): function minimization: stage 1 = one call of `run_search` (5 s limit), threshold 1.3, stage 2 = 10 calls (5 s each), whose score replaces stage 1's; circle packing: stage 1 = one call of `run_packing`, scored as the sum of the radii divided by 2.635 if the packing is valid, threshold 0.5, stage 2 = openevolve's full evaluation (a second call, scored the same way). openevolve's second circle-packing threshold, 0.75, never applies, since there is no third stage.

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
- **Decision**: Besides the parent, the prompt shows a number of other programs, called example programs ("inspirations" in openevolve and ShinkaEvolve), set in the problem file, 2 by default. They are working programs and failed ones alike, presented without any "positive" or "negative" label: the prompt calls them previous attempts, and the LLM judges from each one's score or status, description, feedback and, for a failed one, its error (D10) whether to follow it. The programs are drawn randomly from the same island.

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

How the decisions above become code. Each class has one job; the decisions it implements are named.
Records are plain dataclasses; state derived from them lives in `Database`, never on the records.

### D60. The `Program` class [now]
- **v1**: a small class: `id`, `code`, `score`, `parent_id`, `generation`, `iteration`, with `to_dict` / `from_dict`.
- **OE**: a dataclass with the evaluation flattened into it (`metrics` dict, `complexity`, `diversity`,
  `changes_description`, `prompts`, artifacts, `embedding`) and a free-form `metadata` dict holding the
  island, the diff summary, the parent's metrics, token usage and a migrant flag.
- **SE**: a dataclass mapped onto a SQLite table, also flattened (`combined_score`, `public_metrics`,
  `text_feedback`, `correct`, ...), with database state on it (`in_archive`, `children_count`,
  `migration_history`) and a `metadata` dict.
- **Decision**: A dataclass of facts fixed once the program exists, with no free-form `metadata` dict and
  no database state on it:
  - `id`: a UUID.
  - `code`: the full file.
  - `result`: its `Result` (D6), kept as one object.
  - `parent_id`: `None` for the initial program; for a copy, the program it was copied from.
  - `origin`: `initial`, `llm` (written by the LLM) or `copy` (the initial program placed on an island, or a
    migrant); D13's checks and D19's children count apply to `llm` programs only.
  - `island`: the island it was made on (D23).
  - `iteration`: the iteration that produced it; a copy gets the iteration of its migration.
  - `generation`: its distance from the initial program.
  - `description`: the LLM's self-contained description (D15).
  - `fingerprint`: the hash of its syntax tree (D13), `None` if it does not compile.
  - `code_complexity`: its node count inside the evolve blocks (D17); the output features are in `result.features`.
  - `example_ids`: the programs shown in its prompt (D26).
  - `llm`: the model used and its token counts (D35); prompt and reply are stored separately (D48).
  - `created_at`: when it was made.

  Grid cells, elite status, the archive and children counts are derived by `Database` (D63), never stored here.

### D61. The `Grid` class [now]
- **v1**: none on `main` (`aeaf384` rebuilt a grid from all programs at each sample).
- **OE**: a dict per island from a cell key to a program id, inside `ProgramDatabase`.
- **SE**: no grid.
- **Decision**: One MAP-Elites grid with fixed dimensions from the problem file (features, ranges, bins,
  D17, D18). It computes a program's cell from its `code_complexity` and `result.features`, holds the elite
  of each cell, places a program (it takes the cell if the cell is empty or its score is strictly higher)
  and lists its elites. Only `ok` programs are placed (D7).

### D62. The `Island` class [now]
- **OE**: sets of program ids, alongside the grids, inside `ProgramDatabase`.
- **SE**: an `island_idx` column, managed by an `IslandManager` and migration strategy classes.
- **Decision**: An island's number and its `Grid`; its population is its grid's elites (D23). It gives its
  best elite and its elites for parent selection and migration.

### D63. The `Database` class [now]
- **v1**: `Database`: a flat dict of programs and the 70/30 parent choice.
- **OE**: `ProgramDatabase`, 2,800 lines: islands, grids, archive, migration, sampling, saving, artifacts.
- **SE**: `ProgramDatabase` over SQLite, with separate classes for parents, islands and inspirations.
- **Decision**: Every program of the run (D22), the islands, the set of fingerprints (D13) and the
  children counts (D19). It adds programs (placing `ok` ones on their island's grid), computes the archive
  on demand (D21), migrates (D23), and draws parents through a strategy interface with two
  implementations, ShinkaEvolve's weighted rule and openevolve's rule (D19). Example programs (D26) are drawn
  here too. Rebuilt on resume by replaying the saved programs in order (D49); only the main thread changes it (D36).

### D64. The `Sandbox` class [now]
- **v1**: `DockerEvaluator`, plus the `container_worker` module that runs inside the container.
- **OE**: none.
- **SE**: `JobScheduler` and the `launch` modules (local processes, Slurm).
- **Decision**: A fresh Docker container for each cascade stage of a program, and after a call over its time limit (D40, with D41's limits): it loads the
  program in the container, gives the evaluator the namespace stand-in, and runs each call in the
  container, with plain data in and out and an optional time limit per call; a call over its limit kills
  the container and the next call starts a fresh one (D8). So each cascade stage gets a freshly loaded
  program (D9). It always removes its containers, even on Ctrl+C (D42). A worker module runs inside the
  container, as in v1.

### D65. The `Evaluator` class [now]
- **v1**: the `Evaluator` base class, implemented by `DockerEvaluator`.
- **OE**: `Evaluator`: cascade, artifacts, retries, LLM feedback.
- **SE**: the evaluation script itself, helped by `run_shinka_eval`.
- **Decision**: Loads the problem's evaluation file on the host, runs its cascade stages through a
  `Sandbox` (D9), enforces each stage's time limit, and turns what happens into a `Result`
  (D6, D7): status, score, metrics, features, feedback (D10), error, stage reached and duration.

### D66. The `LLM` class [now]
- **v1**: an `LLM` base class with one method, `generate`, and an `OpenAICompatibleLLM` implementation.
- **OE**: `LLMInterface`, implemented per provider, and `LLMEnsemble` on top.
- **SE**: `LLMClient` and `AsyncLLMClient`, over one module per provider.
- **Decision**: An abstract class with one method that turns the prompt's messages into a reply, with its token counts (D35) and the name of the model that wrote it (D60). Implemented by `OpenAICompatibleLLM` (one model, D32) and by `Ensemble` (several `OpenAICompatibleLLM`s drawn by weight, which also drops failing models, D31, D34).

### D67. The `PromptBuilder` class [now]
- **v1**: `PromptSampler`: one template, filled with the description, the parent and the allowed packages.
- **OE**: `PromptSampler` with a `TemplateManager` over text files.
- **SE**: `PromptSampler`, with one prompt module per change format.
- **Decision**: Builds the system and user messages of Appendix A (D25): the instruction, the problem's description and contract (D4), the rules (evolve blocks, D12; allowed packages, D71; higher is better), the reply format (D15), then the example programs and the parent with their scores or statuses, descriptions, feedback and errors (D10, D26, D27), and the request. Templates are Python constants (D29).

### D68. Reply parsing [now]
- **v1**: functions in `reply_parser.py`.
- **OE**: functions in `utils/code_utils.py`.
- **SE**: functions in `edit/` (`apply_full_patch`, `apply_diff_patch`).
- **Decision**: Functions, not a class: they extract the description (between `<DESCRIPTION>` and `</DESCRIPTION>`) and the code (a fenced Python block) from a reply, wherever they appear in it; anything else the LLM writes around them is ignored. The code is found with v1's rules (dropping thinking sections, preferring valid Python, then the longest block). A reply without code is rejected (D13); one without a description is accepted (D15).

### D69. The `Storage` class [now]
- **v1**: `RunStorage`: appends to `programs.jsonl`, writes `best_program.py`, reads a run back.
- **OE**: `save` and `load` methods of `ProgramDatabase`, plus checkpoint folders.
- **SE**: the SQLite file itself, plus the generation folders written by the runner.
- **Decision**: Owns the run folder and its files (D47): appends each program to `programs.jsonl` the moment it is stored, each LLM call to `llm_calls.jsonl` and each completed iteration to `history.csv`; rewrites `best_program.py` and writes the snapshots in `best/`; writes `run.json` and `problem.yaml` (D50); and reads everything back for a resume (D49).

### D70. The loop [now]
- **v1**: the function `run_my_alphaevolve`.
- **OE**: the `OpenEvolve` controller and `ProcessParallelController`.
- **SE**: `ShinkaEvolveRunner`.
- **Decision**: A function, `run`, taking the `Problem`, an `LLM` and the run's settings. It picks an
  island and a parent, builds the prompt, asks the LLM, parses the reply, runs the checks (D13), evaluates
  the child, stores it, migrates when due, and stops when D37 says so, with several iterations at once in
  threads (D36). Only its main thread touches the `Database` and the `Storage`; Ctrl+C is handled here (D53, D54).

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
- The order of the previous attempts is still to be decided (D26).

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
