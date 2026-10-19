"""Designs with history on more than one chip, for the "Related tapeouts" part of a slot's page.

``runs/related/designs.toml`` lists designs that were made more than once: on several wafer.space runs, or
also on Tiny Tapeout chips (see the file for its format). A wafer.space slot is also related to the slots
on other wafer.space runs that have the same repository, without being listed.

:func:`for_slot` gives what a slot's page shows: the design, the other wafer.space slots with their run and
page, and the Tiny Tapeout projects with their chip, title, author and page (on tinytapeout.com, and here
too when the die is one of the Tiny Tapeout dies these pages measure).
"""

import tomllib
from functools import cache

from . import config, external, links
from .config import https_url

DESIGNS = config.RUNS_DIR / "related" / "designs.toml"


@cache
def designs() -> list[dict]:
    if not DESIGNS.exists():
        return []
    return [{"notes": {}, "wafer_space": [], "tiny_tapeout": [], **d}
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


def _slot(key: str, design: dict) -> dict | None:
    run_name, _, code = key.partition("/")
    run, project = _runs().get(run_name), _projects(run_name).get(code)
    if not run or not project:
        return None
    return {"key": key, "run": run_label(run), "code": code, "name": project.name, "slot": project.slot_size,
            "url": f"{run.pages_url}projects/{code}.html", "note": design.get("notes", {}).get(key, "")}


def _tt(key: str, design: dict) -> dict:
    chip, _, macro = key.partition("/")
    index = external.tt_index(chip)
    project = index.get("projects", {}).get(macro, {})
    return {"key": key, "chip": chip, "macro": macro, "shuttle": index.get("name") or chip,
            "chip_url": f"https://tinytapeout.com/chips/{chip}/",
            "title": project.get("title") or macro, "author": project.get("author", ""),
            "url": f"https://tinytapeout.com/chips/{chip}/{macro}", "here": _tt_dies().get((chip, macro), ""),
            "note": design.get("notes", {}).get(key, "")}


def _key(run, project) -> tuple[str, str]:
    """("tiny_tapeout", "<chip>/<macro>") for a project on a Tiny Tapeout die, else ("wafer_space", "<run>/<code>")."""
    if run.site.get("kind") == "tiny-tapeout":
        return "tiny_tapeout", f"{run.site.get('tt_chip', '')}/{project.top}"
    return "wafer_space", f"{run.name}/{project.code}"


def for_slot(run, project) -> dict | None:
    """The related tapeouts of ``project`` on ``run``, or None when it has none.

    {"name", "started_on_tiny_tapeout", "here": this slot's note, "wafer_space": [other slots],
    "tiny_tapeout": [Tiny Tapeout projects other than this one]}
    """
    kind, key = _key(run, project)
    design = next((d for d in designs() if key in d[kind]), None)
    if design is None:
        design = {"name": project.name, "notes": {}, "wafer_space": [], "tiny_tapeout": []}
    keys = list(design["wafer_space"])
    # Slots with the same repository on other wafer.space runs.
    repo = https_url(project.repository) if kind == "wafer_space" else ""
    if repo:
        for name, other in _runs().items():
            if other.name != run.name and other.site.get("kind") != "tiny-tapeout":
                keys += [f"{name}/{p.code}" for p in _projects(name).values()
                         if https_url(p.repository) == repo and f"{name}/{p.code}" not in keys]
    slots = [s for s in (_slot(k, design) for k in keys if k != key) if s]
    tt = [_tt(k, design) for k in design["tiny_tapeout"] if k != key]
    if not slots and not tt:
        return None
    return {"name": design["name"], "started_on_tiny_tapeout": design.get("started_on_tiny_tapeout", False),
            "here": design["notes"].get(key, ""), "wafer_space": slots, "tiny_tapeout": tt}
