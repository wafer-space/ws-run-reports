"""End-to-end check of the analyser on a small synthetic reticle."""

import csv

import klayout.db as kdb
import pytest

from ws_run_reports import analyze

DBU = 0.001


def um(value):
    return round(value / DBU)


def make_stdcell(layout, name, width_um, transistors):
    """A 3.92 um tall cell with a placement boundary, an overhanging well and some gates."""
    cell = layout.create_cell(name)
    cell.shapes(layout.layer(0, 0)).insert(kdb.Box(0, 0, um(width_um), um(3.92)))
    cell.shapes(layout.layer(21, 0)).insert(kdb.Box(um(-0.43), um(1.76), um(width_um + 0.43), um(4.35)))
    comp = layout.layer(22, 0)
    poly = layout.layer(30, 0)
    if transistors:
        cell.shapes(comp).insert(kdb.Box(um(0.2), um(0.5), um(width_um - 0.2), um(1.5)))
        pitch = (width_um - 0.6) / transistors
        for i in range(transistors):
            x = 0.3 + i * pitch
            cell.shapes(poly).insert(kdb.Box(um(x), um(0.2), um(x + 0.1), um(1.8)))
    return cell


@pytest.fixture
def reticle(tmp_path):
    layout = kdb.Layout()
    layout.dbu = DBU
    inv = make_stdcell(layout, "gf180mcu_fd_sc_mcu7t5v0__inv_1", 2.24, 2)
    nand = make_stdcell(layout, "XY_gf180mcu_fd_sc_mcu7t5v0__nand2_1", 2.80, 4)
    fill = make_stdcell(layout, "gf180mcu_fd_sc_mcu7t5v0__fill_1", 0.56, 0)

    macro = layout.create_cell("gf180mcu_fd_ip_sram__sram64x8m8wm1")
    macro.shapes(layout.layer(108, 5)).insert(kdb.Box(0, 0, um(400), um(200)))

    design = layout.create_cell("ABCD_chip_top_0_0")
    design.shapes(layout.layer(0, 0)).insert(kdb.Box(0, 0, um(2000), um(2500)))
    design.shapes(layout.layer(37, 0)).insert(kdb.Box(um(10), um(10), um(70), um(70)))
    # A 10 x 4 array of inverters, a single NAND and a row of 5 fill cells.
    design.insert(kdb.CellInstArray(inv.cell_index(), kdb.Trans(um(500), um(500)),
                                    kdb.Vector(um(2.24), 0), kdb.Vector(0, um(3.92)), 10, 4))
    design.insert(kdb.CellInstArray(nand.cell_index(), kdb.Trans(um(500), um(700))))
    design.insert(kdb.CellInstArray(fill.cell_index(), kdb.Trans(um(500), um(800)),
                                    kdb.Vector(um(0.56), 0), kdb.Vector(0, um(3.92)), 5, 1))
    design.insert(kdb.CellInstArray(macro.cell_index(), kdb.Trans(um(1200), um(1500))))

    top = layout.create_cell("reticle")
    top.insert(kdb.CellInstArray(design.cell_index(), kdb.Trans(um(60), um(60))))
    top.insert(kdb.CellInstArray(design.cell_index(), kdb.Trans(um(4000), um(60))))
    text = layout.create_cell("TEXT")
    text.shapes(layout.layer(53, 0)).insert(kdb.Box(0, 0, um(100), um(100)))
    top.insert(kdb.CellInstArray(text.cell_index(), kdb.Trans(um(8000), um(60))))

    path = tmp_path / "reticle.oas"
    layout.write(str(path))
    return path


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("jobs", [1, 2])
def test_analyze_counts(reticle, tmp_path, jobs):
    paths = analyze.analyze(reticle, tmp_path / "out" / "reticle_analysis.csv", jobs=jobs)

    summary = read(paths["summary"])
    assert [r["slot_id"] for r in summary] == ["ABCD", "ABCD"], "both placements, and not the TEXT cell"
    row = summary[0]
    assert (row["width_mm"], row["height_mm"]) == ("2.00", "2.50")
    assert (row["pos_x_mm"], summary[1]["pos_x_mm"]) == ("0.06", "4.00")
    assert row["pad_count"] == "1"
    assert row["sram_block_count"] == "1"
    assert row["stdcell_count"] == "41", "40 inverters + 1 NAND; fill cells are not logic"
    assert row["transistor_count"] == str(40 * 2 + 4)

    usage = {(r["cell_type"], r["is_fill"]): int(r["instance_count"])
             for r in read(paths["cells"]) if r["cell_name"] == row["cell_name"]}
    assert usage == {("inv_1", "False"): 40, ("nand2_1", "False"): 1, ("fill_1", "True"): 5}

    grid = read(paths["grid"])
    assert sum(int(r["stdcell_count"]) for r in grid) == 2 * 41, "every logic cell lands in exactly one grid cell"
    # The die is 2.0 x 2.5 mm: a 2 x 3 grid, minus the one cell the SRAM macro sits in.
    assert len(grid) == 2 * (6 - 1)


def test_library_uses_placement_boundary(reticle, tmp_path):
    paths = analyze.analyze(reticle, tmp_path / "out" / "reticle_analysis.csv", jobs=1)
    library = {r["cell_type"]: r for r in read(paths["library"])}

    inv = library["inv_1"]
    assert (inv["width_um"], inv["height_um"]) == ("2.240", "3.920")
    assert (inv["bbox_width_um"], inv["bbox_height_um"]) == ("3.100", "4.350"), "bounding box includes the well"
    assert inv["transistor_count"] == "2"
    assert library["nand2_1"]["transistor_count"] == "4", "namespaced cells are measured too"
    assert library["fill_1"]["is_fill"] == "True"


def test_macros_and_areas(reticle, tmp_path):
    paths = analyze.analyze(reticle, tmp_path / "out" / "reticle_analysis.csv", jobs=1)

    (macro,) = read(paths["macros"])
    assert macro["macro"] == "gf180mcu_fd_ip_sram__sram64x8m8wm1"
    assert (macro["width_um"], macro["height_um"], macro["instances"]) == ("400.000", "200.000", "2")

    slot_macros = read(paths["slot_macros"])
    assert [(r["slot_id"], r["instances"]) for r in slot_macros] == [("ABCD", "1"), ("ABCD", "1")]

    area = read(paths["slot_areas"])[0]
    assert float(area["die_area_mm2"]) == pytest.approx(5.0)
    assert float(area["sram_area_mm2"]) == pytest.approx(0.08)
    assert float(area["pad_area_mm2"]) == pytest.approx(0.0036)


def test_classify_stdcell():
    prefixes = analyze.DEFAULT_STDCELL_PREFIXES
    assert analyze.classify_stdcell("gf180mcu_fd_sc_mcu7t5v0__dffq_1", prefixes) == ("mcu7t5v0", "dffq_1", False)
    assert analyze.classify_stdcell("OH_gf180mcu_fd_sc_mcu9t5v0__filltie$3", prefixes) == ("mcu9t5v0", "filltie", True)
    assert analyze.classify_stdcell("gf180mcu_as_sc_mcu7t3v3__tieh_4", prefixes) == ("as_sc_mcu7t3v3", "tieh_4", True)
    assert analyze.classify_stdcell("gf180mcu_as_ex_mcu7t5v0__dfxtp_2", prefixes) == ("as_ex_mcu7t5v0", "dfxtp_2", False)
    assert analyze.classify_stdcell("6079_gf180mcu_osu_sc_gp9t3v3__inv_1", prefixes) == ("osu_sc_gp9t3v3", "inv_1", False)
    assert analyze.classify_stdcell("gf180mcu_as_sc_mcu7t3v3__inv_1", prefixes, qualified=False) == ("mcu7t3v3", "inv_1", False)
    assert analyze.classify_stdcell("gf180mcu_fd_io__bi_t", prefixes) is None


@pytest.fixture
def caravel(tmp_path):
    """A die whose harness has standard cells placed directly next to the user's wrapper."""
    layout = kdb.Layout()
    layout.dbu = DBU
    inv = make_stdcell(layout, "6079_gf180mcu_fd_sc_mcu7t5v0__inv_1", 2.24, 2)
    nand = make_stdcell(layout, "6079_gf180mcu_fd_sc_mcu7t5v0__nand2_1", 2.80, 4)
    pad = layout.create_cell("6079_gf180mcu_fd_io__bi_t")
    pad.shapes(layout.layer(37, 0)).insert(kdb.Box(0, 0, um(60), um(60)))
    pad.shapes(layout.layer(22, 0)).insert(kdb.Box(0, 0, um(10), um(10)))
    pad.shapes(layout.layer(30, 0)).insert(kdb.Box(um(4), um(-1), um(5), um(11)))

    wrapper = layout.create_cell("6079_user_project_wrapper")
    wrapper.shapes(layout.layer(0, 0)).insert(kdb.Box(0, 0, um(1000), um(1500)))
    wrapper.insert(kdb.CellInstArray(nand.cell_index(), kdb.Trans(um(100), um(100)),
                                     kdb.Vector(um(2.8), 0), kdb.Vector(0, um(3.92)), 5, 2))
    core = layout.create_cell("6079_caravel_core")
    core.insert(kdb.CellInstArray(inv.cell_index(), kdb.Trans(um(1200), um(100)),
                                  kdb.Vector(um(2.24), 0), kdb.Vector(0, um(3.92)), 7, 1))
    core.insert(kdb.CellInstArray(wrapper.cell_index(), kdb.Trans(um(50), um(50))))

    die = layout.create_cell("6079_caravel_0_0")
    die.shapes(layout.layer(0, 0)).insert(kdb.Box(0, 0, um(2000), um(2500)))
    die.insert(kdb.CellInstArray(core.cell_index(), kdb.Trans(um(300), um(300))))
    die.insert(kdb.CellInstArray(pad.cell_index(), kdb.Trans(um(10), um(10)), kdb.Vector(um(100), 0), kdb.Vector(), 3, 1))
    top = layout.create_cell("GFMPW0")
    top.insert(kdb.CellInstArray(die.cell_index(), kdb.Trans()))
    top.insert(kdb.CellInstArray(die.cell_index(), kdb.Trans(um(3930), 0)))
    path = tmp_path / "caravel.oas"
    layout.write(str(path))
    return path


def test_exclusion_keeps_only_the_user_area(caravel, tmp_path):
    measure = {"exclude": ["pad_ring", "harness"], "groups": {"harness": ["caravel_core"]},
               "keep": ["user_project_wrapper"], "core_cell": "user_project_wrapper"}
    paths = analyze.analyze(caravel, tmp_path / "out" / "reticle_analysis.csv", jobs=1, measure=measure)

    row = read(paths["summary"])[0]
    assert row["slot_id"] == "6079"
    assert row["stdcell_count"] == "10", "the harness inverters are excluded, the wrapper's NANDs are kept"
    assert row["transistor_count"] == "40", "the pad transistors are excluded too"
    assert row["pad_count"] == "3", "bond pads are always counted"
    usage = {r["cell_type"]: int(r["instance_count"]) for r in read(paths["cells"]) if r["cell_name"] == row["cell_name"]}
    assert usage == {"nand2_1": 10}
    area = read(paths["slot_areas"])[0]
    assert float(area["core_area_mm2"]) == pytest.approx(1.5)

    import json
    meta = json.loads(paths["meta"].read_text())
    assert meta["exclude"] == {"pad_ring": ["gf180mcu_*_io__*"], "harness": ["caravel_core"]}
    assert meta["keep"] == ["user_project_wrapper"]


def test_without_exclusion_everything_counts(caravel, tmp_path):
    paths = analyze.analyze(caravel, tmp_path / "out" / "reticle_analysis.csv", jobs=1)
    row = read(paths["summary"])[0]
    assert row["stdcell_count"] == "17"
    assert row["transistor_count"] == str(7 * 2 + 10 * 4 + 3)
    assert read(paths["slot_areas"])[0]["core_area_mm2"] == ""


def test_unknown_group_is_an_error(caravel, tmp_path):
    with pytest.raises(ValueError, match="unknown group"):
        analyze.analyze(caravel, tmp_path / "out" / "reticle_analysis.csv", jobs=1, measure={"exclude": ["nope"]})


def test_report_says_what_was_excluded(caravel, tmp_path):
    from ws_run_reports import config, report, stats

    out = tmp_path / "out"
    measure = {"exclude": ["harness"], "groups": {"harness": ["caravel_core"]},
               "keep": ["user_project_wrapper"], "core_cell": "user_project_wrapper"}
    analyze.analyze(caravel, out / "reticle_analysis.csv", jobs=1, measure=measure)
    (tmp_path / "manifest.csv").write_text(
        "CODE,PROJECT,SLOT_SIZE,TOP,SHA256,LAYOUT,VISIBILITY,PROJECT_DETAILS,REPOSITORY\n"
        "6079,Example,1x1,caravel,,,Public,An example,https://example.com/x\n")
    run = config.Run(name="test", title="Test Shuttle", number=0, shuttle="T1", process="GF180MCU", repo="x/y",
                     slots=2, repo_dir=tmp_path, layout={"file": "caravel.oas", "md5": ""},
                     manifest={"csv": "manifest.csv"}, measure=measure)
    run_stats = stats.load(run, out)
    (design,) = run_stats.designs
    assert design.core_area_mm2 == pytest.approx(1.5)
    assert "Outside the user area" in design.area_breakdown
    text = report.build_report(run_stats)
    assert "Excluded from the measurements:** harness (`caravel_core`)" in text
    assert "area of each design's `user_project_wrapper` cell" in text
