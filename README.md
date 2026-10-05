# wafer.space run reports

Generators for the reports published from the [wafer.space](https://wafer.space/)
shuttle run repositories ([ws-run1](https://github.com/wafer-space/ws-run1),
[ws-run2](https://github.com/wafer-space/ws-run2), ...):

* **density statistics** measured from the public reticle layout: logic
  standard cells, transistors, SRAM, and a 1 mm density grid per design;
* a **Markdown density report** comparing what designers achieved with the
  theoretical maximum of the standard cell libraries;
* **layout renders** of every design and of the whole reticle;
* a **web page** per run, in the style of the main website, served from the
  run repository's `gh-pages` branch at `https://wafer.space/<run>/`.

## Quick start

Requires [uv](https://docs.astral.sh/uv/). Check out the run repository next to
this one (`../ws-run2`), or pass `--repo-dir`.

```bash
uv run ws-run-reports analyze ws-run2    # measure the layout -> out/ws-run2/*.csv
uv run ws-run-reports report  ws-run2    # -> out/ws-run2/reticle_density_report.md
uv run ws-run-reports render  ws-run2    # -> out/ws-run2/site/renders/
uv run ws-run-reports site    ws-run2    # -> out/ws-run2/site/index.html
uv run ws-run-reports all     ws-run2    # the four steps above

uv run ws-run-reports publish ws-run2 density-report          # commit in a scratch clone
uv run ws-run-reports publish ws-run2 density-report --push   # ... and push it
uv run ws-run-reports publish ws-run2 gh-pages --push
```

`analyze` and `render` load the whole reticle, which takes 6 to 9 GB of memory
before any worker starts (`--jobs`, default 4). A 31 GB desktop ran out of
memory with 3 workers; on a large machine with 20 workers each step took about
10 minutes. `report` and `site` only read the CSV files and take seconds.

## Adding a run

Everything that differs between runs is in `runs/<name>.toml`. For a new run,
copy `runs/ws-run2.toml` and change:

| Key | Meaning |
|---|---|
| `name`, `title`, `number`, `shuttle`, `repo`, `slots` | Identity of the run |
| `[layout] parts`, `file`, `md5` | The split layout in the run repository, as in its `layout/create-reticle-oas.sh` |
| `[manifest] csv` | The project list (`data/manifest.csv`) |
| `[site] runs_yml_key` | The run's key in the website's `_data/runs.yml`, for the shuttle timeline |
| `[site] cob_repo`, `cob_url` | Chip-on-board bonding results, once they exist |
| `[site] photos_url`, `photos_prefix`, `photos_credit` | Die photographs, once they exist |
| `[categories]` | Optional `CODE = "Category"` overrides for the classifier |

The reticle is expected to follow the layout used so far: one top cell whose
children are named `<CODE>_<top cell>_<column>_<row>`, plus `RETICLE_FILL` and
`TEXT` cells that are ignored.

The first time a run's page is published, enable GitHub Pages for the run
repository on the `gh-pages` branch:

```bash
gh api repos/wafer-space/ws-run2/pages -X POST -f 'source[branch]=gh-pages' -f 'source[path]=/'
```

## What is measured

| Output | Contents |
|---|---|
| `reticle_analysis.csv` | Per slot: size, position, pads, SramCore shapes, logic cells, transistors |
| `reticle_analysis_grid.csv` | Logic cells and transistors in each 1 mm grid square of each slot |
| `reticle_analysis_cells.csv` | Instances per slot of every standard cell type |
| `reticle_analysis_library.csv` | Every standard cell: placement boundary, bounding box, transistors |
| `reticle_analysis_macros.csv` | Every SRAM macro: size, transistors, placements |
| `reticle_analysis_slot_macros.csv` | SRAM macros per slot |
| `reticle_analysis_slot_areas.csv` | Die, SRAM marker and pad opening area per slot |

* **Logic cells** are instances of cells whose name contains a standard cell
  library prefix (`gf180mcu_fd_sc_`, `gf180mcu_as_sc_`, `gf180mcu_as_ex_`),
  excluding fillers, end caps, taps, antenna diodes and tie cells. The prefix
  may appear anywhere in the name, which covers Tiny Tapeout's per-project
  name prefixes.
* **Transistors** are the merged polygons of diffusion (GDS 22/0) AND gate
  polysilicon (30/0).
* **Theoretical maximum density** tiles one cell at its placement boundary
  (GDS 0/0). The cell bounding box is larger, because wells overhang into the
  neighbouring cells, and must not be used for this.
* **SRAM macros** are identified by name. The SramCore marker (108/5) appears
  twice per GF180MCU macro, so counting marker shapes doubles the count.

The first three files keep the exact format of the original March 2026
analysis. [docs/provenance.md](docs/provenance.md) records where that came from
and how the current code is checked against it.

## Project categories

`src/ws_run_reports/classify.py` assigns each project a category from keyword
rules on its name and description, falling back to what is on the die. Where
the rules get a project wrong, add an override to the run's TOML:

```toml
[categories]
SCUP = "Test structures"
```

## Development

```bash
uv run pytest
```

The tests build a small synthetic reticle, so they do not need a real layout.

## License

Apache-2.0. See [LICENSE](LICENSE). The projects on the reticles have their own
licences; see the individual repositories.
