"""Where each wafer.space design's core is: its LibreLane ``CORE_AREA``, read from the design's repository at the
commit that was checked, for density per mm² of core.

A design's area can be measured three ways, and the pages give the first two side by side:

* **inside the seal ring**: everything a customer's slot gives them to use, so the pad ring's share counts against
  the density (the die minus the 26 µm seal ring on each side);
* **inside the core**: the area a design's own logic is placed in, which is what a designer changes (the template
  puts it 442 µm in from the die's edge, inside the pad ring);
* in the densest window (the per-mm² squares), which needs no outline at all.

``ws-run-reports cores <run>`` writes ``out/<run>/core_areas.json``:
{code: {"core_um": [x0, y0, x1, y1], "die_um": [...], "source": "librelane/slots/slot_1x1.yaml"}}.
A design whose repository or config could not be read is left out, and its core is the template's.
"""

import json
import subprocess
from pathlib import Path

import yaml

from . import projects

RUNS_ROOT = Path.home() / "github" / "wafer-space" / "runs"
FILE = "core_areas.json"
# The configs that can set the floorplan, the slot's own first (the template's layout).
CONFIG_PATHS = ("librelane/slots/slot_{slot}.yaml", "librelane/config.yaml", "librelane/config.json")


def _floorplan(repo: Path, commit: str, slot: str) -> dict | None:
    """DIE_AREA and CORE_AREA from the first config at ``commit`` that sets them, with that config's path."""
    die = core = None
    source = ""
    for pattern in CONFIG_PATHS:
        path = pattern.format(slot=slot)
        shown = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"], capture_output=True, text=True)
        if shown.returncode:
            continue
        try:
            data = yaml.safe_load(shown.stdout) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        if not core and isinstance(data.get("CORE_AREA"), list) and len(data["CORE_AREA"]) == 4:
            core, source = [float(v) for v in data["CORE_AREA"]], path
        if not die and isinstance(data.get("DIE_AREA"), list) and len(data["DIE_AREA"]) == 4:
            die = [float(v) for v in data["DIE_AREA"]]
    if not core:
        return None
    return {"core_um": core, "die_um": die, "source": source}


def read(run, out_dir: Path) -> dict:
    """Every design's floorplan that its repository records (see the module docstring)."""
    details = projects.load(out_dir)
    found = {}
    for code, project in run.projects().items():
        repo = RUNS_ROOT / run.name / code / "repo"
        commit = ((details.get(code) or {}).get("licence") or {}).get("repo_commit", "")
        if commit and (repo / ".git").exists():
            plan = _floorplan(repo, commit, project.slot_size)
            if plan:
                found[code] = plan
    return found


def write(run, out_dir: Path) -> Path:
    path = out_dir / FILE
    path.write_text(json.dumps(read(run, out_dir), indent=1, sort_keys=True) + "\n")
    return path


def load(out_dir: Path) -> dict:
    """The run's ``core_areas.json`` in ``out_dir``, or {} before ``cores`` has been run."""
    path = out_dir / FILE
    return json.loads(path.read_text()) if path.exists() else {}
