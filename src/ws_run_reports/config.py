"""Run configuration and project manifests.

A *run* is one shuttle (ws-run1, ws-run2, google-gf180mcu-mpw0, ...). Every
run goes through the same code; everything that differs between runs lives in
``runs/<name>.toml`` and everything that differs between projects comes from
the run repository's own manifest. Only ``title``, ``shuttle``, ``slots`` and
``[layout] md5`` are required; see :func:`load_run` for the defaults.
"""

import csv
import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parents[2] / "runs"

# Slot sizes as written in the manifests, as (width, height) fractions of a full slot.
SLOT_FRACTIONS = {
    "1x1": (1.0, 1.0),
    "1x0p5": (1.0, 0.5),
    "0p5x1": (0.5, 1.0),
    "0p5x0p5": (0.5, 0.5),
}


@dataclass
class Project:
    code: str
    name: str
    slot_size: str = ""
    details: str = ""
    repository: str = ""
    top: str = ""
    visibility: str = "Public"


@dataclass
class Run:
    name: str
    title: str
    shuttle: str
    slots: int
    repo_dir: Path
    layout: dict
    repo: str = ""
    process: str = "GF180MCU"
    manifest: dict = field(default_factory=lambda: {"csv": "data/manifest.csv"})
    site: dict = field(default_factory=dict)
    # Markdown sections appended to the density report, e.g. notes on earlier versions of it.
    report: dict = field(default_factory=dict)
    # How the layout is measured: library naming, excluded cells (see analyze.py).
    measure: dict = field(default_factory=dict)
    # Project code -> category, for projects the keyword rules in classify.py get wrong.
    categories: dict = field(default_factory=dict)

    @property
    def layout_file(self) -> Path:
        return self.repo_dir / self.layout["file"]

    @property
    def github_url(self) -> str:
        return f"https://github.com/{self.repo}"

    @property
    def heading(self) -> list:
        """Lines of the run page's title: ``[site] heading``, or the title."""
        return list(self.site.get("heading") or [self.title])

    @property
    def short_title(self) -> str:
        """The heading on one line, e.g. 'GFMPW-0 · Google & Efabless GF180MCU Open MPW Shuttle'."""
        first, *rest = self.heading
        return f"{first} · {' '.join(rest)}" if rest else first

    @property
    def pages_url(self) -> str:
        return f"https://wafer.space/{self.name}/"

    def assemble_layout(self) -> Path:
        """Join the split layout parts and check the result against the configured md5.

        An assembled file left over from an earlier layout is rebuilt from the
        parts rather than trusted.
        """
        target = self.layout_file
        if target.exists() and _md5(target) == self.layout["md5"]:
            return target
        parts = sorted(self.repo_dir.glob(self.layout["parts"]))
        if not parts:
            raise FileNotFoundError(f"no layout parts match {self.layout['parts']} in {self.repo_dir}")
        with open(target, "wb") as out:
            for part in parts:
                out.write(part.read_bytes())
        digest = _md5(target)
        if digest != self.layout["md5"]:
            raise ValueError(f"{target}: md5 {digest} of the joined parts does not match expected {self.layout['md5']}")
        return target

    def slot_cells(self) -> dict | None:
        """Cell name -> code when the manifest names each slot's cell (``[layout] slots = "manifest"``)."""
        if self.layout.get("slots", "children") != "manifest":
            return None
        return {p.top: p.code for p in self.projects().values()}

    def projects(self) -> dict[str, Project]:
        """Projects of this run keyed by their four character code."""
        if "csv" in self.manifest:
            projects = _projects_from_csv(self.repo_dir / self.manifest["csv"])
        else:
            projects = _projects_from_readme(self.repo_dir / self.manifest["readme"])
        return {p.code: p for p in projects}


def load_run(name: str, repo_dir: Path | None = None) -> Run:
    """Load ``runs/<name>.toml``. ``repo_dir`` defaults to a sibling checkout of the run repository.

    Defaults: ``name`` is the file name, ``repo`` is ``wafer-space/<name>``, the
    layout is ``layout/<shuttle>.oas`` split into ``layout/<shuttle>-part-*``,
    and the manifest is ``data/manifest.csv``.
    """
    path = Path(name) if name.endswith(".toml") else RUNS_DIR / f"{name}.toml"
    with open(path, "rb") as f:
        data = tomllib.load(f)
    data.setdefault("name", path.stem)
    data.setdefault("repo", f"wafer-space/{data['name']}")
    layout = data.setdefault("layout", {})
    layout.setdefault("parts", f"layout/{data['shuttle']}-part-*")
    layout.setdefault("file", f"layout/{data['shuttle']}.oas")
    if repo_dir is None:
        repo_dir = RUNS_DIR.parent.parent / data["name"]
    return Run(repo_dir=Path(repo_dir).resolve(), **data)


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            digest.update(chunk)
    return digest.hexdigest()


def available_runs() -> list[str]:
    return sorted(p.stem for p in RUNS_DIR.glob("*.toml"))


def _clean(text: str) -> str:
    """Collapse the manifests' embedded line breaks into single spaces."""
    text = re.sub(r"<br\s*/?>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _projects_from_csv(path: Path) -> list[Project]:
    with open(path, newline="") as f:
        return [
            Project(
                code=row["CODE"],
                name=_clean(row["PROJECT"]),
                slot_size=row["SLOT_SIZE"],
                details=_clean(row["PROJECT_DETAILS"]),
                repository=row["REPOSITORY"].strip(),
                top=row["TOP"],
                visibility=row["VISIBILITY"],
            )
            for row in csv.DictReader(f)
        ]


def _projects_from_readme(path: Path) -> list[Project]:
    """Parse the ``| Code | Project | Slot Size | Project Details | Repository |`` README table."""
    projects = []
    in_table = False
    for line in path.read_text().splitlines():
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] == "Code":
            in_table = True
            continue
        if not in_table or set(cells[0]) <= set("-: "):
            continue
        code, name, slot_size, details, repository = (cells + [""] * 5)[:5]
        visibility = "Private" if name == "Private" else "Public"
        projects.append(Project(code, _clean(name), slot_size, _clean(details), repository, visibility=visibility))
    return projects
