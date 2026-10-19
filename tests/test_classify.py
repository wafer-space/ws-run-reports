import re

from ws_run_reports.classify import CATEGORY_IDS, CATEGORY_ORDER, FALLBACK_CUSTOM, category_id


def test_every_category_has_its_own_one_word_id():
    ids = [category_id(category) for category in CATEGORY_ORDER + [FALLBACK_CUSTOM]]
    assert all(re.fullmatch(r"[a-z]+", i) for i in ids)
    assert len(set(ids)) == len(set(CATEGORY_ORDER + [FALLBACK_CUSTOM]))
    assert set(CATEGORY_IDS) == set(CATEGORY_ORDER)


def test_a_configured_category_gets_its_name_squashed():
    assert category_id("Radio & RF") == "radiorf"
