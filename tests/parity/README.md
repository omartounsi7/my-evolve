# Parity programs

Programs scored both by OpenEvolve's evaluators and by my-evolve's ports of them
(`examples/*/evaluation.py`), to check that every working program gets exactly
OpenEvolve's score (D3). `tests/test_examples.py` runs the comparison.

| Path | Contents |
|---|---|
| `programs/circle_packing/` | Valid packings, packings breaking each rule, answers that cannot be read |
| `programs/function_minimization/` | Fixed points near and far from the minimum, wrong answers, slow and flaky searches |
| `openevolve_scores.json` | The scores OpenEvolve's evaluators gave them, after their cascade |
| `record_openevolve_scores.py` | The script that recorded them, from the openevolve checkout |

`programs/circle_packing/best_program.py` is OpenEvolve's best known circle packing
(`examples/circle_packing/best_program.py` at commit `da3d701`, Apache License 2.0,
see `examples/LICENSE-openevolve`), unchanged. The other programs were written for
these tests. None of them are checked by ruff or mypy: they are written as an LLM
might write them.

To record the scores again, after changing a program or updating OpenEvolve:

```bash
.venv/bin/python tests/parity/record_openevolve_scores.py ../openevolve
```
