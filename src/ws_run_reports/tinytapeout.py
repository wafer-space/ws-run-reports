"""Tiny Tapeout dies: one die of a Tiny Tapeout shuttle, measured like a reticle.

A Tiny Tapeout chip on a wafer.space reticle is a die (``tt_gf_wrapper``)
holding many small projects, each a ``tt_um_*`` macro of one or more tiles.
Its run measures the die as the "reticle" and each project as a "slot":

* the run repository's ``data/manifest.csv`` lists the projects, with the
  mux address as the code and the macro as ``TOP``;
* the run config sets ``[layout] slots = "manifest"`` so that the slots are
  the placements of those macros, and ``[site] kind = "tiny-tapeout"``.

``ws-run-reports tt-manifest`` writes the manifest from the tapeout
release's ``shuttle_index.json`` and the project ``info.yaml`` files at the
release commit of the Tiny Tapeout shuttle repository.
"""

import csv
import re
import json
import subprocess
from pathlib import Path

import yaml

from .config import https_url

FIELDS = ["CODE", "PROJECT", "SLOT_SIZE", "VISIBILITY", "PROJECT_DETAILS", "REPOSITORY", "TOP",
          "MACRO_ADDRESS", "TILE_X", "TILE_Y", "AUTHOR", "COMMIT", "LANGUAGE", "CLOCK_HZ",
          "FLOW_VERSION", "PDK_VERSION", "LICENSE_FILE", "DOCS_FILE"]


def code(address: int) -> str:
    """The project code: its mux address, as Tiny Tapeout numbers projects, padded to three digits."""
    return f"{int(address):03d}"


def _one_line(value) -> str:
    """Text from info.yaml on one line: runs of whitespace, newlines included, become one space."""
    return " ".join(str(value or "").split())


def _exists(tt_repo: Path, commit: str, path: str) -> bool:
    return subprocess.run(["git", "-C", str(tt_repo), "cat-file", "-e", f"{commit}:{path}"],
                          capture_output=True).returncode == 0


def _pdk(tt_repo: Path, commit: str, macro: str) -> dict:
    """``projects/<macro>/pdk.json`` at the release commit: the LibreLane and PDK the project was built with."""
    result = subprocess.run(["git", "-C", str(tt_repo), "show", f"{commit}:projects/{macro}/pdk.json"],
                            capture_output=True, text=True)
    return json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}


def _info(tt_repo: Path, commit: str, macro: str) -> dict:
    """``projects/<macro>/info.yaml`` at the release commit, or {} when it is missing."""
    result = subprocess.run(["git", "-C", str(tt_repo), "show", f"{commit}:projects/{macro}/info.yaml"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  warning: no info.yaml for {macro} at {commit[:12]}: {result.stderr.strip()}")
        return {}
    return (yaml.safe_load(result.stdout) or {}).get("project") or {}


def manifest_rows(index: dict, tt_repo: Path) -> list[dict]:
    """One manifest row per project of a shuttle index, in address order."""
    rows = []
    for project in sorted(index["projects"], key=lambda p: p["address"]):
        info = _info(tt_repo, index["commit"], project["macro"])
        pdk = _pdk(tt_repo, index["commit"], project["macro"])
        rows.append({
            "CODE": code(project["address"]),
            "PROJECT": _one_line(info.get("title") or project["macro"]),
            "SLOT_SIZE": project["tiles"],
            "VISIBILITY": "Public",
            "PROJECT_DETAILS": _one_line(info.get("description")),
            "REPOSITORY": https_url(project.get("repo")),
            "TOP": project["macro"],
            "MACRO_ADDRESS": project["address"],
            "TILE_X": project["x"],
            "TILE_Y": project["y"],
            "AUTHOR": _one_line(info.get("author")),
            "COMMIT": project.get("commit") or "",
            "LANGUAGE": _one_line(info.get("language")),
            "CLOCK_HZ": info.get("clock_hz") if info.get("clock_hz") is not None else "",
            "FLOW_VERSION": pdk.get("FLOW_VERSION") or "",
            "PDK_VERSION": pdk.get("PDK_VERSION") or "",
            # The project's licence and documentation in the shuttle repository, where it has them.
            "LICENSE_FILE": "LICENSE" if _exists(tt_repo, index["commit"], f"projects/{project['macro']}/LICENSE") else "",
            "DOCS_FILE": "docs/info.md" if _exists(tt_repo, index["commit"], f"projects/{project['macro']}/docs/info.md") else "",
        })
    return rows


def write_manifest(index_path: Path, tt_repo: Path, out: Path, release_tag: str = "") -> int:
    """Write the manifest, and with ``release_tag`` the shuttle's milestones (data/tt_shuttle.json) beside it."""
    index = json.loads(Path(index_path).read_text())
    rows = manifest_rows(index, tt_repo)
    if release_tag:
        info = shuttle_info(index, tt_repo, release_tag)
        (out.parent / SHUTTLE_NAME).write_text(json.dumps(info, indent=1, sort_keys=True) + "\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def load_index(repo_dir: Path) -> dict | None:
    """The run repository's copy of the release's shuttle index, if it has one."""
    path = Path(repo_dir) / "data" / "shuttle_index.json"
    return json.loads(path.read_text()) if path.exists() else None


SHUTTLE_NAME = "tt_shuttle.json"
PROJECTS_NAME = "projects.csv"


def shuttle_info(index: dict, tt_repo: Path, release_tag: str = "") -> dict:
    """The Tiny Tapeout shuttle's own milestones: when submissions closed (``end_date`` in its
    config.yaml at the release commit) and when the tapeout release was published (GitHub)."""
    info = {"name": index.get("name", ""), "repo": https_url(index.get("repo")), "commit": index.get("commit", "")}
    result = subprocess.run(["git", "-C", str(tt_repo), "show", f"{index['commit']}:config.yaml"],
                            capture_output=True, text=True)
    if result.returncode == 0:
        config = yaml.safe_load(result.stdout) or {}
        info.update(id=str(config.get("id") or ""), end_date=str(config.get("end_date") or ""))
    if release_tag and info["repo"].startswith("https://github.com/"):
        repo = info["repo"].removeprefix("https://github.com/")
        result = subprocess.run(["gh", "api", f"repos/{repo}/releases/tags/{release_tag}",
                                 "--jq", "{published_at, html_url}"], capture_output=True, text=True)
        if result.returncode == 0:
            release = json.loads(result.stdout)
            info["release"] = {"tag": release_tag, "date": release["published_at"][:10], "url": release["html_url"]}
        else:
            print(f"  warning: no release {release_tag} in {repo}: {result.stderr.strip()}")
    return info


def load_projects(repo_dir: Path) -> list[dict]:
    """The Tiny Tapeout projects of a die whose slots are blocks (GF 0.1), from ``data/projects.csv``: one row
    per project, measured from the shared block's netlist, without the ``shared`` row. [] for other dies."""
    path = Path(repo_dir) / "data" / PROJECTS_NAME
    if not path.exists():
        return []
    with open(path) as f:
        return [row for row in csv.DictReader(f) if row["CODE"] != "shared"]


def shared_cells(repo_dir: Path) -> dict:
    """The ``shared`` row of ``data/projects.csv``: the shared block's own logic, or {}."""
    path = Path(repo_dir) / "data" / PROJECTS_NAME
    if not path.exists():
        return {}
    with open(path) as f:
        return next((row for row in csv.DictReader(f) if row["CODE"] == "shared"), {})


def load_shuttle(repo_dir: Path) -> dict:
    path = Path(repo_dir) / "data" / SHUTTLE_NAME
    return json.loads(path.read_text()) if path.exists() else {}


def _display_date(iso: str) -> str:
    """'2026-06-19' -> '19 June 2026', as the run schedule writes dates."""
    from datetime import date
    day = date.fromisoformat(iso)
    return f"{day.day} {day:%B %Y}"


def display_date(text: str) -> str:
    """A date from tinytapeout.com/chips as the pages write it: ISO dates in words, anything else
    ("April 2027", "None - test shuttle") as it is."""
    return _display_date(text) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text or "") else (text or "")


def timeline_items(shuttle: dict) -> list:
    """The shuttle's milestones in the format of the run timeline (external.timeline)."""
    items = []
    # "Tiny Tapeout GF 0p3" as "Tiny Tapeout GF 0.3", as the chip is named everywhere else on the pages.
    name = re.sub(r"(\d)p(\d)", r"\1.\2", shuttle.get("name") or "Tiny Tapeout")
    if shuttle.get("end_date"):
        items.append({"owner": "Tiny Tapeout", "title": f"{name} submissions close", "date": shuttle["end_date"],
                      "display_date": _display_date(shuttle["end_date"]),
                      "description": "Last day to submit a project to this Tiny Tapeout shuttle",
                      "status": "critical",
                      "url": f"{shuttle['repo']}/blob/{shuttle['commit']}/config.yaml" if shuttle.get("repo") else ""})
    if shuttle.get("release"):
        release = shuttle["release"]
        items.append({"owner": "Tiny Tapeout", "title": f"{name} tapeout release", "date": release["date"],
                      "display_date": _display_date(release["date"]),
                      "description": release.get("description") or
                                     f"Tiny Tapeout publishes the die's layout ({release['tag']}) and sends it to wafer.space",
                      "status": "milestone", "url": release["url"]})
    return items


# --- the chips on tinytapeout.com/chips --------------------------------------

# The tables of tinytapeout.com/chips, under these headings of its source.
CHIP_SECTIONS = {"Open for Submission": "open", "Future Chips": "future", "Past Chips": "past"}


def parse_chips(markdown: str) -> list[dict]:
    """The rows of the chip tables in the source of tinytapeout.com/chips, in page order.

    Each row is a dict of the table's columns by lower-cased header ("run", "closes", "shuttle", ...) plus
    ``section`` ("open", "future" or "past"), ``chip`` (the run lower-cased, "ttgf26c") and ``url`` (the run's
    link, made absolute).
    """
    rows, section, headers = [], None, None
    for line in markdown.splitlines():
        heading = re.match(r"#+\s*(.+?)\s*$", line)
        if heading:
            section, headers = CHIP_SECTIONS.get(heading.group(1)), None
            continue
        if not section or not line.lstrip().startswith("|"):
            headers = None if not line.strip() else headers
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if headers is None:
            headers = [cell.lower() for cell in cells]
            continue
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        row = dict(zip(headers, (cell.replace("\\#", "#") for cell in cells)))
        link = re.match(r"\[([^\]]+)\]\(([^)]+)\)\s*(.*)", row.get("run", ""))
        name = link.group(1) if link else row.get("run", "").rstrip("†* ")
        url = link.group(2) if link else ""
        rows.append({**row, "section": section, "run": name, "chip": name.lower(),
                     "url": f"https://tinytapeout.com{url}" if url.startswith("/") else url,
                     "note": "†" in row.get("run", "")})
    return rows


def gf_chips(rows: list[dict]) -> list[dict]:
    """The GF180MCU chips (TTGF...) of :func:`parse_chips`."""
    return [row for row in rows if row["chip"].startswith("ttgf")]


def chip_name(run: str) -> str:
    """A chip's name as the pages write it: 'TTGF26c' -> 'Tiny Tapeout GF 26c', 'TTGF0p2' -> 'Tiny Tapeout GF 0.2',
    'TTSKY26d' -> 'Tiny Tapeout SKY 26d', 'TT10' -> 'Tiny Tapeout 10'."""
    m = re.fullmatch(r"TT(GF|SKY|IHP)?(\w+)", run or "", re.I)
    if not m:
        return run
    process, number = m.groups()
    number = re.sub(r"(\d)p(\d)", r"\1.\2", number)
    return f"Tiny Tapeout {process.upper() + ' ' if process else ''}{number}"


def next_shuttles(rows: list[dict]) -> list[dict]:
    """The GF180MCU chips still taking projects, the soonest to close first: each with its "name", "url", the
    "closes" date in words and the wafer.space run it will be made on."""
    from . import links
    open_rows = sorted((row for row in gf_chips(rows) if row["section"] == "open" and row.get("closes")),
                       key=lambda row: (row["closes"], row["run"]))
    return [{"name": chip_name(row["run"]), "chip": row["chip"], "url": row.get("url", ""),
             "closes": display_date(row["closes"]), "closes_iso": row["closes"],
             "ws_run": links.run_alias(row.get("shuttle", ""))} for row in open_rows]
