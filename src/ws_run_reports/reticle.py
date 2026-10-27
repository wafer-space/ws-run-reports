"""The slot grid of a reticle: which column and row each die is in, and their labels.

Slots are labelled with a letter for the column and a number for the row, as
on platform.wafer.space: A1 is the top left slot, G4 is seventh from the left
and fourth from the top. Half and quarter slots take the label of the full
slot they sit in. A run can move A1 to another corner, and swap which axis
has the letters, with ``[site] slot_origin`` and ``slot_letters``.

The grid pitch is found from the dies themselves: the spacing between the
positions of the widest (or tallest) dies, which are full slots.
"""

import string
import xml.etree.ElementTree as ET

ORIGINS = ("top-left", "top-right", "bottom-left", "bottom-right")


def _pitch(positions_and_sizes):
    """Smallest spacing between the positions of the largest dies, or their size if there is only one."""
    largest = max(size for _, size in positions_and_sizes)
    positions = sorted({round(pos, 3) for pos, size in positions_and_sizes if size >= largest * 0.99})
    gaps = [b - a for a, b in zip(positions, positions[1:]) if b - a > largest * 0.5]
    if not gaps:
        return largest
    # Empty columns or rows between full slots make a gap a multiple of the pitch.
    gap = min(gaps)
    return gap / max(1, round(gap / largest))


def svg_slots(path):
    """Every slot of a run repository's reticle map (``images/<shuttle>.svg``), private ones included.

    The map draws each slot as a rectangle with its code written in the middle,
    in millimetres from the reticle's top left corner; its first rectangle is
    the reticle itself. Returns placements as the renders give them: ``code``,
    ``x_mm`` and ``y_mm`` (lower left, from the reticle's lower left corner),
    ``width_mm`` and ``height_mm``.
    """
    ns = {"svg": "http://www.w3.org/2000/svg"}
    root = ET.parse(path).getroot()
    rects = [{key: float(r.get(key)) for key in ("x", "y", "width", "height")} for r in root.iterfind(".//svg:rect", ns)]
    outline, rects = rects[0], rects[1:]
    slots = []
    for text in root.iterfind(".//svg:text", ns):
        code = "".join(text.itertext()).strip()
        x, y = float(text.get("x")), float(text.get("y"))
        inside = [r for r in rects if r["x"] <= x <= r["x"] + r["width"] and r["y"] <= y <= r["y"] + r["height"]]
        if len(inside) != 1:
            raise ValueError(f"{path}: the label {code!r} at ({x}, {y}) is in {len(inside)} slots, not 1")
        r = inside[0]
        slots.append({"code": code, "x_mm": round(r["x"] - outline["x"], 3),
                      "y_mm": round(outline["y"] + outline["height"] - r["y"] - r["height"], 3),
                      "width_mm": r["width"], "height_mm": r["height"]})
    if len(slots) != len(rects):
        raise ValueError(f"{path}: {len(rects)} slots but {len(slots)} labels")
    return slots


def _letters(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    text = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        text = string.ascii_uppercase[rem] + text
    return text


def slot_grid(placements, reticle_width_mm, reticle_height_mm, origin="top-left", letters="columns"):
    """Label every placement with its slot, and describe the grid for drawing labels.

    ``placements`` are dicts with ``x_mm``, ``y_mm`` (lower left, from the
    reticle's lower left corner), ``width_mm`` and ``height_mm``. Returns
    ``(slots, columns, rows)``: ``slots`` gives each placement's column,
    row and label in placement order; ``columns`` and ``rows`` give each
    grid line's label and its extent as fractions of the reticle, left to
    right and top to bottom.
    """
    if origin not in ORIGINS:
        raise ValueError(f"slot_origin must be one of {', '.join(ORIGINS)}, not {origin!r}")
    if not placements:
        return [], [], []
    pitch_x = _pitch([(p["x_mm"], p["width_mm"]) for p in placements])
    pitch_y = _pitch([(p["y_mm"], p["height_mm"]) for p in placements])
    x0 = min(p["x_mm"] for p in placements)
    y0 = min(p["y_mm"] for p in placements)
    # Grid indices from the left and from the top.
    cols = [int((p["x_mm"] - x0) / pitch_x + 0.25) for p in placements]
    rows_from_bottom = [int((p["y_mm"] - y0) / pitch_y + 0.25) for p in placements]
    ncols, nrows = max(cols) + 1, max(rows_from_bottom) + 1
    rows = [nrows - 1 - r for r in rows_from_bottom]

    def col_label(c):
        index = c if origin.endswith("left") else ncols - 1 - c
        return _letters(index) if letters == "columns" else str(index + 1)

    def row_label(r):
        index = r if origin.startswith("top") else nrows - 1 - r
        return str(index + 1) if letters == "columns" else _letters(index)

    def name(c, r):
        return col_label(c) + row_label(r) if letters == "columns" else row_label(r) + col_label(c)

    slots = [{"col": c, "row": r, "col_label": col_label(c), "row_label": row_label(r), "label": name(c, r)}
             for c, r in zip(cols, rows)]
    # Each label spans the dies in its column or row, which can be narrower
    # than the pitch where a reticle edge holds only half slots.
    def extent(index, starts, sizes, indices, pitch, origin_mm):
        members = [(s, s + size) for s, size, i in zip(starts, sizes, indices) if i == index]
        if members:
            return min(lo for lo, _ in members), max(hi for _, hi in members)
        return origin_mm + index * pitch, origin_mm + (index + 1) * pitch

    xs, widths = [p["x_mm"] for p in placements], [p["width_mm"] for p in placements]
    ys, heights = [p["y_mm"] for p in placements], [p["height_mm"] for p in placements]
    columns = []
    for c in range(ncols):
        lo, hi = extent(c, xs, widths, cols, pitch_x, x0)
        columns.append({"label": col_label(c), "left": lo / reticle_width_mm, "width": (hi - lo) / reticle_width_mm})
    rows_out = []
    for r in range(nrows):
        lo, hi = extent(nrows - 1 - r, ys, heights, rows_from_bottom, pitch_y, y0)
        rows_out.append({"label": row_label(r), "top": (reticle_height_mm - hi) / reticle_height_mm,
                         "height": (hi - lo) / reticle_height_mm})
    return slots, columns, rows_out
