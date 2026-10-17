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

On a shared machine, run the layout steps inside a memory-limited systemd scope
with `scripts/kl-run`, so that a runaway job is killed instead of exhausting the
machine:

```bash
scripts/kl-run uv run ws-run-reports analyze ws-run2 --jobs 20
KL_MEM=96G scripts/kl-run uv run ws-run-reports render ws-run2 --jobs 20
```

## Adding a run

Every run, wafer.space's or another shuttle's, goes through the same code.
What differs lives in `runs/<name>.toml`, and only four keys are required:

```toml
title = "wafer.space GF180MCU Run 3"
shuttle = "G803"       # the layout is layout/G803.oas, split into layout/G803-part-*
slots = 40             # slots on the shuttle, including private and empty ones

[layout]
md5 = "..."            # of the assembled layout, as in the run repository's create-reticle-oas.sh
```

Everything else is optional:

| Key | Meaning | Default |
|---|---|---|
| `name`, `repo` | Run name and GitHub repository | The file name; `wafer-space/<name>` |
| `process` | Process name used in the text | `GF180MCU` |
| `[layout] parts`, `file` | The split layout in the run repository | `layout/<shuttle>-part-*`, `layout/<shuttle>.oas` |
| `[manifest] csv` | The project list | `data/manifest.csv` |
| `[site] heading` | Lines of the page title, the first at full size and the rest smaller | The title |
| `[site] slot_origin`, `slot_letters`, `slot_labels` | Slot labels around the reticle: the corner of A1 (`top-left`, `top-right`, `bottom-left`, `bottom-right`), whether letters name the `columns` or the `rows`, or `slot_labels = false` for none | As platform.wafer.space: A1 top left, letters for columns |
| `[site] reticle_frame_mm` | `[width, height]` of a frame to draw a small reticle on, in its top left corner, so its dies appear at the same scale as other runs' (MPW-18H1 uses `[30.0, 23.379]`) | The reticle's own size |
| `[site] runs_yml_key` | The run's key in the website's `_data/runs.yml`, for the shuttle timeline | No timeline |
| `[site] runs_yml_path`, `timeline_source`, `timeline_source_url` | A timeline file in the same format in the run repository, and the source the page credits for it | The website's file, credited to wafer.space |
| `[site] campaign_url` | Crowd Supply or similar campaign page | None |
| `[site] cob_repo`, `cob_url` | Chip-on-board bonding results | None |
| `[site] photos_url`, `photos_prefix` | Die photographs | None |
| `[site] photos_credit`, `photos_credit_url`, `photos_year`, `photos_licence`, `photos_licence_url` | Copyright line shown wherever a photograph appears: "© 2026 Name, Licence", with links | |
| `[site] photos_viewer_url` | The photographer's zoomable viewer for one die, with `{code}`, `{CODE}` and `{setup}` filled in. Listed first on each project page | |
| `[measure] exclude`, `keep`, `core_cell`, `[measure.groups]` | Leave groups of cells out of the measurements; see below | Measure whole dies |
| `[report.notes]` | Extra Markdown sections for the density report, `"Heading" = """text"""` | None |
| `[categories]` | `CODE = "Category"` overrides for the classifier | |

`slots` is the number of slots on the shuttle, whatever their arrangement; dies
may sit anywhere on the reticle and positions may be empty. Slot sizes are
taken from the manifest; sizes other than wafer.space's four are shown as
written.

### Excluding cells

To measure only part of each die, name groups of cells to exclude. Patterns
are shell globs on cell names (also tried without a leading `<CODE>_`). The
groups `pad_ring` (all `gf180mcu_*_io__*` cells), `caravel_harness` (an
Efabless Caravel die apart from its `user_project_wrapper`),
`wafer_space_artwork` and `seal_ring` (the `sealring` cell reticle-stitcher
puts around each die) are built in. `keep` names cells below an excluded one that are still measured, and
`core_cell` names the cell whose area the densities are taken over (otherwise
the die minus a 350 µm pad ring). For a Caravel die:

```toml
[measure]
exclude = ["pad_ring", "caravel_harness"]
keep = ["user_project_wrapper"]
core_cell = "user_project_wrapper"
```

A run can define its own groups as `[measure.groups] name = ["pattern", ...]`.

Die sizes are always measured on the whole die, and bond pads on the whole die
apart from its seal ring, whose ring on the pad layer is not a pad. Transistors are
never counted in dummy fill cells (`dummy_fill`), whose COMP and Poly2 squares
overlap. The exclusions
are recorded in `reticle_analysis_meta.json`, and the report and page say what
was left out.

### Project details from the platform

`import` adds details that are not in the layout: the description, declared
licence, chip-on-board option and latest precheck from a platform.wafer.space
export, and the licences found in each project's repository from a licence
audit. Only public fields are kept (no user data, UUIDs or storage paths):

```bash
uv run ws-run-reports import ws-run1 --platform ws-run1-projects.json --audit audit.json \
    --precheck platform-export/
```

`--precheck` reads the platform's precheck export: `acceptance-checks.json`
(the check each design was accepted on, the newest finished check on the
submitted file at or before submission, and its latest re-run), the steps of
each check parsed from its LibreLane run directory (`steps/<run>/<CODE>.json`,
`<CODE>.acceptance.json`) and its log (`logs/<run>/<CODE>[.acceptance].precheck.log`).
The step files and gzipped logs are kept in `precheck/` and published with the
data on both branches; the project pages show every step of both checks.

The reticle is expected to follow the layout used so far: one top cell whose
children are named `<CODE>_<top cell>_<column>_<row>`, plus `RETICLE_FILL` and
`TEXT` cells that are ignored.

Each run's page also has `embed.html`, a strip of the designs (die photograph
and layout render side by side where both exist) that other pages can show
in an iframe without any JavaScript:

```html
<iframe src="https://wafer.space/ws-run1/embed.html" title="Run 1 designs"
        style="width: 100%; height: 300px; border: 0" loading="lazy"></iframe>
```

The first time a run's page is published, enable GitHub Pages for the run
repository on the `gh-pages` branch:

```bash
gh api repos/wafer-space/ws-run2/pages -X POST -f 'source[branch]=gh-pages' -f 'source[path]=/'
```

### Tiny Tapeout dies

A Tiny Tapeout chip on a wafer.space reticle gets its own run: the die is
the "reticle" and its projects are the "slots". To add one:

1. Make a folder for the die in `wafer-space/tinytapeouts` (e.g. `ttgf0p3/ws-run2-t0p3`) holding the die as
   cut from the wafer.space reticle in `layout/<CODE>-part-*`, the
   release's `shuttle_index.json` in `data/`, and a manifest made from it:

   ```bash
   uv run ws-run-reports tt-manifest --index data/shuttle_index.json \
       --tt-repo <checkout of TinyTapeout/tinytapeout-gf-...> --output data/manifest.csv
   ```

   Each project's code is its mux address, three digits (`000`, `295`).
   Its title, author, description, language and clock come from its
   `info.yaml` at the release commit.

2. Add `runs/tinytapeouts-<chip>-<run>-<code>.toml`, as `runs/tinytapeouts-ttgf0p3-ws-run2-t0p3.toml`:

   | Setting | Purpose |
   |---|---|
   | `[layout] slots = "manifest"` | Slots are the outermost placements of each manifest `TOP` cell (a project's own nested `tt_um_*` cells stay part of it) |
   | `[measure] grid_um`, `bin_um` | Density map squares and densest window (100 µm), and its step (20 µm); peaks stay per mm² |
   | `[measure] pad_ring_um = 0` | Each project's core is its whole area |
   | `[site] kind = "tiny-tapeout"`, `tt_chip` | Die/project/tiles wording, project details and tinytapeout.com links |
   | `[site.parent] title`, `url` | Link back to the die on its wafer.space run |
   | `[site.render]` | Design, thumbnail and die scales (`design_px_per_mm`, `design_max_px`, `thumb_px_per_mm`, `thumb_max_px`, `reticle_px_per_mm`), and `reticle_background = true` to draw the whole die under the projects |

3. Run `ws-run-reports all <run>` as for any run.

The Tiny Tapeout dies share one repository, `wafer-space/tinytapeouts`, with
a folder per die (`<chip>/<run>-<code>`); a run config says so with `repo`
and `path`, and its pages are published into that folder of the repository's
gh-pages branch, at `https://wafer.space/tinytapeouts/<chip>/<run>-<code>/`,
leaving the other dies alone. `runs/collections/tinytapeouts.toml` describes
the index page at the root, which lists every run in the repository:

```bash
uv run ws-run-reports collection tinytapeouts             # build out/tinytapeouts/site/index.html
uv run ws-run-reports collection tinytapeouts --publish --push
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
| `reticle_analysis_slot_areas.csv` | Die, SRAM marker and pad opening area per slot, and the core cell's area when `core_cell` is set |
| `reticle_analysis_map.csv` | Every 1 mm square of each design, including those with SRAM, with the share of the square that is SRAM |
| `reticle_analysis_windows.csv` | The densest whole 1 x 1 mm window of each design, sliding in 100 µm steps, overall and avoiding SRAM |
| `reticle_analysis_sram_rects.csv` | The outline of every SRAM macro in each design |
| `reticle_analysis_features.csv` | Designer-drawn transistors by voltage and optional devices per design, and the I/O library used |
| `reticle_analysis_meta.json` | What was measured: top cell, library prefixes, exclusions |
| `projects.json` | Imported project details (see above) |

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
* **Standard cell libraries** are the foundry's (`fd_sc`), Avalon
  Semiconductors' (`as_sc`, `as_ex`) and Oklahoma State University's (`osu_sc`).
  The foundry libraries are named by their last part (`mcu7t5v0`), the others
  with their vendor prefix (`as_ex_mcu7t5v0`).
* **Process features** count only what the designer drew: standard cell, SRAM,
  I/O, fill and artwork cells are skipped. A gate is thick oxide inside
  Dualgate (55/0), 5 V where V5_XTOR (112/1) also covers it and 6 V where it
  does not, 3.3 V otherwise. MIM capacitors are FuseTop (75/0); poly resistors
  are Poly2 under RES_MK (110/5), high resistance under Resistor (62/0). Other
  devices are found by their marker layers from the open PDK's `gf180mcu.lyp`.
* **Densest mm²** slides a 1 x 1 mm window over each die in 100 µm steps,
  counting logic cells by their origin and transistors by their gate centre,
  and skips windows that touch an SRAM macro.
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
