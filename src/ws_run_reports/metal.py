"""Per-layer metal coverage of every design, with and without dummy fill, and its densest 1 mm square.

For each design and each of Metal1-5 and MetalTop (the x/0 drawing layers) this measures three things:

* **design**: what the designer drew plus the standard cells and SRAM, the same as the ``_metal`` CSV of
  :mod:`analyze` (pad cells, seal ring, dummy fill and wafer.space artwork left out);
* **with_fill**: the same plus the dummy metal fill (``METALn_FILL`` and ``*_fill_cell`` cells);
* **all**: every shape on the layer, pads and seal ring included, which is what a foundry density check sees.

Each is given as the area and share of the die, and over every 1 mm square inside the die, stepped by 250 um
from its lower left corner: the share of the densest and of the sparsest square, and where the densest one is.
In a direction where the die is under 1 mm the square is as wide as the die.

The die is cut into 250 um bins, each clipped and merged on its own, so a die's millions of fill shapes are never
flattened at once; the squares are sums of 4 x 4 bins.

The results are data only (``reticle_metal_coverage.csv``); no page uses them.
"""

import csv
import multiprocessing
import os
from pathlib import Path

import klayout.db as kdb

from . import features
from .analyze import enumerate_slots, extract_slot_id
from .exclude import Selection, base_name, selection_for
from .usage import LAYERS, METALS

BIN_UM = 250.0
WINDOW_BINS = 4  # 1 mm
SCOPES = ("design", "with_fill", "all")
FIELDS = ["slot_id", "cell_name", "layer", "scope", "die_mm2", "area_um2", "share",
          "windows", "window_mm", "max_window_share", "max_window_x_mm", "max_window_y_mm", "min_window_share"]

_STATE = {}


def fill_cells(layout) -> list:
    """Dummy fill cells: FILL_RE without the seal ring and artwork it also matches."""
    return [c.cell_index() for c in layout.each_cell()
            if features.FILL_RE.search(base_name(c.name))
            and not base_name(c.name).lower().startswith("sealring")
            and "gf180mcu_ws_ip__" not in base_name(c.name)]


def selections(layout, measure: dict) -> dict:
    """scope -> Selection. ``design`` is the selection analyze.py measures metal with."""
    run = selection_for(layout, measure)
    fill = set(fill_cells(layout))
    others = [c.cell_index() for c in layout.each_cell()
              if (features.FILL_RE.search(base_name(c.name)) or features.IO_RE.search(base_name(c.name)))
              and c.cell_index() not in fill]
    # A run that excludes dummy_fill itself must not hide the fill from the with_fill scope.
    run_without_fill = Selection(groups=run.groups, keep=run.keep, core_cell=run.core_cell,
                                 excluded=[ci for ci in run.excluded if ci not in fill], kept=run.kept)
    return {
        "design": features.designer_selection(run_without_fill, others + sorted(fill)),
        "with_fill": features.designer_selection(run_without_fill, others),
        "all": Selection(),
    }


def edges(low: int, high: int, step: int) -> list:
    """Bin edges from ``low`` to ``high``: full steps, then a last partial bin if one is left."""
    return list(range(low, high, step)) + [high]


def window_starts(edges_: list, full: int) -> list:
    """(first bin, bin count) of every window along one axis: WINDOW_BINS full bins at each bin step, or all
    the bins when there are fewer full ones than that."""
    if full < WINDOW_BINS:
        return [(0, len(edges_) - 1)]
    return [(i, WINDOW_BINS) for i in range(full - WINDOW_BINS + 1)]


def prefix(grid: list) -> list:
    """2D prefix sums of ``grid`` (rows of numbers), with a zero row and column in front."""
    out = [[0] * (len(grid[0]) + 1) for _ in range(len(grid) + 1)]
    for j, row in enumerate(grid):
        for i, v in enumerate(row):
            out[j + 1][i + 1] = v + out[j][i + 1] + out[j + 1][i] - out[j][i]
    return out


def box_sum(p: list, i: int, j: int, ni: int, nj: int):
    return p[j + nj][i + ni] - p[j][i + ni] - p[j + nj][i] + p[j][i]


def merged_area(layout, cell, index, selection: Selection, box: kdb.Box) -> int:
    """Area, in dbu², of the merged shapes on layer ``index`` inside ``box``."""
    it = selection.iterator(layout, cell, index, kdb.Region(box))
    region = kdb.Region(it) & kdb.Region(box)
    region.merge()
    return region.area()


def coverage(areas: list, die: kdb.Box, xs: list, ys: list, step: int, dbu: float) -> dict:
    """The row fields for one layer and scope from its bin ``areas`` (rows bottom to top, dbu²)."""
    bin_area = [[(x1 - x0) * (y1 - y0) for x0, x1 in zip(xs, xs[1:])] for y0, y1 in zip(ys, ys[1:])]
    pa, pb = prefix(areas), prefix(bin_area)
    wx = window_starts(xs, die.width() // step)
    wy = window_starts(ys, die.height() // step)
    shares = [(box_sum(pa, i, j, ni, nj) / box_sum(pb, i, j, ni, nj), i, j)
              for j, nj in wy for i, ni in wx]
    densest = max(shares)
    total = sum(map(sum, areas))
    width = xs[wx[0][0] + wx[0][1]] - xs[wx[0][0]]
    height = ys[wy[0][0] + wy[0][1]] - ys[wy[0][0]]
    return {
        "die_mm2": round(die.area() * dbu * dbu / 1e6, 4),
        "area_um2": round(total * dbu * dbu, 1), "share": round(total / die.area(), 4) if die.area() else 0,
        "windows": len(shares), "window_mm": f"{width * dbu / 1000:g}x{height * dbu / 1000:g}",
        "max_window_share": round(densest[0], 4),
        # No position for a layer with nothing on it.
        "max_window_x_mm": round((xs[densest[1]] - die.left) * dbu / 1000, 3) if densest[0] else "",
        "max_window_y_mm": round((ys[densest[2]] - die.bottom) * dbu / 1000, 3) if densest[0] else "",
        "min_window_share": round(min(shares)[0], 4),
    }


def measure_cell(cell_index) -> tuple:
    layout, sels = _STATE["layout"], _STATE["selections"]
    cell = layout.cell(cell_index)
    die = cell.bbox()
    step = round(BIN_UM / layout.dbu)
    xs, ys = edges(die.left, die.right, step), edges(die.bottom, die.top, step)
    rows = []
    for layer in METALS:
        index = layout.find_layer(kdb.LayerInfo(*LAYERS[layer]))
        for scope in SCOPES:
            areas = [[merged_area(layout, cell, index, sels[scope], kdb.Box(x0, y0, x1, y1)) if index is not None else 0
                      for x0, x1 in zip(xs, xs[1:])] for y0, y1 in zip(ys, ys[1:])]
            rows.append({"layer": layer, "scope": scope, **coverage(areas, die, xs, ys, step, layout.dbu)})
    return cell_index, rows


def measure_layout(input_path: Path, output: Path, measure: dict, slot_cells=None, jobs=None) -> Path:
    layout = kdb.Layout()
    print(f"Loading {input_path}...", flush=True)
    layout.read(str(input_path))
    top = max(layout.top_cells(), key=lambda c: c.bbox().area())
    slots = enumerate_slots(top, slot_cells) or [("top", top, kdb.Trans())]
    unique = {cell.cell_index(): cell for _, cell, _ in slots}
    order = sorted(unique, key=lambda ci: -unique[ci].bbox().area())
    jobs = max(1, min(jobs or min(4, os.cpu_count() or 1), len(order)))
    _STATE.update(layout=layout, selections=selections(layout, measure))
    print(f"Measuring metal of {len(order)} designs with {jobs} worker(s)...", flush=True)
    results = {}
    if jobs == 1:
        iterator = map(measure_cell, order)
    else:
        pool = multiprocessing.get_context("fork").Pool(jobs)
        iterator = pool.imap_unordered(measure_cell, order)
    for cell_index, rows in iterator:
        results[cell_index] = rows
        print(f"  [{len(results)}/{len(order)}] {unique[cell_index].name}", flush=True)
    if jobs > 1:
        pool.close()
        pool.join()
    output.parent.mkdir(parents=True, exist_ok=True)
    written = set()
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for cell_name, cell, _ in slots:
            slot_id = extract_slot_id(cell_name)
            if (slot_id, cell.cell_index()) in written:
                continue
            written.add((slot_id, cell.cell_index()))
            for row in results[cell.cell_index()]:
                writer.writerow({"slot_id": slot_id, "cell_name": cell_name, **row})
    return output
