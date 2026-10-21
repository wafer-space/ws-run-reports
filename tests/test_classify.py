import re
from types import SimpleNamespace

from ws_run_reports.classify import CATEGORY_IDS, CATEGORY_ORDER, FALLBACK_CUSTOM, category_id, classify


def test_every_category_has_its_own_one_word_id():
    ids = [category_id(category) for category in CATEGORY_ORDER + [FALLBACK_CUSTOM]]
    assert all(re.fullmatch(r"[a-z]+", i) for i in ids)
    assert len(set(ids)) == len(set(CATEGORY_ORDER + [FALLBACK_CUSTOM]))
    assert set(CATEGORY_IDS) == set(CATEGORY_ORDER)


def test_a_configured_category_gets_its_name_squashed():
    assert category_id("Radio & RF") == "radiorf"


def design(name, details=""):
    return SimpleNamespace(code="X", project=SimpleNamespace(name=name, details=details),
                           transistors=100, logic_cells=50, custom_transistors=0, utilisation=0.5)


def test_workshop_tiles_are_first_designs():
    for name in ("Tiny Tapeout Template Copy", "Mi copia del Tiny Tapeout", "Tiny Tapeout Workshop Malaga 2jun2026",
                 "First Tinytapeout", "Tiny Tapeout testtest 111233", "Pacos first design",
                 "Matt’s first Wokwi design", "El primer diseño", "test1"):
        assert classify(design(name), tiles=True) == "First designs", name


def test_tiny_tapeout_tiles_are_never_multi_project_dies():
    assert classify(design("Tiny Tapeout RJAP"), tiles=True) != "Multi-project die"
    # TinyQV's description names a Tiny Tapeout competition; its name says what it is.
    assert classify(design("TinyQV Risc-V SoC", "from the Tiny Tapeout RISC-V competition"), tiles=True) == "RISC-V and CPUs"
    # A whole wafer.space die that carries a Tiny Tapeout chip is one.
    assert classify(design("Tiny Tapeout GF 26a")) == "Multi-project die"
    assert classify(design("Tiny Tapeout Factory Test"), tiles=True) == "Test structures"
