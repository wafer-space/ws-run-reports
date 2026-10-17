"""Write the Markdown standard cell and SRAM density report for a run."""

import re
import statistics
from pathlib import Path

from . import links
from . import stats as stats_module
from .analyze import FILL_CELL_PREFIXES
from .features import FEATURE_LABELS
from .stats import REFERENCE_CELLS, FLIP_FLOP_RE, describe_cell, library_label, library_long_label

REPORT_NAME = "reticle_density_report.md"

HIGH_DENSITY = 10_000   # logic cells per mm2 of core
MEDIUM_DENSITY = 3_000
MINIMAL_LOGIC_CELLS = 1_000


def k(value: float) -> str:
    """Round to thousands the way the reports quote densities: 21800 -> '22k', 400 -> '<1k'."""
    if value <= 0:
        return "0"
    if value < 500:
        return "<1k"
    return f"{round(value / 1000):,}k"


def pct(fraction: float) -> str:
    if fraction <= 0:
        return "0%"
    if fraction < 0.005:
        return "<1%"
    return f"{round(fraction * 100)}%"


def count_fine(value: float) -> str:
    """Like count, with a decimal for small runs: 2430 -> '2.4k', 2054000 -> '2.05M', 12.4 -> '12'."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1000:,.1f}k"
    return f"{value:,.0f}"


def count(value: float) -> str:
    """Compact count for prose: 2054000 -> '2.1M', 36000 -> '36k', 122 -> '122'."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{round(value / 1000):,}k"
    return f"{value:,.0f}"


def link(design) -> str:
    """A design's code, linking to its page on the run's site."""
    return links.markdown(design.code, design.page_url)


def lib_link(library: str, long: bool = False) -> str:
    """A library's label, linking to its documentation."""
    return links.markdown(library_long_label(library) if long else library_label(library), links.library(library))


def cell_link(library: str, cell_type: str) -> str:
    """A standard cell's name, linking to its own documentation page."""
    return links.markdown(cell_type, links.cell(library, cell_type), code=True)


def macro_link(name: str) -> str:
    return links.markdown(name, links.macro(name), code=True)


def gds(text: str) -> str:
    """Every GDS layer number in text ("GDS 22/0", or "(22/0)" after a layer's name) linked to the PDK's layer table."""
    text = re.sub(r"GDS \d{1,3}/\d{1,3}\b", lambda m: links.markdown(m.group(0), links.layers()), text)
    return re.sub(r"\((\d{1,3}/\d{1,3})\)", lambda m: "(" + links.markdown(m.group(1), links.layers()) + ")", text)


def design_lib(design) -> str:
    """A design's library label, linking to the library when it uses just one."""
    if design.libraries and not design.is_mixed:
        return lib_link(design.primary_library)
    return design.library_label


def name(design, limit: int = 70) -> str:
    """A design's name, shortened, linking to its source repository."""
    return links.markdown(short(design.name, limit), design.project.repository)


def table(header: list, rows: list) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def short(text: str, limit: int = 70) -> str:
    text = text.replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def density_rows(designs):
    return [
        [link(d), design_lib(d), k(d.core_density), pct(d.pct_of_buffer_max), pct(d.utilisation),
         count(d.logic_cells), d.sram_label, name(d)]
        for d in designs
    ]


def build_report(stats) -> str:
    run = stats.run
    designs = stats.designs
    digital = stats.digital_designs
    libs = stats.libraries
    out = []
    add = out.append

    logic_total = stats.logic_cells
    fill_total = stats.fill_cells
    ratio = fill_total / logic_total if logic_total else 0

    add(f"# {run.title} — Standard Cell & SRAM Density Report\n")
    add(f"**{run.process} Process (GlobalFoundries 180nm), Shuttle {run.shuttle}**\n")

    add("## Introduction\n")
    on = f"the {run.title}"
    add(f"This report analyzes the standard cell and SRAM density achieved by the {len(designs)} unique public chip "
        f"designs on {on} reticle. "
        f"The reticle has {run.slots} slots; the public layout contains {stats.placements} slot placements "
        "(some designs appear more than once, and private designs are not included).\n"
        + ("\n> **Partial measurement:** parts of every die are excluded from these figures; see "
           "[Methodology](#methodology).\n" if stats.exclusions else ""))
    add("All designs were fabricated on GlobalFoundries' GF180MCU process, a 180-nanometer (0.18um) technology "
        "node. This is a mature, relatively large-geometry process — for comparison, modern smartphone chips use "
        "3nm or 5nm processes with features roughly 50x smaller.\n")
    add("> **Note on counting methodology:** All standard cell counts in this report count only **logic cells** — "
        "cells that perform actual computation (gates, flip-flops, buffers, multiplexers, etc.). Infrastructure "
        "cells are excluded: filler cells (fill, fillcap, endcap, filltie), well taps, antenna fix diodes, ESD "
        "diodes, and tie-high/tie-low cells. These infrastructure cells are inserted by automated tools to satisfy "
        f"manufacturing rules but perform no logic function. On this reticle there are {count(fill_total)} "
        f"infrastructure cell instances and {count(logic_total)} logic cell instances across the unique designs "
        f"— {ratio:.1f} infrastructure cells for every logic cell.\n")

    add("## What Are Standard Cells?\n")
    add('A "standard cell" is a pre-designed, pre-verified building block used to construct digital circuits. '
        "Think of them like LEGO bricks for chip design: each cell performs one simple logic function (an AND "
        "gate, a flip-flop for storing one bit, a buffer for boosting signal strength), and a chip designer "
        "assembles thousands or millions of them to build complex circuits.\n")
    add("Standard cells in a library all share the same height (so they line up in rows) but vary in width "
        "depending on their function. Automated tools place these cells in rows and then route wires between "
        "them.\n")
    add('The "density" of standard cells — how many fit per square millimeter — is a key measure of how '
        "efficiently a design uses its silicon area. Higher density generally means more logic functionality "
        "packed into less chip area, which reduces cost.\n")

    # --- Libraries -------------------------------------------------------
    add("## Standard Cell Libraries on This Reticle\n")
    base_height = min((stats.row_height_um(lib) for lib in libs), default=0) or 1
    rows = []
    for lib in libs:
        height = stats.row_height_um(lib)
        share = stats.library_logic_totals[lib] / logic_total if logic_total else 0
        rows.append([lib_link(lib, long=True), f"{height:.2f} um", f"{1000 / height:.0f} rows",
                     pct(base_height / height), count(stats.library_logic_totals[lib]), pct(share)])
    add(table(["Library", "Row Height", "Rows per mm", "Relative Density", "Logic instances", "Share"], rows) + "\n")
    add("Row height is the height of the cells' placement boundary, which is what rows are stacked at. "
        "Taller rows hold fewer cells per mm² but leave more room for wiring inside the cell.\n")
    mixed = [d for d in digital if d.is_mixed]
    if mixed:
        parts = []
        for d in mixed:
            mix = " + ".join(f"{count(n)} {lib_link(lib)}" for lib, n in sorted(d.libraries.items(), key=lambda kv: -kv[1]))
            parts.append(f"{link(d)} ({mix})")
        add("Most designs use one library exclusively. The designs that mix libraries are: " + "; ".join(parts) + ".\n")

    # --- Theoretical maximum ----------------------------------------------
    add("## Theoretical Maximum Standard Cell Density\n")
    add("If you filled an entire square millimeter with nothing but one type of logic standard cell (no wiring, "
        "no gaps, no infrastructure cells), the theoretical maximum density would be:\n")
    rows = []
    for label, what, pattern in REFERENCE_CELLS:
        row = [label]
        for lib in libs:
            cell = stats.reference_cell(lib, pattern)
            row.append(f"{k(cell.per_mm2)}/mm² ({cell_link(lib, cell.cell_type)}, {cell.width_um:.2f}um)" if cell else "—")
        rows.append(row + [what])
    add(table(["Cell Type"] + [lib_link(lib) for lib in libs] + ["What it does"], rows) + "\n")
    add("These are hard upper bounds — the density if you packed cells edge-to-edge with zero routing overhead. "
        "For each library the smallest cell of that kind is used; the 3.3V library has no drive strength 1 cells, "
        "so its smallest cells are the `_2` variants.\n")
    add("In practice, real designs achieve significantly less because:\n")
    add("- **(a) Routing overhead** — wires connecting cells need room, which limits how tightly cells can be placed\n"
        f"- **(b) Infrastructure cells** — fillers, taps, antenna diodes, and tie cells make up "
        f"{pct(fill_total / (fill_total + logic_total) if fill_total + logic_total else 0)} of cell instances on "
        "this reticle\n"
        "- **(c) Mixed cell types** — designs use a mix of small and large cells\n"
        "- **(d) Power planning** — power/ground straps consume area\n"
        "- **(e) Clock distribution** — clock tree buffers and wiring take space\n")

    # --- Achieved density ---------------------------------------------------
    add("## Achieved Standard Cell Density — Design Averages\n")
    add('The following tables show the average logic standard cell density for each design\'s "core area" — the '
        f"interior of the chip excluding the I/O pad ring (a {stats_module.PAD_RING_MM * 1000:.0f}um border of "
        "large pads around the perimeter used for external connections).\n")
    add('"% of max" compares against the buffer theoretical maximum for the design\'s primary library. '
        '"Cell area" is the share of the core area actually covered by logic cells — the placement utilisation '
        "of the die as a whole, including any area left empty or given to SRAM.\n")
    ranked = [d for d in stats.by_core_density if d.logic_cells >= MINIMAL_LOGIC_CELLS]
    header = ["Design", "Library", "Core SC/mm²", "% of max", "Cell area", "Logic SC", "SRAM", "Project"]
    groups = [
        (f"High Density (above {k(HIGH_DENSITY)} logic SC/mm² core average)",
         [d for d in ranked if d.core_density >= HIGH_DENSITY]),
        (f"Medium Density ({k(MEDIUM_DENSITY)}–{k(HIGH_DENSITY)} logic SC/mm² core average)",
         [d for d in ranked if MEDIUM_DENSITY <= d.core_density < HIGH_DENSITY]),
        (f"Low Density (below {k(MEDIUM_DENSITY)} logic SC/mm² core average)",
         [d for d in ranked if d.core_density < MEDIUM_DENSITY]),
    ]
    for title, group in groups:
        if group:
            add(f"### {title}\n")
            add(table(header, density_rows(group)) + "\n")
    minimal = [d for d in designs if d.logic_cells < MINIMAL_LOGIC_CELLS]
    if minimal:
        add("### Minimal (analog, custom or test structures)\n")
        add(f"These designs contain fewer than {MINIMAL_LOGIC_CELLS:,} logic standard cells:\n")
        add(table(["Design", "Logic SC", "Transistors", "SRAM", "Pads", "Project"],
                  [[link(d), f"{d.logic_cells:,}", count(d.transistors), d.sram_label, d.pads_label, name(d)]
                   for d in sorted(minimal, key=lambda d: d.code)]) + "\n")

    # --- Peak grid -----------------------------------------------------------
    side, step = stats_module.length_label(stats.window_um, True), stats_module.length_label(stats.step_um, True)
    add(f"## Achieved Density — Peak {side} x {side} Regions\n")
    if windowed(stats):
        add(f"While the averages above include sparse regions, the densest {side} x {side} square found anywhere on a "
            f"design shows the highest density it achieved. The square slides over the die in {step} steps and may "
            "not touch an SRAM macro.\n")
    else:
        add(f"While the averages above include sparse regions, the peak density in the best single {side} x {side} grid "
            "cell shows the maximum density achieved anywhere on each design. Grid cells that overlap an SRAM macro "
            "are excluded.\n")
    peaks = sorted((d for d in digital if d.peak_cells), key=lambda d: -d.peak_cells)[:15]
    add(table(["Design", "Peak Logic SC/mm²", "% of buffer max", "Library"],
              [[link(d), k(d.peak_cells), f"{pct(d.peak_pct_of_buffer_max)} of {k(d.buffer_max_per_mm2)}",
                design_lib(d)] for d in peaks]) + "\n")
    if peaks:
        best = peaks[0]
        region = "1mm²" if stats.window_um == 1000 else f"{side} square"
        add(f"The highest achieved density on this reticle is {pct(best.peak_pct_of_buffer_max)} of the buffer "
            f"theoretical maximum, observed in the densest {region} region of {link(best)}. The rest of that area is "
            "consumed by larger cells, infrastructure cells and the gaps left for routing.\n")

    # --- Library comparison ---------------------------------------------------
    compared = [lib for lib in libs if stats.single_library_designs(lib)]
    if len(compared) > 1:
        add("## Library Comparison\n")
        add("Comparing designs that use one library exclusively:\n")
        rows = [["Designs using this library"], ["Best core density"], ["Best peak grid cell"],
                ["Median core density"]]
        for lib in compared:
            group = stats.single_library_designs(lib)
            best_core = max(group, key=lambda d: d.core_density)
            best_peak = max(group, key=lambda d: d.peak_cells)
            median = stats.median_core_density(lib)
            buffer_max = stats.buffer_max(lib)
            rows[0].append(len(group))
            rows[1].append(f"{k(best_core.core_density)} SC/mm² · {pct(best_core.pct_of_buffer_max)} of max "
                           f"({link(best_core)})")
            rows[2].append(f"{k(best_peak.peak_cells)} SC/mm² · {pct(best_peak.peak_pct_of_buffer_max)} of max "
                           f"({link(best_peak)})")
            rows[3].append(f"{k(median)} SC/mm² · {pct(median / buffer_max if buffer_max else 0)} of max")
        add(table(["Metric"] + [lib_link(lib, long=True) for lib in compared], rows) + "\n")
        add("Differences between libraries here reflect which designs chose which library as much as the "
            "libraries themselves; the theoretical difference from row height alone is in the table above.\n")

    # --- Cell types -------------------------------------------------------------
    add("## Most Common Logic Cell Types\n")
    totals = stats.cell_type_totals
    add("The 15 most-used logic cell types across all unique designs on the reticle:\n")
    add(table(["Cell Type", "Library", "Instances", "What it does"],
              [[cell_link(lib, cell_type), lib_link(lib), count(n), describe_cell(cell_type)]
               for (lib, cell_type), n in totals.most_common(15)]) + "\n")
    nand2 = sum(n for (_, ct), n in totals.items() if ct.startswith("nand2_"))
    flops = sum(n for (_, ct), n in totals.items() if FLIP_FLOP_RE.match(ct))
    if nand2 and flops:
        add(f"Across the reticle there are {count(nand2)} 2-input NAND gates and {count(flops)} flip-flops — "
            f"{nand2 / flops:.1f} NAND2 gates per flip-flop.\n")

    # --- SRAM ----------------------------------------------------------------
    with_sram = sorted((d for d in designs if d.has_sram), key=lambda d: (-d.sram_macros, d.code))
    add("## SRAM Block Usage\n")
    add("SRAM (Static Random-Access Memory) blocks are pre-designed memory macros. Unlike standard cells, which "
        "are composed by automated tools, SRAM blocks are hand-optimized fixed-size units designed to store data "
        "as densely as possible.\n")
    if with_sram:
        add(f"{len(with_sram)} of the {len(designs)} designs include SRAM, holding "
            f"{stats.sram_bits / 8 / 1024:.0f} KiB of memory between them:\n")
        add(table(["Design", "SRAM macros", "SRAM bits", "SRAM area", "Logic SC", "Project"],
                  [[link(d), d.sram_label, f"{d.sram_bits:,}" if d.sram_bits else "—",
                    f"{d.sram_area_mm2:.2f} mm² ({pct(d.sram_area_mm2 / d.core_area_mm2)} of core)",
                    count(d.logic_cells), name(d)] for d in with_sram]) + "\n")
        add("SRAM macros are identified by cell name, and their area is the macro footprint. \"custom\" marks a "
            "design with SRAM marker shapes (GDS 108/5) but no recognised macro, where the count and size are "
            "not known and the area is that of the marked bitcell arrays.\n")
    else:
        add("None of the designs on this reticle include SRAM blocks.\n")

    # --- Transistor density -----------------------------------------------------
    add("## SRAM vs Standard Cell Transistor Density\n")
    add('"Transistor density" here counts the number of distinct regions where a gate electrode (polysilicon, '
        "GDS 30/0) crosses an active area (diffusion, GDS 22/0) — each such crossing forms one transistor.\n")
    add("### Theoretical Maximum Transistor Density for Standard Cells\n")
    best_flop = None
    for lib in libs:
        rows = []
        for label, _, pattern in REFERENCE_CELLS:
            cell = stats.reference_cell(lib, pattern)
            if cell:
                rows.append([cell_link(lib, cell.cell_type), f"{cell.width_um:.2f} um", k(cell.per_mm2), cell.transistors,
                             f"{k(cell.transistors_per_mm2)}/mm²"])
                if label == "Flip-flop" and (best_flop is None or cell.transistors_per_mm2 >
                                             best_flop.transistors_per_mm2):
                    best_flop = cell
        if rows:
            add(table([f"Cell ({lib_link(lib)})", "Width", "Cells/mm²", "Trans/cell",
                       "Trans/mm² theoretical max"], rows) + "\n")
    flop_max = best_flop.transistors_per_mm2 if best_flop else 0

    if stats.macros:
        add("### SRAM Macros\n")
        add(table(["Macro", "Size", "Trans/mm²", "% of flip-flop max", "Placements"],
                  [[macro_link(m.name), f"{m.width_um:.0f} x {m.height_um:.0f} um", f"{k(m.transistors_per_mm2)}/mm²",
                    pct(m.transistors_per_mm2 / flop_max if flop_max else 0), m.instances]
                   for m in sorted(stats.macros.values(), key=lambda m: -m.transistors_per_mm2)]) + "\n")
        add("The macro density includes the peripheral circuits (address decoders, sense amplifiers, I/O drivers) "
            "around the bitcell array, which is why larger macros of a family are denser than smaller ones.\n")

    add("### Best Standard Cell Regions\n")
    top_t = sorted((d for d in digital if d.peak_transistors), key=lambda d: -d.peak_transistors)[:8]
    add(table(["Design", "Peak 1mm² Trans/mm²", "% of flip-flop max", "Library"],
              [[link(d), f"{k(d.peak_transistors)}/mm²", pct(d.peak_transistors / flop_max if flop_max else 0),
                design_lib(d)] for d in top_t]) + "\n")
    add("Infrastructure cells are excluded from logic cell counts but their transistors (decoupling capacitors in "
        "particular) are included in transistor counts.\n")

    # --- Process features ---------------------------------------------------------
    if stats.has_features:
        add(features_section(stats))

    # --- Key findings ---------------------------------------------------------
    add("## Key Findings\n")
    findings = []
    if ranked:
        top = ranked[0]
        findings.append(
            f"The densest logic standard cell design, {link(top)} ({top.name}), achieves "
            f"**{k(top.core_density)} logic SC/mm²** averaged over its core ({pct(top.pct_of_buffer_max)} of buffer "
            f"max), with a peak of **{k(top.peak_cells)} logic SC/mm²** in its densest 1mm² region.")
    if libs:
        findings.append("Standard cell libraries in use: " + ", ".join(
            f"**{lib_link(lib)}** ({pct(stats.library_logic_totals[lib] / logic_total)} of logic cells)"
            for lib in libs) + ".")
    densities = [d.core_density for d in digital if d.logic_cells >= MINIMAL_LOGIC_CELLS]
    if densities:
        findings.append(
            f"The median digital design achieves **{k(statistics.median(densities))} logic SC/mm²** over its core. "
            f"{sum(1 for v in densities if v >= HIGH_DENSITY)} of {len(densities)} designs exceed "
            f"{k(HIGH_DENSITY)} logic SC/mm².")
    if stats.macros and top_t:
        common = max(stats.macros.values(), key=lambda m: m.instances)
        findings.append(
            f"The best standard cell region reaches **{k(top_t[0].peak_transistors)} transistors/mm²** "
            f"({link(top_t[0])}); the most used SRAM macro, {macro_link(common.name)}, is "
            f"{k(common.transistors_per_mm2)} transistors/mm².")
    findings.append(
        f"Infrastructure cells (fillers, taps, antenna diodes, ties) outnumber logic cells **{ratio:.1f} to 1** "
        f"across the reticle ({count(fill_total)} vs {count(logic_total)}). Any density analysis must exclude "
        "these to avoid dramatically overstating actual logic content.")
    if totals:
        (lib, cell_type), n = totals.most_common(1)[0]
        findings.append(f"The most common logic cell is **{cell_link(lib, cell_type)}** ({count(n)} instances in "
                        f"{lib_link(lib)}).")
    for i, finding in enumerate(findings, 1):
        add(f"{i}. {finding}\n")

    # --- Per-design detail ------------------------------------------------------
    add("## Per-Design Details\n")
    add(table(
        ["Design", "Cell", "Die (mm)", "Core mm²", "Placements", "Pads", "Logic SC", "Infra SC", "Transistors",
         "SRAM", "Libraries"],
        [[link(d), f"`{d.cell_name}`", f"{d.width_mm:.2f} x {d.height_mm:.2f}", f"{d.core_area_mm2:.1f}",
          d.placements, d.pads_label, f"{d.logic_cells:,}", f"{d.fill_cells:,}", f"{d.transistors:,}", d.sram_label,
          ", ".join(f"{lib_link(lib)}: {n:,}" for lib, n in sorted(d.libraries.items(), key=lambda kv: -kv[1])) or "—"]
         for d in designs]) + "\n")

    # --- Methodology -------------------------------------------------------------
    add("## Methodology\n")
    add("- **Logic cell counts** come from walking the layout hierarchy and counting instances of every cell "
        "whose name contains a standard cell library prefix, excluding types starting with "
        + ", ".join(f"`{p}`" for p in FILL_CELL_PREFIXES) + ".\n"
        "- **Transistor counts** are the number of merged polygons in the boolean AND of the diffusion (22/0) and "
        "gate polysilicon (30/0) layers, leaving out dummy fill cells, whose diffusion and polysilicon squares "
        "overlap without forming transistors.\n"
        + (f"- **Core area** is the area of each design's `{stats.meta['core_cell']}` cell.\n"
           if stats.meta.get("core_cell") else
           f"- **Core area** is (die width − {2 * stats_module.PAD_RING_MM:.2f}mm) x (die height − "
           f"{2 * stats_module.PAD_RING_MM:.2f}mm), removing a {stats_module.PAD_RING_MM * 1000:.0f}um pad ring "
           "from each side.\n") +
        "- **Cell dimensions** are the width and height of each standard cell's placement boundary (GDS 0/0), "
        "measured from the cells present in this layout.\n"
        "- **Theoretical maximum** = (1000um / cell width) x (1000um / row height).\n"
        "- **Pads** are openings on the pad layer (37/0) at least 20um across. Those in the pad ring (within "
        "400um of the die edge) or in a second ring of pads inside it are bond pads; the others are probe pads, "
        "shown as \"+ N probe\". Letters and logos on the pad layer are not pads.\n"
        + boundary_note(stats)
        + (f"- **Peak figures** are the densest {side} x {side} square anywhere inside each die, found by sliding the "
           f"square in {step} steps over the die and skipping positions that touch an SRAM macro. Logic cells are "
           "placed by their origin and transistors by the centre of their gate."
           + (" They are given per mm².\n" if stats.window_um != 1000 else "\n")
           if windowed(stats) else
           f"- **Peak figures** are the best single cell of a {side} x {side} grid laid over each design, skipping grid "
           "cells that overlap an SRAM macro. Grid cells at the top and right edges of a die are smaller than "
           f"{side}², so peaks are lower bounds.\n") +
        "- **SRAM macros** are counted by cell name. The `sram_block_count` column of the summary CSV is kept "
        "for comparison with earlier results; it counts SramCore marker shapes, of which each GF180MCU macro "
        "has two.\n"
        "- Designs placed more than once on the reticle are counted once.\n"
        + exclusion_note(stats))
    for heading, text in run.report.get("notes", {}).items():
        add(f"### {heading}\n")
        # Lines within a paragraph may be wrapped in the TOML; blank lines separate paragraphs.
        add("\n\n".join(" ".join(para.split()) for para in text.strip().split("\n\n")) + "\n")

    add("---\n")
    add(f"*Generated by [ws-run-reports](https://github.com/wafer-space/ws-run-reports) from "
        f"`{Path(run.layout['file']).name}` (md5 `{run.layout['md5']}`) in "
        f"[{run.repo}{'/' + run.path if run.path else ''}]({run.source_url}). Analysis method: " + links.markdown("KLayout", links.tool("KLayout")) + " boolean geometry operations on GDS layers. "
        f"Grid resolution: {side} x {side}. Density figures are rounded to the nearest 1k.*")
    return gds("\n".join(out) + "\n")


def features_section(stats) -> str:
    """Which transistor voltages and optional process features the designs use."""
    designs = stats.designs
    out = ["## Process Features and Voltages\n",
           f"Which transistor voltages and optional devices of the {stats.run.process} process the "
           f"{len(designs)} designs use. Voltages count both the libraries a design chose (standard cells and "
           "SRAM) and transistors the designer drew. Devices count only what the designer drew: standard cells, "
           "SRAM macros, I/O pads and fill are left out, because every die has them. A single test structure "
           "counts the same as a large block.\n"]
    rows = [[v, f"{len(stats.voltage_users(v))} of {len(designs)}",
             ", ".join(link(d) for d in stats.voltage_users(v))] for v in stats.voltage_levels]
    out.append(table(["Transistor voltage", "Designs", "Which"], rows) + "\n")
    rows = [[label, f"{len(users)} of {len(designs)}", ", ".join(link(d) for d in users) or "—"]
            for _, label, users in stats.feature_popularity]
    out.append(table(["Device", "Designs drawing it", "Which"], rows) + "\n")
    rows = []
    for d in designs:
        gates = " / ".join(f"{d.custom_gates.get(v, 0):,}" for v in ("3.3 V", "5 V", "6 V"))
        def notes(key):
            parts = ([", ".join(d.mim_levels)] if key == "mim" and d.mim_levels else []) + \
                    ([f"only in {', '.join(d.ip_sources[key])}"] if d.ip_only(key) else [])
            return f" ({'; '.join(parts)})" if parts else ""
        devices = ", ".join(FEATURE_LABELS[key] + notes(key) for key in d.device_features)
        rows.append([link(d), ", ".join(d.voltages) or "—", gates, devices or "—",
                     ", ".join(lib.replace("gf180mcu_", "") for lib in d.io_libraries) or "—"])
    out.append(table(["Design", "Voltages", "Custom transistors 3.3 / 5 / 6 V", "Devices drawn", "I/O library"],
                     rows) + "\n")
    out.append("Detection uses the open GF180MCU layers: a transistor is gate polysilicon (30/0) over diffusion "
               "(22/0), thick oxide inside Dualgate (55/0), 5 V where V5_XTOR (112/1) also covers it and 6 V where "
               "it does not; MIM capacitors are FuseTop (75/0) shapes; poly resistors are Poly2 under RES_MK "
               "(110/5), high resistance under the Resistor layer (62/0) and otherwise unsalicided under SAB "
               "(49/0) or salicided. Other devices are found by their marker layers.\n")
    return "\n".join(out)


def boundary_note(stats) -> str:
    """Say where cell sizes came from when the layout lacks placement boundaries."""
    reference, bbox = stats.boundary_sources.get("reference", 0), stats.boundary_sources.get("bbox", 0)
    if not reference and not bbox:
        return ""
    text = (f"- **Missing placement boundaries:** {reference + bbox} standard cells in this layout have no "
            "placement boundary (GDS 0/0).")
    if reference:
        text += (f" For {reference} of them the boundary measured from the wafer.space Run 1 and Run 2 layouts "
                 "of the same cell is used.")
    if bbox:
        text += f" For {bbox} no reference exists and the cell's bounding box is used, which overstates its size."
    return text + "\n"


def windowed(stats) -> bool:
    """Whether the peaks come from the sliding window rather than the fixed 1 mm grid."""
    return any(d.windows for d in stats.designs)


def exclusion_note(stats) -> str:
    """A Markdown paragraph saying which cells were left out of the measurements, or nothing."""
    if not stats.exclusions:
        return ""
    groups = "; ".join(f"{name.replace('_', ' ')} (" + ", ".join(f"`{p}`" for p in patterns) + ")"
                       for name, patterns in stats.exclusions.items())
    keep = stats.meta.get("keep") or []
    kept = (" Cells matching " + ", ".join(f"`{p}`" for p in keep) + " are measured even inside those."
            if keep else "")
    return ("- **Excluded from the measurements:** " + groups + "." + kept + " Logic cell, transistor and "
            "SRAM figures therefore cover only part of each die and are not directly comparable with reports "
            "that measure whole dies. Die sizes are measured on the whole die, and bond pads on the whole die apart from its seal ring.\n")


def write_report(run, out_dir: Path) -> Path:
    stats = stats_module.load(run, out_dir)
    path = out_dir / REPORT_NAME
    path.write_text(build_report(stats))
    return path
