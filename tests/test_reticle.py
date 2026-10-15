"""Slot labels on the reticle."""

import pytest

from ws_run_reports import reticle


def die(x, y, w=3.93, h=5.12):
    return {"x_mm": x, "y_mm": y, "width_mm": w, "height_mm": h}


# Part of ws-run1's G801 reticle: 8 columns at a 3.99 mm pitch, 5 rows at 5.18 mm.
RUN1 = {
    "BTAP": die(0.06, 0.06), "MOSB_a": die(8.04, 0.06), "MOSB_b": die(8.04, 5.24),
    "RZML": die(24.01, 5.24), "OCD2": die(4.05, 20.79, h=2.53), "TQVA": die(28.0, 20.79, w=1.94, h=2.53),
    "GD02": die(28.0, 10.42, w=1.94), "FS02": die(26.0, 10.42, w=1.94),
}


def labels(origin="top-left", letters="columns"):
    slots, columns, rows = reticle.slot_grid(list(RUN1.values()), 31.92, 25.95, origin, letters)
    return dict(zip(RUN1, (s["label"] for s in slots))), columns, rows


def test_wafer_space_labels_match_the_platform():
    found, columns, rows = labels()
    assert found["RZML"] == "G4", "the platform puts RZML in G4"
    assert (found["MOSB_a"], found["MOSB_b"]) == ("C5", "C4"), "and MOSB in C4 and C5"
    assert found["BTAP"] == "A5"
    assert found["OCD2"] == "B1"
    assert (found["GD02"], found["FS02"], found["TQVA"]) == ("H3", "G3", "H1"), "half slots share the full slot's label"
    assert [c["label"] for c in columns] == list("ABCDEFGH")
    assert [r["label"] for r in rows] == ["1", "2", "3", "4", "5"]
    assert columns[0]["left"] == pytest.approx(0.06 / 31.92)


def test_other_origins_and_axes():
    found, columns, rows = labels(origin="top-right")
    assert found["BTAP"] == "H5" and [c["label"] for c in columns][0] == "H"
    found, _, rows = labels(origin="bottom-left")
    assert found["BTAP"] == "A1" and rows[0]["label"] == "5"
    found, _, _ = labels(letters="rows")
    assert found["RZML"] == "D7"
    with pytest.raises(ValueError):
        labels(origin="middle")


def test_letters_past_z():
    assert reticle._letters(0) == "A" and reticle._letters(25) == "Z" and reticle._letters(26) == "AA"


def test_gfmpw0_labels_match_the_efabless_manifest():
    """GFMPW-0, rotated: rows lettered from the top, columns numbered from the right (A1 top right)."""
    pitch_x, pitch_y = 3.99, 5.18
    dies = {"6079": (7, 4), "5F3A": (0, 4), "0AFF": (7, 0), "8BB5": (0, 0), "56C6": (6, 2)}  # (column, row from bottom)
    placements = [die(0.09 + c * pitch_x, 0.09 + r * pitch_y, 3.88, 5.07) for c, r in dies.values()]
    slots, _, _ = reticle.slot_grid(placements, 31.82, 25.80, origin="top-right", letters="rows")
    assert dict(zip(dies, (s["label"] for s in slots))) == {
        "6079": "A1", "5F3A": "A8", "0AFF": "E1", "8BB5": "E8", "56C6": "C2"}


def test_labels_span_the_dies_in_their_row_and_column():
    """Run 1's top row and right column hold only half slots, so their labels are half size."""
    _, columns, rows = labels()
    assert rows[0]["height"] == pytest.approx(2.53 / 25.95), "row 1 is the half-height top row"
    assert rows[0]["top"] == pytest.approx((25.95 - 23.32) / 25.95)
    assert rows[3]["height"] == pytest.approx(5.12 / 25.95), "row 4 holds full slots"
    assert rows[1]["height"] == pytest.approx(5.18 / 25.95), "an empty row falls back to the pitch"
    assert columns[7]["width"] == pytest.approx(1.94 / 31.92), "column H holds half-width slots"
