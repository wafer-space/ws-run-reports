#!/usr/bin/env python3
"""Analyze GDS/OAS layout files to extract quantitative metrics.

For reticle layouts (multiple design slots), produces per-slot metrics.
For single designs, produces metrics for the top cell.

Extracts: design dimensions, pad count, SRAM block count, standard cell count,
transistor count, and a 1mm x 1mm grid-level density map.

Usage:
    uv run python analyze_layout.py <input.gds|oas> [-o output.csv] [--stdcell-prefix PREFIX]
"""

import argparse
import csv
import sys
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

# Standard cell name suffixes (after '__') that are physical infrastructure,
# not logic. These are inserted by automated tools for manufacturing rules.
FILL_CELL_PREFIXES = (
    "fill", "endcap", "filltie", "fillcap",  # gap fillers
    "tap",                                     # well tap (latch-up prevention)
    "antenna",                                 # antenna rule fix diodes
    "diode",                                   # ESD/antenna diodes
    "tiel", "tieh",                            # tie-low/tie-high (constant generators)
)


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


def _extract_stdcell_parts(name, prefixes):
    """Extract library and cell_type from a standard cell name.

    Tries each prefix in order. Returns (library, cell_type) or None.
    The prefix is the substring up to and including '_sc_' or '_ex_',
    and the library is the portion between that and '__'.
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
        return lib, cell_type
    return None


def _is_fill_cell(name, prefixes):
    """Check if a standard cell is a filler (not logic).

    Filler cells (fill, endcap, filltie, fillcap) are inserted to satisfy
    manufacturing rules but don't perform any logic function.
    """
    parts = _extract_stdcell_parts(name, prefixes)
    if parts is None:
        return False
    _, cell_type = parts
    return any(cell_type.startswith(fp) for fp in FILL_CELL_PREFIXES)


def _is_stdcell(name, prefixes):
    """Check if a cell name matches any of the standard cell prefixes."""
    return any(prefix in name for prefix in prefixes)


def _classify_stdcell(name, prefixes):
    """Classify a standard cell by library, type, and fill status.

    Returns (library, cell_type, is_fill) or None if not a stdcell.
    Library examples: 'mcu7t5v0', 'mcu9t5v0', 'mcu7t3v3'.
    Cell type examples: 'inv_1', 'dffq_2', 'fill_4'.
    """
    parts = _extract_stdcell_parts(name, prefixes)
    if parts is None:
        return None
    lib, cell_type = parts
    is_fill = any(cell_type.startswith(fp) for fp in FILL_CELL_PREFIXES)
    return lib, cell_type, is_fill


def create_stdcell_marker_layer(layout, prefixes):
    """Add a tiny marker at the origin of each logic standard cell definition.

    Matches cells where any prefix appears anywhere in the name (handles Tiny
    Tapeout's hash-prefix namespacing). Excludes filler cells (fill, endcap,
    filltie, fillcap) which don't represent useful logic.

    Returns the marker layer index.
    """
    marker_layer = layout.layer()
    marker = kdb.Box(0, 0, 1, 1)
    logic_count = 0
    fill_count = 0
    for cell_idx in range(layout.cells()):
        cell = layout.cell(cell_idx)
        if cell is None or not _is_stdcell(cell.name, prefixes):
            continue
        if _is_fill_cell(cell.name, prefixes):
            fill_count += 1
            continue
        cell.shapes(marker_layer).insert(marker)
        logic_count += 1
    print(f"  Marked {logic_count} logic stdcell definitions (excluded {fill_count} filler definitions)")
    return marker_layer


def create_per_library_markers(layout, prefixes):
    """Create separate marker layers for each stdcell library variant.

    Each library gets two layers: one for logic cells, one for fill cells.
    Also returns a mapping from cell_index -> (library, cell_type, is_fill).
    """
    # First pass: classify all stdcell definitions
    cell_info = {}  # cell_index -> (library, cell_type, is_fill)
    for cell_idx in range(layout.cells()):
        cell = layout.cell(cell_idx)
        if cell is None or not _is_stdcell(cell.name, prefixes):
            continue
        info = _classify_stdcell(cell.name, prefixes)
        if info is not None:
            cell_info[cell_idx] = info

    # Discover all libraries
    libraries = sorted(set(lib for lib, _, _ in cell_info.values()))

    # Create marker layers per library, separate for logic and fill
    marker = kdb.Box(0, 0, 1, 1)
    lib_layers = {}  # lib -> {"logic": layer_idx, "fill": layer_idx}
    for lib in libraries:
        lib_layers[lib] = {
            "logic": layout.layer(),
            "fill": layout.layer(),
        }

    # Insert markers
    for cell_idx, (lib, cell_type, is_fill) in cell_info.items():
        cell = layout.cell(cell_idx)
        key = "fill" if is_fill else "logic"
        cell.shapes(lib_layers[lib][key]).insert(marker)

    return lib_layers, cell_info


def count_stdcell_usage(layout, cell, prefixes, cell_info):
    """Count instances of each stdcell type within a design's hierarchy.

    Uses a bottom-up traversal with caching: for each unique cell, compute
    its stdcell content once, then scale by instance count at each level.

    Returns dict mapping (library, cell_type, is_fill) -> instance_count.
    """
    from collections import Counter

    cache = {}  # cell_index -> Counter of (lib, cell_type, is_fill)

    def get_counts(c):
        ci = c.cell_index()
        if ci in cache:
            return cache[ci]

        counts = Counter()
        # Is this cell itself a stdcell?
        if ci in cell_info:
            counts[cell_info[ci]] = 1
            cache[ci] = counts
            return counts

        # Otherwise, aggregate children
        for inst in c.each_inst():
            child = inst.cell
            n_copies = 0
            for _ in inst.cell_inst.each_trans():
                n_copies += 1
            child_counts = get_counts(child)
            for key, cnt in child_counts.items():
                counts[key] += cnt * n_copies

        cache[ci] = counts
        return counts

    return dict(get_counts(cell))


def count_transistors(layout, cell, l_comp, l_poly2):
    """Count transistor regions (COMP AND Poly2) in a cell hierarchy."""
    if l_comp is None or l_poly2 is None:
        return 0
    comp = kdb.Region()
    rsi = kdb.RecursiveShapeIterator(layout, cell, l_comp)
    comp.insert(rsi)
    poly2 = kdb.Region()
    rsi = kdb.RecursiveShapeIterator(layout, cell, l_poly2)
    poly2.insert(rsi)
    transistors = comp & poly2
    transistors.merge()
    return transistors.count()


def enumerate_slots(layout, top_cell):
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


def analyze_slot(layout, cell, dbu, l_comp, l_poly2, l_pad, l_sram, l_marker):
    """Analyze a single design slot cell. Returns dict of metrics."""
    bbox = cell.bbox()
    w_mm = bbox.width() * dbu / 1000.0
    h_mm = bbox.height() * dbu / 1000.0

    pad_count, _ = count_region(layout, cell, l_pad)
    sram_count, sram_region = count_region(layout, cell, l_sram)
    stdcell_count = count_rsi(layout, cell, l_marker)
    transistor_count = count_transistors(layout, cell, l_comp, l_poly2)

    return {
        "width_mm": w_mm,
        "height_mm": h_mm,
        "pad_count": pad_count,
        "sram_block_count": sram_count,
        "stdcell_count": stdcell_count,
        "transistor_count": transistor_count,
        "sram_region": sram_region,
    }


def analyze_slot_grid(layout, cell, dbu, l_comp, l_poly2, l_marker, sram_region):
    """Compute 1mm grid density map for a single slot cell."""
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
            x1 = x0 + grid_size_dbu
            y1 = y0 + grid_size_dbu
            clip_box = kdb.Box(x0, y0, x1, y1)

            # Skip grid cells that overlap SRAM
            if not sram_region.is_empty():
                grid_region = kdb.Region(clip_box)
                overlap = grid_region & sram_region
                if not overlap.is_empty():
                    continue

            # Transistor count
            comp_clipped = build_clipped_region(layout, cell, l_comp, clip_box)
            poly2_clipped = build_clipped_region(layout, cell, l_poly2, clip_box)
            transistor_region = comp_clipped & poly2_clipped
            transistor_region.merge()
            t_count = transistor_region.count()

            # Standard cell count
            sc_count = count_rsi(layout, cell, l_marker, clip_box)

            x_mm = (x0 - x_start) * dbu / 1000.0
            y_mm = (y0 - y_start) * dbu / 1000.0
            rows.append((gx, gy, x_mm, y_mm, t_count, sc_count))

    return rows


def analyze(input_path, output_path, stdcell_prefixes):
    """Main analysis routine."""
    layout = kdb.Layout()
    print(f"Loading {input_path}...")
    layout.read(str(input_path))

    dbu = layout.dbu
    top_cell = layout.top_cell()
    if top_cell is None:
        top_cells = layout.top_cells()
        if not top_cells:
            print("Error: no cells found in layout", file=sys.stderr)
            sys.exit(1)
        top_cell = top_cells[0]
        print(f"Warning: multiple top cells found, using '{top_cell.name}'")

    print(f"Top cell: {top_cell.name}, dbu: {dbu} um")
    print(f"Stdcell prefixes: {stdcell_prefixes}")

    # Find layers
    l_comp = find_layer(layout, *LAYER_COMP)
    l_poly2 = find_layer(layout, *LAYER_POLY2)
    l_pad = find_layer(layout, *LAYER_PAD)
    l_sram = find_layer(layout, *LAYER_SRAM_CORE)

    # Create stdcell marker layers
    print("Creating standard cell markers...")
    l_marker = create_stdcell_marker_layer(layout, stdcell_prefixes)

    print("Classifying standard cell libraries...")
    lib_layers, cell_info = create_per_library_markers(layout, stdcell_prefixes)
    print(f"  Libraries found: {', '.join(lib_layers.keys())}")

    # --- Detect reticle vs single design ---
    slots = enumerate_slots(layout, top_cell)

    if len(slots) <= 1:
        # Single design — treat top cell (or sole child) as the design
        print("Single design detected")
        target_cell = slots[0][1] if slots else top_cell
        slots = [("top", target_cell, kdb.Trans())]

    print(f"Found {len(slots)} design slots")

    # --- Analyze each slot ---
    summary_path = output_path
    grid_path = output_path.parent / (output_path.stem + "_grid" + output_path.suffix)
    cells_path = output_path.parent / (output_path.stem + "_cells" + output_path.suffix)

    summary_rows = []
    all_grid_rows = []
    all_cell_usage = []  # (slot_id, cell_name, library, cell_type, is_fill, count)

    for i, (cell_name, cell, trans) in enumerate(slots):
        slot_id = extract_slot_id(cell_name)
        pos_x_mm = trans.disp.x * dbu / 1000.0
        pos_y_mm = trans.disp.y * dbu / 1000.0

        print(f"\n[{i+1}/{len(slots)}] {slot_id} ({cell_name}) at ({pos_x_mm:.1f}, {pos_y_mm:.1f}) mm")

        metrics = analyze_slot(layout, cell, dbu, l_comp, l_poly2, l_pad, l_sram, l_marker)
        print(f"  Size: {metrics['width_mm']:.1f} x {metrics['height_mm']:.1f} mm")
        print(f"  Pads: {metrics['pad_count']}, SRAM: {metrics['sram_block_count']}, "
              f"Stdcells: {metrics['stdcell_count']}, Transistors: {metrics['transistor_count']}")

        # Count stdcell usage by type
        print(f"  Counting cell usage by type...")
        usage = count_stdcell_usage(layout, cell, stdcell_prefixes, cell_info)
        libs_used = {}
        for (lib, cell_type, is_fill), count in sorted(usage.items()):
            all_cell_usage.append((slot_id, cell_name, lib, cell_type, is_fill, count))
            if not is_fill:
                libs_used[lib] = libs_used.get(lib, 0) + count
        if libs_used:
            lib_summary = ", ".join(f"{lib}: {cnt:,}" for lib, cnt in sorted(libs_used.items(), key=lambda x: -x[1]))
            print(f"  Libraries (logic): {lib_summary}")

        summary_rows.append({
            "slot_id": slot_id,
            "cell_name": cell_name,
            "width_mm": f"{metrics['width_mm']:.2f}",
            "height_mm": f"{metrics['height_mm']:.2f}",
            "pos_x_mm": f"{pos_x_mm:.2f}",
            "pos_y_mm": f"{pos_y_mm:.2f}",
            "pad_count": metrics["pad_count"],
            "sram_block_count": metrics["sram_block_count"],
            "stdcell_count": metrics["stdcell_count"],
            "transistor_count": metrics["transistor_count"],
        })

        # Grid analysis for this slot
        print(f"  Computing grid density...")
        grid_rows = analyze_slot_grid(
            layout, cell, dbu, l_comp, l_poly2, l_marker, metrics["sram_region"]
        )
        for row in grid_rows:
            all_grid_rows.append((slot_id, cell_name) + row)
        print(f"  Grid: {len(grid_rows)} cells")

    # --- Write summary CSV ---
    print(f"\nWriting {summary_path}...")
    summary_fields = [
        "slot_id", "cell_name", "width_mm", "height_mm",
        "pos_x_mm", "pos_y_mm", "pad_count", "sram_block_count",
        "stdcell_count", "transistor_count",
    ]
    with open(summary_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)

    # --- Write grid CSV ---
    print(f"Writing {grid_path}...")
    with open(grid_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "slot_id", "cell_name", "grid_x", "grid_y",
            "x_mm", "y_mm", "transistor_count", "stdcell_count",
        ])
        for row in all_grid_rows:
            writer.writerow(row)

    # --- Write cell usage CSV ---
    print(f"Writing {cells_path}...")
    with open(cells_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "slot_id", "cell_name", "library", "cell_type",
            "is_fill", "instance_count",
        ])
        for row in all_cell_usage:
            writer.writerow(row)

    print(f"\nDone. {len(summary_rows)} slots, {len(all_grid_rows)} grid cells, {len(all_cell_usage)} cell type entries.")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze GDS/OAS layout: per-slot dimensions, pads, SRAM, transistor density"
    )
    parser.add_argument("input", type=Path, help="Input GDS or OAS file")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output CSV path (default: <input_stem>_analysis.csv)"
    )
    parser.add_argument(
        "--stdcell-prefix", action="append", default=None,
        help="Cell name prefix for standard cell identification (may be repeated; "
             "default: gf180mcu_fd_sc_, gf180mcu_as_sc_, gf180mcu_as_ex_)"
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    prefixes = args.stdcell_prefix or [
        "gf180mcu_fd_sc_",
        "gf180mcu_as_sc_",
        "gf180mcu_as_ex_",
    ]

    output = args.output or args.input.with_stem(args.input.stem + "_analysis").with_suffix(".csv")
    analyze(args.input, output, prefixes)


if __name__ == "__main__":
    main()
