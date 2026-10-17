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


def repo_file(repo: str, commit: str, path: str) -> str:
    """A file in a repository at a commit (GitHub and GitLab layouts)."""
    if not (_github(repo) and commit and path):
        return ""
    sep = "/-/blob/" if repo.startswith("https://gitlab.com/") else "/blob/"
    return f"{repo}{sep}{commit}/{path}"


def repo_commit(repo: str, commit: str) -> str:
    if not (_github(repo) and commit):
        return ""
    sep = "/-/commit/" if repo.startswith("https://gitlab.com/") else "/commit/"
    return f"{repo}{sep}{commit}"


def repo_tree(repo: str, commit: str) -> str:
    """The repository's files at a commit."""
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
