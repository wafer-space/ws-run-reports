"""Device usage, the gate matrix, MIM levels and provenance on a small synthetic design."""

import klayout.db as kdb

from ws_run_reports import usage
from ws_run_reports.exclude import Selection

DBU = 0.001


def um(v):
    return round(v / DBU)


def box(cell, layer, x0, y0, x1, y1):
    cell.shapes(cell.layout().layer(*layer)).insert(kdb.Box(um(x0), um(y0), um(x1), um(y1)))


def fet(cell, x, implant=(32, 0), extra=()):
    """A transistor at x: COMP 0..3 wide, a Poly2 gate across it at x+1..x+2."""
    box(cell, (22, 0), x, 0, x + 3, 2)
    box(cell, (30, 0), x + 1, -1, x + 2, 3)
    box(cell, implant, x - 0.5, -0.5, x + 3.5, 2.5)
    for layer in extra:
        box(cell, layer, x - 0.5, -0.5, x + 3.5, 2.5)


def design():
    layout = kdb.Layout()
    layout.dbu = DBU
    top = layout.create_cell("AB12_chip_top_0_0")
    fet(top, 0)                                             # plain 3.3 V NMOS
    fet(top, 10, extra=[(55, 0)])                           # 6 V NMOS (Dualgate, no V5_XTOR) ...
    box(top, (49, 0), 12.2, 0, 13, 2)                       # ... with SAB on its drain
    fet(top, 20, extra=[(166, 5)])                          # NMOS capacitor
    box(top, (75, 0), 30, 0, 40, 10)                        # MIM top plate
    box(top, (41, 0), 34, 4, 35, 5)                         # Via4 on it
    box(top, (38, 0), 31, 1, 32, 2)                         # Via2 of routing passing underneath
    por = layout.create_cell("simple_por")
    box(por, (30, 0), 0, 0, 10, 1)                          # a poly resistor inside a reused block
    box(por, (110, 5), 0, 0, 10, 1)
    top.insert(kdb.CellInstArray(por.cell_index(), kdb.Trans(um(50), 0)))
    return layout, top


def test_gate_matrix_mim_level_and_provenance():
    layout, top = design()
    found = usage.measure(layout, top, Selection(), Selection(), Selection(), {}, usage.PadMatrices(layout))
    rec = {(r["scope"], r["device"]): r for r in found["records"]}
    assert rec[("designer", "nmos_3v3")]["count"] == 1
    assert rec[("designer", "nmos_sab_6v")]["count"] == 1
    assert rec[("designer", "nmoscap_3v3")]["count"] == 1
    assert rec[("designer", "custom_3v3")]["count"] == 1 and rec[("designer", "custom_6v")]["count"] == 1
    assert rec[("designer", "mim")]["count"] == 1
    # Level from the via on the plate, not the Via2 passing underneath.
    assert ("designer", "mim_top_via_Metal4-Metal5") in rec and ("designer", "mim_top_via_Metal2-Metal3") not in rec
    assert rec[("designer", "poly_sal")]["count"] == 1
    prov = {(r["device"], r["source_class"], r["ip_cell"]): r["count"] for r in found["provenance"]}
    assert prov[("poly_sal", "third_party", "simple_por")] == 1
    assert ("poly_sal", "own", "") not in prov
    assert prov[("custom_3v3", "own", "")] == 1
    assert len(found["content_hash"]) == 64


def test_gates_split_across_cells_count_once():
    """One gate drawn across two cells is one transistor (unmerged deep regions count each piece)."""
    layout = kdb.Layout()
    layout.dbu = DBU
    top = layout.create_cell("AB12_chip_top_0_0")
    half = layout.create_cell("half_comp")
    box(half, (22, 0), 0, 0, 2, 2)                          # half of the diffusion
    box(half, (32, 0), -0.5, -0.5, 2, 2.5)
    for x in (0, 2):                                        # two abutting halves make one 4 um wide COMP
        top.insert(kdb.CellInstArray(half.cell_index(), kdb.Trans(um(x), 0)))
    box(top, (30, 0), 1.5, -1, 2.5, 3)                      # the gate's poly crosses the seam
    m = usage.Measure(layout, top, Selection())
    assert usage.gate_matrix(m)["nmos_3v3"][0] == 1
