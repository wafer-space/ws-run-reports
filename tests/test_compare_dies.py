from ws_run_reports.site import same_layouts


def row(run, code, logic, transistors):
    return {"run": run, "code": code, "logic_cells": logic, "transistors": transistors}


def test_a_die_made_again_names_the_earlier_one():
    rows = same_layouts([row("Run 1", "TQVA", 35711, 900), row("Run 1", "TQVB", 30000, 800),
                         row("Run 2", "TQVC", 36116, 950), row("Run 2", "TQVA", 35711, 900)])
    assert [(r["run"], r["code"]) for r in rows] == [("Run 1", "TQVA"), ("Run 1", "TQVB"),
                                                     ("Run 2", "TQVA"), ("Run 2", "TQVC")]
    assert [r["same_as"] for r in rows] == ["", "", "TQVA on Run 1", ""]


def test_equal_logic_cells_but_different_transistors_is_not_the_same():
    rows = same_layouts([row("Run 1", "AAAA", 5000, 100), row("Run 2", "AAAA", 5000, 101)])
    assert [r["same_as"] for r in rows] == ["", ""]


def test_dies_without_logic_cells_are_never_the_same():
    rows = same_layouts([row("Run 1", "ART1", 0, 0), row("Run 2", "ART1", 0, 0)])
    assert [r["same_as"] for r in rows] == ["", ""]
