# Provenance of the ws-run1 density report

This records where the first wafer.space run report came from, so that later
changes to the generators can be checked against it.

## What was published

Branch [`density-report`](https://github.com/wafer-space/ws-run1/tree/density-report)
of `wafer-space/ws-run1`, commit `fac8aa47` (17 March 2026), "Add standard cell
and SRAM density report with analysis data":

| File | Size | md5 |
|---|---|---|
| `reticle_analysis.csv` | 2,554 | `a53538edc16613a1baccaa43e77e3395` |
| `reticle_analysis_cells.csv` | 213,684 | `164962e59d5977e71b910dab89dfe6ba` |
| `reticle_analysis_grid.csv` | 27,470 | `5416583e48d6f6a096264c26c104dba0` |
| `reticle_density_report.md` | 38,004 | `d94d15901d31d28452af0ec24bbfe89a` |

Copies of all four are kept unmodified in [`reference/ws-run1/`](../reference/ws-run1/),
together with `reticle_density_report.txt`, an earlier plain-text draft of the
report that was never published.

## How it was generated

* **Machine:** `big-storage.welland.mithis.com`
* **Directory:** `~/github/mithro/wafer-space/design-analysis`
* **Script:** `analyze_layout.py`, first published as
  [`mithro/wafer-space-design-analysis`](https://github.com/mithro/wafer-space-design-analysis)
  (commit `e055f0e`, 19 March 2026). That commit is the first commit of this
  repository.
* **Environment:** Python 3.13.5, `klayout` 0.30.7 from PyPI, managed by `uv`.
* **Input:** `ws-run1/layout/reticle.oas`, 335,535,334 bytes, md5
  `316f07f37e148457558053f4d4d11540`, assembled with
  `cat reticle-part-?? > reticle.oas` from `wafer-space/ws-run1@aa0bfb6`.
* **Command:**

  ```bash
  uv run python analyze_layout.py ~/github/wafer-space/ws-run1/layout/reticle.oas -o reticle_analysis.csv
  ```

## What the script did and did not produce

`analyze_layout.py` wrote the three CSV files. It did **not** write the report.

`reticle_density_report.md` was written by hand, in a Claude Code session, from
the CSVs. The following parts of it have no generator in the original commit:

* the prose, the grouping into high / medium / low density and the 46 footnotes;
* project names, descriptions and repository links (taken from the ws-run1 README);
* core area, which assumes a 350 um pad ring on every side of the die;
* the theoretical maximum tables, which use standard cell widths and row
  heights "measured from layout bounding boxes";
* transistors per standard cell (inv 2, buf 4, nand2 4, dffq 24);
* SRAM macro sizes and transistor densities per macro;
* "unique design" de-duplication of slots that are placed more than once.

No record of that session survives, so those figures can only be checked by
recomputing them.

## Checking the current code against it

`tests/ws-run1-2026-03.toml` describes the March layout. With a checkout of
`wafer-space/ws-run1` at commit `aa0bfb6`:

```bash
uv run ws-run-reports analyze tests/ws-run1-2026-03.toml --repo-dir <checkout> --out out/regression
md5sum out/regression/ws-run1/reticle_analysis{,_cells,_grid}.csv
```

must print the three md5 sums in the table above. This was last confirmed on
5 October 2026 with klayout 0.30.7.

Generating the report from the same data reproduces the March figures for
logic cell counts, transistor counts, core densities and peak densities. Two
kinds of figure differ, both because the March method was wrong:

* **Theoretical maximum density, and every "% of max".** The March report took
  cell width and row height from the cell bounding box (4.22 x 4.78 um for a
  7-track `buf_1`). Cells are placed at their boundary (3.36 x 3.92 um); the
  wells overhang and overlap the neighbours. The maxima were about 35% too low,
  so for example the densest square millimetre of design 2975 is 41% of the
  buffer maximum, not 62%, and no design exceeds the flip-flop transistor
  maximum.
* **SRAM block counts.** The March report counted SramCore marker shapes, and
  each GF180MCU macro has two. MOLE has 6 macros (as its own description
  says), not 12.

## Later changes to ws-run1

On 21 September 2026 the ws-run1 layout was re-published as `G801` with the
RZML project made public (md5 `3ae7349e205f60d9f997cf7d3a688500`), and the
project list moved to `data/manifest.csv`. `runs/ws-run1.toml` describes that
layout, so current reports cover 30 designs where the March report had 24
unique designs.
