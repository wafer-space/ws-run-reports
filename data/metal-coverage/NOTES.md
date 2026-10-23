# Metal coverage of wafer.space Runs 1 and 2

How much of each die each metal layer covers, with and without the dummy metal fill. These files are data
only: no run page uses them.

This was measured as a baseline for comparing process options with fewer metal layers. For example, it shows
whether designs use the upper metals at all, and how dense the fill leaves each layer.

- `ws-run1.csv`: wafer.space Run 1 (reticle G801), 30 designs in 38 slots.
- `ws-run2.csv`: wafer.space Run 2 (reticle G802), 40 designs in 43 slots.

Made on 24 October 2026 with `ws-run-reports metal ws-run1` and `ws-run-reports metal ws-run2`
(`src/ws_run_reports/metal.py`) from the reticle layouts in the run repositories.

## What is measured

There is one row per slot, layer and scope. The layers are Metal1 to Metal5 and MetalTop, the x/0 drawing
layers of the open GF180MCU PDK. MetalTop is empty on both runs, which use the 5-metal stack with Metal5 on top.

| Scope | What it counts |
|---|---|
| `design` | What the designer drew, plus the standard cells and SRAM macros. Pad cells, the seal ring, dummy fill and wafer.space artwork are left out. This equals `reticle_analysis_metal.csv` exactly: the areas match on all 486 rows of both runs. |
| `with_fill` | `design` plus the dummy metal fill (`METALn_FILL` and `*_fill_cell` cells). |
| `all` | Every shape on the layer, pads and seal ring included. This is what a foundry density check sees. |

| Column | Meaning |
|---|---|
| `slot_id`, `cell_name` | The project code and its cell on the reticle. A design placed in two slots has a row for each (8 designs on Run 1, 3 on Run 2), and their figures are the same. |
| `die_mm2` | Area of the die's bounding box, seal ring included. |
| `area_um2`, `share` | Merged area on the layer, and that area as a share of the die. |
| `windows`, `window_mm` | The number of 1 mm squares checked, and their size. The squares lie fully inside the die, stepped by 250 µm from its lower left corner. Where the die is under 1 mm in one direction, the square is as wide as the die there. |
| `max_window_share`, `max_window_x_mm`, `max_window_y_mm` | The densest square's share, and its lower left corner measured from the die's lower left corner. The position is empty when the layer is empty. |
| `min_window_share` | The sparsest square's share. Between squares of exactly equal share, the densest is the top right one. |

Each die is cut into 250 µm bins, each bin clipped and merged on its own, and each square is the sum of
4 × 4 bins. A strip narrower than 250 µm along the die's top and right edges falls in no square, though it
still counts in `area_um2`.

## Summary

Per design (each design counted once, at its first placement). "Using it" means more than 1 % of the die in
the `design` scope.

Every share is of the whole die, with the pad ring and seal ring in the denominator. The `design` scope leaves
the pads out of the numerator, so these shares understate how dense a design's core is.

The two "1 mm" columns are extremes over all the run's designs: the densest square found on any die, and the
sparsest. They are not typical values.

### Run 1 (30 designs)

| Layer | Using it | Design, median | Design, max | With fill, median | With fill, min | Densest 1 mm with fill | Sparsest 1 mm with fill |
|---|---|---|---|---|---|---|---|
| Metal1 | 29 of 30 | 19.4 % | 23.6 % | 25.1 % | 16.4 % | 68.8 % | 10.7 % |
| Metal2 | 29 of 30 | 9.3 % | 19.9 % | 20.7 % | 15.6 % | 71.0 % | 8.6 % |
| Metal3 | 29 of 30 | 10.1 % | 23.7 % | 19.0 % | 12.2 % | 68.8 % | 7.5 % |
| Metal4 | 29 of 30 | 9.2 % | 26.9 % | 17.2 % | 11.0 % | 69.8 % | 4.5 % |
| Metal5 | 29 of 30 | 9.5 % | 39.1 % | 18.2 % | 11.1 % | 67.9 % | 4.6 % |
| MetalTop | 0 of 30 | 0 | 0 | 0 | 0 | 0 | 0 |

29 of the 30 designs use more than 1 % of the die on every layer from Metal1 to Metal5. MOS2 uses 1.3 %
on Metal2 and 0.6–1.0 % on each of the others, and BRWN uses under 1 % on Metal2.

### Run 2 (40 designs)

| Layer | Using it | Design, median | Design, max | With fill, median | With fill, min | Densest 1 mm with fill | Sparsest 1 mm with fill |
|---|---|---|---|---|---|---|---|
| Metal1 | 38 of 40 | 17.2 % | 24.1 % | 21.5 % | 14.9 % | 71.0 % | 6.7 % |
| Metal2 | 38 of 40 | 8.1 % | 36.7 % | 19.1 % | 12.0 % | 69.0 % | 5.8 % |
| Metal3 | 39 of 40 | 9.6 % | 36.6 % | 18.8 % | 8.9 % | 69.5 % | 5.6 % |
| Metal4 | 39 of 40 | 9.8 % | 36.7 % | 18.2 % | 10.7 % | 69.1 % | 5.6 % |
| Metal5 | 40 of 40 | 10.3 % | 45.7 % | 17.5 % | 11.1 % | 84.0 % | 9.4 % |
| MetalTop | 0 of 40 | 0 | 0 | 0 | 0 | 0 | 0 |

Every Run 2 design uses Metal5. The densest square of either run is 84.0 % on Metal5, on the Tiny Tapeout
GF 0.3 die (T0P3), 2.25 mm right of and 3.25 mm above its lower left corner.

FC01 (flip-chip bonding test pads) has no Metal1 to Metal4 of its own; 0000 uses 0.1 % on Metal1 and 0.7 % on
Metal2. These two make up the 38 of 40 on Metal1 and Metal2. SALU, at 1.1 % on Metal2, is just over the
threshold.

## What it suggests

- Almost every design uses all five metals, at more than 1 % of the die each. In the median design, Metal2 to
  Metal5 each cover about 8–10 % of the die before fill. So a 3-metal option would mean re-routing nearly
  every design, not just dropping unused layers.
- With fill, the median coverage of Metal2 to Metal5 rises to about 17–21 % of the die. That is 1.5 to 2.2
  times the design's own coverage: most on Metal2, least on Metal3. Even with fill, some 1 mm squares are as
  sparse as 4.5 % (Run 1, Metal4).
- These files don't measure what fills the densest squares (68–84 %) on its own. In the `all` scope some
  densest squares sit at a die's corner, on the pad ring or seal ring: Run 1's 71.3 % on Metal5 for TTPG is
  at (0, 4.0) mm.

## Reproduce

```
scripts/kl-run uv run ws-run-reports metal ws-run1 --repo-dir <ws-run1 checkout> --jobs 8
scripts/kl-run uv run ws-run-reports metal ws-run2 --repo-dir <ws-run2 checkout> --jobs 8
```

`scripts/kl-run` runs the command in a memory-limited systemd scope, so a runaway layout operation is killed
instead of exhausting the machine. Each run took about 15 minutes with 8 workers. The command writes
`out/<run>/reticle_metal_coverage.csv`, and the files here are copies of those, renamed `<run>.csv`.
