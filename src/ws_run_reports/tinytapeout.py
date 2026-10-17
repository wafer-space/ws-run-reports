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


def load_shuttle(repo_dir: Path) -> dict:
    path = Path(repo_dir) / "data" / SHUTTLE_NAME
    return json.loads(path.read_text()) if path.exists() else {}


def _display_date(iso: str) -> str:
    """'2026-06-19' -> '19 June 2026', as the run schedule writes dates."""
    from datetime import date
    day = date.fromisoformat(iso)
    return f"{day.day} {day:%B %Y}"


def timeline_items(shuttle: dict) -> list:
    """The shuttle's milestones in the format of the run timeline (external.timeline)."""
    items = []
    name = shuttle.get("name") or "Tiny Tapeout"
    if shuttle.get("end_date"):
        items.append({"title": f"{name} submissions close", "date": shuttle["end_date"],
                      "display_date": _display_date(shuttle["end_date"]),
                      "description": "Last day to submit a project to this Tiny Tapeout shuttle", "status": "critical",
                      "url": f"{shuttle['repo']}/blob/{shuttle['commit']}/config.yaml" if shuttle.get("repo") else ""})
    if shuttle.get("release"):
        release = shuttle["release"]
        items.append({"title": f"{name} tapeout release", "date": release["date"],
                      "display_date": _display_date(release["date"]),
                      "description": f"Tiny Tapeout publishes the chip's layout as {release['tag']}",
                      "status": "milestone", "url": release["url"]})
    return items
