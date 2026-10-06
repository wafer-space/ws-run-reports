"""Build the static web page for a run.

The pages are meant to be served from the ``gh-pages`` branch of the run
repository, which GitHub Pages publishes under ``https://wafer.space/<run>/``.
They load the main website's stylesheets from ``https://wafer.space/assets``
so that they follow its theme without copying it.
"""

import json
import shutil
import statistics
from collections import Counter
from datetime import date
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

from . import external, report
from . import stats as stats_module
from .analyze import GRID_SIZE_UM
from .classify import CATEGORY_ORDER
from .stats import REFERENCE_CELLS, describe_cell, library_label

WEBSITE = "https://wafer.space"

AREA_COLOURS = {
    "Logic cells": "#5ca7db",
    "SRAM": "#9b6bd6",
    "Filler and tap cells": "#b9c7d6",
    "Other": "#e6ebf0",
    "Pad ring": "#f0b84c",
}
AREA_ORDER = ["Logic cells", "SRAM", "Filler and tap cells", "Other", "Pad ring"]
AREA_NOTES = {
    "Logic cells": "gates and flip-flops doing the design's actual work",
    "SRAM": "memory macros",
    "Filler and tap cells": "inserted by the tools to keep rows continuous and wells tied",
    "Other": "routing channels, analog and custom layout, power grid and empty space",
    "Pad ring": "the 350 µm border of I/O cells and bond pads",
}
CATEGORY_COLOURS = ["#5ca7db", "#9b6bd6", "#45c4a0", "#f0b84c", "#e2626b", "#6f7bd9", "#3fb6c9", "#d98a4f",
                    "#8fb84e", "#c56bb4", "#7d8a99", "#a0a8b3"]


def _slot_guidance(stats):
    """What designs of each slot size achieved, for people sizing a new design."""
    rows = []
    digital = [d for d in stats.digital_designs if d.logic_cells >= report.MINIMAL_LOGIC_CELLS]
    best_density = max((d.core_density for d in digital), default=0)
    median_density = statistics.median([d.core_density for d in digital]) if digital else 0
    for slot_size in ("1x1", "1x0p5", "0p5x1", "0p5x0p5"):
        group = [d for d in stats.designs if d.project.slot_size == slot_size]
        if not group:
            continue
        sample = group[0]
        cells = sorted(d.logic_cells for d in group if d in digital)
        rows.append({
            "label": sample.slot_label,
            "die": f"{sample.width_mm:.2f} × {sample.height_mm:.2f} mm",
            "core_mm2": sample.core_area_mm2,
            "designs": len(group),
            "best": cells[-1] if cells else 0,
            "median": statistics.median(cells) if cells else 0,
            "at_median_density": sample.core_area_mm2 * median_density,
            "at_best_density": sample.core_area_mm2 * best_density,
        })
    return rows, best_density, median_density


def _heatmap(design):
    """Grid cells for the per-design density map, with image-style (top-down) rows."""
    if not design.grid:
        return None
    step = GRID_SIZE_UM / 1000
    nx = max(1, -(-round(design.width_mm * 1000) // int(GRID_SIZE_UM)))
    ny = max(1, -(-round(design.height_mm * 1000) // int(GRID_SIZE_UM)))
    measured = {(gx, gy): (transistors, cells) for gx, gy, transistors, cells in design.grid}
    peak = max((c for _, c in measured.values()), default=0) or 1
    cells = []
    for gy in range(ny):
        for gx in range(nx):
            width = min(step, design.width_mm - gx * step)
            height = min(step, design.height_mm - gy * step)
            entry = {"x": gx * step, "y": design.height_mm - gy * step - height, "w": width, "h": height}
            if (gx, gy) in measured:
                transistors, count = measured[(gx, gy)]
                entry.update(cells=count, transistors=transistors, level=count / peak)
            else:
                entry.update(sram=True)
            cells.append(entry)
    return {"cells": cells, "width": design.width_mm, "height": design.height_mm, "peak": peak}


def _area_bar(breakdown):
    total = sum(breakdown.values()) or 1
    return [{"label": label, "mm2": breakdown[label], "share": breakdown[label] / total,
             "colour": AREA_COLOURS[label]} for label in AREA_ORDER]


def build_context(run, out_dir: Path) -> dict:
    stats = stats_module.load(run, out_dir)
    site_dir = out_dir / "site"
    site_dir.mkdir(parents=True, exist_ok=True)

    renders_path = site_dir / "renders" / "renders.json"
    renders = json.loads(renders_path.read_text()) if renders_path.exists() else None

    print("Collecting external content...")
    timeline = external.timeline(run)
    cob = external.cob_pages(run)
    photos = external.die_photos(run, site_dir)

    today = date.today().isoformat()
    for item in timeline:
        item["done"] = item["date"] <= today

    categories = sorted(stats.by_category.items(),
                        key=lambda kv: (-len(kv[1]), CATEGORY_ORDER.index(kv[0]) if kv[0] in CATEGORY_ORDER else 99))
    category_colour = {name: CATEGORY_COLOURS[i % len(CATEGORY_COLOURS)] for i, (name, _) in enumerate(categories)}

    total_breakdown = Counter()
    for d in stats.designs:
        total_breakdown.update(d.area_breakdown)

    reference = []
    for label, what, pattern in REFERENCE_CELLS:
        entries = []
        for lib in stats.libraries:
            cell = stats.reference_cell(lib, pattern)
            if cell:
                entries.append({"library": library_label(lib), "cell": cell})
        if entries:
            reference.append({"label": label, "what": what, "entries": entries,
                              "best": max(e["cell"].per_mm2 for e in entries)})

    digital = [d for d in stats.by_core_density if d.logic_cells >= report.MINIMAL_LOGIC_CELLS]
    slot_guidance, best_density, median_density = _slot_guidance(stats)
    scale_max = max([stats.buffer_max(lib) for lib in stats.libraries] or [1])
    best_peak = max(digital, key=lambda d: d.peak_cells, default=None)
    utilisations = [d.utilisation for d in digital]

    placements = []
    if renders:
        reticle = renders["reticle"]
        for p in renders["placements"]:
            placements.append({
                "code": p["code"],
                "left": p["x_mm"] / reticle["width_mm"],
                "top": 1 - (p["y_mm"] + p["height_mm"]) / reticle["height_mm"],
                "width": p["width_mm"] / reticle["width_mm"],
                "height": p["height_mm"] / reticle["height_mm"],
            })

    return {
        "run": run,
        "stats": stats,
        "website": WEBSITE,
        "generated": today,
        "renders": renders,
        "placements": placements,
        "timeline": timeline,
        "cob": cob,
        "photos": photos,
        "categories": categories,
        "category_colour": category_colour,
        "total_area": _area_bar(total_breakdown),
        "area_notes": AREA_NOTES,
        "reference": reference,
        "digital": digital,
        "scale_max": scale_max,
        "slot_guidance": slot_guidance,
        "best_density": best_density,
        "median_density": median_density,
        "best_peak": best_peak,
        "median_utilisation": statistics.median(utilisations) if utilisations else 0,
        "best_utilisation": max(digital, key=lambda d: d.utilisation, default=None),
        "slot_mix": Counter(d.slot_label for d in stats.designs).most_common(),
        "open_source": sum(1 for d in stats.designs if d.project.repository),
        "pads": sum(d.pads for d in stats.designs),
        "design_by_code": {d.code: d for d in stats.designs},
    }


def _photo_credit(run) -> Markup:
    """Copyright line for the die photographs: "© 2026 Name, Licence", linked where the run gives URLs."""
    def linked(text, url):
        return Markup('<a href="{}">{}</a>').format(url, text) if url else Markup.escape(text)

    site = run.site
    credit = linked(site.get("photos_credit", ""), site.get("photos_credit_url"))
    if site.get("photos_year"):
        credit = Markup("© {} {}").format(site["photos_year"], credit)
    if site.get("photos_licence"):
        credit = Markup("{}, {}").format(credit, linked(site["photos_licence"], site.get("photos_licence_url")))
    return credit


def build_site(run, out_dir: Path) -> Path:
    """Render ``index.html`` and one page per project into ``out_dir/site``."""
    context = build_context(run, out_dir)
    stats = context["stats"]
    site_dir = out_dir / "site"

    env = Environment(loader=PackageLoader("ws_run_reports", "templates"),
                      autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    env.filters.update(k=report.k, pct=report.pct, count=report.count, library_label=library_label,
                       describe_cell=describe_cell)
    env.globals.update(area_bar=_area_bar, heatmap=_heatmap, photo_credit=lambda: _photo_credit(run))

    # The data behind the page, so every figure on it can be checked.
    data_dir = site_dir / "data"
    data_dir.mkdir(exist_ok=True)
    for path in sorted(out_dir.glob(f"{stats_module.OUTPUT_STEM}*.csv")):
        shutil.copy(path, data_dir / path.name)
    report_path = out_dir / report.REPORT_NAME
    if report_path.exists():
        shutil.copy(report_path, data_dir / report_path.name)
    context["data_files"] = sorted(p.name for p in data_dir.iterdir())

    (site_dir / "index.html").write_text(env.get_template("index.html").render(root="", **context))

    projects_dir = site_dir / "projects"
    projects_dir.mkdir(exist_ok=True)
    designs = stats.designs
    template = env.get_template("project.html")
    for i, design in enumerate(designs):
        page = template.render(root="../", design=design, previous=designs[i - 1],
                               following=designs[(i + 1) % len(designs)], **context)
        (projects_dir / f"{design.code}.html").write_text(page)

    static = Path(__file__).parent / "static"
    for path in static.iterdir():
        shutil.copy(path, site_dir / path.name)
    (site_dir / ".nojekyll").write_text("")
    return site_dir / "index.html"
