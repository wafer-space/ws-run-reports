"""Extract quantitative metrics from a reticle (or single design) GDS/OAS layout.

For every design slot this measures dimensions, pad count, SRAM block count,
logic standard cell count and transistor count, plus a 1 mm x 1 mm density
grid and a per-cell-type usage breakdown. It also measures the standard cell
library and the SRAM macros themselves, which is what the theoretical maximum
densities in the reports are derived from.

The three per-slot CSV files keep the exact format of the original
``analyze_layout.py`` so that results stay comparable between runs.
"""

import csv
import multiprocessing
import os
import re
import sys
from collections import Counter
from pathlib import Path

import klayout.db as kdb

# GDS layer definitions (from gf180mcu.lyp)
LAYER_COMP = (22, 0)       # Diffusion/active area
LAYER_POLY2 = (30, 0)      # Gate polysilicon
LAYER_PAD = (37, 0)        # Bond pads
LAYER_SRAM_CORE = (108, 5) # SRAM macro boundaries
LAYER_PR_BNDRY = (0, 0)    # Cell/slot boundaries

GRID_SIZE_UM = 1000.0  # 1mm = 1000um

# Cell names to skip when enumerating design slots in a reticle
SKIP_CELL_PREFIXES = ("RETICLE_FILL", "TEXT")

DEFAULT_STDCELL_PREFIXES = ("gf180mcu_fd_sc_", "gf180mcu_as_sc_", "gf180mcu_as_ex_")

# Standard cell name suffixes (after '__') that are physical infrastructure,
# not logic. These are inserted by automated tools for manufacturing rules.
FILL_CELL_PREFIXES = (
    "fill", "endcap", "filltie", "fillcap",  # gap fillers
    "tap",                                     # well tap (latch-up prevention)
    "antenna",                                 # antenna rule fix diodes
    "diode",                                   # ESD/antenna diodes
    "tiel", "tieh",                            # tie-low/tie-high (constant generators)
)

# A complete SRAM macro, e.g. gf180mcu_fd_ip_sram__sram512x8m8wm1. Their
# internal sub-cells carry further suffixes and do not match.
SRAM_MACRO_RE = re.compile(r"(gf180mcu_\w+?_ip_sram__sram\d+x\d+[a-z0-9]*)$")

SUMMARY_FIELDS = [
    "slot_id", "cell_name", "width_mm", "height_mm",
    "pos_x_mm", "pos_y_mm", "pad_count", "sram_block_count",
    "stdcell_count", "transistor_count",
]
GRID_FIELDS = [
    "slot_id", "cell_name", "grid_x", "grid_y",
    "x_mm", "y_mm", "transistor_count", "stdcell_count",
]
CELLS_FIELDS = ["slot_id", "cell_name", "library", "cell_type", "is_fill", "instance_count"]
LIBRARY_FIELDS = [
    "library", "cell_type", "is_fill", "width_um", "height_um",
    "bbox_width_um", "bbox_height_um", "transistor_count", "definitions",
]
MACRO_FIELDS = ["macro", "width_um", "height_um", "transistor_count", "instances"]
SLOT_MACRO_FIELDS = ["slot_id", "cell_name", "macro", "instances"]
SLOT_AREA_FIELDS = ["slot_id", "cell_name", "die_area_mm2", "sram_area_mm2", "pad_area_mm2"]


def find_layer(layout, layer_num, datatype):
    """Find a layer index in the layout, or return None if not present."""
    info = kdb.LayerInfo(layer_num, datatype)
    idx = layout.find_layer(info)
    if idx is None or idx < 0:
        return None
    return idx


def build_clipped_region(layout, cell, layer_idx, clip_box):
    """Build a Region from shapes on a layer, geometrically clipped to a box.

    RecursiveShapeIterator with clip_box only *selects* overlapping shapes —
    it does not geometrically clip them. We AND with the box to get exact
    clipping, preventing double-counting at grid boundaries.
    """
    region = kdb.Region()
    if layer_idx is None:
        return region
    rsi = kdb.RecursiveShapeIterator(layout, cell, layer_idx, clip_box)
    region.insert(rsi)
    region &= kdb.Region(clip_box)
    region.merge()
    return region


def count_region(layout, cell, layer_idx):
    """Count merged polygons on a layer within a cell hierarchy."""
    region = kdb.Region()
    if layer_idx is None:
        return 0, region
    rsi = kdb.RecursiveShapeIterator(layout, cell, layer_idx)
    region.insert(rsi)
    region.merge()
    return region.count(), region


def count_rsi(layout, cell, layer_idx, clip_box=None):
    """Count shapes via RecursiveShapeIterator (no merge, just instance count)."""
    if layer_idx is None:
        return 0
    if clip_box is not None:
        rsi = kdb.RecursiveShapeIterator(layout, cell, layer_idx, clip_box)
    else:
        rsi = kdb.RecursiveShapeIterator(layout, cell, layer_idx)
    count = 0
    for _ in rsi.each():
        count += 1
    return count


def classify_stdcell(name, prefixes):
    """Classify a standard cell by library, type, and fill status.

    The prefix may appear anywhere in the name, which handles Tiny Tapeout's
    namespacing where each user design's cells get a unique hash prefix
    (e.g. ``OH_gf180mcu_fd_sc_...``).

    Returns (library, cell_type, is_fill) or None if not a stdcell.
    Library examples: 'mcu7t5v0', 'mcu9t5v0', 'mcu7t3v3'.
    Cell type examples: 'inv_1', 'dffq_2', 'fill_4'.
    """
    for prefix in prefixes:
        idx = name.find(prefix)
        if idx < 0:
            continue
        rest = name[idx + len(prefix):]
        if "__" not in rest:
            continue
        lib, cell_type = rest.split("__", 1)
        cell_type = cell_type.split("$")[0]
        is_fill = any(cell_type.startswith(fp) for fp in FILL_CELL_PREFIXES)
        return lib, cell_type, is_fill
    return None


def is_stdcell(name, prefixes):
    """Check if a cell name matches any of the standard cell prefixes."""
    return any(prefix in name for prefix in prefixes)


def create_stdcell_marker_layer(layout, prefixes):
    """Add a tiny marker at the origin of each logic standard cell definition.

    Counting the markers through the hierarchy then counts logic cell
    instances, including inside an arbitrary clip box. Infrastructure cells
    get no marker.

    Returns the marker layer index.
    """
    marker_layer = layout.layer()
    marker = kdb.Box(0, 0, 1, 1)
    logic_count = 0
    fill_count = 0
    for cell_idx in range(layout.cells()):
        cell = layout.cell(cell_idx)
        if cell is None or not is_stdcell(cell.name, prefixes):
            continue
        info = classify_stdcell(cell.name, prefixes)
        if info is not None and info[2]:
            fill_count += 1
            continue
        cell.shapes(marker_layer).insert(marker)
        logic_count += 1
    print(f"  Marked {logic_count} logic stdcell definitions (excluded {fill_count} filler definitions)")
    return marker_layer


def classify_all_stdcells(layout, prefixes):
    """Map cell_index -> (library, cell_type, is_fill) for every stdcell definition."""
    cell_info = {}
    for cell_idx in range(layout.cells()):
        cell = layout.cell(cell_idx)
        if cell is None or not is_stdcell(cell.name, prefixes):
            continue
        info = classify_stdcell(cell.name, prefixes)
        if info is not None:
            cell_info[cell_idx] = info
    return cell_info


def count_stdcell_usage(cell, cell_info):
    """Count instances of each stdcell type within a design's hierarchy.

    Uses a bottom-up traversal with caching: for each unique cell, compute
    its stdcell content once, then scale by instance count at each level.

    Returns dict mapping (library, cell_type, is_fill) -> instance_count.
    """
    cache = {}

    def get_counts(c):
        ci = c.cell_index()
        if ci in cache:
            return cache[ci]
        counts = Counter()
        if ci in cell_info:
            counts[cell_info[ci]] = 1
            cache[ci] = counts
            return counts
        for inst in c.each_inst():
            n_copies = inst.cell_inst.size()
            for key, cnt in get_counts(inst.cell).items():
                counts[key] += cnt * n_copies
        cache[ci] = counts
        return counts

    return dict(get_counts(cell))


def count_transistors(layout, cell, l_comp, l_poly2):
    """Count transistor regions (COMP AND Poly2) in a cell hierarchy."""
    if l_comp is None or l_poly2 is None:
        return 0
    comp = kdb.Region()
    comp.insert(kdb.RecursiveShapeIterator(layout, cell, l_comp))
    poly2 = kdb.Region()
    poly2.insert(kdb.RecursiveShapeIterator(layout, cell, l_poly2))
    transistors = comp & poly2
    transistors.merge()
    return transistors.count()


def enumerate_slots(top_cell):
    """Find design slots as direct children of the top cell.

    Returns list of (cell_name, cell, placement_trans) for each design slot,
    filtering out fill patterns and text/alignment marks.
    """
    slots = []
    for inst in top_cell.each_inst():
        child = inst.cell
        if any(child.name.startswith(prefix) for prefix in SKIP_CELL_PREFIXES):
            continue
        for t in inst.cell_inst.each_trans():
            slots.append((child.name, child, t))
    # Sort by position: column then row
    slots.sort(key=lambda s: (s[2].disp.x, s[2].disp.y))
    return slots


def extract_slot_id(cell_name):
    """Extract the 4-character project code from a slot cell name.

    e.g., 'BTAP_chip_top_0_0' -> 'BTAP'
         'OCD2_gf180mcu_ocd_sram_top_2_8' -> 'OCD2'
    """
    parts = cell_name.split("_", 1)
    return parts[0] if parts else cell_name


def analyze_slot(layout, cell, dbu, layers):
    """Analyze a single design slot cell. Returns dict of metrics."""
    bbox = cell.bbox()
    pad_count, pad_region = count_region(layout, cell, layers["pad"])
    sram_count, sram_region = count_region(layout, cell, layers["sram"])
    dbu2_per_mm2 = 1e6 / (dbu * dbu)
    return {
        "die_area_mm2": bbox.area() / dbu2_per_mm2,
        "sram_area_mm2": sram_region.area() / dbu2_per_mm2,
        "pad_area_mm2": pad_region.area() / dbu2_per_mm2,
        "width_mm": bbox.width() * dbu / 1000.0,
        "height_mm": bbox.height() * dbu / 1000.0,
        "pad_count": pad_count,
        "sram_block_count": sram_count,
        "stdcell_count": count_rsi(layout, cell, layers["marker"]),
        "transistor_count": count_transistors(layout, cell, layers["comp"], layers["poly2"]),
        "sram_region": sram_region,
    }


def analyze_slot_grid(layout, cell, dbu, layers, sram_region):
    """Compute 1mm grid density map for a single slot cell.

    Grid cells that overlap an SRAM macro are skipped, so the grid describes
    standard cell regions only.
    """
    grid_size_dbu = int(GRID_SIZE_UM / dbu)
    bbox = cell.bbox()
    x_start = bbox.left
    y_start = bbox.bottom
    nx = max(1, (bbox.width() + grid_size_dbu - 1) // grid_size_dbu)
    ny = max(1, (bbox.height() + grid_size_dbu - 1) // grid_size_dbu)

    rows = []
    for gy in range(ny):
        for gx in range(nx):
            x0 = x_start + gx * grid_size_dbu
            y0 = y_start + gy * grid_size_dbu
            clip_box = kdb.Box(x0, y0, x0 + grid_size_dbu, y0 + grid_size_dbu)

            if not sram_region.is_empty():
                overlap = kdb.Region(clip_box) & sram_region
                if not overlap.is_empty():
                    continue

            comp_clipped = build_clipped_region(layout, cell, layers["comp"], clip_box)
            poly2_clipped = build_clipped_region(layout, cell, layers["poly2"], clip_box)
            transistor_region = comp_clipped & poly2_clipped
            transistor_region.merge()

            x_mm = (x0 - x_start) * dbu / 1000.0
            y_mm = (y0 - y_start) * dbu / 1000.0
            rows.append((gx, gy, x_mm, y_mm, transistor_region.count(),
                         count_rsi(layout, cell, layers["marker"], clip_box)))
    return rows


# State shared with forked worker processes. The layout is loaded once in the
# parent and inherited copy-on-write, so workers never reload or pickle it.
_STATE = {}


def _analyze_cell_index(cell_index):
    layout = _STATE["layout"]
    layers = _STATE["layers"]
    cell = layout.cell(cell_index)
    dbu = layout.dbu
    metrics = analyze_slot(layout, cell, dbu, layers)
    grid_rows = analyze_slot_grid(layout, cell, dbu, layers, metrics.pop("sram_region"))
    usage = count_stdcell_usage(cell, _STATE["cell_info"])
    metrics["macros"] = count_macro_usage(cell, _STATE["macro_cells"])
    return cell_index, metrics, grid_rows, usage


def layer_bbox(cell, layer_idx):
    """Bounding box of a cell's shapes on one layer (the method was renamed between KLayout versions)."""
    if hasattr(cell, "bbox_per_layer"):
        return cell.bbox_per_layer(layer_idx)
    return cell.bbox(layer_idx)


def measure_library(layout, prefixes, cell_info, layers):
    """Measure every distinct standard cell: footprint, bounding box and transistor count.

    The footprint is the PR boundary shape, which is what cells tile at when
    placed in a row. The bounding box is larger because wells and implants
    deliberately overhang into the neighbouring cells.
    """
    dbu = layout.dbu
    rows = {}
    for cell_idx, (lib, cell_type, is_fill) in cell_info.items():
        cell = layout.cell(cell_idx)
        key = (lib, cell_type)
        if key in rows:
            rows[key]["definitions"] += 1
            continue
        bbox = cell.bbox()
        boundary = layer_bbox(cell, layers["boundary"]) if layers["boundary"] is not None else kdb.Box()
        if boundary.empty():
            boundary = bbox
        rows[key] = {
            "library": lib,
            "cell_type": cell_type,
            "is_fill": is_fill,
            "width_um": f"{boundary.width() * dbu:.3f}",
            "height_um": f"{boundary.height() * dbu:.3f}",
            "bbox_width_um": f"{bbox.width() * dbu:.3f}",
            "bbox_height_um": f"{bbox.height() * dbu:.3f}",
            "transistor_count": count_transistors(layout, cell, layers["comp"], layers["poly2"]),
            "definitions": 1,
        }
    return [rows[key] for key in sorted(rows)]


def find_macro_cells(layout):
    """Map cell_index -> macro name for every SRAM macro definition."""
    macro_cells = {}
    for cell_idx in range(layout.cells()):
        cell = layout.cell(cell_idx)
        if cell is None:
            continue
        m = SRAM_MACRO_RE.search(cell.name.split("$")[0])
        if m:
            macro_cells[cell_idx] = m.group(1)
    return macro_cells


def count_macro_usage(cell, macro_cells):
    """Count flat placements of each SRAM macro below a cell with one bottom-up walk."""
    cache = {}

    def placements(c):
        ci = c.cell_index()
        if ci not in cache:
            counts = Counter()
            if ci in macro_cells:
                counts[macro_cells[ci]] = 1
            else:
                for inst in c.each_inst():
                    n = inst.cell_inst.size()
                    for key, cnt in placements(inst.cell).items():
                        counts[key] += cnt * n
            cache[ci] = counts
        return cache[ci]

    return dict(placements(cell))


def measure_macros(layout, top_cell, layers, macro_cells):
    """Measure each distinct SRAM macro: size, transistor count and number of placements."""
    dbu = layout.dbu
    totals = count_macro_usage(top_cell, macro_cells)
    rows = {}
    for cell_idx, name in macro_cells.items():
        if name in rows:
            continue
        cell = layout.cell(cell_idx)
        bbox = cell.bbox()
        rows[name] = {
            "macro": name,
            "width_um": f"{bbox.width() * dbu:.3f}",
            "height_um": f"{bbox.height() * dbu:.3f}",
            "transistor_count": count_transistors(layout, cell, layers["comp"], layers["poly2"]),
            "instances": totals.get(name, 0),
        }
    return [rows[name] for name in sorted(rows)]


def output_paths(output_path):
    """The set of CSV files written by :func:`analyze`, keyed by kind."""
    def sibling(suffix):
        return output_path.parent / (output_path.stem + suffix + output_path.suffix)
    return {
        "summary": output_path,
        "grid": sibling("_grid"),
        "cells": sibling("_cells"),
        "library": sibling("_library"),
        "macros": sibling("_macros"),
        "slot_macros": sibling("_slot_macros"),
        "slot_areas": sibling("_slot_areas"),
    }


def analyze(input_path, output_path, stdcell_prefixes=DEFAULT_STDCELL_PREFIXES, jobs=None):
    """Analyze a layout and write the summary, grid, cell usage, library and macro CSVs."""
    layout = kdb.Layout()
    print(f"Loading {input_path}...")
    layout.read(str(input_path))

    dbu = layout.dbu
    top_cells = layout.top_cells()
    if not top_cells:
        print("Error: no cells found in layout", file=sys.stderr)
        sys.exit(1)
    top_cell = top_cells[0]
    if len(top_cells) > 1:
        print(f"Warning: multiple top cells found, using '{top_cell.name}'")

    print(f"Top cell: {top_cell.name}, dbu: {dbu} um")
    print(f"Stdcell prefixes: {list(stdcell_prefixes)}")

    layers = {
        "comp": find_layer(layout, *LAYER_COMP),
        "poly2": find_layer(layout, *LAYER_POLY2),
        "pad": find_layer(layout, *LAYER_PAD),
        "sram": find_layer(layout, *LAYER_SRAM_CORE),
        "boundary": find_layer(layout, *LAYER_PR_BNDRY),
    }

    print("Classifying standard cells...")
    cell_info = classify_all_stdcells(layout, stdcell_prefixes)
    print(f"  Libraries found: {', '.join(sorted({lib for lib, _, _ in cell_info.values()}))}")

    print("Measuring standard cell library and SRAM macros...")
    library_rows = measure_library(layout, stdcell_prefixes, cell_info, layers)
    macro_cells = find_macro_cells(layout)
    macro_rows = measure_macros(layout, top_cell, layers, macro_cells)
    print(f"  {len(library_rows)} distinct standard cells, {len(macro_rows)} distinct SRAM macros")

    # The marker layer is added after the library is measured so the markers
    # never contribute to a cell's bounding box.
    print("Creating standard cell markers...")
    layers["marker"] = create_stdcell_marker_layer(layout, stdcell_prefixes)

    # --- Detect reticle vs single design ---
    slots = enumerate_slots(top_cell)
    if len(slots) <= 1:
        print("Single design detected")
        target_cell = slots[0][1] if slots else top_cell
        slots = [("top", target_cell, kdb.Trans())]
    print(f"Found {len(slots)} design slots")

    # A design placed several times on the reticle shares one cell, so analyse
    # each cell once. Largest first keeps the worker pool evenly loaded.
    unique = {}
    for _, cell, _ in slots:
        unique[cell.cell_index()] = cell
    order = sorted(unique, key=lambda ci: -unique[ci].bbox().area())
    jobs = max(1, min(jobs or min(4, os.cpu_count() or 1), len(order)))
    print(f"Analysing {len(order)} unique designs with {jobs} worker(s)...")

    _STATE.update(layout=layout, layers=layers, cell_info=cell_info, macro_cells=macro_cells)
    results = {}
    if jobs == 1:
        iterator = map(_analyze_cell_index, order)
    else:
        pool = multiprocessing.get_context("fork").Pool(jobs)
        iterator = pool.imap_unordered(_analyze_cell_index, order)
    for cell_index, metrics, grid_rows, usage in iterator:
        results[cell_index] = (metrics, grid_rows, usage)
        print(f"  [{len(results)}/{len(order)}] {unique[cell_index].name}: "
              f"{metrics['width_mm']:.1f} x {metrics['height_mm']:.1f} mm, pads {metrics['pad_count']}, "
              f"SRAM {metrics['sram_block_count']}, stdcells {metrics['stdcell_count']}, "
              f"transistors {metrics['transistor_count']}, grid {len(grid_rows)}", flush=True)
    if jobs > 1:
        pool.close()
        pool.join()

    paths = output_paths(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    all_grid_rows = []
    all_cell_usage = []
    slot_macro_rows = []
    slot_area_rows = []
    for cell_name, cell, trans in slots:
        slot_id = extract_slot_id(cell_name)
        metrics, grid_rows, usage = results[cell.cell_index()]
        summary_rows.append({
            "slot_id": slot_id,
            "cell_name": cell_name,
            "width_mm": f"{metrics['width_mm']:.2f}",
            "height_mm": f"{metrics['height_mm']:.2f}",
            "pos_x_mm": f"{trans.disp.x * dbu / 1000.0:.2f}",
            "pos_y_mm": f"{trans.disp.y * dbu / 1000.0:.2f}",
            "pad_count": metrics["pad_count"],
            "sram_block_count": metrics["sram_block_count"],
            "stdcell_count": metrics["stdcell_count"],
            "transistor_count": metrics["transistor_count"],
        })
        for row in grid_rows:
            all_grid_rows.append((slot_id, cell_name) + row)
        for (lib, cell_type, is_fill), count in sorted(usage.items()):
            all_cell_usage.append((slot_id, cell_name, lib, cell_type, is_fill, count))
        for macro, count in sorted(metrics["macros"].items()):
            slot_macro_rows.append({"slot_id": slot_id, "cell_name": cell_name, "macro": macro, "instances": count})
        slot_area_rows.append({
            "slot_id": slot_id,
            "cell_name": cell_name,
            "die_area_mm2": f"{metrics['die_area_mm2']:.4f}",
            "sram_area_mm2": f"{metrics['sram_area_mm2']:.4f}",
            "pad_area_mm2": f"{metrics['pad_area_mm2']:.4f}",
        })

    print(f"\nWriting {paths['summary']}...")
    with open(paths["summary"], "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"Writing {paths['grid']}...")
    with open(paths["grid"], "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(GRID_FIELDS)
        writer.writerows(all_grid_rows)

    print(f"Writing {paths['cells']}...")
    with open(paths["cells"], "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CELLS_FIELDS)
        writer.writerows(all_cell_usage)

    for kind, fields, rows in (
        ("library", LIBRARY_FIELDS, library_rows),
        ("macros", MACRO_FIELDS, macro_rows),
        ("slot_macros", SLOT_MACRO_FIELDS, slot_macro_rows),
        ("slot_areas", SLOT_AREA_FIELDS, slot_area_rows),
    ):
        print(f"Writing {paths[kind]}...")
        with open(paths[kind], "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    print(f"\nDone. {len(summary_rows)} slots, {len(all_grid_rows)} grid cells, "
          f"{len(all_cell_usage)} cell type entries.")
    return paths
