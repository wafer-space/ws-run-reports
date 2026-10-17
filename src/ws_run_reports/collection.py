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

from . import config, external, links, tinytapeout
from . import stats as stats_module
from .site import WEBSITE

COLLECTIONS_DIR = config.RUNS_DIR / "collections"


def load(name: str) -> SimpleNamespace:
    data = tomllib.loads((COLLECTIONS_DIR / f"{name}.toml").read_text())
    repo_name = data["repo"].split("/")[-1]
    return SimpleNamespace(
        name=name, title=data["title"], repo=data["repo"], heading=list(data.get("heading") or [data["title"]]),
        intro=" ".join(data.get("intro", "").split()), site={},
        short_title=" · ".join([data["heading"][0], " ".join(data["heading"][1:])]) if data.get("heading") else data["title"],
        github_url=f"https://github.com/{data['repo']}", source_url=f"https://github.com/{data['repo']}",
        report_url=f"https://github.com/{data['repo']}/tree/density-report", pages_url=f"https://wafer.space/{repo_name}/")


def members(collection) -> list:
    """The runs in the collection's repository, by run then path."""
    runs = [config.load_run(name) for name in config.available_runs()]
    return sorted((r for r in runs if r.repo == collection.repo and r.path), key=lambda r: r.path)


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
                        "chip": run.site.get("tt_chip", ""),
                        "chip_url": f"https://tinytapeout.com/chips/{run.site['tt_chip']}/" if run.site.get("tt_chip") else ""})
    env = Environment(loader=PackageLoader("ws_run_reports", "templates"),
                      autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    static = Path(__file__).parent / "static"
    digest = hashlib.sha256(b"".join(path.read_bytes() for path in sorted(static.iterdir())))
    env.globals.update(static_version=digest.hexdigest()[:10], links=links, link=links.html)
    site_dir = out / name / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text(env.get_template("collection.html").render(
        run=collection, collection=collection, entries=entries, root="", website=WEBSITE, renders=None,
        generated=date.today().isoformat()))
    for path in static.iterdir():
        shutil.copy(path, site_dir / path.name)
    (site_dir / ".nojekyll").write_text("")
    return site_dir / "index.html"
