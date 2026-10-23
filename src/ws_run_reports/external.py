"""Content the run pages pull in from elsewhere.

Each source is optional and configured per run in the ``[site]`` table of
``runs/<run>.toml``. A source that is missing or unreachable is reported and
skipped, so a new run can be published before any of this exists for it.
"""

import functools
import io
import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "ws-run-reports (https://github.com/wafer-space/ws-run-reports)"
RUNS_YML_URL = "https://raw.githubusercontent.com/wafer-space/wafer-space.github.io/main/_data/runs.yml"
WEBSITE_URL = "https://wafer.space"
# Words a milestone title keeps capitalised in sentence case: names, not words of the sentence.
PROPER_WORDS = {"Tiny", "Tapeout", "Crowd", "Supply", "Run", "GlobalFoundries", "Google", "Efabless", "Caravel"}
PHOTO_PREVIEW_PX = 1100
# Each GitHub account's type ("User" or "Organization"), as looked up; kept between builds.
GITHUB_ACCOUNTS = Path(__file__).resolve().parents[2] / "out" / "github_accounts.json"
PACKAGE_PREVIEW_PX = 600


def fetch(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _try(label, function, default):
    try:
        return function()
    except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
        print(f"  warning: {label} unavailable: {error}")
        return default


@functools.cache
def _github_accounts() -> dict:
    return json.loads(GITHUB_ACCOUNTS.read_text()) if GITHUB_ACCOUNTS.exists() else {}


def github_user(repository: str) -> str:
    """The GitHub account that owns ``repository`` when it is a person's, else "" (an organisation's, not on
    GitHub, or not found). Looked up with ``gh api`` once, then kept in GITHUB_ACCOUNTS."""
    m = re.match(r"https://github\.com/([^/]+)/", repository or "")
    if not m:
        return ""
    owner, accounts = m.group(1), _github_accounts()
    if owner not in accounts:
        result = subprocess.run(["gh", "api", f"users/{owner}", "--jq", ".type"], capture_output=True, text=True)
        if result.returncode != 0 and "HTTP 404" not in result.stderr:
            print(f"  warning: GitHub account {owner} unavailable: {result.stderr.strip()}")
            return ""
        # A deleted account is kept as "" (none), so that it is not looked up again.
        accounts[owner] = result.stdout.strip() if result.returncode == 0 else ""
        GITHUB_ACCOUNTS.parent.mkdir(parents=True, exist_ok=True)
        GITHUB_ACCOUNTS.write_text(json.dumps(accounts, indent=1, sort_keys=True) + "\n")
    return owner if accounts[owner] == "User" else ""


GITHUB_REPOS = Path(__file__).resolve().parents[2] / "out" / "github_repos.json"


@functools.cache
def _github_repos() -> dict:
    return json.loads(GITHUB_REPOS.read_text()) if GITHUB_REPOS.exists() else {}


def repository_public(repository: str) -> bool:
    """Whether a project's repository can still be opened: a GitHub repository that answers 404 cannot. Anything
    not on GitHub, or not looked up for another reason, counts as public. Kept in GITHUB_REPOS once looked up."""
    m = re.match(r"https://github\.com/([^/]+/[^/#?]+)", repository or "")
    if not m:
        return bool(repository)
    name, repos = m.group(1).removesuffix(".git"), _github_repos()
    if name not in repos:
        result = subprocess.run(["gh", "api", f"repos/{name}", "--jq", ".private"], capture_output=True, text=True)
        if result.returncode != 0 and "HTTP 404" not in result.stderr:
            print(f"  warning: GitHub repository {name} unavailable: {result.stderr.strip()}")
            return True
        repos[name] = result.returncode == 0 and result.stdout.strip() == "false"
        GITHUB_REPOS.parent.mkdir(parents=True, exist_ok=True)
        GITHUB_REPOS.write_text(json.dumps(repos, indent=1, sort_keys=True) + "\n")
    return repos[name]


def clock_24h(text: str) -> str:
    """A schedule's "30 April 2026 @ 11:59 PM AoE" as "30 April 2026, 23:59 AoE"."""
    def convert(m):
        hour = int(m.group(1)) % 12 + (12 if (m.group(3) or "").upper() == "PM" else 0)
        return f", {hour:02d}:{m.group(2)}" if m.group(3) else f", {int(m.group(1)):02d}:{m.group(2)}"
    return re.sub(r"\s*@\s*(\d{1,2}):(\d{2})(?:\s*([AaPp][Mm]))?", convert, text or "")


def sentence_case(title: str) -> str:
    """A schedule's "Early Bird Deadline" as "Early bird deadline": later plain capitalised words lowercased,
    names (PROPER_WORDS) and acronyms ("GDS", "Q4") kept."""
    words = title.split(" ")
    return " ".join([words[0]] + [w.lower() if re.fullmatch(r"[A-Z][a-z]+", w) and w not in PROPER_WORDS else w
                                  for w in words[1:]])


def _deadline_pages(entry: dict) -> dict:
    """The page each of a run's deadline entries points to ("Submission Deadline": the platform), by title."""
    pages = {}
    for value in entry.values():
        if isinstance(value, dict) and value.get("title") and value.get("button_url"):
            url = value["button_url"]
            pages[value["title"]] = url if url.startswith("http") else WEBSITE_URL + url
    return pages


def _page_for(title: str, pages: dict) -> str:
    """The deadline page for a milestone: by its title, or one that starts the other ("Design Submission")."""
    return pages.get(title) or next((url for name, url in pages.items() if name.startswith(title) or title.startswith(name)), "")


def timeline(run) -> list:
    """Milestones for this run from the wafer.space website's ``_data/runs.yml``.

    A milestone's optional ``done`` says whether it has happened (see ``site.milestone_done``).

    ``runs_yml_path`` reads a file in the same format from the run repository
    instead, for shuttles that are not on the wafer.space schedule.
    """
    key = run.site.get("runs_yml_key")
    if not key:
        return []

    def load():
        import yaml
        if run.site.get("runs_yml_path"):
            text = (run.repo_dir / run.site["runs_yml_path"]).read_bytes()
        else:
            text = fetch(run.site.get("runs_yml_url", RUNS_YML_URL))
        data = yaml.safe_load(text)
        entry = data["runs"][key]
        pages = _deadline_pages(entry)
        return [
            {"title": sentence_case(item["title"]), "date": str(item["date"]), "display_date": clock_24h(item.get("display_date", "")),
             "description": item.get("description", ""), "status": item.get("status", ""), "done": item.get("done"),
             # Where the milestone is recorded, when a schedule names it (the Google shuttles' sources).
             # else the page the run's matching deadline entry sends people to.
             **({"url": item.get("url") or _page_for(item["title"], pages)} if item.get("url") or _page_for(item["title"], pages) else {})}
            for item in entry.get("timeline", [])
        ]

    # A run that names its schedule must have it: a failed fetch stops the build rather than
    # publishing the page without its status section.
    return load()


@functools.cache
def next_run() -> dict:
    """The wafer.space run now taking orders, from the website's ``_data/runs.yml``: the first run whose
    purchase deadline has not passed. {"name": "wafer.space Run 3", "deadline": "9 December 2026",
    "submission": "16 December 2026", "url": where to buy a slot}, or {}."""
    from datetime import datetime, timezone

    def load():
        import yaml
        now = datetime.now(timezone.utc).isoformat()
        for key, entry in yaml.safe_load(fetch(RUNS_YML_URL))["runs"].items():
            deadline = entry.get("campaign_deadline") or {}
            if str(deadline.get("date", "")) > now:
                day = lambda text: re.sub(r"\s*@.*$", "", text or "")
                return {"key": key, "name": f"wafer.space Run {entry.get('run_number', '')}".strip(),
                        "deadline": day(deadline.get("display_date")),
                        "submission": day((entry.get("submission_deadline") or {}).get("display_date")),
                        "url": deadline.get("button_url") or "https://buy.wafer.space/"}
        return {}

    return _try("next wafer.space run", load, {})


@functools.cache
def available(url: str) -> bool:
    """Whether ``url`` answers with a page (not a 404): for links to pages that may not exist yet."""
    def load():
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status == 200
    try:
        return load()
    except urllib.error.HTTPError:
        return False
    except (urllib.error.URLError, OSError, ValueError) as error:
        print(f"  warning: {url} unavailable: {error}")
        return False


@functools.cache
def tt_chips() -> list:
    """Every chip on tinytapeout.com/chips (tinytapeout.parse_chips), or [] when it cannot be read."""
    from . import links, tinytapeout
    return _try("Tiny Tapeout chips", lambda: tinytapeout.parse_chips(
        fetch(links.tinytapeout("chips_source")).decode()), [])


@functools.cache
def tt_index(chip: str) -> dict:
    """A Tiny Tapeout chip's project index from index.tinytapeout.com: {"name", "projects": {macro: {...}}},
    or {} when it cannot be read."""
    def load():
        data = json.loads(fetch(f"https://index.tinytapeout.com/{chip}.json"
                                "?fields=macro&fields=title&fields=author&fields=tiles"))
        return {"name": data.get("name", ""), "projects": {p["macro"]: p for p in data.get("projects", [])}}
    return _try(f"Tiny Tapeout index of {chip}", load, {})


@functools.cache
def tt_tiles() -> dict:
    """Tiles used and in total of each open Tiny Tapeout shuttle, by chip ("ttgf26c")."""
    def load():
        data = json.loads(fetch("https://app.tinytapeout.com/api/shuttles/submission-stats"))
        return {s["slug"]: s for s in data.get("shuttles", [])}
    return _try("Tiny Tapeout tile counts", load, {})


def cob_pages(run) -> dict:
    """Project code -> URL of its chip-on-board bonding results page."""
    repo = run.site.get("cob_repo")
    base = run.site.get("cob_url")
    if not repo or not base:
        return {}

    def load():
        entries = json.loads(fetch(f"https://api.github.com/repos/{repo}/contents/"))
        return {e["name"]: f"{base.rstrip('/')}/{e['name']}/" for e in entries
                if e["type"] == "dir" and re.fullmatch(r"[A-Z0-9]{4}", e["name"])}

    return _try("chip-on-board pages", load, {})


def die_photos(run, site_dir: Path) -> dict:
    """Project code -> die photograph, with a small preview saved into the site.

    The published photographs are very large (the "thumbnails" are about 3 MB
    and the full images hundreds of megabytes), so the page shows a resized
    preview and links to the originals.

    ``photos_viewer_url`` is an optional template for the photographer's
    zoomable viewer of one die, with ``{code}`` (lower case), ``{CODE}`` and
    ``{setup}`` (the imaging setup from the file name) filled in.
    """
    base = run.site.get("photos_url")
    prefix = run.site.get("photos_prefix")
    viewer = run.site.get("photos_viewer_url")
    if not base or not prefix:
        return {}

    def load():
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        names = re.findall(r'href="([^"]+\.jpe?g)"', fetch(base).decode())
        photos = {}
        for name in names:
            m = re.match(re.escape(prefix) + r"([a-z0-9]{4})_(.+?)(_th|_66p)?\.jpe?g$", name)
            if not m:
                continue
            entry = photos.setdefault(m.group(1).upper(), {"setup": m.group(2)})
            entry["thumb_url" if m.group(3) == "_th" else "full_url"] = base + name
        if viewer:
            for code, entry in photos.items():
                entry["viewer_url"] = viewer.format(code=code.lower(), CODE=code, setup=entry["setup"])
        out_dir = site_dir / "photos"
        out_dir.mkdir(parents=True, exist_ok=True)
        for code, entry in sorted(photos.items()):
            if "thumb_url" not in entry:
                continue
            preview = out_dir / f"{code}.webp"
            if not preview.exists():
                print(f"  fetching die photo preview for {code}")
                image = Image.open(io.BytesIO(fetch(entry["thumb_url"]))).convert("RGB")
                image.thumbnail((PHOTO_PREVIEW_PX, PHOTO_PREVIEW_PX), Image.LANCZOS)
                image.save(preview, "WEBP", quality=82, method=6)
            entry["preview"] = f"photos/{code}.webp"
        return {code: entry for code, entry in photos.items() if "preview" in entry}

    return _try("die photographs", load, {})


def package_photos(run, site_dir: Path, codes) -> dict:
    """Project code -> photographs of how its dies were packed and shipped, with small previews.

    ``package_photos_url`` is a folder holding one folder per die, named by the
    ``package_photos_dir`` template (``{code}`` lower case, ``{CODE}``); every
    JPEG in a die's folder is shown. Dies without a folder have none. They share
    the die photographs' credit.
    """
    base = run.site.get("package_photos_url")
    folder = run.site.get("package_photos_dir")
    if not base or not folder:
        return {}
    from PIL import Image
    out_dir = site_dir / "photos" / "package"
    found = {}
    for code in sorted(codes):
        url = base + folder.format(code=code.lower(), CODE=code)
        try:
            names = re.findall(r'href="([^"/]+\.jpe?g)"', fetch(url).decode())
        except urllib.error.HTTPError as error:
            if error.code != 404:
                print(f"  warning: package photographs for {code} unavailable: {error}")
            continue
        except (urllib.error.URLError, OSError) as error:
            print(f"  warning: package photographs for {code} unavailable: {error}")
            continue
        entries = []
        for name in sorted(names):
            preview = out_dir / f"{code}_{Path(name).stem}.webp"
            if not preview.exists():
                print(f"  fetching package photo preview {code}/{name}")
                out_dir.mkdir(parents=True, exist_ok=True)
                try:
                    image = Image.open(io.BytesIO(fetch(url + name))).convert("RGB")
                except (urllib.error.URLError, OSError) as error:
                    print(f"  warning: package photograph {url + name} unavailable: {error}")
                    continue
                image.thumbnail((PACKAGE_PREVIEW_PX, PACKAGE_PREVIEW_PX), Image.LANCZOS)
                image.save(preview, "WEBP", quality=82, method=6)
            entries.append({"url": url + name, "preview": f"photos/package/{preview.name}"})
        if entries:
            found[code] = entries
    return found
