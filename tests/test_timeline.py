"""Which timeline milestones count as having happened, and how their times read."""

from ws_run_reports.external import _deadline_pages, _page_for, clock_24h, sentence_case
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


def test_rough_dates_in_past_years_are_done():
    # MPW-18H1's history: "2024" and "June – July 2025" were past, but listed after today as pending.
    assert milestone_done({"date": "2024-06-01", "display_date": "2024"}, TODAY)
    assert milestone_done({"date": "2025-06-01", "display_date": "June – July 2025"}, TODAY)
    assert not milestone_done({"date": "2025-06-01", "display_date": "2025", "done": False}, TODAY)


def test_times_are_24_hour_without_an_at_sign():
    assert clock_24h("30 April 2026 @ 11:59 PM AoE") == "30 April 2026, 23:59 AoE"
    assert clock_24h("5 December 2022 @ 11:59 PT") == "5 December 2022, 11:59 PT"
    assert clock_24h("1 March 2026 @ 12:00 AM UTC") == "1 March 2026, 00:00 UTC"
    assert clock_24h("Early Q4 2026") == "Early Q4 2026"


def test_titles_are_sentence_case_keeping_names():
    assert sentence_case("Early Bird Deadline") == "Early bird deadline"
    assert sentence_case("Tape-out to GlobalFoundries") == "Tape-out to GlobalFoundries"
    assert sentence_case("Packaged Parts Shipped") == "Packaged parts shipped"
    assert sentence_case("Tiny Tapeout GF 0.3 submissions close") == "Tiny Tapeout GF 0.3 submissions close"
    assert sentence_case("Submit GDS to Run 2") == "Submit GDS to Run 2"


def test_milestones_link_to_their_deadline_page():
    entry = {"name": "Run 1", "submission_deadline": {"title": "Design Submission Deadline", "button_url": "/how.html"},
             "delivery_date": {"title": "Estimated Delivery"},
             "campaign_deadline": {"title": "Purchase Deadline", "button_url": "https://buy.wafer.space/#products"}}
    pages = _deadline_pages(entry)
    assert _page_for("Design Submission", pages) == "https://wafer.space/how.html"
    assert _page_for("Purchase Deadline", pages) == "https://buy.wafer.space/#products"
    assert _page_for("Estimated Delivery", pages) == ""
