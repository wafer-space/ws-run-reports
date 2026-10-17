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
          "MACRO_ADDRESS", "TILE_X", "TILE_Y", "AUTHOR", "COMMIT", "LANGUAGE", "CLOCK_HZ"]


def code(address: int) -> str:
    """The project code: its mux address, as Tiny Tapeout numbers projects, padded to three digits."""
    return f"{int(address):03d}"


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
        rows.append({
            "CODE": code(project["address"]),
            "PROJECT": str(info.get("title") or project["macro"]).strip(),
            "SLOT_SIZE": project["tiles"],
            "VISIBILITY": "Public",
            "PROJECT_DETAILS": str(info.get("description") or "").strip(),
            "REPOSITORY": https_url(project.get("repo")),
            "TOP": project["macro"],
            "MACRO_ADDRESS": project["address"],
            "TILE_X": project["x"],
            "TILE_Y": project["y"],
            "AUTHOR": str(info.get("author") or "").strip(),
            "COMMIT": project.get("commit") or "",
            "LANGUAGE": str(info.get("language") or "").strip(),
            "CLOCK_HZ": info.get("clock_hz") if info.get("clock_hz") is not None else "",
        })
    return rows


def write_manifest(index_path: Path, tt_repo: Path, out: Path) -> int:
    index = json.loads(Path(index_path).read_text())
    rows = manifest_rows(index, tt_repo)
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
