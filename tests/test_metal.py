import klayout.db as kdb

from ws_run_reports.metal import coverage, edges, window_starts

# dbu 0.001 um: a 250 um bin is 250,000 dbu across.
STEP = 250_000
FULL = STEP * STEP


def grid(nx, ny, fill=0):
    return [[fill] * nx for _ in range(ny)]


def test_densest_square_slides_by_a_bin():
    die = kdb.Box(0, 0, 8 * STEP, 4 * STEP)  # 2 x 1 mm
    xs, ys = edges(die.left, die.right, STEP), edges(die.bottom, die.top, STEP)
    areas = grid(8, 4)
    for j in range(4):
        for i in (3, 4, 5, 6):  # a fully covered 1 mm square starting 0.75 mm in
            areas[j][i] = FULL
    row = coverage(areas, die, xs, ys, STEP, 0.001)
    assert row["windows"] == 5 and row["window_mm"] == "1x1"
    assert row["max_window_share"] == 1.0
    assert (row["max_window_x_mm"], row["max_window_y_mm"]) == (0.75, 0.0)
    assert row["min_window_share"] == 0.25  # the square at 0 mm overlaps only column 3
    assert row["share"] == 0.5 and row["area_um2"] == 1_000_000


def test_a_die_under_1_mm_is_one_square():
    die = kdb.Box(0, 0, 3 * STEP + 100_000, 6 * STEP)  # 0.85 x 1.5 mm
    xs, ys = edges(die.left, die.right, STEP), edges(die.bottom, die.top, STEP)
    assert len(xs) == 5 and window_starts(xs, die.width() // STEP) == [(0, 4)]
    areas = grid(4, 6, 0)
    row = coverage(areas, die, xs, ys, STEP, 0.001)
    assert row["window_mm"] == "0.85x1" and row["windows"] == 3
    assert row["max_window_share"] == 0 and row["max_window_x_mm"] == ""
