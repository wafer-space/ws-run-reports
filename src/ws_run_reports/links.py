"""Where the names on the pages and in the report link to.

Every external URL the generator writes comes from here: the documentation
of the PDK's libraries, cells and macros, the tools, the precheck and
template releases, licences and the sites they name. The URL tables are in
``data/links.toml`` so that they can be corrected without touching code.

Each function returns a URL, or "" when there is nothing sensible to link
to; ``html`` and ``markdown`` turn a name and a URL into a link, or leave
the name as it is.
"""

import re
import tomllib
from functools import cache
from pathlib import Path

from markupsafe import Markup, escape

DATA = Path(__file__).parent / "data" / "links.toml"

# SPDX identifiers; anything else (e.g. "proprietary") is not linked.
_SPDX_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")
_NOT_SPDX = {"proprietary", "other", "none", "unknown", "noassertion"}


@cache
def tables() -> dict:
    return tomllib.loads(DATA.read_text())


def html(text, url: str, mono: bool = False) -> Markup:
    """``text`` as a link to ``url``, or as plain (escaped) text without one."""
    inner = Markup('<span class="run-mono">{}</span>').format(text) if mono else escape(text)
    return Markup('<a href="{}">{}</a>').format(url, inner) if url else Markup(inner)


def markdown(text, url: str, code: bool = False) -> str:
    inner = f"`{text}`" if code else str(text)
    return f"[{inner}]({url})" if url else inner


# --- licences, repositories and sites ------------------------------------

def spdx(licence: str) -> str:
    """The SPDX page of a licence identifier."""
    licence = (licence or "").strip()
    if not _SPDX_RE.fullmatch(licence) or licence.lower() in _NOT_SPDX:
        return ""
    return f"https://spdx.org/licenses/{licence}.html"


def _github(repo: str) -> bool:
    return (repo or "").startswith(("https://github.com/", "https://gitlab.com/"))


def repo_base(repo: str) -> str:
    """A GitHub repository URL without a branch or path after it:
    ".../owner/repo/tree/some-branch" -> ".../owner/repo". Other URLs are returned unchanged."""
    m = re.match(r"(https://github\.com/[^/]+/[^/]+)", repo or "")
    return m.group(1) if m else repo


def repo_file(repo: str, commit: str, path: str) -> str:
    """A file in a repository at a commit (GitHub and GitLab layouts)."""
    repo = repo_base(repo)
    if not (_github(repo) and commit and path):
        return ""
    sep = "/-/blob/" if repo.startswith("https://gitlab.com/") else "/blob/"
    return f"{repo}{sep}{commit}/{path}"


def repo_commit(repo: str, commit: str) -> str:
    repo = repo_base(repo)
    if not (_github(repo) and commit):
        return ""
    sep = "/-/commit/" if repo.startswith("https://gitlab.com/") else "/commit/"
    return f"{repo}{sep}{commit}"


def repo_tree(repo: str, commit: str) -> str:
    """The repository's files at a commit."""
    repo = repo_base(repo)
    if not (_github(repo) and commit):
        return ""
    sep = "/-/tree/" if repo.startswith("https://gitlab.com/") else "/tree/"
    return f"{repo}{sep}{commit}"


def site(name: str) -> str:
    """A site the pages mention by name, e.g. "platform.wafer.space"."""
    return tables().get("sites", {}).get(name, "")


def tool(name: str) -> str:
    """A tool's home page: KLayout, Magic, LibreLane..."""
    return tables().get("tools", {}).get(name, "")


# --- precheck, LibreLane, templates --------------------------------------

def precheck_version(version: str, digest: str = "") -> str:
    """The precheck version a check ran: as recorded, or from its image digest."""
    return version or tables()["precheck"]["digests"].get(digest or "", "")


def precheck(version: str) -> str:
    """The precheck repository at a release tag (or, for a "1.7.0-2-ga39b1e2" build between
    releases, at its commit), or the repository itself."""
    repo = tables()["precheck"]["repo"]
    if not version:
        return repo
    between = re.fullmatch(r".+-\d+-g([0-9a-f]+)", version)
    return f"{repo}/tree/{between.group(1) if between else version}"


def precheck_contents(version: str) -> dict:
    """What a precheck release runs: {"pdk", "pdk_url", "librelane", "librelane_url"}, or {}."""
    info = dict(tables()["precheck"].get("versions", {}).get(version, {}))
    if info.get("librelane"):
        info["librelane_url"] = f"{tables()['librelane']['repo']}/tree/{info['librelane']}"
    return info


def precheck_image() -> str:
    return tables()["precheck"]["package"]


def librelane(version: str) -> str:
    """LibreLane at a tag or commit."""
    return f"{tables()['librelane']['repo']}/tree/{version}" if version else tool("LibreLane")


def template(repo_name: str, version: str = "") -> str:
    """A project template ("owner/repo"), at a release tag when known."""
    url = tables().get("templates", {}).get(repo_name, {}).get("url", "")
    return f"{url}/tree/{version}" if url and version else url


def template_versions(repo_name: str, pins: dict) -> list:
    """The template releases whose Makefile pins the same PDK as ``pins`` ({"PDK_TAG": ...} or {"PDK_COMMIT": ...})."""
    found = []
    for version, pin in tables().get("templates", {}).get(repo_name, {}).get("pdk", {}).items():
        key, _, value = pin.partition("=")
        if pins.get(key) == value:
            found.append(version)
    return found


def open_pdks(commit: str) -> str:
    """open_pdks at a commit or tag."""
    return f"{tables()['open_pdks']['repo']}/tree/{commit}" if commit else tables()["open_pdks"]["repo"]


# --- the PDK: libraries, cells, macros, layers; LibreLane steps -------------

CELL_DOCS = Path(__file__).parent / "data" / "cell_docs.csv"


@cache
def _cell_docs() -> dict:
    import csv
    with open(CELL_DOCS, newline="") as f:
        return {row["cell"]: row["url"] for row in csv.DictReader(f)}


def full_library(library: str) -> str:
    """The library column's name as the full library name: "mcu7t5v0" -> "gf180mcu_fd_sc_mcu7t5v0",
    "as_sc_mcu7t3v3" -> "gf180mcu_as_sc_mcu7t3v3"; full names are returned as they are."""
    if library.startswith("gf180mcu_"):
        return library
    return f"gf180mcu_{library}" if "_" in library else f"gf180mcu_fd_sc_{library}"


def library(name: str) -> str:
    """A standard cell, I/O or SRAM library's documentation."""
    return tables().get("libraries", {}).get(full_library(name), "")


def cell(library_name: str, cell_type: str) -> str:
    """A standard cell's own documentation page (its datasheet page, for the OSU libraries),
    or its library's when the cell has none."""
    full = full_library(library_name)
    return _cell_docs().get(f"{full}__{cell_type}") or library(full)


def macro(name: str) -> str:
    """An SRAM macro's or I/O cell's documentation, by its full cell name."""
    name = name.split("$")[0]
    if name in _cell_docs():
        return _cell_docs()[name]
    return library(name.split("__")[0]) if "__" in name else ""


def layers() -> str:
    """The PDK's table of GDS layer numbers."""
    return tables()["pdk"]["layers"]


def step(step_id: str) -> str:
    """A LibreLane step's reference entry, e.g. "KLayout.DRC" -> ...#step-klayout-drc."""
    return f"{tables()['librelane']['steps']['reference']}#step-{step_id.lower().replace('.', '-')}" if step_id else ""


def pdk_pin(key: str, value: str) -> str:
    """The PDK a Makefile pins: PDK_TAG is a wafer-space/gf180mcu tag, PDK_COMMIT an open_pdks commit."""
    if key == "PDK_TAG":
        return f"https://github.com/wafer-space/gf180mcu/tree/{value}"
    return open_pdks(value) if key == "PDK_COMMIT" else ""
