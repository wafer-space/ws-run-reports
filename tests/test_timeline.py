"""Which timeline milestones count as having happened."""

from ws_run_reports.site import milestone_done

TODAY = "2026-10-19"


def test_exact_dates_are_done_once_passed():
    shipped = {"date": "2026-04-28", "display_date": "28 April 2026"}
    deadline = {"date": "2026-12-09", "display_date": "9 December 2026 @ 11:59 PM AoE"}
    assert milestone_done(shipped, TODAY)
    assert not milestone_done(deadline, TODAY)
    assert milestone_done({"date": "2026-04-28", "display_date": ""}, TODAY)


def test_estimates_are_not_done_by_date_alone():
    # Run 2's "Parts Shipped" is dated 2026-10-01 but shown as an estimate, and had not happened on this day.
    estimate = {"date": "2026-10-01", "display_date": "Early Q4 2026"}
    assert not milestone_done(estimate, TODAY)
    assert milestone_done({**estimate, "done": True}, TODAY)
    assert not milestone_done({"date": "2026-04-28", "display_date": "28 April 2026", "done": False}, TODAY)
