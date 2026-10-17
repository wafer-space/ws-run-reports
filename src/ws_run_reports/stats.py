"""Derive per-design and per-run statistics from the analysis CSV files.

Nothing here opens the layout. The Markdown report and the web page are both
views of the :class:`RunStats` built by :func:`load`.
"""

import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .classify import classify
from .features import FEATURES, FEATURE_LABELS, MIM_VIA_LEVELS
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

# Supply voltage of the SRAM macro families: the foundry macros are 5 V, Open Circuit Design's 3.3 V.
SRAM_FAMILY_VOLTAGE = {"fd": "5 V", "ocd": "3.3 V"}

FLIP_FLOP_RE = re.compile(r"^s?d(ff|f[a-z]*t)")
SRAM_SIZE_RE = re.compile(r"sram(\d+)x(\d+)")


# Library name prefixes (see analyze.library_name) and how they are labelled.
LIBRARY_VENDORS = {"": "", "as_sc_": "AS ", "as_ex_": "AS extra ", "osu_sc_": "OSU "}
LIBRARY_RE = re.compile(r"(?P<vendor>(?:as_sc_|as_ex_|osu_sc_)?)(?:mcu|gp|hd)?(?P<tracks>\d+)t(?P<volts>\d)v(?P<tenths>\d)")


def library_voltage(library: str) -> float:
    """Supply voltage a library is characterised for: 'mcu7t5v0' -> 5.0, 'osu_sc_gp9t3v3' -> 3.3."""
    m = LIBRARY_RE.fullmatch(library)
    return int(m["volts"]) + int(m["tenths"]) / 10 if m else 0.0


def library_label(library: str) -> str:
    """'mcu7t5v0' -> '7t-5V', 'as_sc_mcu7t3v3' -> 'AS 7t-3.3V', 'osu_sc_gp9t3v3' -> 'OSU 9t-3.3V'."""
    m = LIBRARY_RE.fullmatch(library)
    if not m:
        return library
    volts = m["volts"] if m["tenths"] == "0" else f"{m['volts']}.{m['tenths']}"
    return f"{LIBRARY_VENDORS[m['vendor']]}{m['tracks']}t-{volts}V"


def library_long_label(library: str) -> str:
    m = LIBRARY_RE.fullmatch(library)
    if not m:
        return library
    volts = m["volts"] if m["tenths"] == "0" else f"{m['volts']}.{m['tenths']}"
    return f"{library} ({LIBRARY_VENDORS[m['vendor']]}{m['tracks']}-track, {volts}V)"


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
    density_map: list = field(default_factory=list)     # every 1 mm square: dicts from _map.csv
    sram_rects: list = field(default_factory=list)      # (macro, x0, y0, x1, y1) in mm from the die corner
    windows: dict = field(default_factory=dict)         # kind -> densest 1 mm window, from _windows.csv
    window_mm: float = 1.0                              # side of the map squares and windows ([measure] grid_um)
    pad_ring_mm: float = PAD_RING_MM                    # [measure] pad_ring_um; 0 makes the whole design its core
    page_url: str = ""                                  # the design's page on the run's site
    features: dict = field(default_factory=dict)        # feature -> (count, area_um2), designer-drawn only
    buffer_max_per_mm2: float = 0.0
    category: str = ""
    # Area of the run's core cell (e.g. a Caravel user_project_wrapper), when it names one.
    measured_core_mm2: float | None = None

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
        """Die area inside the I/O pad ring, or the area of the run's core cell."""
        if self.measured_core_mm2 is not None:
            return self.measured_core_mm2
        return max(0.0, self.width_mm - 2 * self.pad_ring_mm) * max(0.0, self.height_mm - 2 * self.pad_ring_mm)

    @property
    def outside_core_label(self) -> str:
        return "Pad ring" if self.measured_core_mm2 is None else "Outside the user area"

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
        parts = {
            self.outside_core_label: ring,
            "Logic cells": self.logic_area_mm2,
            "SRAM": self.sram_area_mm2,
            "Filler and tap cells": self.fill_area_mm2,
            "Other": max(0.0, self.core_area_mm2 - used),
        }
        if self.measured_core_mm2 is None and self.pad_ring_mm == 0:
            del parts[self.outside_core_label]          # the whole design is its core
        return parts

    # --- process features -------------------------------------------------

    @property
    def device_features(self) -> list:
        """Designer-drawn device features present, in display order (voltages excluded)."""
        return [key for key, _, group in FEATURES if group == "device" and key in self.features]

    @property
    def custom_gates(self) -> dict:
        """Designer-drawn transistors by voltage: '3.3 V' -> count."""
        return {label: self.features[key][0] for key, label in
                (("gates_3v3", "3.3 V"), ("gates_5v", "5 V"), ("gates_6v", "6 V")) if key in self.features}

    @property
    def mim_levels(self) -> list:
        return [metal for metal in MIM_VIA_LEVELS.values() if f"mim_on_{metal.lower()}" in self.features]

    @property
    def io_libraries(self) -> dict:
        return {key[3:]: n for key, (n, _) in self.features.items() if key.startswith("io:")}

    @property
    def voltages(self) -> dict:
        """Transistor voltage -> what on the die uses it: libraries chosen and the designer's own devices."""
        found = defaultdict(list)
        for lib, n in sorted(self.libraries.items(), key=lambda kv: -kv[1]):
            volts = library_voltage(lib)
            if volts:
                found[f"{volts:g} V"].append(f"{library_label(lib)} standard cells")
        for name in sorted(self.macros):
            family = Macro(name, 0, 0, 0, 0).family
            if family in SRAM_FAMILY_VOLTAGE:
                found[SRAM_FAMILY_VOLTAGE[family]].append(f"{family} SRAM")
        for label, n in self.custom_gates.items():
            found[label].append(f"{n:,} custom transistor{'s' if n != 1 else ''}")
        return {v: found[v] for v in sorted(found, key=lambda v: float(v.split()[0]))}

    @property
    def slot_label(self) -> str:
        size = self.project.slot_size
        known = {"1x1": "1 × 1", "1x0p5": "1 × ½", "0p5x1": "½ × 1", "0p5x0p5": "½ × ½"}
        return known.get(size) or re.sub(r"^(\d+)x(\d+)$", r"\1 × \2", size)


@dataclass
class RunStats:
    run: Run
    designs: list
    library: dict        # (library, cell_type) -> LibCell
    macros: dict         # name -> Macro
    placements: int
    meta: dict = field(default_factory=dict)   # reticle_analysis_meta.json: what was measured and excluded

    @property
    def window_um(self) -> float:
        """Side of the density map squares and the densest window ([measure] grid_um)."""
        return float(self.meta.get("grid_um", 1000))

    @property
    def step_um(self) -> float:
        """Step the densest window slides in ([measure] bin_um)."""
        return float(self.meta.get("bin_um", 100))
    boundary_sources: Counter = field(default_factory=Counter)  # where cell sizes came from: layout, reference, bbox

    @property
    def exclusions(self) -> dict:
        """Groups of cells left out of the measurements: name -> cell name patterns."""
        return self.meta.get("exclude", {})

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

    @property
    def has_features(self) -> bool:
        return any(d.features for d in self.designs)

    def feature_users(self, feature: str) -> list:
        return [d for d in self.designs if feature in d.features]

    def voltage_users(self, voltage: str) -> list:
        return [d for d in self.designs if voltage in d.voltages]

    @property
    def voltage_levels(self) -> list:
        return sorted({v for d in self.designs for v in d.voltages}, key=lambda v: float(v.split()[0]))

    @property
    def feature_popularity(self) -> list:
        """(feature, label, designs using it) for every device feature, most used first."""
        rows = [(key, label, self.feature_users(key)) for key, label, group in FEATURES if group == "device"]
        return sorted(rows, key=lambda row: -len(row[2]))

    def single_library_designs(self, library: str) -> list:
        return [d for d in self.digital_designs if not d.is_mixed and d.primary_library == library]

    def median_core_density(self, library: str) -> float:
        values = [d.core_density for d in self.single_library_designs(library)]
        return statistics.median(values) if values else 0.0


def data_files(out_dir: Path) -> list:
    """The measurement files published with a run: the CSVs, what was measured, imported project details."""
    from .projects import PROJECTS_NAME
    files = sorted(out_dir.glob(f"{OUTPUT_STEM}*.csv")) + sorted(out_dir.glob(f"{OUTPUT_STEM}*.json"))
    return files + [path for path in [out_dir / PROJECTS_NAME] if path.exists()]


def _read(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def length_label(um: float, compact: bool = False) -> str:
    """A length as the report ("1mm", "100um") or the pages ("1 mm", "0.1 mm", "20 µm") write it."""
    if compact:
        return f"{um / 1000:g}mm" if um >= 1000 else f"{um:g}um"
    return f"{um / 1000:g} mm" if um >= 100 else f"{um:g} µm"


def load(run: Run, out_dir: Path) -> RunStats:
    """Build the statistics for a run from the CSV files in ``out_dir``."""
    stem = out_dir / OUTPUT_STEM
    summary = _read(Path(f"{stem}.csv"))
    if not summary:
        raise FileNotFoundError(f"{stem}.csv not found; run 'ws-run-reports analyze {run.name}' first")

    library_rows = _read(Path(f"{stem}_library.csv"))
    library = {
        (r["library"], r["cell_type"]): LibCell(
            r["library"], r["cell_type"], r["is_fill"] == "True", float(r["width_um"]), float(r["height_um"]),
            float(r["bbox_width_um"]), float(r["bbox_height_um"]), int(r["transistor_count"]))
        for r in library_rows
    }
    macros = {
        r["macro"]: Macro(r["macro"], float(r["width_um"]), float(r["height_um"]),
                          int(r["transistor_count"]), int(r["instances"]))
        for r in _read(Path(f"{stem}_macros.csv"))
    }

    meta_path = Path(f"{stem}_meta.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    # Map squares and windows are 1 mm unless the run measured smaller ones;
    # peak densities are always given per mm².
    window_mm = float(meta.get("grid_um", 1000)) / 1000
    pad_ring_mm = float(meta["pad_ring_um"]) / 1000 if "pad_ring_um" in meta else PAD_RING_MM
    per_mm2 = 1 / (window_mm * window_mm)

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
            transistors=int(r["transistor_count"]), positions=[position], window_mm=window_mm,
            pad_ring_mm=pad_ring_mm, page_url=f"{run.pages_url}projects/{code}.html")
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
        d.peak_cells = max(d.peak_cells, round(cells * per_mm2))
        d.peak_transistors = max(d.peak_transistors, round(transistors * per_mm2))

    # The sliding-window peaks replace the fixed grid's where they were measured.
    for r in _read(Path(f"{stem}_map.csv")):
        d = first_cell.get(r["cell_name"])
        if d is not None:
            d.density_map.append({"gx": int(r["grid_x"]), "gy": int(r["grid_y"]), "x": float(r["x_mm"]),
                                  "y": float(r["y_mm"]), "w": float(r["width_mm"]), "h": float(r["height_mm"]),
                                  "cells": int(r["stdcell_count"]), "transistors": int(r["transistor_count"]),
                                  "sram": float(r["sram_fraction"])})
    for r in _read(Path(f"{stem}_sram_rects.csv")):
        d = first_cell.get(r["cell_name"])
        if d is not None:
            d.sram_rects.append((r["macro"], float(r["x0_mm"]), float(r["y0_mm"]), float(r["x1_mm"]), float(r["y1_mm"])))
    for r in _read(Path(f"{stem}_windows.csv")):
        d = first_cell.get(r["cell_name"])
        if d is None:
            continue
        window = {"x": float(r["x_mm"]), "y": float(r["y_mm"]), "cells": int(r["stdcell_count"]),
                  "transistors": int(r["transistor_count"]), "sram": float(r["sram_fraction"])}
        d.windows[r["kind"]] = window
        if r["kind"] == "densest_sram_free":
            d.peak_cells, d.peak_transistors = round(window["cells"] * per_mm2), round(window["transistors"] * per_mm2)

    for r in _read(Path(f"{stem}_features.csv")):
        d = first_cell.get(r["cell_name"])
        if d is not None:
            d.features[r["feature"]] = (int(r["count"]), float(r["area_um2"]))

    for r in _read(Path(f"{stem}_slot_areas.csv")):
        d = first_cell.get(r["cell_name"])
        if d is not None:
            d.sram_area_mm2 = float(r["sram_area_mm2"])
            d.pad_area_mm2 = float(r["pad_area_mm2"])
            if r.get("core_area_mm2"):
                d.measured_core_mm2 = float(r["core_area_mm2"])

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

    meta_path = Path(f"{stem}_meta.json")
    stats = RunStats(run=run, designs=sorted(designs.values(), key=lambda d: d.code),
                     library=library, macros=macros, placements=len(summary),
                     meta=json.loads(meta_path.read_text()) if meta_path.exists() else {},
                     boundary_sources=Counter(r.get("boundary_source") or "layout" for r in library_rows))
    for d in stats.designs:
        d.buffer_max_per_mm2 = stats.buffer_max(d.primary_library) if d.libraries else 0.0
        d.category = classify(d, run.categories)
    return stats
