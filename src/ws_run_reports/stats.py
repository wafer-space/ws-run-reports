"""Derive per-design and per-run statistics from the analysis CSV files.

Nothing here opens the layout. The Markdown report and the web page are both
views of the :class:`RunStats` built by :func:`load`.
"""

import csv
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .classify import classify
from .config import Project, Run

OUTPUT_STEM = "reticle_analysis"

# Width of the I/O pad ring on each side of a die. GF180MCU I/O cells are 350 um deep.
PAD_RING_MM = 0.35

# A design counts as using several libraries when a second library holds at
# least this share of its logic cells.
MIXED_LIBRARY_SHARE = 0.01

# Reference cells for the theoretical maximum tables: (label, description, regex on cell type).
# The smallest matching cell of each library is used, because not every
# library has a drive strength 1 variant.
REFERENCE_CELLS = [
    ("Inverter", "Flips a signal", r"inv_\d+"),
    ("NAND gate", "Basic logic gate", r"nand2_\d+"),
    ("Buffer", "Strengthens a signal", r"buff?_\d+"),
    ("Flip-flop", "Stores one bit", r"(dffq|dfxtp)_\d+"),
]

CELL_DESCRIPTIONS = {
    "nand2": "2-input NAND gate", "nand3": "3-input NAND gate", "nand4": "4-input NAND gate",
    "nor2": "2-input NOR gate", "nor3": "3-input NOR gate", "nor4": "4-input NOR gate",
    "and2": "2-input AND gate", "and3": "3-input AND gate", "or2": "2-input OR gate", "or3": "3-input OR gate",
    "xor2": "2-input XOR gate", "xnor2": "2-input XNOR gate", "xor3": "3-input XOR gate",
    "inv": "Inverter", "clkinv": "Clock inverter", "buf": "Buffer", "buff": "Buffer", "clkbuf": "Clock buffer",
    "oai21": "OR-AND-Invert compound gate", "aoi21": "AND-OR-Invert compound gate",
    "oai22": "OR-AND-Invert (2x2 inputs)", "aoi22": "AND-OR-Invert (2x2 inputs)",
    "oai211": "OR-AND-Invert compound gate", "aoi211": "AND-OR-Invert compound gate",
    "oai31": "OR-AND-Invert compound gate", "aoi31": "AND-OR-Invert compound gate",
    "oai221": "OR-AND-Invert compound gate", "aoi221": "AND-OR-Invert compound gate",
    "mux2": "2-input multiplexer", "mux4": "4-input multiplexer",
    "dffq": "D flip-flop (1 bit storage)", "dffrnq": "D flip-flop with reset", "dffsnq": "D flip-flop with set",
    "dffnq": "D flip-flop (falling edge)", "dffrsnq": "D flip-flop with set and reset",
    "dfxtp": "D flip-flop (1 bit storage)", "dfrtp": "D flip-flop with reset", "dfstp": "D flip-flop with set",
    "sdffq": "Scan D flip-flop", "sdffrnq": "Scan D flip-flop with reset",
    "latq": "Latch (level-sensitive)", "latrnq": "Latch with reset", "dlyb": "Delay buffer",
    "dlxtp": "Latch (level-sensitive)", "dlxfp": "Latch (level-sensitive)", "dlybuff": "Delay buffer", "clkbuff": "Clock buffer",
    "nand2b": "2-input NAND, one input inverted", "nor2b": "2-input NOR, one input inverted",
    "and2b": "2-input AND, one input inverted", "or2b": "2-input OR, one input inverted",
    "maj3": "3-input majority gate", "fa": "Full adder", "ha": "Half adder",
    "dlya": "Delay buffer", "dlyc": "Delay buffer", "dlyd": "Delay buffer",
    "addh": "Half adder", "addf": "Full adder", "icgtp": "Clock gating cell", "bufz": "Tri-state buffer",
    "invz": "Tri-state inverter", "hold": "Bus hold cell",
}

FLIP_FLOP_RE = re.compile(r"^s?d(ff|f[a-z]*t)")
SRAM_SIZE_RE = re.compile(r"sram(\d+)x(\d+)")


def library_label(library: str) -> str:
    """'mcu7t5v0' -> '7t-5V', 'mcu7t3v3' -> '7t-3.3V'."""
    m = re.fullmatch(r"mcu(\d+)t(\d)v(\d)", library)
    if not m:
        return library
    tracks, volts, tenths = m.groups()
    return f"{tracks}t-{volts}V" if tenths == "0" else f"{tracks}t-{volts}.{tenths}V"


def library_long_label(library: str) -> str:
    m = re.fullmatch(r"mcu(\d+)t(\d)v(\d)", library)
    if not m:
        return library
    tracks, volts, tenths = m.groups()
    voltage = f"{volts}V" if tenths == "0" else f"{volts}.{tenths}V"
    return f"{library} ({tracks}-track, {voltage})"


def describe_cell(cell_type: str) -> str:
    base, _, drive = cell_type.rpartition("_")
    text = CELL_DESCRIPTIONS.get(base or cell_type, "")
    if text and drive.isdigit() and int(drive) > 1:
        text += f" ({drive}x drive)"
    return text


@dataclass
class LibCell:
    library: str
    cell_type: str
    is_fill: bool
    width_um: float
    height_um: float
    bbox_width_um: float
    bbox_height_um: float
    transistors: int

    @property
    def area_um2(self) -> float:
        return self.width_um * self.height_um

    @property
    def per_mm2(self) -> float:
        """Cells per mm2 when tiled edge to edge at their placement boundary."""
        return 1e6 / self.area_um2

    @property
    def bbox_per_mm2(self) -> float:
        """The figure the March 2026 report used: tiling at the oversized bounding box."""
        return 1e6 / (self.bbox_width_um * self.bbox_height_um)

    @property
    def transistors_per_mm2(self) -> float:
        return self.transistors * self.per_mm2


@dataclass
class Macro:
    name: str
    width_um: float
    height_um: float
    transistors: int
    instances: int

    @property
    def area_mm2(self) -> float:
        return self.width_um * self.height_um / 1e6

    @property
    def transistors_per_mm2(self) -> float:
        return self.transistors / self.area_mm2

    @property
    def bits(self) -> int:
        m = SRAM_SIZE_RE.search(self.name)
        return int(m.group(1)) * int(m.group(2)) if m else 0

    @property
    def family(self) -> str:
        """'fd' for the foundry macros, 'ocd' for the Open Circuit Design ones, ..."""
        m = re.match(r"gf180mcu_(\w+?)_ip_sram", self.name)
        return m.group(1) if m else ""

    @property
    def short_name(self) -> str:
        m = SRAM_SIZE_RE.search(self.name)
        return f"sram{m.group(1)}x{m.group(2)} ({self.family})" if m else self.name


@dataclass
class Design:
    code: str
    cell_name: str
    project: Project
    width_mm: float
    height_mm: float
    pads: int
    sram_blocks: int
    logic_cells: int
    transistors: int
    placements: int = 1
    positions: list = field(default_factory=list)
    libraries: dict = field(default_factory=dict)       # library -> logic cell count
    fill_cells: int = 0
    cell_usage: dict = field(default_factory=dict)      # (library, cell_type) -> logic cell count
    logic_area_mm2: float = 0.0
    fill_area_mm2: float = 0.0
    stdcell_transistors: int = 0
    sram_area_mm2: float = 0.0
    sram_macro_area_mm2: float = 0.0
    pad_area_mm2: float = 0.0
    macros: dict = field(default_factory=dict)          # macro name -> instances
    sram_bits: int = 0
    sram_transistors: int = 0
    peak_cells: int = 0
    peak_transistors: int = 0
    grid: list = field(default_factory=list)            # (gx, gy, transistors, logic cells)
    buffer_max_per_mm2: float = 0.0
    category: str = ""

    @property
    def name(self) -> str:
        return self.project.name or self.code

    @property
    def sram_macros(self) -> int:
        """Number of SRAM macros identified by name.

        ``sram_blocks`` counts SramCore marker shapes instead, and the
        GF180MCU macros contain two of those each.
        """
        return sum(self.macros.values())

    @property
    def has_sram(self) -> bool:
        return bool(self.macros) or self.sram_blocks > 0

    @property
    def sram_label(self) -> str:
        if self.macros:
            return str(self.sram_macros)
        return "custom" if self.sram_blocks else "0"

    @property
    def die_area_mm2(self) -> float:
        return self.width_mm * self.height_mm

    @property
    def core_area_mm2(self) -> float:
        """Die area inside the I/O pad ring."""
        return max(0.0, self.width_mm - 2 * PAD_RING_MM) * max(0.0, self.height_mm - 2 * PAD_RING_MM)

    @property
    def core_density(self) -> float:
        """Logic standard cells per mm2 of core area."""
        return self.logic_cells / self.core_area_mm2 if self.core_area_mm2 else 0.0

    @property
    def core_transistor_density(self) -> float:
        return self.transistors / self.core_area_mm2 if self.core_area_mm2 else 0.0

    @property
    def primary_library(self) -> str:
        return max(self.libraries, key=self.libraries.get) if self.libraries else ""

    @property
    def is_mixed(self) -> bool:
        total = sum(self.libraries.values())
        ranked = sorted(self.libraries.values(), reverse=True)
        return len(ranked) > 1 and ranked[1] / total >= MIXED_LIBRARY_SHARE

    @property
    def library_label(self) -> str:
        if not self.libraries:
            return "none"
        return "mixed" if self.is_mixed else library_label(self.primary_library)

    @property
    def pct_of_buffer_max(self) -> float:
        return self.core_density / self.buffer_max_per_mm2 if self.buffer_max_per_mm2 else 0.0

    @property
    def peak_pct_of_buffer_max(self) -> float:
        return self.peak_cells / self.buffer_max_per_mm2 if self.buffer_max_per_mm2 else 0.0

    @property
    def utilisation(self) -> float:
        """Share of the core area covered by logic standard cells."""
        return self.logic_area_mm2 / self.core_area_mm2 if self.core_area_mm2 else 0.0

    @property
    def custom_transistors(self) -> int:
        """Transistors that are in neither a standard cell nor an SRAM macro."""
        return max(0, self.transistors - self.stdcell_transistors - self.sram_transistors)

    @property
    def area_breakdown(self) -> dict:
        """How the die area is spent, in mm2. The parts sum to the die area."""
        ring = self.die_area_mm2 - self.core_area_mm2
        used = self.logic_area_mm2 + self.fill_area_mm2 + self.sram_area_mm2
        return {
            "Pad ring": ring,
            "Logic cells": self.logic_area_mm2,
            "SRAM": self.sram_area_mm2,
            "Filler and tap cells": self.fill_area_mm2,
            "Other": max(0.0, self.core_area_mm2 - used),
        }

    @property
    def slot_label(self) -> str:
        return {"1x1": "1 × 1", "1x0p5": "1 × ½", "0p5x1": "½ × 1", "0p5x0p5": "½ × ½"}.get(
            self.project.slot_size, self.project.slot_size)


@dataclass
class RunStats:
    run: Run
    designs: list
    library: dict        # (library, cell_type) -> LibCell
    macros: dict         # name -> Macro
    placements: int

    # --- library level -------------------------------------------------

    @property
    def libraries(self) -> list:
        """Libraries in use, most used first."""
        totals = self.library_logic_totals
        return sorted(totals, key=lambda lib: -totals[lib])

    @property
    def library_logic_totals(self) -> Counter:
        totals = Counter()
        for d in self.designs:
            totals.update(d.libraries)
        return totals

    def row_height_um(self, library: str) -> float:
        heights = Counter(c.height_um for (lib, _), c in self.library.items() if lib == library)
        return heights.most_common(1)[0][0] if heights else 0.0

    def reference_cell(self, library: str, pattern: str):
        """Smallest cell of a library whose type matches a reference pattern."""
        matches = [c for (lib, ct), c in self.library.items() if lib == library and re.fullmatch(pattern, ct)]
        return min(matches, key=lambda c: (c.area_um2, c.cell_type)) if matches else None

    def buffer_max(self, library: str) -> float:
        cell = self.reference_cell(library, REFERENCE_CELLS[2][2])
        return cell.per_mm2 if cell else 0.0

    # --- run level -----------------------------------------------------

    @property
    def logic_cells(self) -> int:
        return sum(d.logic_cells for d in self.designs)

    @property
    def fill_cells(self) -> int:
        return sum(d.fill_cells for d in self.designs)

    @property
    def transistors(self) -> int:
        return sum(d.transistors for d in self.designs)

    @property
    def sram_bits(self) -> int:
        return sum(d.sram_bits for d in self.designs)

    @property
    def die_area_mm2(self) -> float:
        return sum(d.die_area_mm2 for d in self.designs)

    @property
    def cell_type_totals(self) -> Counter:
        """Logic cell instances per (library, cell_type) across the unique designs."""
        totals = Counter()
        for d in self.designs:
            totals.update(d.cell_usage)
        return totals

    @property
    def digital_designs(self) -> list:
        return [d for d in self.designs if d.logic_cells > 0]

    @property
    def by_core_density(self) -> list:
        return sorted(self.designs, key=lambda d: -d.core_density)

    @property
    def by_category(self) -> dict:
        groups = defaultdict(list)
        for d in self.designs:
            groups[d.category].append(d)
        return dict(sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])))

    def single_library_designs(self, library: str) -> list:
        return [d for d in self.digital_designs if not d.is_mixed and d.primary_library == library]

    def median_core_density(self, library: str) -> float:
        values = [d.core_density for d in self.single_library_designs(library)]
        return statistics.median(values) if values else 0.0


def _read(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load(run: Run, out_dir: Path) -> RunStats:
    """Build the statistics for a run from the CSV files in ``out_dir``."""
    stem = out_dir / OUTPUT_STEM
    summary = _read(Path(f"{stem}.csv"))
    if not summary:
        raise FileNotFoundError(f"{stem}.csv not found; run 'ws-run-reports analyze {run.name}' first")

    library = {
        (r["library"], r["cell_type"]): LibCell(
            r["library"], r["cell_type"], r["is_fill"] == "True", float(r["width_um"]), float(r["height_um"]),
            float(r["bbox_width_um"]), float(r["bbox_height_um"]), int(r["transistor_count"]))
        for r in _read(Path(f"{stem}_library.csv"))
    }
    macros = {
        r["macro"]: Macro(r["macro"], float(r["width_um"]), float(r["height_um"]),
                          int(r["transistor_count"]), int(r["instances"]))
        for r in _read(Path(f"{stem}_macros.csv"))
    }

    projects = run.projects()
    designs = {}
    for r in summary:
        code = r["slot_id"]
        position = (float(r["pos_x_mm"]), float(r["pos_y_mm"]))
        if code in designs:
            designs[code].placements += 1
            designs[code].positions.append(position)
            continue
        designs[code] = Design(
            code=code, cell_name=r["cell_name"], project=projects.get(code, Project(code, code)),
            width_mm=float(r["width_mm"]), height_mm=float(r["height_mm"]), pads=int(r["pad_count"]),
            sram_blocks=int(r["sram_block_count"]), logic_cells=int(r["stdcell_count"]),
            transistors=int(r["transistor_count"]), positions=[position])
    first_cell = {d.cell_name: d for d in designs.values()}

    for r in _read(Path(f"{stem}_cells.csv")):
        d = first_cell.get(r["cell_name"])
        if d is None:
            continue
        count = int(r["instance_count"])
        cell = library.get((r["library"], r["cell_type"]))
        area = cell.area_um2 * count / 1e6 if cell else 0.0
        if cell:
            d.stdcell_transistors += cell.transistors * count
        if r["is_fill"] == "True":
            d.fill_cells += count
            d.fill_area_mm2 += area
        else:
            d.libraries[r["library"]] = d.libraries.get(r["library"], 0) + count
            d.cell_usage[(r["library"], r["cell_type"])] = count
            d.logic_area_mm2 += area

    for r in _read(Path(f"{stem}_grid.csv")):
        d = first_cell.get(r["cell_name"])
        if d is None:
            continue
        transistors, cells = int(r["transistor_count"]), int(r["stdcell_count"])
        d.grid.append((int(r["grid_x"]), int(r["grid_y"]), transistors, cells))
        d.peak_cells = max(d.peak_cells, cells)
        d.peak_transistors = max(d.peak_transistors, transistors)

    for r in _read(Path(f"{stem}_slot_areas.csv")):
        d = first_cell.get(r["cell_name"])
        if d is not None:
            d.sram_area_mm2 = float(r["sram_area_mm2"])
            d.pad_area_mm2 = float(r["pad_area_mm2"])

    for r in _read(Path(f"{stem}_slot_macros.csv")):
        d = first_cell.get(r["cell_name"])
        macro = macros.get(r["macro"])
        if d is None or macro is None:
            continue
        count = int(r["instances"])
        d.macros[macro.name] = count
        d.sram_bits += macro.bits * count
        d.sram_transistors += macro.transistors * count
        d.sram_macro_area_mm2 += macro.area_mm2 * count

    # The SramCore marker only covers the bitcell arrays. Where the macros are
    # known, their whole footprint is the area the design gave up to memory.
    for d in designs.values():
        d.sram_area_mm2 = max(d.sram_area_mm2, d.sram_macro_area_mm2)

    stats = RunStats(run=run, designs=sorted(designs.values(), key=lambda d: d.code),
                     library=library, macros=macros, placements=len(summary))
    for d in stats.designs:
        d.buffer_max_per_mm2 = stats.buffer_max(d.primary_library) if d.libraries else 0.0
        d.category = classify(d, run.categories)
    return stats
