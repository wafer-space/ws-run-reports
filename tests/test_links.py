"""The URLs names link to."""

from ws_run_reports import links, report


def test_cells_libraries_and_macros():
    assert links.full_library("mcu7t5v0") == "gf180mcu_fd_sc_mcu7t5v0"
    assert links.full_library("as_sc_mcu7t3v3") == "gf180mcu_as_sc_mcu7t3v3"
    assert links.cell("mcu7t5v0", "nand2_1").endswith(
        "/gf180mcu_fd_sc_mcu7t5v0/cells/nand2/gf180mcu_fd_sc_mcu7t5v0__nand2_1.html")
    # The upstream page for xor3_4 in 7t is misnamed or3_4.
    assert links.cell("mcu7t5v0", "xor3_4").endswith("/cells/xor3/gf180mcu_fd_sc_mcu7t5v0__or3_4.html")
    assert links.cell("osu_sc_gp9t3v3", "inv_1").endswith(".pdf#page=110")
    # A cell without its own page links to its library.
    assert links.cell("as_sc_mcu7t3v3", "inv_1") == links.library("as_sc_mcu7t3v3") != ""
    assert links.macro("gf180mcu_fd_ip_sram__sram512x8m8wm1$3").endswith("sram512x8m8wm1.html")
    assert links.library("gf180mcu_fd_io").endswith("datasheet.html#cell-list")
    assert links.macro("unknown_cell") == ""


def test_steps_versions_and_licences():
    assert links.step("Checker.MagicDRC").endswith("step_config_vars.html#step-checker-magicdrc")
    assert links.precheck("1.7.3").endswith("/gf180mcu-precheck/tree/1.7.3")
    assert links.precheck("1.7.0-2-ga39b1e2").endswith("/gf180mcu-precheck/tree/a39b1e2")
    assert links.precheck_version("", "sha256:f6c0cb88efce8769ec87de5a2035ada731fd8fffb1b3e5e1968078f6dd191c2f") == "1.7.3"
    assert links.precheck_contents("1.7.3")["pdk"] == "open_pdks 1.0.604"
    assert links.template_versions("wafer-space/gf180mcu-project-template", {"PDK_TAG": "1.6.6"}) == ["1.3.5"]
    assert links.pdk_pin("PDK_TAG", "1.6.6") == "https://github.com/wafer-space/gf180mcu/tree/1.6.6"
    assert links.spdx("Apache-2.0") == "https://spdx.org/licenses/Apache-2.0.html"
    assert links.spdx("proprietary") == ""
    assert links.repo_file("https://gitlab.com/a/b", "abc", "LICENSE") == "https://gitlab.com/a/b/-/blob/abc/LICENSE"
    assert links.repo_file("https://foss-eda-tools.googlesource.com/x", "abc", "LICENSE") == ""


def test_report_links_layer_numbers():
    text = report.gds("diffusion (22/0) and GDS 0/0, not 2026-10/17")
    assert "([22/0](" in text and "[GDS 0/0](" in text and "2026-10/17" in text


def test_html_link_escapes():
    assert str(links.html("a<b", "https://x/?a=1&b=2")) == '<a href="https://x/?a=1&amp;b=2">a&lt;b</a>'
    assert str(links.html("plain", "")) == "plain"


def test_every_process_feature_links_to_the_pdk_documentation():
    from ws_run_reports.features import FEATURES
    for key, _, _ in FEATURES:
        assert links.feature(key).startswith("https://gf180mcu-pdk.readthedocs.io/en/latest/"), key
    assert links.voltage("5 V") == links.feature("gates_5v")
    assert links.voltage("10 V") == links.feature("unknown") == ""


def test_run_names_link_to_their_pages():
    assert links.runs_linked("Die T0P3 on wafer.space Run 2 (G802)") == (
        'Die T0P3 on <a href="https://wafer.space/ws-run2/">wafer.space Run 2</a> (G802)')
    assert "<a " not in links.runs_linked("wafer.space Run 20 & more")
    assert "&amp;" in links.runs_linked("wafer.space Run 1 & Run 2")
    assert links.tinytapeout("store").startswith("https://store.tinytapeout.com/")
