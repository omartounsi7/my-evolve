# Examples

The two problems are OpenEvolve's
([circle_packing](https://github.com/algorithmicsuperintelligence/openevolve/tree/main/examples/circle_packing)
and [function_minimization](https://github.com/algorithmicsuperintelligence/openevolve/tree/main/examples/function_minimization)),
so that runs start from the same baseline as OpenEvolve's and can be compared
with them (design decision D3). Circle packing is the main experiment.

- Source: OpenEvolve, commit `da3d7011d6b87bf139f3291108be51536685828f`, the
  checkout next to this repository. Its two newest commits are local and do not
  touch these files, which OpenEvolve last changed in `ba01403`.
- Licence: Apache License 2.0, copied in [LICENSE-openevolve](LICENSE-openevolve).

| File | Contents |
|---|---|
| `circle_packing/initial_program.py` | OpenEvolve's initial program, unchanged |
| `function_minimization/initial_program.py` | OpenEvolve's initial program, unchanged |

The initial programs keep OpenEvolve's `EVOLVE-BLOCK` markers: the LLM may change
only the code between them (D12). They are left exactly as OpenEvolve wrote
them, so ruff neither checks nor reformats them (see `pyproject.toml`).
