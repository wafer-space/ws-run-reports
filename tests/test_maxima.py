from types import SimpleNamespace

from ws_run_reports import stats
from ws_run_reports.stats import REFERENCE_CELLS, RunStats


def _ref(library, pattern, used=(), whole_library=True):
    """RunStats.reference_cell for a run that used only the cells in ``used``."""
    run = SimpleNamespace(library={(c.library, c.cell_type): c for c in used})
    return RunStats.reference_cell(run, library, pattern, whole_library)


def test_buffer_maximum_comes_from_the_library():
    # A run that used only buf_2 still gets the library's buf_1 (3.36 x 3.92 um) as its buffer maximum.
    buf_2 = stats.LibCell("mcu7t5v0", "buf_2", False, 4.48, 3.92, 4.48, 3.92, 20)
    cell = _ref("mcu7t5v0", REFERENCE_CELLS[2][2], [buf_2])
    assert cell.cell_type == "buf_1"
    assert round(cell.per_mm2) == 75_923
    # Figures that need a measured transistor count stay with the cells the run used.
    assert _ref("mcu7t5v0", REFERENCE_CELLS[2][2], [buf_2], whole_library=False).cell_type == "buf_2"


def test_thin_oxide_copies_use_the_foundry_library():
    assert _ref("hfd_sc_mcu7t5v0", REFERENCE_CELLS[0][2]).cell_type == "inv_1"
    assert stats.library_label("hfd_sc_mcu7t5v0") == "7t-5V as 3.3V"
    assert stats.library_voltage("hfd_sc_mcu7t5v0") == 3.3


def test_unknown_library_has_no_reference_cells():
    assert _ref("osu_sc_gp9t3v3", REFERENCE_CELLS[2][2]) is None
