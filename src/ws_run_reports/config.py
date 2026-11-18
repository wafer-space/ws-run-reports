"""Run configuration and project manifests.

A *run* is one shuttle (ws-run1, ws-run2, google-gf180mcu-mpw0, ...). Every
run goes through the same code; everything that differs between runs lives in
``runs/<name>.toml`` and everything that differs between projects comes from
the run repository's own manifest. Only ``title``, ``shuttle``, ``slots`` and
``[layout] md5`` are required; see :func:`load_run` for the defaults.
"""

import csv
import hashlib
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parents[2] / "runs"
# The directory holding the run repositories' checkouts, when they are not beside this repository (as in CI).
REPOS_ENV = "WS_RUN_REPOS"

# Names spelled the usual way on the pages, whatever a project's own record says, and plain typos in them.
DISPLAY_SPELLINGS = [(r"\bRisc-?V\b|\bRISCV\b", "RISC-V"), (r"(?i:\bwafer\.space\b)", "wafer.space"),
                     (r"\bTinyTapeout\b", "Tiny Tapeout"), (r"\bGF (\d)p(\d)\b", r"GF \1.\2"),
                     (r"Mpbs\b", "Mbps"), (r"\bFashioMNIST\b", "FashionMNIST"), (r"\baperature\b", "aperture"),
                     (r"\bcut-though\b", "cut-through")]


def spelled(name: str) -> str:
    """``name`` with DISPLAY_SPELLINGS applied."""
    for wrong, right in DISPLAY_SPELLINGS:
        name = re.sub(wrong, right, name)
    return name

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
    extra: dict = field(default_factory=dict)   # any other manifest columns, e.g. a Tiny Tapeout die's AUTHOR


@dataclass
class Run:
    name: str
    title: str
    shuttle: str
    slots: int
    repo_dir: Path
    layout: dict
    repo: str = ""
    # The run's folder inside a repository shared with other runs (e.g. "ttgf0p3/ws-run2-t0p3" in
    # wafer-space/tinytapeouts); its files, density report and web page all live there.
    path: str = ""
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
    def source_url(self) -> str:
        """The run's files on GitHub: the repository, or the run's folder in it."""
        return f"{self.github_url}/tree/main/{self.path}" if self.path else self.github_url

    @property
    def report_url(self) -> str:
        """The density report on the repository's density-report branch."""
        folder = f"{self.path}/" if self.path else ""
        return f"{self.github_url}/blob/density-report/{folder}reticle_density_report.md"

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
        if self.path:
            return f"https://wafer.space/{self.repo.split('/')[-1]}/{self.path}/"
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
        # [site.display_names]: a name for a project whose own says too little ("AS16 CPU") or is a raw repository name.
        for p in projects:
            p.name = self.site.get("display_names", {}).get(p.code, p.name)
        return {p.code: p for p in projects}


def load_run(name: str, repo_dir: Path | None = None) -> Run:
    """Load ``runs/<name>.toml``. ``repo_dir`` defaults to a checkout of the run repository in the directory
    that ``$WS_RUN_REPOS`` names, or else beside this repository.

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
        # A checkout of the run repository, and the run's folder in it.
        root = Path(os.environ[REPOS_ENV]) if os.environ.get(REPOS_ENV) else RUNS_DIR.parent.parent
        repo_dir = root / data["repo"].split("/")[-1] / data.get("path", "")
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


def https_url(url: str) -> str:
    """A repository URL as an https link: git@host:owner/repo, ssh://git@host/owner/repo and
    http:// become https://host/owner/repo, www.github.com becomes github.com, and a trailing
    .git and slashes are dropped. Anything else is returned stripped."""
    url = (url or "").strip()
    if not url:
        return ""
    if m := re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+)$", url):
        url = f"https://{m.group(1)}/{m.group(2)}"
    url = re.sub(r"^http://", "https://", url)
    url = re.sub(r"^https://www\.github\.com/", "https://github.com/", url)
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4].rstrip("/")
    return url


_MANIFEST_COLUMNS = {"CODE", "PROJECT", "SLOT_SIZE", "PROJECT_DETAILS", "REPOSITORY", "TOP", "VISIBILITY"}


def _projects_from_csv(path: Path) -> list[Project]:
    with open(path, newline="") as f:
        return [
            Project(
                code=row["CODE"],
                name=_clean(row["PROJECT"]),
                slot_size=row["SLOT_SIZE"],
                details=_clean(row["PROJECT_DETAILS"]),
                repository=https_url(row["REPOSITORY"]),
                top=row["TOP"],
                visibility=row["VISIBILITY"],
                extra={key: value or "" for key, value in row.items() if key not in _MANIFEST_COLUMNS},
            )
            for row in csv.DictReader(f)
        ]


def private_codes(readme: Path) -> set[str]:
    """Codes of the projects a run repository's README lists as private."""
    return {p.code for p in _projects_from_readme(readme) if p.visibility == "Private"}


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
        projects.append(Project(code, _clean(name), slot_size, _clean(details), https_url(repository),
                                visibility=visibility))
    return projects
