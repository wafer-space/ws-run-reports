"""The three scopes and the bin clipping of metal.py on a small synthetic layout."""

import klayout.db as kdb

from ws_run_reports import metal

METAL2 = (36, 0)
STEP = 250_000  # 250 um at dbu 0.001


def layout_with_everything():
    """A 1 x 1 mm die with a design shape, a fill cell, a seal ring, a pad cell and a wafer.space artwork cell,
    each a different size on Metal2 so their areas can be told apart."""
    layout = kdb.Layout()
    layout.dbu = 0.001
    m2 = layout.layer(*METAL2)
    top = layout.create_cell("TOP")
    # The die's bounding box, on a layer that isn't metal.
    boundary = layout.layer(0, 0)
    top.shapes(boundary).insert(kdb.Box(0, 0, 1_000_000, 1_000_000))
    # The design: two overlapping boxes straddling the bin edge at x = 250 um; merged, 200 x 100 um.
    top.shapes(m2).insert(kdb.Box(150_000, 0, 300_000, 100_000))
    top.shapes(m2).insert(kdb.Box(200_000, 0, 350_000, 100_000))
    for name, box in (("METAL2_FILL", kdb.Box(500_000, 500_000, 510_000, 510_000)),       # 100 um2
                      ("sealring", kdb.Box(0, 900_000, 1_000_000, 901_000)),              # 1,000 um2
                      ("gf180mcu_fd_io__bi_t", kdb.Box(800_000, 0, 820_000, 20_000)),     # 400 um2
                      ("gf180mcu_ws_ip__logo", kdb.Box(600_000, 600_000, 602_000, 602_000))):  # 4 um2
        cell = layout.create_cell(name)
        cell.shapes(m2).insert(box)
        top.insert(kdb.CellInstArray(cell.cell_index(), kdb.Trans()))
    return layout, top


def areas(layout, top, measure):
    metal._STATE.update(layout=layout, selections=metal.selections(layout, measure))
    _, rows = metal.measure_cell(top.cell_index())
    return {r["scope"]: r["area_um2"] for r in rows if r["layer"] == "Metal2"}


def test_scopes_add_fill_then_everything_else():
    layout, top = layout_with_everything()
    assert areas(layout, top, {}) == {"design": 20_000.0, "with_fill": 20_100.0, "all": 21_504.0}


def test_a_run_that_excludes_fill_still_measures_it_with_fill():
    layout, top = layout_with_everything()
    assert areas(layout, top, {"exclude": ["dummy_fill"]})["with_fill"] == 20_100.0


def test_fill_cells_leave_out_seal_ring_and_artwork():
    layout, _ = layout_with_everything()
    names = {layout.cell(ci).name for ci in metal.fill_cells(layout)}
    assert names == {"METAL2_FILL"}


def test_a_shape_across_bins_is_counted_once():
    layout, top = layout_with_everything()
    index = layout.find_layer(kdb.LayerInfo(*METAL2))
    design = metal.selections(layout, {})["design"]
    left = metal.merged_area(layout, top, index, design, kdb.Box(0, 0, STEP, STEP))
    right = metal.merged_area(layout, top, index, design, kdb.Box(STEP, 0, 2 * STEP, STEP))
    assert (left * 1e-6, right * 1e-6) == (10_000.0, 10_000.0)
