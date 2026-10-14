"""Which optional process features and transistor voltages each design uses.

Only what the designer drew counts. Standard cells, SRAM macros, I/O pad
cells, dummy fill and wafer.space artwork are left out, because every die
has them: the pads alone contain thick-oxide transistors, MOS capacitors
and resistors. The libraries a design chose are reported separately (the
standard cell libraries come from the cell counts, the I/O library from
here).

Layer numbers are those of the open GF180MCU PDK (``gf180mcu.lyp``):

* a transistor gate is Poly2 AND COMP; it is thick oxide inside Dualgate,
  5 V where V5_XTOR also covers it and 6 V where it does not, and 3.3 V
  otherwise; NAT marks native devices, LDMOS_XTOR the 10 V LDMOS and
  MOS_CAP_MK MOS capacitors (which are not counted as transistors);
* a resistor is Poly2 or COMP under RES_MK; poly resistors are high
  resistance under the Resistor layer, otherwise unsalicided under SAB or
  salicided;
* a MIM capacitor is a FuseTop shape; the via layer it touches gives the
  metal level it sits on;
* the remaining features are their marker layers.

A design "uses" a feature if it has any such shape, so a single test
structure counts the same as a large block.
"""

import re
from collections import Counter

import klayout.db as kdb

from .exclude import Selection, base_name

LAYERS = {
    "COMP": (22, 0), "Poly2": (30, 0), "DNWELL": (12, 0), "Dualgate": (55, 0), "V5_XTOR": (112, 1),
    "NAT": (5, 0), "LDMOS_XTOR": (226, 0), "SAB": (49, 0), "Resistor": (62, 0), "RES_MK": (110, 5),
    "FuseTop": (75, 0), "MOS_CAP_MK": (166, 5), "Schottky_diode": (241, 0), "ZENER": (178, 0),
    "LVS_BJT": (118, 5), "EFUSE_MK": (80, 5), "PLFUSE": (125, 5), "POLYFUSE": (220, 0), "OTP_MK": (173, 5),
    "IND_MK": (151, 5), "Via2": (38, 0), "Via3": (40, 0), "Via4": (41, 0), "Via5": (82, 0),
}

# (key, label, group) in display order. Groups: voltage, device.
FEATURES = [
    ("gates_3v3", "3.3 V transistors", "voltage"),
    ("gates_5v", "5 V transistors", "voltage"),
    ("gates_6v", "6 V transistors", "voltage"),
    ("gates_native", "Native transistors", "device"),
    ("gates_ldmos", "10 V LDMOS", "device"),
    ("mim", "MIM capacitors", "device"),
    ("moscap", "MOS capacitors", "device"),
    ("res_poly_high", "High-resistance poly resistors", "device"),
    ("res_poly_unsalicided", "Unsalicided poly resistors", "device"),
    ("res_poly_salicided", "Salicided poly resistors", "device"),
    ("res_diffusion", "Diffusion resistors", "device"),
    ("dnwell", "Deep N-well", "device"),
    ("bjt", "Bipolar transistors", "device"),
    ("schottky", "Schottky diodes", "device"),
    ("zener", "Zener diodes", "device"),
    ("efuse", "eFuses", "device"),
    ("otp", "One-time programmable memory", "device"),
    ("inductor", "Inductors", "device"),
]
FEATURE_LABELS = {key: label for key, label, _ in FEATURES}
MIM_VIA_LEVELS = {"Via2": "Metal2", "Via3": "Metal3", "Via4": "Metal4", "Via5": "Metal5"}

FIELDS = ["slot_id", "cell_name", "feature", "count", "area_um2"]

STDCELL_RE = re.compile(r"gf180mcu_\w+?_(?:sc|ex)_\w+?__")
SRAM_RE = re.compile(r"gf180mcu_\w+?_ip_sram__sram\d+x\d+")
IO_RE = re.compile(r"(gf180mcu_\w+?_io)__")
# Added by the wafer.space flow (dummy fill, seal ring, logo and ID artwork), not by the designer.
FILL_RE = re.compile(r"(_fill_cell|^(METAL\d|COMP|POLY2|Metal\d|Poly2)_FILL|^sealring|gf180mcu_ws_ip__)", re.I)


def is_library_cell(name: str) -> bool:
    base = base_name(name)
    return bool(STDCELL_RE.search(base) or SRAM_RE.search(base) or IO_RE.search(base) or FILL_RE.search(base))


def library_cells(layout) -> list:
    return [c.cell_index() for c in layout.each_cell() if is_library_cell(c.name)]


def io_cells(layout) -> dict:
    """cell index -> I/O library ('gf180mcu_fd_io', 'gf180mcu_ocd_io', ...) of every pad cell."""
    found = {}
    for cell in layout.each_cell():
        m = IO_RE.search(base_name(cell.name))
        if m:
            found[cell.cell_index()] = m.group(1)
    return found


def designer_selection(selection: Selection, libraries: list) -> Selection:
    """The run's selection, additionally skipping every library, pad and fill cell."""
    return Selection(groups=selection.groups, keep=selection.keep, core_cell=selection.core_cell,
                     excluded=selection.excluded + libraries, kept=selection.kept)


def measure(layout, cell, selection: Selection) -> dict:
    """feature -> (count, area_um2) for the designer-drawn devices below ``cell``.

    ``selection`` must skip the library cells (see :func:`designer_selection`).
    """
    dbu2 = layout.dbu * layout.dbu
    layer_index = {name: layout.find_layer(kdb.LayerInfo(*ld)) for name, ld in LAYERS.items()}

    def region(name):
        index = layer_index[name]
        if index is None:
            return kdb.Region()
        result = kdb.Region(selection.iterator(layout, cell, index))
        result.merge()
        return result

    poly, comp = region("Poly2"), region("COMP")
    dualgate, v5 = region("Dualgate"), region("V5_XTOR")
    moscap_mk, res_mk = region("MOS_CAP_MK"), region("RES_MK")

    all_gates = poly & comp
    moscap = all_gates & moscap_mk
    gates = all_gates - moscap_mk
    thick = gates & dualgate
    poly_res = poly & res_mk
    poly_plain = poly_res - region("Resistor")
    sab = region("SAB")
    fusetop = region("FuseTop")

    found = {
        "gates_3v3": gates - dualgate,
        "gates_5v": thick & v5,
        "gates_6v": thick - v5,
        "gates_native": gates & region("NAT"),
        "gates_ldmos": gates & region("LDMOS_XTOR"),
        "moscap": moscap,
        "res_poly_high": poly_res & region("Resistor"),
        "res_poly_unsalicided": poly_plain & sab,
        "res_poly_salicided": poly_plain - sab,
        "res_diffusion": comp & res_mk,
        "mim": fusetop,
        "dnwell": region("DNWELL"),
        "bjt": region("LVS_BJT"),
        "schottky": region("Schottky_diode"),
        "zener": region("ZENER"),
        "efuse": region("EFUSE_MK") + region("PLFUSE") + region("POLYFUSE"),
        "otp": region("OTP_MK"),
        "inductor": region("IND_MK"),
    }
    for via, metal in MIM_VIA_LEVELS.items():
        found[f"mim_on_{metal.lower()}"] = fusetop.interacting(region(via))

    result = {}
    for key, shapes in found.items():
        shapes.merge()
        if not shapes.is_empty():
            result[key] = (shapes.count(), shapes.area() * dbu2)
    return result


def io_libraries(cell, selection: Selection, io_cell_map: dict) -> dict:
    """'io:<library>' -> (placements, 0.0) of the pad cells below ``cell``."""
    counts = selection.flat_counts(cell, io_cell_map.get)
    return {f"io:{library}": (n, 0.0) for library, n in sorted(Counter(counts).items())}
