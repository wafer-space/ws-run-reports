"""Build the static web page for a run.

The pages are meant to be served from the ``gh-pages`` branch of the run
repository, which GitHub Pages publishes under ``https://wafer.space/<run>/``.
They load the main website's stylesheets from ``https://wafer.space/assets``
so that they follow its theme without copying it.
"""

import hashlib
import json
import re
import shutil
import statistics
from collections import Counter
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

from . import config, external, links, projects, related, report, reticle, tinytapeout
from . import stats as stats_module
from .classify import CATEGORY_ORDER, category_id
from .config import SLOT_FRACTIONS, https_url
from .features import FEATURE_LABELS
from .stats import REFERENCE_CELLS, describe_cell, library_label

WEBSITE = "https://wafer.space"

AREA_COLOURS = {
    "Logic cells": "#5ca7db",
    "SRAM": "#9b6bd6",
    "Filler and tap cells": "#b9c7d6",
    "Other": "#e6ebf0",
    "Pad ring": "#f0b84c",
    "Outside the user area": "#f0b84c",
}
AREA_ORDER = ["Logic cells", "SRAM", "Filler and tap cells", "Other", "Pad ring", "Outside the user area"]
AREA_NOTES = {
    "Logic cells": "gates and flip-flops doing the design's actual work",
    "SRAM": "memory macros",
    "Filler and tap cells": "inserted by the tools to keep rows continuous and wells tied",
    "Other": "routing channels, analog and custom layout, power grid and empty space",
    "Pad ring": "the 350 µm border of I/O cells and bond pads",
    "Outside the user area": "the pad frame and shared harness around the user's design, not measured",
}
CATEGORY_COLOURS = ["#5ca7db", "#9b6bd6", "#45c4a0", "#f0b84c", "#e2626b", "#6f7bd9", "#3fb6c9", "#d98a4f",
                    "#8fb84e", "#c56bb4", "#7d8a99", "#a0a8b3"]


def _slot_guidance(stats):
    """What designs of each slot size achieved, for people sizing a new design."""
    rows = []
    digital = [d for d in stats.digital_designs if d.logic_cells >= report.MINIMAL_LOGIC_CELLS]
    best_density = max((d.core_density for d in digital), default=0)
    median_density = statistics.median([d.core_density for d in digital]) if digital else 0
    present = {d.project.slot_size for d in stats.designs}
    known = [s for s in SLOT_FRACTIONS if s in present]
    # The theoretical maxima use the run's most used library; "densest" is the
    # best densest-window density any design on the run reached.
    lib = stats.libraries[0] if stats.libraries else None
    nand = stats.reference_cell(lib, REFERENCE_CELLS[1][2]) if lib else None
    flop = stats.reference_cell(lib, REFERENCE_CELLS[3][2]) if lib else None
    densest = max((d.peak_cells for d in digital), default=0)
    for slot_size in known + sorted(present - set(known)):
        group = [d for d in stats.designs if d.project.slot_size == slot_size]
        sample = group[0]
        cells = sorted(d.logic_cells for d in group if d in digital)
        rows.append({
            "max_nand": sample.core_area_mm2 * nand.per_mm2 if nand else 0,
            "max_flop": sample.core_area_mm2 * flop.per_mm2 if flop else 0,
            "at_densest": sample.core_area_mm2 * densest,
            "label": sample.slot_label,
            "die": f"{sample.width_mm:.2f} × {sample.height_mm:.2f} mm",
            "core_mm2": sample.core_area_mm2,
            "designs": len(group),
            "best": cells[-1] if cells else 0,
            "median": statistics.median(cells) if cells else 0,
            "at_median_density": sample.core_area_mm2 * median_density,
            "at_best_density": sample.core_area_mm2 * best_density,
        })
    maxima = {"library": lib, "nand": nand, "flop": flop, "densest": densest}
    return rows, best_density, median_density, maxima


def _heatmap(design):
    """Squares, SRAM outlines and the densest window for the per-design density map, in image (top-down) mm."""
    if design.density_map:
        return _full_heatmap(design)
    if not design.grid:
        return None
    step = design.window_mm
    nx = max(1, -(-round(design.width_mm * 1000) // round(step * 1000)))
    ny = max(1, -(-round(design.height_mm * 1000) // round(step * 1000)))
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
    return {"cells": cells, "width": design.width_mm, "height": design.height_mm, "peak": peak,
            "rects": [], "window": None}


def _full_heatmap(design):
    """Every map square (1 mm unless the run set otherwise) shaded by logic cells per mm², with SRAM
    macros and the densest SRAM-free window."""
    def flip(y, h):
        return design.height_mm - y - h

    def per_mm2(square):
        area = square["w"] * square["h"]
        return square["cells"] / area if area else 0

    peak = max((per_mm2(s) for s in design.density_map), default=0) or 1
    cells = [{"x": s["x"], "y": flip(s["y"], s["h"]), "w": s["w"], "h": s["h"], "cells": s["cells"],
              "transistors": s["transistors"], "level": per_mm2(s) / peak, "sram_share": s["sram"]}
             for s in design.density_map]
    rects = [{"name": name, "x": x0, "y": flip(y0, y1 - y0), "w": x1 - x0, "h": y1 - y0}
             for name, x0, y0, x1, y1 in design.sram_rects]
    best = design.windows.get("densest_sram_free")
    side = design.window_mm
    window = {"x": best["x"], "y": flip(best["y"], side), "w": side, "h": side, "cells": best["cells"]} if best else None
    return {"cells": cells, "width": design.width_mm, "height": design.height_mm, "peak": peak,
            "rects": rects, "window": window}


def _slot_types(stats, renders):
    """Dies on the reticle and public designs per slot size, with the full slots they take up."""
    size_of = {d.code: d.project.slot_size for d in stats.designs}
    placed = Counter(size_of.get(p["code"], "") for p in (renders or {}).get("placements", []))
    if not placed:
        placed = Counter(d.project.slot_size for d in stats.designs for _ in range(d.placements))
    designs = Counter(size_of.values())
    order = [s for s in SLOT_FRACTIONS if s in placed] + sorted(s for s in placed if s not in SLOT_FRACTIONS)
    rows = []
    for size in order:
        fraction = SLOT_FRACTIONS.get(size)
        label = next((d.slot_label for d in stats.designs if d.project.slot_size == size), size or "unknown")
        rows.append({"label": label, "dies": placed[size], "designs": designs[size],
                     "full_slots": placed[size] * fraction[0] * fraction[1] if fraction else None})
    return rows


def _area_bar(breakdown):
    total = sum(breakdown.values()) or 1
    return [{"label": label, "mm2": breakdown[label], "share": breakdown[label] / total,
             "colour": AREA_COLOURS[label]} for label in AREA_ORDER if label in breakdown]


def _precheck_table(checks: dict):
    """The columns and step rows of a project's precheck table, or None without step results.

    A column per check: the one the design was accepted on and its latest
    re-run, or one column when they are the same check. The steps are the
    union of both, in flow order; a step a check's flow did not have is None.
    """
    accepted, latest = checks.get("accepted"), checks.get("latest")
    if not latest:
        return None
    if accepted and accepted.get("same_as_latest"):
        columns = [("Accepted on, and latest", latest)]
    else:
        columns = [(label, check) for label, check in (("Accepted on", accepted), ("Latest re-run", latest)) if check]
    order = []
    for _, check in columns:
        previous = None
        for step, _ in check.get("steps", []):
            if step not in order:
                order.insert(order.index(previous) + 1 if previous in order else len(order), step)
            previous = step
    rows = [(step, [dict(check.get("steps", [])).get(step) if check.get("details") else "" for _, check in columns])
            for step in order]
    return {"columns": columns, "rows": rows}


def _precheck_summary(details: dict) -> dict:
    """Run-wide precheck figures for the main page."""
    checks = {code: e.get("checks") or {} for code, e in details.items()}
    accepted = {code: c["accepted"] for code, c in checks.items() if c.get("accepted")}
    latest = {code: c["latest"] for code, c in checks.items() if c.get("latest")}
    ran = [c for check in (*accepted.values(), *latest.values()) for c in [check] if c.get("pad_mask_check") == "passed"]
    pad_mask_codes = sorted({code for code, c in (*accepted.items(), *latest.items()) if c.get("pad_mask_check") == "passed"})
    failed_pad_mask = sorted({code for code, c in (*accepted.items(), *latest.items())
                              if c.get("pad_mask_check") not in (None, "passed", "not in flow")})
    magic = sorted(code for code in checks if any((c or {}).get("magic_drc_errors")
                                                  for c in (accepted.get(code), latest.get(code))))
    return {
        "imported": bool(latest),
        "accepted_passed": sum(1 for c in accepted.values() if c["is_manufacturable"]),
        "accepted": len(accepted),
        "accepted_dates": (min(c["created_at"] for c in accepted.values())[:10],
                           max(c["created_at"] for c in accepted.values())[:10]) if accepted else None,
        "accepted_without_details": sorted(code for code, c in accepted.items() if not c.get("details")),
        "latest_passed": sum(1 for c in latest.values() if c["is_manufacturable"]),
        "latest": len(latest),
        "klayout_drc_clear": all(c.get("klayout_drc_errors") == 0 for c in (*accepted.values(), *latest.values())
                                 if c.get("details")),
        "pad_mask_codes": pad_mask_codes,
        "pad_mask_failed": failed_pad_mask,
        "pad_mask_runs": len(ran),
        "pad_mask_not_cob": sorted(code for code in pad_mask_codes if not details[code]["chip_on_board"]),
        "magic_codes": magic,
        "missing": sorted(code for code, c in checks.items() if not c.get("latest")),
    }


# How the pages name things. A Tiny Tapeout run's "reticle" is one die and
# its "dies" are the projects in it, sized in tiles.
TERMS = {
    "wafer.space": {"reticle": "reticle", "Reticle": "Reticle", "die": "die", "dies": "dies", "Die": "Die",
                    "slot": "slot", "Slots": "Slots"},
    "tiny-tapeout": {"reticle": "die", "Reticle": "Die", "die": "project", "dies": "projects", "Die": "Size",
                     "slot": "tiles", "Slots": "Project sizes"},
}


# Timeline milestones about buying a slot, which link to the run's Crowd Supply campaign.
CAMPAIGN_RE = re.compile(r"crowd ?supply|campaign|early bird|purchase", re.I)
# A milestone whose shown date names a day ("28 April 2026") rather than a rough time ("Early Q4 2026").
EXACT_DATE_RE = re.compile(r"\b\d{1,2} (January|February|March|April|May|June|July|August|September|October|"
                           r"November|December) \d{4}\b")


def milestone_done(item: dict, today: str) -> bool:
    """Whether a timeline milestone has happened: as its ``done`` says, else once its date has passed.

    An estimated date ("Early Q4 2026") passing does not mean the milestone happened, so such a milestone
    is done only when marked so.
    """
    if item.get("done") is not None:
        return bool(item["done"])
    shown = item.get("display_date") or item["date"]
    return item["date"] <= today and bool(EXACT_DATE_RE.search(shown) or shown == item["date"])


# The demo board render on a Tiny Tapeout die's pages, published as images/tt-demo-board.webp.
TT_BOARD_IMAGE = Path(__file__).parent / "data" / "tt-demo-board.webp"


def tt_chip_links(site: dict) -> dict:
    """Where a Tiny Tapeout chip is described, sold and driven, from its run's ``[site]``.

    ``tt_store_url`` names the chip's own page in the Tiny Tapeout store; without one the store's
    development kits are linked. ``tt_for_sale = false`` marks a chip that was never sold (GF 0.1). The chip's
    fpgas.online board is linked only once its page is up.
    """
    chip = site.get("tt_chip", "")
    fpgas = links.fpgas_online(chip)
    # ``tt_chip_url`` for a chip tinytapeout.com has no page for (GF 0.1: its shuttle repository).
    chip_url = site.get("tt_chip_url") or (f"https://tinytapeout.com/chips/{chip}/" if chip else "")
    return {"chip": chip, "chip_url": chip_url,
            "chip_label": "Shuttle repository on GitHub" if site.get("tt_chip_url") else "All its projects on tinytapeout.com",
            "store_url": site.get("tt_store_url") or links.tinytapeout("kits"),
            "store_own_page": bool(site.get("tt_store_url")),
            "for_sale": site.get("tt_for_sale", True),
            "fpgas_url": fpgas if fpgas and external.available(fpgas) else ""}


def _tiny_tapeout(run) -> dict | None:
    """Links for a Tiny Tapeout die's pages: the chip on tinytapeout.com and the die on its wafer.space run."""
    if run.site.get("kind") != "tiny-tapeout":
        return None
    index = tinytapeout.load_index(run.repo_dir) or {}
    return {**tt_chip_links(run.site),
            "parent": run.site.get("parent", {}),
            # The shuttle repository at the tapeout release, which holds each project's docs and licence.
            "repo": https_url(index.get("repo")), "commit": index.get("commit", ""), "name": index.get("name", "")}


def _children(run) -> dict:
    """Project code -> the runs whose [site.parent] is that project's page here (a die's Tiny Tapeout site)."""
    found = {}
    prefix = f"{run.pages_url}projects/"
    for name in config.available_runs():
        other = config.load_run(name)
        url = other.site.get("parent", {}).get("url", "")
        if url.startswith(prefix) and url.endswith(".html"):
            found.setdefault(url[len(prefix):-len(".html")], []).append(other)
    return found


def build_context(run, out_dir: Path) -> dict:
    stats = stats_module.load(run, out_dir)
    site_dir = out_dir / "site"
    site_dir.mkdir(parents=True, exist_ok=True)

    renders_path = site_dir / "renders" / "renders.json"
    renders = json.loads(renders_path.read_text()) if renders_path.exists() else None

    print("Collecting external content...")
    timeline = external.timeline(run)
    if run.site.get("kind") == "tiny-tapeout":
        # The Tiny Tapeout shuttle's own milestones among its wafer.space run's,
        # each marked with who owns the step.
        for item in timeline:
            item["owner"] = "wafer.space"
            # The run's slot sales are for whole dies: say so, so a Tiny Tapeout buyer does not think they apply.
            if CAMPAIGN_RE.search(item["title"]) and "deadline" in item["title"].lower():
                item["description"] = f"{item['description']}, for whole-die slots on the run (not Tiny Tapeout projects)"
        timeline = sorted(timeline + tinytapeout.timeline_items(tinytapeout.load_shuttle(run.repo_dir)),
                          key=lambda item: item["date"])
    cob = external.cob_pages(run)
    photos = external.die_photos(run, site_dir)
    package_photos = external.package_photos(run, site_dir, [d.code for d in stats.designs])
    details = projects.load(out_dir)

    today = date.today().isoformat()
    campaign = run.site.get("campaign_url", "")
    for item in timeline:
        item["done"] = milestone_done(item, today)
        # The milestones of buying a slot happen on the run's Crowd Supply campaign.
        if campaign and not item.get("url") and CAMPAIGN_RE.search(f"{item['title']} {item.get('description', '')}"):
            item["url"] = campaign

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
    slot_guidance, best_density, median_density, maxima = _slot_guidance(stats)
    scale_max = max([stats.buffer_max(lib) for lib in stats.libraries] or [1])
    best_peak = max(digital, key=lambda d: d.peak_cells, default=None)
    utilisations = [d.utilisation for d in digital]

    placements, slot_columns, slot_rows = [], [], []
    if renders:
        reticle_info = renders["reticle"]
        # Positions are fractions of the frame the reticle is drawn on, which is
        # the reticle itself unless the run sets [site] reticle_frame_mm. The
        # reticle sits in the frame's top left corner.
        width = reticle_info.get("frame_width_mm", reticle_info["width_mm"])
        height = reticle_info.get("frame_height_mm", reticle_info["height_mm"])
        drop = height - reticle_info["height_mm"]
        in_frame = [dict(p, y_mm=p["y_mm"] + drop) for p in renders["placements"]]
        slots = [{}] * len(in_frame)
        if run.site.get("slot_labels", True):
            slots, slot_columns, slot_rows = reticle.slot_grid(
                in_frame, width, height,
                origin=run.site.get("slot_origin", "top-left"), letters=run.site.get("slot_letters", "columns"))
        for p, slot in zip(in_frame, slots):
            placements.append({
                "code": p["code"],
                "left": p["x_mm"] / width,
                "top": 1 - (p["y_mm"] + p["height_mm"]) / height,
                "width": p["width_mm"] / width,
                "height": p["height_mm"] / height,
                **slot,
            })

    return {
        "run": run,
        "stats": stats,
        "website": WEBSITE,
        "generated": today,
        "renders": renders,
        "placements": placements,
        "slot_columns": slot_columns,
        "slot_rows": slot_rows,
        "slot_types": _slot_types(stats, renders),
        "timeline": timeline,
        "today": {"date": today, "display": tinytapeout.display_date(today)},
        "cob": cob,
        "photos": photos,
        "package_photos": package_photos,
        "categories": categories,
        "category_colour": category_colour,
        "total_area": _area_bar(total_breakdown),
        "area_notes": AREA_NOTES,
        "reference": reference,
        "digital": digital,
        "scale_max": scale_max,
        "slot_guidance": slot_guidance,
        "maxima": maxima,
        "best_density": best_density,
        "median_density": median_density,
        "best_peak": best_peak,
        "median_utilisation": statistics.median(utilisations) if utilisations else 0,
        "best_utilisation": max(digital, key=lambda d: d.utilisation, default=None),
        "open_source": sum(1 for d in stats.designs if d.project.repository),
        "pads": sum(d.bond_pads for d in stats.designs),
        "probe_pads": sum(d.probe_pads for d in stats.designs),
        "design_by_code": {d.code: d for d in stats.designs},
        "details": details,
        "licence_counts": Counter(e["licence"]["declared"] or "not declared" for e in details.values()).most_common(),
        "licence_issues": sorted((code, e["licence"]["status"]) for code, e in details.items()
                                 if e["licence"].get("status") in ("mismatch", "no licence file")),
        "cob_selected": sum(1 for e in details.values() if e["chip_on_board"]),
        "precheck_passed": sum(1 for e in details.values() if e["precheck"] and e["precheck"]["is_manufacturable"]),
        "precheck_missing": sorted(code for code, e in details.items() if not e["precheck"]),
        "precheck": _precheck_summary(details),
        "precheck_table": _precheck_table,
        "feature_labels": FEATURE_LABELS,
        "children": _children(run),
        # [site] terms renames them for a die whose slots are not projects (Tiny Tapeout GF 0.1's blocks).
        "words": {**TERMS["tiny-tapeout" if run.site.get("kind") == "tiny-tapeout" else "wafer.space"],
                  **run.site.get("terms", {})},
        "tt": _tiny_tapeout(run),
        # A die whose projects share one block (GF 0.1): each project measured from the block's netlist.
        "netlist_projects": tinytapeout.load_projects(run.repo_dir),
        "netlist_shared": tinytapeout.shared_cells(run.repo_dir),
        "window_side": stats_module.length_label(stats.window_um),
        "window_step": stats_module.length_label(stats.step_um),
        "window_is_mm": stats.window_um == 1000,
        "windowed": report.windowed(stats),
        "core_area_text": (f"Core area is the area of each die's {stats.meta['core_cell']} cell."
                           if stats.meta.get("core_cell") else
                           f"Core area is the die minus a {stats_module.PAD_RING_MM * 1000:.0f} µm pad ring on each side."),
    }


# GitHub's "link" octicon (MIT licence), as on the headings of its rendered Markdown.
_LINK_ICON = Markup('<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m7.775 3.275 1.25-1.25a3.5 3.5 0 1 1 '
                    '4.95 4.95l-2.5 2.5a3.5 3.5 0 0 1-4.95 0 .751.751 0 0 1 .018-1.042.751.751 0 0 1 1.042-.018 '
                    '1.998 1.998 0 0 0 2.83 0l2.5-2.5a2.002 2.002 0 0 0-2.83-2.83l-1.25 1.25a.751.751 0 0 1-1.042'
                    '-.018.751.751 0 0 1-.018-1.042Zm-4.69 9.64a1.998 1.998 0 0 0 2.83 0l1.25-1.25a.751.751 0 0 1 '
                    '1.042.018.751.751 0 0 1 .018 1.042l-1.25 1.25a3.5 3.5 0 1 1-4.95-4.95l2.5-2.5a3.5 3.5 0 0 1 '
                    '4.95 0 .751.751 0 0 1-.018 1.042.751.751 0 0 1-1.042.018 1.998 1.998 0 0 0-2.83 0l-2.5 2.5a'
                    '1.998 1.998 0 0 0 0 2.83Z"/></svg>')


def _anchor(target: str) -> Markup:
    """The link to section ``target`` that run.css shows beside a heading while it is hovered."""
    return Markup('<a class="run-anchor" href="#{}" aria-label="Link to this section">{}</a>').format(target, _LINK_ICON)


def _photo_credit(run, target=None) -> Markup:
    """Copyright line for the die photographs: "© 2026 Name, Licence", linked where the run gives URLs."""
    def linked(text, url):
        if not url:
            return Markup.escape(text)
        if target:
            return Markup('<a href="{}" target="{}">{}</a>').format(url, target, text)
        return Markup('<a href="{}">{}</a>').format(url, text)

    site = run.site
    credit = linked(site.get("photos_credit", ""), site.get("photos_credit_url"))
    if site.get("photos_year"):
        credit = Markup("© {} {}").format(site["photos_year"], credit)
    if site.get("photos_licence"):
        credit = Markup("{}, {}").format(credit, linked(site["photos_licence"], site.get("photos_licence_url")))
    return credit


def _parent_die(run, out_dir: Path, env) -> dict | None:
    """A Tiny Tapeout die as its wafer.space run measured it: that run's page body for the die
    (_design.html), linking into that run's pages, or None when that run has not been measured here."""
    url = run.site.get("parent", {}).get("url", "")
    for name in config.available_runs():
        parent = config.load_run(name)
        prefix = f"{parent.pages_url}projects/"
        if parent.name == run.name or not url.startswith(prefix):
            continue
        parent_out = out_dir.parent / parent.name
        if not (parent_out / f"{stats_module.OUTPUT_STEM}.csv").exists():
            return None
        try:
            context = build_context(parent, parent_out)
        except FileNotFoundError as error:
            print(f"  warning: {parent.name} is not checked out next to this repository, so its die is left out: {error}")
            return None
        code = url[len(prefix):].removesuffix(".html")
        design = next((d for d in context["stats"].designs if d.code == code), None)
        if design is None:
            return None
        html = env.get_template("_design.html").render(
            **context, design=design, root=parent.pages_url, id_prefix="die-",
            related=lambda d: related.for_slot(parent, d.project),
            photo_credit=lambda target=None: _photo_credit(parent, target))
        return {"run": parent, "label": related.run_label(parent), "design": design, "html": Markup(html)}
    return None


def build_site(run, out_dir: Path) -> Path:
    """Render ``index.html`` and one page per project into ``out_dir/site``."""
    context = build_context(run, out_dir)
    stats = context["stats"]
    site_dir = out_dir / "site"

    env = Environment(loader=PackageLoader("ws_run_reports", "templates"),
                      autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    env.filters.update(k=report.k, pct=report.pct, count=report.count, count_fine=report.count_fine,
                       library_label=library_label,
                       describe_cell=describe_cell)
    # A content hash on the stylesheet and script links, so browsers fetch them again after a change.
    static = Path(__file__).parent / "static"
    digest = hashlib.sha256(b"".join(path.read_bytes() for path in sorted(static.iterdir())))
    env.globals.update(static_version=digest.hexdigest()[:10])
    env.globals.update(area_bar=_area_bar, heatmap=_heatmap, photo_credit=lambda target=None: _photo_credit(run, target))
    env.globals.update(related=lambda design: related.for_slot(run, design.project))
    env.globals.update(links=links, link=links.html, anchor=_anchor, category_id=category_id,
                       runs_linked=links.runs_linked)
    # Where a reader goes next: the Tiny Tapeout GF180MCU chips taking projects, and the wafer.space run taking orders.
    env.globals.update(next_tt=tinytapeout.next_shuttles(external.tt_chips()), next_ws=external.next_run())

    # The data behind the page, so every figure on it can be checked.
    data_dir = site_dir / "data"
    data_dir.mkdir(exist_ok=True)
    for path in stats_module.data_files(out_dir):
        shutil.copy(path, data_dir / path.name)
    report_path = out_dir / report.REPORT_NAME
    if report_path.exists():
        shutil.copy(report_path, data_dir / report_path.name)
    context["data_files"] = sorted(p.name for p in data_dir.iterdir() if p.is_file())
    # The platform's precheck step results and logs, linked from the project pages.
    precheck_dir = out_dir / projects.PRECHECK_DIR
    if (data_dir / projects.PRECHECK_DIR).exists():
        shutil.rmtree(data_dir / projects.PRECHECK_DIR)
    if precheck_dir.exists():
        shutil.copytree(precheck_dir, data_dir / projects.PRECHECK_DIR)

    context["parent_die"] = _parent_die(run, out_dir, env) if context["tt"] else None
    # Designs on this run that were made before or since, each once however many slots it has here; the
    # longest histories first.
    histories = {}
    for design in stats.designs:
        rel = related.for_slot(run, design.project)
        if rel and len(rel["stages"]) > 1:
            histories.setdefault(rel["name"], {"rel": rel, "designs": []})["designs"].append(design)
    # On a die whose projects share one block (GF 0.1) the slots are blocks: take the projects from its table.
    for row in context["netlist_projects"]:
        project = SimpleNamespace(top=row["TOP"], name=row["PROJECT"], repository="", code=row["CODE"])
        rel = related.for_slot(run, project)
        if rel and len(rel["stages"]) > 1:
            histories.setdefault(rel["name"], {"rel": rel, "designs": [], "anchor": f"#p{row['CODE']}"})
    context["histories"] = sorted(histories.values(), key=lambda h: -len(h["rel"]["stages"]))
    (site_dir / "index.html").write_text(env.get_template("index.html").render(root="", **context))
    # A JavaScript-free strip of the designs for other pages to embed; dies with photographs first.
    embed_designs = sorted(stats.designs, key=lambda d: (d.code not in context["photos"], d.code))
    (site_dir / "embed.html").write_text(env.get_template("embed.html").render(embed_designs=embed_designs, **context))

    projects_dir = site_dir / "projects"
    projects_dir.mkdir(exist_ok=True)
    designs = stats.designs
    template = env.get_template("project.html")
    redirect = env.get_template("redirect.html")
    for i, design in enumerate(designs):
        children = context["children"].get(design.code)
        if children:
            # The die has pages of its own, which show everything this page would and more.
            page = redirect.render(title=f"{design.code} {design.name}", url=children[0].pages_url)
        else:
            page = template.render(root="../", design=design, previous=designs[i - 1],
                                   following=designs[(i + 1) % len(designs)], **context)
        (projects_dir / f"{design.code}.html").write_text(page)

    static = Path(__file__).parent / "static"
    for path in static.iterdir():
        shutil.copy(path, site_dir / path.name)
    if context["tt"]:
        (site_dir / "images").mkdir(exist_ok=True)
        shutil.copy(TT_BOARD_IMAGE, site_dir / "images" / TT_BOARD_IMAGE.name)
    (site_dir / ".nojekyll").write_text("")
    return site_dir / "index.html"
