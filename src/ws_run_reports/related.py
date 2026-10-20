"""Designs with history on more than one chip, for the "Related tapeouts" part of a slot's page.

``runs/related/designs.toml`` lists designs that were made more than once: on several wafer.space runs, or
also on Tiny Tapeout chips (see the file for its format). A wafer.space slot is also related to the slots
on other wafer.space runs that have the same repository, without being listed.

:func:`for_slot` gives what a slot's page shows: the design, the other wafer.space slots with their run and
page, and the Tiny Tapeout projects with their chip, title, author and page (on tinytapeout.com, and here
too when the die is one of the Tiny Tapeout dies these pages measure).
"""

import datetime
import re
import tomllib
from functools import cache

from . import config, external, links
from .config import https_url

DESIGNS = config.RUNS_DIR / "related" / "designs.toml"


@cache
def designs() -> list[dict]:
    if not DESIGNS.exists():
        return []
    return [{"notes": {}, "wafer_space": [], "other_shuttles": [], "tiny_tapeout": [], **d}
            for d in tomllib.loads(DESIGNS.read_text()).get("design", [])]


@cache
def _runs() -> dict:
    return {name: config.load_run(name) for name in config.available_runs()}


@cache
def _projects(run_name: str) -> dict:
    """A run's projects, or {} when its repository is not checked out next to this one."""
    try:
        return _runs()[run_name].projects()
    except (FileNotFoundError, KeyError):
        return {}


def run_label(run) -> str:
    """The run as the pages name it: "wafer.space Run 2" for runs with pages listed in links.toml."""
    for name, url in links.tables().get("runs", {}).items():
        if url == run.pages_url:
            return name
    return run.short_title


@cache
def _tt_dies() -> dict:
    """(chip, macro) -> the project's page here, for the Tiny Tapeout dies these pages measure."""
    found = {}
    for name, run in _runs().items():
        chip = run.site.get("tt_chip")
        if run.site.get("kind") == "tiny-tapeout" and chip:
            for code, project in _projects(name).items():
                found[(chip, project.top)] = f"{run.pages_url}projects/{code}.html"
    return found


# Timeline events that mark when a run's designs were handed in, in the order they are looked for.
SUBMISSION_EVENTS = ("Design Submission", "Submission Deadline", "Tapeout Deadline", "Designs Submitted")


@cache
def submitted(run_name: str) -> str:
    """The ISO date a run's designs were due, from its timeline, or ""."""
    events = {e.get("title"): e.get("date", "") for e in external.timeline(_runs()[run_name])}
    return next((events[t] for t in SUBMISSION_EVENTS if events.get(t)), "")


@cache
def _tt_closed() -> dict:
    """Tiny Tapeout chip -> the ISO date its submissions closed, from tinytapeout.com/chips."""
    return {row["chip"]: row.get("closed", "") for row in external.tt_chips()
            if re.fullmatch(r"\d{4}-\d\d-\d\d", row.get("closed", ""))}


def _slot(key: str, design: dict) -> dict | None:
    run_name, _, code = key.partition("/")
    run, project = _runs().get(run_name), _projects(run_name).get(code)
    if not run or not project:
        return None
    kind = "other_shuttles" if key in design.get("other_shuttles", []) else "wafer_space"
    label = f"Google {run.heading[0]}" if kind == "other_shuttles" else run_label(run)
    return {"key": key, "kind": kind, "run": label, "run_url": run.pages_url, "code": code,
            "name": project.name, "slot": project.slot_size, "date": submitted(run_name),
            "url": f"{run.pages_url}projects/{code}.html", "note": design.get("notes", {}).get(key, "")}


@cache
def _shared_block_dies() -> dict:
    """Tiny Tapeout chip -> (its run, the release date) for the dies whose projects share one block (GF 0.1):
    tinytapeout.com has no pages for them, and their projects have no tiles."""
    from . import tinytapeout
    found = {}
    for run in _runs().values():
        if run.site.get("kind") == "tiny-tapeout" and tinytapeout.load_projects(run.repo_dir):
            release = tinytapeout.load_shuttle(run.repo_dir).get("release", {})
            found[run.site.get("tt_chip", "")] = (run, release.get("date", ""))
    return found


def _tt(key: str, design: dict) -> dict:
    chip, _, macro = key.partition("/")
    index = external.tt_index(chip)
    project = index.get("projects", {}).get(macro, {})
    # "Tiny Tapeout GF 0p3" as "Tiny Tapeout GF 0.3", like the index's other test chips.
    shuttle = re.sub(r"(\d)p(\d)", r"\1.\2", index.get("name") or chip)
    step = {"key": key, "kind": "tiny_tapeout", "chip": chip, "macro": macro, "shuttle": shuttle,
            "chip_url": f"https://tinytapeout.com/chips/{chip}/",
            "title": project.get("title") or macro, "author": project.get("author", ""),
            "tiles": project.get("tiles", ""), "date": _tt_closed().get(chip, ""),
            "url": f"https://tinytapeout.com/chips/{chip}/{macro}", "here": _tt_dies().get((chip, macro), ""),
            "note": design.get("notes", {}).get(key, "")}
    if chip in _shared_block_dies():
        # The project's row in the die's table of projects, dated by the release that taped the die out.
        run, released = _shared_block_dies()[chip]
        row = f"{run.pages_url}#p{int(project.get('address', 0)):03d}" if project else run.pages_url
        step.update(chip_url=run.pages_url, url=row, here=row, tiles="", shared=True, date=released)
    return step


def _key(run, project) -> tuple[str, str]:
    """("tiny_tapeout", "<chip>/<macro>") for a project on a Tiny Tapeout die, else ("wafer_space", "<run>/<code>")."""
    if run.site.get("kind") == "tiny-tapeout":
        return "tiny_tapeout", f"{run.site.get('tt_chip', '')}/{project.top}"
    return "wafer_space", f"{run.name}/{project.code}"


def for_slot(run, project) -> dict | None:
    """The related tapeouts of ``project`` on ``run``, or None when it has none.

    {"name", "started_on_tiny_tapeout", "here": this slot's note, "wafer_space": [other slots],
    "other_shuttles": [slots on the Google shuttles], "tiny_tapeout": [Tiny Tapeout projects other than this one],
    "steps": all of them and this one ("current": True) in the order they were submitted}
    """
    kind, key = _key(run, project)
    design = next((d for d in designs() if key in d[kind] or key in d["other_shuttles"]), None)
    if design is None:
        design = {"name": project.name, "notes": {}, "wafer_space": [], "other_shuttles": [], "tiny_tapeout": []}
    keys = list(design["wafer_space"])
    # Slots with the same repository on other wafer.space runs.
    repo = https_url(project.repository) if kind == "wafer_space" else ""
    if repo:
        for name, other in _runs().items():
            if other.name != run.name and other.site.get("kind") != "tiny-tapeout":
                keys += [f"{name}/{p.code}" for p in _projects(name).values()
                         if https_url(p.repository) == repo and f"{name}/{p.code}" not in keys
                         and f"{name}/{p.code}" not in design["other_shuttles"]]
    slots = [s for s in (_slot(k, design) for k in keys if k != key) if s]
    others = [s for s in (_slot(k, design) for k in design["other_shuttles"] if k != key) if s]
    tt = [_tt(k, design) for k in design["tiny_tapeout"] if k != key]
    if not slots and not others and not tt:
        return None
    this = _tt(key, design) if kind == "tiny_tapeout" else _slot(key, design)
    steps = [s | {"current": s is this} for s in [this] + others + tt + slots if s]
    # Undated steps last; versions handed in the same day by shuttle name (GF 0.1 before GF 0.2); a run's slots
    # keep their listed order (the sort is stable).
    steps.sort(key=lambda s: (s["date"] or "9999", s.get("shuttle") or s.get("run", "")))
    return {"name": design["name"], "started_on_tiny_tapeout": design.get("started_on_tiny_tapeout", False),
            "tiny_tapeout_lead": tiny_tapeout_lead(steps),
            "here": design["notes"].get(key, ""), "wafer_space": slots, "other_shuttles": others, "tiny_tapeout": tt,
            "steps": steps, "stages": stages(steps)}


# A Tiny Tapeout version this long before the first full-size one counts as where the design started.
TINY_TAPEOUT_LEAD_DAYS = 90


def tiny_tapeout_lead(steps: list) -> bool:
    """True when the first Tiny Tapeout version was submitted well before any version on a die of its own;
    False when they were made at about the same time (TT02 and GFMPW-0 closed three days apart)."""
    tt = [s["date"] for s in steps if s["kind"] == "tiny_tapeout" and s["date"]]
    whole = [s["date"] for s in steps if s["kind"] != "tiny_tapeout" and s["date"]]
    if not tt or not whole:
        return bool(tt)
    lead = datetime.date.fromisoformat(min(whole)) - datetime.date.fromisoformat(min(tt))
    return lead.days >= TINY_TAPEOUT_LEAD_DAYS


def graduated() -> list:
    """Designs made on Tiny Tapeout chips first and then on wafer.space dies, newest first:
    [{"name", "stages", "url": the latest wafer.space slot's page}]."""
    found = []
    for design in designs():
        slots = [s for s in (_slot(k, design) for k in design["wafer_space"]) if s]
        if not design.get("started_on_tiny_tapeout") or not design["tiny_tapeout"] or not slots:
            continue
        others = [s for s in (_slot(k, design) for k in design["other_shuttles"]) if s]
        steps = sorted(others + [_tt(k, design) for k in design["tiny_tapeout"]] + slots,
                       key=lambda s: (s["date"] or "9999", s.get("shuttle") or s.get("run", "")))
        steps = [s | {"current": False} for s in steps]
        found.append({"name": design["name"], "stages": stages(steps),
                      "url": max(slots, key=lambda s: s["date"])["url"]})
    # Newest first: by the latest version, then the longer history.
    return sorted(found, key=lambda d: (d["stages"][-1]["date"], len(d["stages"])), reverse=True)


def _size(step: dict) -> str:
    """"1×1 tile", "8×2 tiles" or "1×0.5 slot"; "" when not known."""
    if step.get("shared"):
        return "in a shared block"
    if step["kind"] == "tiny_tapeout":
        tiles = step.get("tiles", "")
        return f"{tiles.replace('x', '×')} tile{'' if tiles == '1x1' else 's'}" if tiles else ""
    if step["kind"] == "other_shuttles":
        return "Caravel chip"
    slot = (step.get("slot") or "").replace("p", ".")
    return f"{slot.replace('x', '×')} slot" if slot else ""


# Each kind's class suffix on the pages. Not "wafer-space": the theme's plugins.css styles every class containing
# "space" ([class*="space"] { width: 100%; display: block }).
KIND_CSS = {"tiny_tapeout": "tt", "other_shuttles": "google", "wafer_space": "ws"}


def stages(steps: list) -> list:
    """Steps grouped by shuttle, in order: [{"shuttle", "url", "kind", "css", "date", "when": "Dec 2022", "steps"}],
    each step with its "size"."""
    found = []
    for step in steps:
        shuttle = step.get("shuttle") or step["run"]
        if not found or found[-1]["shuttle"] != shuttle:
            when = datetime.date.fromisoformat(step["date"]).strftime("%b %Y") if step["date"] else ""
            found.append({"shuttle": shuttle, "url": step.get("chip_url") or step["run_url"], "kind": step["kind"],
                          "css": KIND_CSS[step["kind"]],
                          "date": step["date"], "when": when, "steps": []})
        found[-1]["steps"].append(step | {"size": _size(step)})
    return found
