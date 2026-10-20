"""An index page for a repository shared by several runs, such as wafer-space/tinytapeouts.

``runs/collections/<name>.toml`` names the repository and gives the page's
title, heading and introduction. The page lists every run whose ``repo`` is
that repository, newest run first, with its overview render and a link to
its pages, and is published at the root of the repository's gh-pages
branch (``ws-run-reports collection <name> --publish``).
"""

import hashlib
import json
import shutil
import tomllib
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, PackageLoader, select_autoescape

from . import config, external, links, related, tinytapeout
from . import site as site_module
from . import stats as stats_module
from .site import TT_BOARD_IMAGE, WEBSITE, tt_chip_links

COLLECTIONS_DIR = config.RUNS_DIR / "collections"


def load(name: str) -> SimpleNamespace:
    data = tomllib.loads((COLLECTIONS_DIR / f"{name}.toml").read_text())
    repo_name = data["repo"].split("/")[-1]
    return SimpleNamespace(
        name=name, title=data["title"], repo=data["repo"], heading=list(data.get("heading") or [data["title"]]),
        intro=" ".join(data.get("intro", "").split()), site={"kind": data.get("kind", "")},
        other=[{**item, "description": " ".join(item.get("description", "").split())} for item in data.get("other", [])],
        short_title=" · ".join([data["heading"][0], " ".join(data["heading"][1:])]) if data.get("heading") else data["title"],
        github_url=f"https://github.com/{data['repo']}", source_url=f"https://github.com/{data['repo']}",
        report_url=f"https://github.com/{data['repo']}/tree/density-report", pages_url=f"https://wafer.space/{repo_name}/")


def members(collection) -> list:
    """The runs in the collection's repository, by run then path."""
    runs = [config.load_run(name) for name in config.available_runs()]
    return sorted((r for r in runs if r.repo == collection.repo and r.path), key=lambda r: r.path)


def tt_chips(collection, measured: set) -> tuple[list, list]:
    """The GF180MCU Tiny Tapeout chips of tinytapeout.com/chips that have no pages here yet.

    Returns (coming, other): the chips open for projects, planned, or on a wafer.space run but not yet
    measured; and those made elsewhere, with the collection's own ``[[other]]`` chips.
    """
    tiles = external.tt_tiles()
    coming, other = [], []
    for chip in tinytapeout.gf_chips(external.tt_chips()):
        if chip["chip"] in measured:
            continue
        ws_run = links.run_alias(chip.get("shuttle", ""))
        dates = {key: tinytapeout.display_date(chip.get(key, "")) for key in
                 ("closes", "closed", "submission deadline", "chips expected", "estimated shipping date")}
        item = {**chip, "ws_run": ws_run, "dates": dates, "tiles": tiles.get(chip["chip"], {})}
        (coming if ws_run or chip["section"] != "past" else other).append(item)
    known = {item["chip"] for item in other}
    other += [item for item in collection.other if item["chip"] not in known | measured]
    return coming, other


def build(name: str, out: Path) -> Path:
    """Write the collection's index page into ``out/<name>/site``."""
    collection = load(name)
    entries = []
    for run in members(collection):
        out_dir = out / run.name
        renders_path = out_dir / "site" / "renders" / "renders.json"
        renders = json.loads(renders_path.read_text()) if renders_path.exists() else None
        stats = stats_module.load(run, out_dir) if (out_dir / f"{stats_module.OUTPUT_STEM}.csv").exists() else None
        timeline = sorted(external.timeline(run) + tinytapeout.timeline_items(tinytapeout.load_shuttle(run.repo_dir)),
                          key=lambda item: item["date"])
        today = date.today().isoformat()
        reached = [item for item in timeline if item["date"] <= today]
        upcoming = [item for item in timeline if item["date"] > today]
        entries.append({"run": run, "renders": renders, "stats": stats,
                        "status": reached[-1] if reached else None, "next": upcoming[0] if upcoming else None,
                        "projects": len(run.projects()), "parent": run.site.get("parent", {}),
                        "chip": run.site.get("tt_chip", ""), "links": tt_chip_links(run.site),
                        "chip_url": f"https://tinytapeout.com/chips/{run.site['tt_chip']}/" if run.site.get("tt_chip") else ""})
    coming, other = tt_chips(collection, {entry["chip"] for entry in entries}) if collection.site["kind"] == "tiny-tapeout" else ([], [])
    env = Environment(loader=PackageLoader("ws_run_reports", "templates"),
                      autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    static = Path(__file__).parent / "static"
    digest = hashlib.sha256(b"".join(path.read_bytes() for path in sorted(static.iterdir())))
    env.globals.update(static_version=digest.hexdigest()[:10], links=links, link=links.html,
                       anchor=site_module._anchor, runs_linked=links.runs_linked)
    site_dir = out / name / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text(env.get_template("collection.html").render(
        run=collection, collection=collection, entries=entries, coming=coming, other=other,
        graduated=related.graduated() if collection.site["kind"] == "tiny-tapeout" else [],
        tt=collection.site["kind"] == "tiny-tapeout", root="", website=WEBSITE, renders=None,
        generated=date.today().isoformat()))
    for path in static.iterdir():
        shutil.copy(path, site_dir / path.name)
    if collection.site["kind"] == "tiny-tapeout":
        (site_dir / "images").mkdir(exist_ok=True)
        shutil.copy(TT_BOARD_IMAGE, site_dir / "images" / TT_BOARD_IMAGE.name)
    (site_dir / ".nojekyll").write_text("")
    return site_dir / "index.html"
