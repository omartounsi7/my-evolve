# Examples

The two problems are OpenEvolve's
([circle_packing](https://github.com/algorithmicsuperintelligence/openevolve/tree/main/examples/circle_packing)
and [function_minimization](https://github.com/algorithmicsuperintelligence/openevolve/tree/main/examples/function_minimization)),
so that runs start from the same baseline as OpenEvolve's and can be compared
with them (design decision D3). Circle packing is the main experiment.

- Source: OpenEvolve, commit `da3d7011d6b87bf139f3291108be51536685828f`, the
  checkout next to this repository. Its two newest commits are local and do not
  touch the initial programs or the evaluators, which OpenEvolve last changed
  before them.
- Licence: Apache License 2.0, copied in [LICENSE-openevolve](LICENSE-openevolve).

Each folder holds:

| File | Contents |
|---|---|
| `initial_program.py` | OpenEvolve's initial program, unchanged, `EVOLVE-BLOCK` markers included |
| `evaluation.py` | A port of OpenEvolve's `evaluator.py`: the same cascade and the same scores |
| `problem.yaml` | The problem file, with the local models of batch 1 (Appendix B) |
| `problem_claude.yaml` | The same problem with the Claude models of batch 2; only its `llm` section differs |

The LLM may change only the code between the `EVOLVE-BLOCK` markers (D12). The
initial programs are left exactly as OpenEvolve wrote them, so ruff neither checks
nor reformats them (see `pyproject.toml`).

## The same scores as OpenEvolve

Every working program gets exactly the score OpenEvolve's evaluator gives it. What
differs is how failures are told apart (D7): where OpenEvolve scores a program 0,
here it is `invalid` (an answer breaking the rules, with the reason), `failed` (an
answer that cannot be read, or a crash) or `timeout`, and it has no score.
`tests/test_examples.py` checks this on a set of programs in
`tests/parity/programs/`, whose OpenEvolve scores were recorded by
`tests/parity/record_openevolve_scores.py`.

The problem descriptions are OpenEvolve's system messages for these problems
(`config_phase_1.yaml` for circle packing, which names the 2.635 target as
OpenEvolve's does, and `config.yaml` for function minimization), followed by the
contract of the entry function.

### Circle packing

Place 26 circles in the unit square, without overlap, so that the sum of their
radii is as large as possible. `run_packing()` returns the centres, the radii and
their sum. The score is the sum of the radii divided by 2.635, the sum the
AlphaEvolve paper reached; errors up to 1e-6 are tolerated. A packing scoring at
least 0.5 is built and scored a second time (stage 2), and that score is kept.

The initial program scores 0.364 (a sum of about 0.959). Stage 1 also measures two
features for the MAP-Elites grid: `radii_spread` (how unequal the radii are) and
`radius_centre_correlation` (whether big circles sit in the middle or at the edges).

**Threads change some programs' answers.** OpenEvolve's best known program
(`tests/parity/programs/circle_packing/best_program.py`, a sum of 2.635977) is valid
when numpy may use 8 threads, but with one thread, as in the sandbox (D41), its
optimization takes another path and ends with overlapping circles. OpenEvolve's own
evaluator agrees in both cases: the difference is in the program, not the
evaluation. Programs evolved here are always scored with the sandbox's threads.

### Function minimization

Find the global minimum of f(x, y) = sin(x) cos(y) + sin(xy) + (x² + y²) / 20,
about f(-1.704, 0.678) = -1.519. `run_search()` returns `(x, y)` or
`(x, y, value)`; f is always recomputed from x and y. Each call may take 5 s. Stage
1 scores one call; a program scoring at least 1.3 is called 10 more times, which
also rewards succeeding every time, and that score is kept (up to 1.5).

The initial program searches at random, so its score changes from one evaluation
to the next.
