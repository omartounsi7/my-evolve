# Examples

Ready-made problems, one folder each. Each holds the three files a run needs: the
initial program, its evaluation file, and the problem file.

| Problem | Folder |
|---|---|
| Circle packing: 26 circles in the unit square, maximizing the sum of their radii | `circle_packing/` |

The problems are OpenEvolve's, so that runs start from the same baseline as
OpenEvolve's and can be compared with them (D3).

- Source: OpenEvolve, commit `da3d7011d6b87bf139f3291108be51536685828f`.
- Licence: Apache License 2.0, copied in [LICENSE-openevolve](LICENSE-openevolve).

What is the same as in OpenEvolve:

- **The initial programs**: OpenEvolve's files, unchanged, `EVOLVE-BLOCK` markers
  included.
- **The problem description**: the `system_message` of OpenEvolve's config file,
  followed by the contract of the entry function, in the problem file's `description`.
- **The score**: the sum of the radii divided by 2.635.

What changed:

- `evaluate` receives the program's names (`namespace`) and returns the score alone,
  instead of receiving a file path and returning several metrics.
- For now, a single stage, and an illegal packing raises `InvalidProgram` (status
  `invalid`) where OpenEvolve scores it 0. A later step of the plan (1.12) makes the
  evaluation a faithful port of OpenEvolve's, cascade included.
