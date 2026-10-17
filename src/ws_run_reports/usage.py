"""Device and process feature usage of each design, in full, with where each device came from.

For every design this measures, with no threshold:

* **designer** scope: devices drawn outside the standard cells, SRAM macros,
  I/O pad cells, dummy fill, seal ring and wafer.space artwork (the same cells
  features.py leaves out), with uses / count / area / average area each;
* the transistor gate matrix by kind and voltage, for the designer's blocks
  and separately for the pad cells (**pads** scope);
* the libraries it used (standard cells, SRAM, pad cells), by placements;
* metal coverage of each metal layer by what the designer drew plus the
  standard cells and SRAM (pads, seal ring, fill and artwork excluded), and
  the highest metal used;
* provenance: which of the designer-scope devices are the designer's own and
  which come from reused IP blocks (IP_RULES), each block's share being the
  design measured again with the block also left out.

Definitions (layer numbers of the open GF180MCU PDK):

* gate = Poly2 AND COMP; thick oxide inside Dualgate, 5 V where V5_XTOR also
  covers it and 6 V where not, 3.3 V otherwise; n or p by Nplus/Pplus;
* MOS capacitor = gate under MOS_CAP_MK; SAB transistor = gate whose source
  or drain (COMP outside Poly2, touching the gate) has salicide block (SAB);
* MIM capacitor = FuseTop shape; its level is the via on its top plate
  (Via4: Metal4-Metal5), not vias that merely pass underneath;
* resistors: Poly2 or COMP under RES_MK (high resistance under Resistor,
  unsalicided under SAB, salicided otherwise), Nwell under RES_MK, and the
  Metal1-6 resistor markers (110/11-16);
* bipolar transistors: LVS_BJT markers and placements of the PDK's npn_* and
  pnp_* cells; the other devices are their marker layers.

This is the measurement wafer.space's run reports and the GF180 feature
comparison share, so output names and columns are kept stable.
"""

import hashlib
import json
import re
from collections import Counter

import klayout.db as kdb

from .exclude import Selection, base_name, matches

LAYERS = {
    "COMP": (22, 0), "Poly2": (30, 0), "Nwell": (21, 0), "DNWELL": (12, 0), "Dualgate": (55, 0),
    "V5_XTOR": (112, 1), "NAT": (5, 0), "LDMOS_XTOR": (226, 0), "SAB": (49, 0), "Resistor": (62, 0),
    "RES_MK": (110, 5), "FuseTop": (75, 0), "CAP_MK": (117, 5), "MOS_CAP_MK": (166, 5),
    "Schottky_diode": (241, 0), "ZENER": (178, 0), "DIODE_MK": (115, 5), "WELL_DIODE_MK": (153, 51),
    "LVS_BJT": (118, 5), "EFUSE_MK": (80, 5), "PLFUSE": (125, 5), "POLYFUSE": (220, 0), "OTP_MK": (173, 5),
    "IND_MK": (151, 5), "Nplus": (32, 0), "Pplus": (31, 0),
    "Metal1": (34, 0), "Metal2": (36, 0), "Metal3": (42, 0), "Metal4": (46, 0), "Metal5": (81, 0),
    "MetalTop": (53, 0), "Via1": (35, 0), "Via2": (38, 0), "Via3": (40, 0), "Via4": (41, 0), "Via5": (82, 0),
    **{f"Metal{n}_Res": (110, 10 + n) for n in range(1, 7)},
}
METALS = ["Metal1", "Metal2", "Metal3", "Metal4", "Metal5", "MetalTop"]
# A MIM's top plate (FuseTop) connects up through this via to the metal above.
TOP_PLATE_VIAS = {"Via2": "Metal2-Metal3", "Via3": "Metal3-Metal4", "Via4": "Metal4-Metal5", "Via5": "Metal5-MetalTop"}

UNITS = {
    "gates": "gate finger; area of Poly2 AND COMP",
    "resistors": "resistor body; area of the body under its marker",
    "mim": "FuseTop shape; area of the capacitor top plate",
    "other": "merged marker shape; area of the marker",
    "cells": "cell placement; no area",
    "metal": "merged metal; area and share of the design",
}

# (device, unit) of the designer scope, in output order.
DEVICES = [
    ("custom_3v3", "gates"), ("custom_5v", "gates"), ("custom_6v", "gates"), ("native", "gates"),
    ("ldmos", "gates"), ("moscap", "gates"), ("mim", "mim"),
    ("hres", "resistors"), ("poly_unsal", "resistors"), ("poly_sal", "resistors"), ("diff_res", "resistors"),
    ("nwell_res", "resistors"), ("metal_res", "resistors"),
    ("dnwell", "other"), ("bjt", "other"), ("schottky", "other"), ("diode", "other"), ("well_diode", "other"),
    ("zener", "other"), ("efuse", "other"), ("otp", "other"), ("inductor", "other"), ("cap_marker_other", "other"),
]
GATE_KINDS = ["nmos", "pmos", "nmos_sab", "pmos_sab", "nmoscap", "pmoscap"]
VOLTS = ["3v3", "5v", "6v"]

FIELDS = ["slot_id", "cell_name", "scope", "device", "uses", "count", "area_um2", "avg_area_um2", "unit"]
METAL_FIELDS = ["slot_id", "cell_name", "layer", "area_um2", "share"]
PROVENANCE_FIELDS = ["slot_id", "cell_name", "device", "source_class", "ip_cell", "ip_origin", "count", "area_um2",
                     "avg_area_um2", "basis"]
HASH_FIELDS = ["slot_id", "cell_name", "content_hash"]

# Library cells, by the vendor field of gf180mcu_<vendor>_<kind>_...
FOUNDRY, THIRD, OWN = "foundry", "third_party", "own"
VENDORS = {
    "fd": (FOUNDRY, "GlobalFoundries GF180MCU PDK (gf180mcu_fd_*)"),
    "ocd": (THIRD, "Open Circuit Design (gf180mcu_ocd_*)"),
    "ws": (THIRD, "wafer.space (gf180mcu_ws_*)"),
    "as": (THIRD, "Avalon Semiconductors (gf180mcu_as_*)"),
    "osu": (THIRD, "Oklahoma State University (gf180mcu_osu_*)"),
}
STD_RE = re.compile(r"gf180mcu_([a-z0-9]+)_(sc|ex)_(\w+?)__")
SRAM_RE = re.compile(r"(gf180mcu_([a-z0-9]+)_ip_sram)__sram\d+x\d+")
IO_RE = re.compile(r"(gf180mcu_([a-z0-9]+)_io)__")
BJT_CELL_RE = re.compile(r"^(npn|pnp)_")

# Reused blocks among the designer's cells: (cell name patterns, label, class, origin, basis).
IP_RULES = [
    (["simple_por"], "simple_por", THIRD, "Caravel harness power-on reset, vendored at ip/simple_por",
     "confirmed: cell name on the die; the vendored GDS is byte-identical in the five repositories"),
    (["tt_pg_*", "tt_asw_*"], "tt_pg / tt_asw", THIRD,
     "Tiny Tapeout power gates and analog switch (smunaut/tt-multiplexer)",
     "confirmed: cell name on the die and in the repository's tt-multiplexer submodule"),
    (["apad"], "apad", FOUNDRY, "modified copy of gf180mcu_fd_io__asig_5p0 (contains GF_NI_ASIG_5P0_BASE)",
     "confirmed: foundry sub-cell name inside it"),
    (["r2r"], "r2r", THIRD, "8-bit R-2R DAC, probably mattvenn/gf-r2r-dac (Tiny Tapeout tt_um_gf_r2r_dac)",
     "guess: same generated resistor cell name (ppolyf_u_1k_7HW445) and the same 27 resistors"),
    (["fill10_supplyVDD"], "fill10_supplyVDD", FOUNDRY,
     "decoupling cell in the die's own pad frame, probably derived from gf180mcu_fd_io__fill10",
     "guess: from the cell name only"),
]


def library_key(name: str) -> str | None:
    """'std:<lib>' / 'sram:<family>' / 'io:<family>' for a library cell, else None."""
    base = base_name(name)
    if m := SRAM_RE.search(base):
        return "sram:" + m.group(1)
    if m := STD_RE.search(base):
        return f"std:{m.group(1)}_{m.group(2)}_{m.group(3)}"
    if m := IO_RE.search(base):
        return "io:" + m.group(1)
    return None


class Measure:
    """Regions of one cell's hierarchy under a selection, merged in a deep shape store."""

    def __init__(self, layout, cell, selection: Selection):
        self.layout, self.cell, self.selection = layout, cell, selection
        self.dss = kdb.DeepShapeStore()
        self.index = {name: layout.find_layer(kdb.LayerInfo(*ld)) for name, ld in LAYERS.items()}
        self.cache = {}

    def __call__(self, name: str) -> kdb.Region:
        if name not in self.cache:
            index = self.index[name]
            self.cache[name] = (kdb.Region(self.selection.iterator(self.layout, self.cell, index), self.dss)
                                if index is not None else kdb.Region())
        return self.cache[name]

    def stat(self, region) -> tuple:
        merged = region.merged()
        return merged.count(), merged.area() * self.layout.dbu * self.layout.dbu


def gate_matrix(m: Measure) -> dict:
    """'<kind>_<volt>' -> (count, area_um2) of the transistor gates measured by ``m``."""
    poly, comp = m("Poly2"), m("COMP")
    gates = poly & comp
    sab_diffusion = (comp - poly).interacting(m("SAB"))
    cap_mk, dualgate, v5 = m("MOS_CAP_MK"), m("Dualgate"), m("V5_XTOR")
    out = {}
    for pol, implant in (("n", m("Nplus")), ("p", m("Pplus"))):
        g = gates & implant
        caps, fets = g & cap_mk, g - cap_mk
        sab_fets = fets.interacting(sab_diffusion)
        for kind, region in ((f"{pol}mos", fets - sab_fets), (f"{pol}mos_sab", sab_fets), (f"{pol}moscap", caps)):
            thick = region & dualgate
            for volt, r in (("3v3", region - dualgate), ("5v", thick & v5), ("6v", thick - v5)):
                count, area = m.stat(r)
                if count:
                    out[f"{kind}_{volt}"] = (count, area)
    return out


def devices(m: Measure, bjt_boxes: kdb.Region) -> dict:
    """device -> (count, area_um2) for the designer scope measured by ``m``."""
    poly, comp = m("Poly2"), m("COMP")
    dualgate, v5, res_mk, sab = m("Dualgate"), m("V5_XTOR"), m("RES_MK"), m("SAB")
    all_gates = poly & comp
    gates = all_gates - m("MOS_CAP_MK")
    thick = gates & dualgate
    poly_res = poly & res_mk
    poly_plain = poly_res - m("Resistor")
    fusetop = m("FuseTop")
    metal_res = kdb.Region()
    for n in range(1, 7):
        metal_res += m(f"Metal{n}_Res")
    found = {
        "custom_3v3": gates - dualgate, "custom_5v": thick & v5, "custom_6v": thick - v5,
        "native": gates & m("NAT"), "ldmos": gates & m("LDMOS_XTOR"), "moscap": all_gates & m("MOS_CAP_MK"),
        "mim": fusetop,
        "hres": poly_res & m("Resistor"), "poly_unsal": poly_plain & sab, "poly_sal": poly_plain - sab,
        "diff_res": comp & res_mk, "nwell_res": (m("Nwell") & res_mk) - comp - poly, "metal_res": metal_res,
        "dnwell": m("DNWELL"), "bjt": m("LVS_BJT") + bjt_boxes, "schottky": m("Schottky_diode"),
        "diode": m("DIODE_MK"), "well_diode": m("WELL_DIODE_MK"), "zener": m("ZENER"),
        "efuse": m("EFUSE_MK") + m("PLFUSE") + m("POLYFUSE"), "otp": m("OTP_MK"), "inductor": m("IND_MK"),
        "cap_marker_other": m("CAP_MK").not_interacting(fusetop),
    }
    return {key: m.stat(region) for key, region in found.items()}


def mim_top_vias(m: Measure) -> dict:
    """'Metal4-Metal5' etc. -> MIM count, by the via that lands on each MIM's top plate.

    Vias of routing that only passes underneath a MIM also lie within its
    outline, but always lower in the stack, so each plate's level is the
    highest via inside it.
    """
    out = Counter()
    unassigned = m("FuseTop").merged()
    for via, level in reversed(TOP_PLATE_VIAS.items()):
        hit = unassigned.interacting(m(via).inside(unassigned))
        if not hit.is_empty():
            out[level] += hit.count()
            unassigned = unassigned.not_interacting(hit)
    return dict(out)


def bjt_cell_boxes(layout, cell, selection: Selection) -> kdb.Region:
    """Bounding boxes of the PDK's npn_*/pnp_* cells placed below ``cell`` (outside library cells)."""
    targets = [c.cell_index() for c in layout.each_cell() if BJT_CELL_RE.match(base_name(c.name))]
    boxes = kdb.Region()
    if not targets:
        return boxes
    it = kdb.RecursiveInstanceIterator(layout, cell)
    it.targets = targets
    if selection.excluded:
        it.unselect_cells(selection.excluded)
        it.select_cells(selection.kept)
    for _ in it.each():
        boxes.insert(it.inst_cell().bbox().transformed(it.trans() * it.inst_trans()))
    return boxes


def stats(count: int, area: float) -> dict:
    return {"uses": int(count > 0), "count": count, "area_um2": round(area, 3),
            "avg_area_um2": round(area / count, 3) if count else 0}


def libraries(cell, selection: Selection, library_of: dict) -> Counter:
    """'std:<lib>' / 'sram:<family>' / 'io:<family>' -> placements below ``cell``."""
    return Counter(selection.flat_counts(cell, library_of.get))


class PadMatrices:
    """Gate matrix of each pad cell, measured once and reused for every design."""

    def __init__(self, layout):
        self.layout, self.cache = layout, {}

    def __call__(self, cell_index: int) -> dict:
        if cell_index not in self.cache:
            self.cache[cell_index] = gate_matrix(Measure(self.layout, self.layout.cell(cell_index), Selection()))
        return self.cache[cell_index]


def ip_blocks(layout, cell, designer: Selection) -> list:
    """(rule, cell indices) of the reused IP blocks among the designer's cells below ``cell``."""
    excluded = set(designer.excluded)
    below = [ci for ci in [cell.cell_index(), *cell.each_child_cell()] if ci not in excluded]
    seen = set(below)
    stack = list(below)
    while stack:          # every cell below that the designer's selection still reaches
        for child in layout.cell(stack.pop()).each_child_cell():
            if child not in seen and child not in excluded:
                seen.add(child)
                stack.append(child)
    found = []
    for rule in IP_RULES:
        cells = [ci for ci in seen if matches(layout.cell(ci).name, rule[0])]
        if cells:
            found.append((rule, cells))
    return found


def measure(layout, cell, run_selection: Selection, designer: Selection, metal_selection: Selection,
            library_of: dict, pad_matrices: PadMatrices) -> dict:
    """Everything this module reports for one design: usage records, metal rows, provenance rows, content hash."""
    dbu2 = layout.dbu * layout.dbu
    die_area = cell.bbox().area() * dbu2
    m = Measure(layout, cell, designer)
    bjt_boxes = bjt_cell_boxes(layout, cell, designer)
    found = devices(m, bjt_boxes)
    records = [{"scope": "designer", "device": key, "unit": UNITS[unit], **stats(*found[key])} for key, unit in DEVICES]
    for level, n in sorted(mim_top_vias(m).items()):
        records.append({"scope": "designer", "device": f"mim_top_via_{level}", "unit": "MIM capacitor; no area",
                        **stats(n, 0.0)})

    own_matrix = gate_matrix(m)
    placements = libraries(cell, run_selection, library_of)
    pad_matrix = Counter()
    pad_area = Counter()
    pad_cells = Counter(run_selection.flat_counts(cell, lambda ci: ci if library_of.get(ci, "").startswith("io:")
                                                  else None))
    for ci, n in pad_cells.items():
        for key, (count, area) in pad_matrices(ci).items():
            pad_matrix[key] += count * n
            pad_area[key] += area * n
    for scope, matrix in (("designer", {k: v for k, v in own_matrix.items()}),
                          ("pads", {k: (pad_matrix[k], pad_area[k]) for k in pad_matrix})):
        for kind in GATE_KINDS:
            for volt in VOLTS:
                count, area = matrix.get(f"{kind}_{volt}", (0, 0.0))
                records.append({"scope": scope, "device": f"{kind}_{volt}", "unit": UNITS["gates"],
                                **stats(count, area)})
    for key, n in sorted(placements.items()):
        records.append({"scope": "library", "device": key, "unit": UNITS["cells"], **stats(n, 0.0)})

    # Metal coverage by the designer, standard cells and SRAM.
    metal = Measure(layout, cell, metal_selection)
    metal_rows, highest = [], 0
    for i, layer in enumerate(METALS, start=1):
        area = metal(layer).merged().area() * dbu2
        metal_rows.append({"layer": layer, "area_um2": round(area, 1), "share": round(area / die_area, 4) if die_area else 0})
        if area > 0:
            highest = i
    records.append({"scope": "designer", "device": "highest_metal", "unit": "metal level (1-5, 6 = MetalTop)",
                    "uses": int(highest > 0), "count": highest, "area_um2": 0, "avg_area_um2": 0})

    # Provenance: library cells by vendor, pad gates, then the designer's devices split into reused IP and own.
    provenance = []

    def row(device, cls, ip_cell, origin, count, basis, area=None):
        if count:
            provenance.append({"device": device, "source_class": cls, "ip_cell": ip_cell, "ip_origin": origin,
                               "count": count, "area_um2": "" if area is None else round(area, 3),
                               "avg_area_um2": "" if area is None else round(area / count, 3), "basis": basis})

    for key, n in sorted(placements.items()):
        kind, library = key.split(":", 1)
        vendor = library.split("_")[0] if kind == "std" else library.split("_")[1]
        cls, origin = VENDORS.get(vendor, (THIRD, f"unknown vendor prefix gf180mcu_{vendor}_"))
        device = {"std": "standard_cells_" + library[-3:], "sram": "sram_macros", "io": "pad_cells"}[kind]
        name = f"gf180mcu_{library}" if kind == "std" else library
        row(device, cls, name, origin, n, "confirmed: library cell name prefix")
    pad_families = Counter()
    for ci, n in pad_cells.items():
        family = library_of[ci][3:]
        for key, (count, area) in pad_matrices(ci).items():
            pad_families[(family, key, "count")] += count * n
            pad_families[(family, key, "area")] += area * n
    for family, key in sorted({(f, k) for f, k, _ in pad_families}):
        cls, origin = VENDORS.get(family.split("_")[1], (THIRD, family))
        row("pad_" + key, cls, family, origin, pad_families[(family, key, "count")],
            "confirmed: inside pad library cells", pad_families[(family, key, "area")])

    total = dict(found)
    for key, (count, area) in own_matrix.items():
        if "sab" in key or "cap" in key:
            total[key] = (count, area)
    remaining = {k: list(v) for k, v in total.items()}
    for (patterns, label, cls, origin, basis), cells in ip_blocks(layout, cell, designer):
        without = Selection(groups=designer.groups, keep=designer.keep, core_cell=designer.core_cell,
                            excluded=designer.excluded + cells, kept=designer.kept)
        rest_m = Measure(layout, cell, without)
        rest = devices(rest_m, bjt_cell_boxes(layout, cell, without))
        rest.update({k: v for k, v in gate_matrix(rest_m).items() if "sab" in k or "cap" in k})
        for device in sorted(total):
            share = total[device][0] - rest.get(device, (0, 0.0))[0]
            share_area = total[device][1] - rest.get(device, (0, 0.0))[1]
            row(device, cls, label, origin, share, basis, share_area)
            remaining[device][0] -= share
            remaining[device][1] -= share_area
    for device in sorted(remaining):
        row(device, OWN, "", "", remaining[device][0], "not in a recognised library or reused block",
            remaining[device][1])

    # The same design taped out again has the same size, libraries and designer devices.
    canonical = json.dumps([round(cell.dbbox().width(), 3), round(cell.dbbox().height(), 3), dict(placements),
                            {k: [v[0], round(v[1], 3)] for k, v in sorted(found.items())},
                            {k: [v[0], round(v[1], 3)] for k, v in sorted(own_matrix.items())}], sort_keys=True)
    return {"records": records, "metal": metal_rows, "provenance": provenance,
            "content_hash": hashlib.sha256(canonical.encode()).hexdigest()}
