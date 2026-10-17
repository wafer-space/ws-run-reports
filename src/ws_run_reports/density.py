"""Fine-grained density of each design: where its logic cells, transistors and SRAM are.

Logic cells and transistors are binned once at ``BIN_UM`` by position (a cell
by its origin, a transistor by the centre of its gate). Everything else is
sums over those bins, so it is cheap to ask for:

* a map of the whole die in ``WINDOW_UM`` squares (1 mm), including squares
  that SRAM overlaps, with the share of each square that is SRAM;
* the densest ``WINDOW_UM`` square window anywhere in the die, sliding in
  ``BIN_UM`` steps, both overall and among windows that touch no SRAM macro.

A run can set both sizes (``[measure] grid_um`` and ``bin_um``), for
example to map designs much smaller than 1 mm.

SRAM macros are recorded as rectangles, so pages can draw them.
"""

import klayout.db as kdb

BIN_UM = 100.0
WINDOW_UM = 1000.0

SRAM_RECT_FIELDS = ["slot_id", "cell_name", "macro", "x0_mm", "y0_mm", "x1_mm", "y1_mm"]
MAP_FIELDS = ["slot_id", "cell_name", "grid_x", "grid_y", "x_mm", "y_mm", "width_mm", "height_mm",
              "stdcell_count", "transistor_count", "sram_fraction"]
WINDOW_FIELDS = ["slot_id", "cell_name", "kind", "x_mm", "y_mm", "stdcell_count", "transistor_count",
                 "sram_fraction"]


class Bins:
    """Counts on a grid of ``bin_um`` squares anchored at the die's lower left corner."""

    def __init__(self, box, dbu, bin_um=BIN_UM):
        self.box, self.dbu, self.bin_um = box, dbu, bin_um
        self.step = round(bin_um / dbu)
        self.nx = max(1, -(-box.width() // self.step))
        self.ny = max(1, -(-box.height() // self.step))
        self.cells = [[0] * self.nx for _ in range(self.ny)]
        self.transistors = [[0] * self.nx for _ in range(self.ny)]
        self.sram = [[0.0] * self.nx for _ in range(self.ny)]   # um2 of SRAM in each bin

    def index(self, point):
        gx = min(self.nx - 1, max(0, (point.x - self.box.left) // self.step))
        gy = min(self.ny - 1, max(0, (point.y - self.box.bottom) // self.step))
        return gx, gy

    def add_sram(self, rect):
        x0, y0 = self.index(rect.p1)
        x1, y1 = self.index(kdb.Point(rect.right - 1, rect.top - 1))
        for gy in range(y0, y1 + 1):
            for gx in range(x0, x1 + 1):
                left = self.box.left + gx * self.step
                bottom = self.box.bottom + gy * self.step
                overlap = rect & kdb.Box(left, bottom, left + self.step, bottom + self.step)
                if not overlap.empty():
                    self.sram[gy][gx] += overlap.width() * overlap.height() * self.dbu * self.dbu

    def bin_area_um2(self, gx, gy):
        width = min(self.step, self.box.width() - gx * self.step)
        height = min(self.step, self.box.height() - gy * self.step)
        return width * height * self.dbu * self.dbu


def _prefix(grid):
    """Summed-area table with a leading row and column of zeros."""
    ny, nx = len(grid), len(grid[0])
    table = [[0] * (nx + 1) for _ in range(ny + 1)]
    for y in range(ny):
        running = 0
        for x in range(nx):
            running += grid[y][x]
            table[y + 1][x + 1] = table[y][x + 1] + running
    return table


def _sum(table, x0, y0, x1, y1):
    """Sum over bins x0 <= x < x1, y0 <= y < y1."""
    return table[y1][x1] - table[y0][x1] - table[y1][x0] + table[y0][x0]


def sram_rects(layout, cell, macro_cells, selection):
    """(macro name, box in database units) for every SRAM macro placed below ``cell``."""
    if not macro_cells:
        return []
    it = kdb.RecursiveInstanceIterator(layout, cell)
    it.targets = list(macro_cells)
    if selection.excluded:
        it.unselect_cells(selection.excluded)
        it.select_cells(selection.kept)
    rects = []
    for _ in it.each():
        macro = it.inst_cell()
        rects.append((macro_cells[macro.cell_index()], macro.bbox().transformed(it.trans() * it.inst_trans())))
    return rects


def measure(layout, cell, marker_layer, transistor_region, macro_cells, selection, bin_um=BIN_UM):
    """Bin one design. Returns (bins, sram rectangles)."""
    dbu = layout.dbu
    bins = Bins(cell.bbox(), dbu, bin_um)
    if marker_layer is not None:
        it = selection.iterator(layout, cell, marker_layer)
        while not it.at_end():
            gx, gy = bins.index(it.shape().bbox().transformed(it.trans()).p1)
            bins.cells[gy][gx] += 1
            it.next()
    for polygon in transistor_region.each():
        gx, gy = bins.index(polygon.bbox().center())
        bins.transistors[gy][gx] += 1
    rects = sram_rects(layout, cell, macro_cells, selection)
    for _, rect in rects:
        bins.add_sram(rect & bins.box)
    return bins, rects


def map_rows(bins, window_um=WINDOW_UM):
    """The map: (grid_x, grid_y, x_mm, y_mm, width_mm, height_mm, cells, transistors, sram_fraction)."""
    bin_um = bins.bin_um
    per = round(window_um / bin_um)
    cells, transistors, sram = _prefix(bins.cells), _prefix(bins.transistors), _prefix(bins.sram)
    rows = []
    for gy in range(-(-bins.ny // per)):
        for gx in range(-(-bins.nx // per)):
            x0, y0 = gx * per, gy * per
            x1, y1 = min(bins.nx, x0 + per), min(bins.ny, y0 + per)
            width_mm = min(window_um, bins.box.width() * bins.dbu - x0 * bin_um) / 1000
            height_mm = min(window_um, bins.box.height() * bins.dbu - y0 * bin_um) / 1000
            area = width_mm * height_mm * 1e6
            rows.append((gx, gy, x0 * bin_um / 1000, y0 * bin_um / 1000, width_mm, height_mm,
                         _sum(cells, x0, y0, x1, y1), _sum(transistors, x0, y0, x1, y1),
                         min(1.0, _sum(sram, x0, y0, x1, y1) / area) if area else 0.0))
    return rows


def densest_windows(bins, window_um=WINDOW_UM):
    """The densest whole ``window_um`` square windows inside the die, by logic cells.

    Returns {"densest_any": row, "densest_sram_free": row} with rows of
    (x_mm, y_mm, cells, transistors, sram_fraction); a kind is missing when
    no window qualifies (a die smaller than the window, or SRAM everywhere).
    """
    bin_um = bins.bin_um
    per = round(window_um / bin_um)
    if bins.box.width() * bins.dbu < window_um or bins.box.height() * bins.dbu < window_um:
        return {}
    cells, transistors, sram = _prefix(bins.cells), _prefix(bins.transistors), _prefix(bins.sram)
    # Windows must lie wholly inside the die; the last partial bin may not start one.
    last_x = int((bins.box.width() * bins.dbu - window_um) // bin_um)
    last_y = int((bins.box.height() * bins.dbu - window_um) // bin_um)
    best = {}
    for y in range(last_y + 1):
        for x in range(last_x + 1):
            n = _sum(cells, x, y, x + per, y + per)
            sram_um2 = _sum(sram, x, y, x + per, y + per)
            row = (x * bin_um / 1000, y * bin_um / 1000, n, _sum(transistors, x, y, x + per, y + per),
                   min(1.0, sram_um2 / (window_um * window_um)))
            kinds = ["densest_any"] + (["densest_sram_free"] if sram_um2 == 0 else [])
            for kind in kinds:
                if kind not in best or n > best[kind][2]:
                    best[kind] = row
    return best
