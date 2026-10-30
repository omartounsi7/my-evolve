# Examples

Ready-made problems, one folder each. Each holds the three files a run needs: the
initial program, its evaluation file, and the problem file.

| Problem | Folder |
|---|---|
| Circle packing: 26 circles in the unit square, maximizing the sum of their radii | `circle_packing/` |
| Function minimization: the global minimum of a function with many local minima | `function_minimization/` |
| Circle packing at full precision, for going past the best packing known | `circle_packing_precise/` |

`circle_packing_precise/` is my-evolve's own; the others are OpenEvolve's. Its score is
the sum of the radii itself, of legal geometry only (a violation is subtracted from every
radius rather than tolerated), with no reference dividing it; neither its evaluation nor
its prompt refers to any earlier result. Its initial program is OpenEvolve's, without the
comment naming AlphaEvolve's score, and its problem file gives each program one stage of
5 minutes and 4 CPUs, Claude's models, and a 3D grid. Its scores are sums of radii, not
`circle_packing/`'s ratios.

The other problems are OpenEvolve's, so that runs start from the same baseline as
OpenEvolve's and can be compared with them (D3).

- Source: OpenEvolve, commit `da3d7011d6b87bf139f3291108be51536685828f`.
- Licence: Apache License 2.0, copied in [LICENSE-openevolve](LICENSE-openevolve).

What is the same as in OpenEvolve:

- **The initial programs**: OpenEvolve's files, unchanged, `EVOLVE-BLOCK` markers
  included.
- **The problem description**: the `system_message` of OpenEvolve's config file,
  followed by the contract of the entry function, in the problem file's `description`.
- **The scores**: each `evaluation.py` is a port of OpenEvolve's evaluator, with the same
  cascade (two stages; threshold 0.5 for circle packing, 1.3 for function minimization):
  every program OpenEvolve scores above 0 gets exactly the same score. `tests/parity/`
  checks this on a set of programs.
- **The packages** programs may import (`packages` in the problem file).

What changed:

- The stage functions receive the program's names (`namespace`) and return a
  `StageResult` (score, metrics, feedback), instead of receiving a file path and
  returning a dictionary of metrics.
- Where OpenEvolve scores a program 0, the evaluation says why: an illegal answer
  raises `InvalidProgram` (status `invalid`), an answer that breaks the contract of the
  entry function raises `ProgramFailure` (status `failed`), and a stage-1 search over its
  5 s raises `CallTimeout` (status `timeout`).
- Function minimization limits each call of `run_search` to 5 s with `call_with_timeout`,
  as OpenEvolve's `run_with_timeout` does, and always recomputes the function's value
  from the point returned.
