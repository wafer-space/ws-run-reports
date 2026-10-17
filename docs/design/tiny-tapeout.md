# Design: a page for each Tiny Tapeout die on a wafer.space run

Status: proposal, 17 Oct 2026. Nothing is built yet.

Tim wants a ws-run-style repo and page for each Tiny Tapeout GF die on a
wafer.space reticle, at `https://wafer.space/<repo>/`:

| Repo | Die | TT shuttle | Tag (commit) | Projects |
|---|---|---|---|---|
| ws-run1-ttgf0p2-ttp2 | TTP2 (G801) | ttgf0p2 | tapeout-ws2512 (7416232) | 52 |
| ws-run1-ttgf0p2-ttpg | TTPG (G801) | ttgf0p2, powergate | tapeout-ws2512-powergate (7416232) | 52 |
| ws-run2-ttgf0p3-t0p3 | T0P3 (G802) | ttgf0p3 | tapeout-ws2607 (3050476) | 32 |
| ws-run2-ttgf26a-t26a | T26A (G802) | ttgf26a | tapeout-ws2607 (35e7026) | 95 |
| ws-run2-ttgf26b-t26b | T26B (G802) | ttgf26b | tapeout-ws2607 (b7b04a0) | 90 |

The "reticle" of such a run is one die (`tt_gf_wrapper`, 3932 x 5122 um with
its seal ring and fill), and its "slots" are the Tiny Tapeout projects in it.

## The idea: the manifest drives the slots

Almost everything the tool does works on a list of slots, each a cell
placement with a code. Today the slots are the top cell's children named
`<CODE>_<top>_<c>_<r>`. The one real change is a second way to find
them, which is general rather than Tiny Tapeout-only:

> **Slots are the placements of the manifest's `TOP` cells.** For each
> manifest row, the placements of the cell named `TOP`, anywhere below the
> top cell, outermost only, with the row's `CODE`.

A run picks it with `[layout] slots = "manifest"`; the default stays
`"children"`. Driving it from the manifest also handles the nested
`tt_um_*` cells correctly (`tt_um_dino7_logo` inside `tt_um_dino7`,
`tt_um_example` inside the T0P3 UART/TRNG lab). Only projects listed in
`projects/` at the tag are slots, and a project cell's own children are
measured as part of it, as now.

`$N` suffixes don't matter: matching is on the name before `$`, as in
`exclude.py`.

So each TT repo carries a normal `data/manifest.csv`, generated from the TT
repo at the tag:

| Column | From |
|---|---|
| `CODE` | the mux address from `modules.yaml`, zero-padded to 3 digits (`045`), as the TT datasheet numbers projects |
| `PROJECT` | `info.yaml` `project.title` |
| `SLOT_SIZE` | `info.yaml` `project.tiles` (`1x1` ... `4x4`) |
| `VISIBILITY` | `Public` |
| `PROJECT_DETAILS` | `info.yaml` description and author |
| `REPOSITORY` | the project's source repo and commit from `commit_id.json` |
| `TOP` | the `tt_um_*` cell name |

`config.projects()` then works unchanged. Making the manifest is a small
`ws-run-reports tt-manifest <tt repo> <tag>` command, or part of whatever
builds the repos; either works.

**Why the mux address for CODE:** it is unique per die and stable. It is
what the datasheet and the TT site use, and it makes short URLs
(`projects/045.html`). The `tt_um_*` name is shown on every page and is
searchable.

## Run config

```toml
title = "Tiny Tapeout GF 0.3 on wafer.space Run 2 (die T0P3)"
shuttle = "T0P3"
slots = 32

[layout]
md5 = "..."
slots = "manifest"                 # new: slots are the manifest's TOP cells

[measure]
exclude = ["tt_harness", "seal_ring"]   # new built-in group: mux, controller, power switches, wrapper logic
# fill is already left out of transistor counts

[site]
kind = "tiny-tapeout"              # new: TT wording and links (below)
tt_shuttle = "ttgf0p3"
slot_labels = false                # no letter/number grid; the hover tag shows "045 · title"
reticle_px_per_mm = 400            # new: the "reticle" is one die, so draw it larger
density_grid_um = 100              # new: map squares and the densest window sized for tiles
```

## What changes, file by file

**`analyze.py`**
- `enumerate_slots`: add the manifest mode. Use a `RecursiveInstanceIterator`
  that targets the `TOP` cells and does not descend into them, so only
  outermost placements count, and take each placement's bbox and transform.
- The 1 mm grid size and the densest-window size become run settings.
  `density_grid_um = 100` gives about 7 squares across a 1x1 tile
  (~340 x 160 um).
  - The page's "per mm²" figures stay in /mm², so they compare directly
    with the wafer.space runs.
  - The "densest 1 mm²" wording becomes "densest 100 µm square".

**`exclude.py`**
- Add a `tt_harness` built-in group: the cells of `tt_gf_wrapper` that are
  not projects (mux, controller, power switches). Before naming the
  patterns I'd list the wrapper's direct children on one die.
- Die-level totals on the main page cover the whole die. Per-project
  numbers cover only each project's cell.

**`render.py`**
- The overview is the die at `reticle_px_per_mm`: 400 px/mm gives about
  1570 x 2050 px for the die.
- Per-project renders at the existing 2.5 um/px would be only ~136 px wide
  for a 1x1 tile. Scale them per project so the long side is about 1600 px.
  The layer styles (all layers, transistors, signal routing, power and
  pads) carry over.
- **Tile-grid SVG** (new, `tiles.svg`):
  - the die outline, the tile grid (from the tile size and origin), and each
    project's rectangle labelled with its address;
  - a `<title>` and link per project, so it works with no JavaScript;
  - the page can use it as the map, laid over the render the way the
    reticle map is now, and `embed.html` can use it too.

**`site.py` and templates, `kind = "tiny-tapeout"`**
- **Header:** "Tiny Tapeout GF 0.3", with "die T0P3 on wafer.space Run 2 (G802)"
  linking back to the run page.
- **Slots table:** projects by tile size (1x1: n, 1x2: n, ...), the same as the
  slot-type table now.
- **Project pages:**
  - TT title, author, description (`docs/info.md` rendered as text),
    `tt_um_*` name, tiles, language, clock;
  - links to the source repo at its commit and to the project's page on
    tinytapeout.com (the exact URL scheme still needs checking);
  - the existing layout stats, renders, density map and process features
    (MIM, resistors and so on, which matter for the analog projects).
- **No platform precheck section:** TT projects aren't on platform.wafer.space,
  and the section is already omitted when `projects.json` has no checks.
- **Licence:** from the project's `LICENSE` at its commit, through the
  existing licence audit format, so the "declared vs repository" display
  still works.
- **Optional:** import TT's `stats/metrics.csv` (utilisation, cell counts,
  wire length) next to our measurements, as a cross-check and for
  utilisation figures from the flow itself.

**`publish.py`**
- No change. Each TT repo gets `density-report` and `gh-pages` like the
  others.
- A gh-pages push to a public repo goes live at once.

## Layout source

The peer found the die cut from the wafer.space reticle
(`runs/<run>/<CODE>/layout/<CODE>.oas`) identical to TT's precheck output
at the tag, apart from COMP dummy 22/4 merged into 22/0 and the `$N` names.

I suggest committing the **cut from the reticle**. It is what was
manufactured, and its numbers then match the run page's figures for that
die exactly. The TT release GDS and tag are recorded in the README for
provenance.

## Size of the work

| Area | Rough size |
|---|---|
| Manifest slot mode | ~60 lines |
| `tt_harness` group | a few patterns |
| Grid size setting | ~30 lines |
| Render scale | ~20 lines |
| `tiles.svg` | ~100 lines |
| `kind = "tiny-tapeout"` wording and metadata | ~150 lines of template |
| TT manifest generator | ~80 lines |

Tests use a synthetic die with nested `tt_um_*` cells.

The existing runs are unaffected: every new setting defaults to today's
behaviour, and the March 2026 regression check still applies.

## Open questions for Tim

1. CODE as the zero-padded mux address (`045`), or the `tt_um_*` name?
2. Layout from the reticle cut (as manufactured), or TT's release GDS?
3. TTP2 and TTPG share their projects (powergate config only). Should they
   be two separate repos, as listed, or one repo with two dies?
4. Should a die's run page (ws-run1/ws-run2) link to its TT repo from the
   TT dies' project pages?
