# wafer.space Design Analysis

Quantitative layout analysis tool for GDS/OAS chip designs, built for the [wafer.space](https://wafer.space/) shuttle program.

Extracts per-design metrics from multi-project reticle layouts:
- **Standard cell counts** by library and cell type (logic cells only, excluding infrastructure)
- **Transistor density** via COMP/Poly2 boolean intersection at 1mm x 1mm grid resolution
- **SRAM block counts** from SramCore layer
- **Pad counts** and design dimensions
- **Per-slot analysis** with automatic reticle slot detection

## Quick Start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.10+.

```bash
# Analyze a GDS/OAS file
uv run python analyze_layout.py <input.gds|oas> -o output.csv

# Example: analyze the ws-run1 reticle
cd ~/github/wafer-space/ws-run1/layout && cat reticle-part-?? > reticle.oas
cd ~/github/mithro/wafer-space/design-analysis
uv run python analyze_layout.py ~/github/wafer-space/ws-run1/layout/reticle.oas -o reticle_analysis.csv
```

## Output Files

The tool produces three CSV files:

| File | Contents |
|---|---|
| `*_analysis.csv` | Per-slot summary: dimensions, pad count, SRAM blocks, logic stdcell count, transistor count |
| `*_analysis_grid.csv` | 1mm x 1mm grid density map: transistor and stdcell count per grid cell per slot |
| `*_analysis_cells.csv` | Per-slot cell usage: instance count by library, cell type, and logic/infrastructure classification |

## Standard Cell Classification

Cells are classified as **logic** or **infrastructure**:

- **Logic cells**: gates, flip-flops, buffers, multiplexers, latches, adders, clock gating cells, delay buffers, etc.
- **Infrastructure cells** (excluded from logic counts): fillers (fill, fillcap, endcap, filltie), well taps, antenna fix diodes, ESD diodes, tie-high/tie-low cells

On the ws-run1 reticle, infrastructure cells outnumber logic cells nearly 3:1.

## Supported Standard Cell Libraries

The tool auto-detects GF180MCU standard cell libraries by matching cell name prefixes:

| Prefix | Library | Notes |
|---|---|---|
| `gf180mcu_fd_sc_` | Foundry-provided standard cells | mcu7t5v0 (7-track 5V), mcu9t5v0 (9-track 5V) |
| `gf180mcu_as_sc_` | Application-specific standard cells | mcu7t3v3 (7-track 3.3V) |
| `gf180mcu_as_ex_` | Extra/extension cells | dfxtp, dfxtn variants |

Custom prefixes can be specified with `--stdcell-prefix` (may be repeated).

The tool handles Tiny Tapeout's namespacing convention where each user design's cells get a unique hash prefix (e.g., `OH_gf180mcu_fd_sc_...`) by matching the prefix anywhere in the cell name.

## CLI Options

```
usage: analyze_layout.py [-h] [-o OUTPUT] [--stdcell-prefix STDCELL_PREFIX] input

positional arguments:
  input                 Input GDS or OAS file

options:
  -o, --output OUTPUT   Output CSV path (default: <input_stem>_analysis.csv)
  --stdcell-prefix      Cell name prefix for standard cell identification
                        (may be repeated; default: gf180mcu_fd_sc_,
                        gf180mcu_as_sc_, gf180mcu_as_ex_)
```

## ws-run1 Analysis Report

See [`reticle_density_report.md`](reticle_density_report.md) for a detailed analysis of the 24 unique designs on the wafer.space Run 1 (GF180MCU, G801) reticle, including:

- Standard cell density by design (logic cells/mm², with theoretical max comparison)
- 7-track vs 9-track and 3.3V vs 5V library comparison
- SRAM vs standard cell transistor density
- Most common logic cell types
- Per-design footnotes with detailed metrics

## Dependencies

- [klayout](https://www.klayout.de/) (PyPI package) — KLayout's Python API for GDS/OAS layout processing

## License

Apache-2.0. See [LICENSE](LICENSE).
