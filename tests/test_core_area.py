"""The two areas a design's density is given over: its core, and everything inside the seal ring."""

from ws_run_reports.config import Project
from ws_run_reports.stats import Design


def design(**kw):
    # A 1 × 1 slot of the project template: 3932 × 5122 µm with a 26 µm seal ring.
    return Design(code="X", cell_name="x", project=Project("X", "X"), width_mm=3.932, height_mm=5.122, pads=0,
                  sram_blocks=0, logic_cells=100_000, transistors=0, **kw)


def test_core_without_a_config_is_the_templates():
    d = design()
    assert d.core_source == "template"
    assert round(d.core_area_mm2, 3) == round((3.932 - 0.884) * (5.122 - 0.884), 3)


def test_the_designs_own_core_area_wins_and_a_core_cell_over_that():
    d = design(config_core_mm2=12.0)
    assert (d.core_area_mm2, d.core_source) == (12.0, "design config")
    d = design(config_core_mm2=12.0, measured_core_mm2=10.0)
    assert (d.core_area_mm2, d.core_source) == (10.0, "core cell")


def test_inside_the_seal_ring_counts_the_pad_ring_against_the_design():
    d = design(seal_ring_mm=0.026)
    assert round(d.usable_area_mm2, 2) == round(3.880 * 5.070, 2)
    assert d.usable_density < d.core_density


def test_names_are_shown_with_the_usual_spellings_and_no_repeated_code():
    def named(code, name):
        return Design(code=code, cell_name="x", project=Project(code, name), width_mm=1, height_mm=1, pads=0,
                      sram_blocks=0, logic_cells=0, transistors=0).name
    assert named("TQVA", "TinyQV Risc-V SoC") == "TinyQV RISC-V SoC"
    assert named("WSLG", "Wafer.space Logo VGA Screensaver") == "wafer.space Logo VGA Screensaver"
    assert named("001", "TinyTapeout Factory Test") == "Tiny Tapeout Factory Test"
    assert named("AS04", "AS04 Multi-Project die using 3.3V SCL") == "Multi-Project die using 3.3V SCL"
    assert named("X", "") == "X"


def test_typos_in_names_are_fixed_for_display():
    from ws_run_reports.config import spelled
    assert spelled("100Mpbs 3 port Ethernet switch") == "100Mbps 3 port Ethernet switch"
    assert spelled("Wafer.Space Logo") == "wafer.space Logo"
    assert spelled("trained on FashioMNIST") == "trained on FashionMNIST"
    assert spelled("Unmanaged cut-though switch") == "Unmanaged cut-through switch"
