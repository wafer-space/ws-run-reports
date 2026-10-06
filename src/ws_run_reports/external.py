"""Content the run pages pull in from elsewhere.

Each source is optional and configured per run in the ``[site]`` table of
``runs/<run>.toml``. A source that is missing or unreachable is reported and
skipped, so a new run can be published before any of this exists for it.
"""

import io
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "ws-run-reports (https://github.com/wafer-space/ws-run-reports)"
RUNS_YML_URL = "https://raw.githubusercontent.com/wafer-space/wafer-space.github.io/main/_data/runs.yml"
PHOTO_PREVIEW_PX = 1100


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


def timeline(run) -> list:
    """Milestones for this run from the wafer.space website's ``_data/runs.yml``."""
    key = run.site.get("runs_yml_key")
    if not key:
        return []

    def load():
        import yaml
        data = yaml.safe_load(fetch(run.site.get("runs_yml_url", RUNS_YML_URL)))
        entry = data["runs"][key]
        return [
            {"title": item["title"], "date": str(item["date"]), "display_date": item.get("display_date", ""),
             "description": item.get("description", ""), "status": item.get("status", "")}
            for item in entry.get("timeline", [])
        ]

    return _try("shuttle timeline", load, [])


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
