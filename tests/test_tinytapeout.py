"""Reading tinytapeout.com/chips: the chip tables and the footnotes below them."""

from ws_run_reports import tinytapeout

CHIPS = """
### Open for Submission

| Run | Opened | Closes | Shuttle | Chips expected | Estimated shipping date |
|-----|--------|--------|---------|----------------|-------------------------|
| [TTGF26d](https://app.tinytapeout.com/shuttles/ttgf26d)†  | 2026-09-23 | 2026-12-07 | w.s Run \\#3 | 2027-05-12 | 2027-06-09 |
| [TTGF26c](https://app.tinytapeout.com/shuttles/ttgf26c)   | 2026-09-22 | 2026-12-07 | w.s Run \\#3 | 2027-05-12 | 2027-06-09 |

<small>† Currently reserved for [ArtScience Museum](https://example.com/) Singapore. Unused tiles will be made available two days before the deadline.</small>

### Future Chips

| Run | Submission deadline | Estimated shipping date |
|-----|---------------------|-------------------------|
| TTGF27a* | April 2027 | October 2027 |
"""


def test_footnotes_are_attached_to_the_chips_they_mark():
    rows = {row["chip"]: row for row in tinytapeout.parse_chips(CHIPS)}
    assert rows["ttgf26d"]["run"] == "TTGF26d"
    assert rows["ttgf26d"]["note"] is True
    assert rows["ttgf26d"]["note_text"] == ("Currently reserved for ArtScience Museum Singapore. "
                                            "Unused tiles will be made available two days before the deadline.")
    assert rows["ttgf26d"]["shuttle"] == "w.s Run #3"


def test_chips_without_a_marker_or_footnote_have_no_note():
    rows = {row["chip"]: row for row in tinytapeout.parse_chips(CHIPS)}
    assert rows["ttgf26c"]["note_text"] == ""
    # A marker with no footnote below the tables: the name is still read without it.
    assert rows["ttgf27a"]["run"] == "TTGF27a" and rows["ttgf27a"]["note_text"] == ""
