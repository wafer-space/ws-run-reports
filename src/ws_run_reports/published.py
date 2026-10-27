"""Build the run pages again from what is already published, without the layout (for CI).

``analyze`` and ``render`` read the whole reticle, which needs more memory and time than a CI runner has.
Everything else the pages are made from is published in each run repository:

* its ``density-report`` branch: the run's own files (manifest, README, reticle map, Tiny Tapeout index)
  with the analysis files and the density report beside them (``publish <run> density-report``);
* its ``gh-pages`` branch: the renders and the die photograph previews (``publish <run> gh-pages``).

:func:`fetch` clones just those, without the layout, and lays them out as ``analyze`` and ``render`` would
have, so that ``site`` and ``collection`` run as usual. :func:`preview` gathers the built pages as wafer.space
serves them, marked as a preview: not to be indexed, with a banner saying what they are.

The run repositories are cloned into one directory, which ``$WS_RUN_REPOS`` must name before any run is
loaded (``config.load_run`` looks for each run's files there).
"""

import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import collection as collection_module
from . import config, cores, projects, publish, report
from . import site as site_module
from . import stats as stats_module

DATA_BRANCH = "density-report"
PAGES_BRANCH = "gh-pages"
GITHUB_URL = "https://github.com/{repo}.git"
# The run's folders a site is rebuilt around: the renders, and die photograph previews kept so that they
# are not fetched (megabytes each) again.
PAGES_KEPT = ("renders", "photos")


def repo_name(repo: str) -> str:
    """``wafer-space/ws-run1`` -> ``ws-run1``: the folder its checkout and its pages are in."""
    return repo.split("/")[-1]


def load_runs(repos_root: Path) -> list:
    """Every configured run, its files looked for in ``repos_root``."""
    os.environ[config.REPOS_ENV] = str(Path(repos_root).resolve())
    return [config.load_run(name) for name in config.available_runs()]


def site_repos(runs) -> list:
    """The repositories the runs' pages are published from, in order."""
    return sorted({run.repo for run in runs})


def _folder(path: str, name: str) -> str:
    """A sparse checkout pattern for folder ``name`` of a run's folder ``path`` ("" for the top)."""
    return "/" + "/".join(part for part in (path, name) if part) + "/"


def _clone(url: str, branch: str, dest: Path, patterns: list) -> None:
    """A shallow clone of ``branch`` with only the files ``patterns`` (gitignore style) name."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Blobs are fetched on checkout, and only those the sparse patterns name.
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none", "--no-checkout",
                    "--branch", branch, url, str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "sparse-checkout", "set", "--no-cone", *patterns], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", branch], check=True)


def data_patterns() -> list:
    """Everything on the data branch but the layout, which only analyze and render read."""
    return ["/*", "!layout/", "!*.oas", "!*.gds"]


def pages_patterns(runs, full: bool) -> list:
    """The gh-pages files to keep for ``runs``: the renders and photographs, or with ``full`` false only
    the renders' index and the photographs, which another run's pages need to show one of its dies."""
    patterns = []
    for run in runs:
        if full:
            patterns += [_folder(run.path, name) for name in PAGES_KEPT]
        else:
            patterns += [_folder(run.path, "renders").rstrip("/") + "/renders.json", _folder(run.path, "photos")]
    return patterns


def copy_data(src: Path, out_dir: Path) -> None:
    """The published analysis of one run, from its folder ``src`` on the data branch, into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in stats_module.data_files(src) + [src / report.REPORT_NAME]:
        if path.exists():
            shutil.copy(path, out_dir / path.name)
    precheck = src / projects.PRECHECK_DIR
    if precheck.is_dir():
        if (out_dir / precheck.name).exists():
            shutil.rmtree(out_dir / precheck.name)
        shutil.copytree(precheck, out_dir / precheck.name)


def needs_core_areas(src: Path) -> bool:
    """Whether the run in ``src`` measures density over each design's core but has no published core areas.

    A run whose designs are all core (``pad_ring_um`` 0, the Tiny Tapeout dies) does not use them.
    """
    if (src / cores.FILE).exists():
        return False
    meta_path = src / f"{stats_module.OUTPUT_STEM}_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return float(meta.get("pad_ring_um", 1)) != 0


def copy_pages(src: Path, site_dir: Path) -> None:
    """A run's renders and photographs from its folder ``src`` on gh-pages into its site folder."""
    for name in PAGES_KEPT:
        if (src / name).is_dir():
            shutil.copytree(src / name, site_dir / name, dirs_exist_ok=True)


def fetch(runs, repos_root: Path, out_root: Path, full_pages=None, url: str = GITHUB_URL) -> tuple[list, list]:
    """Clone each run repository's published data into ``repos_root`` and copy it to ``out_root/<run>``.

    The renders and photographs of the runs in the repositories ``full_pages`` (all when None) are copied
    too; of the other runs only what their dies need on another run's pages. Returns the runs that have
    published data and those that have none yet.
    """
    found, missing = [], []
    for repo in site_repos(runs):
        members = [run for run in runs if run.repo == repo]
        name = repo_name(repo)
        print(f"Fetching {repo}: {DATA_BRANCH} and {PAGES_BRANCH}")
        data = Path(repos_root) / name
        _clone(url.format(repo=repo), DATA_BRANCH, data, data_patterns())
        full = full_pages is None or repo in full_pages
        pages = Path(repos_root) / f".{PAGES_BRANCH}" / name
        _clone(url.format(repo=repo), PAGES_BRANCH, pages, pages_patterns(members, full))
        for run in members:
            src = data / run.path
            if not (src / f"{stats_module.OUTPUT_STEM}.csv").exists():
                print(f"  {run.name}: nothing published on {DATA_BRANCH} yet, skipped")
                missing.append(run)
                continue
            copy_data(src, Path(out_root) / run.name)
            if needs_core_areas(src):
                # Indented "  warning:", as external.py prints its own, so that a log can be searched for both.
                print(f"  warning: {run.name}: no {cores.FILE} on {DATA_BRANCH} yet, so each design's core is "
                      f"the project template's; publish the density report again ('publish {run.name} "
                      f"{DATA_BRANCH} --push') to include it")
            copy_pages(pages / run.path, Path(out_root) / run.name / "site")
            found.append(run)
    return found, missing


def collections_for(repos) -> list:
    """The collections (index pages of shared repositories) published from ``repos``."""
    names = sorted(p.stem for p in collection_module.COLLECTIONS_DIR.glob("*.toml"))
    return [name for name in names if collection_module.load(name).repo in set(repos)]


def build(runs, collections, out_root: Path) -> None:
    """``site`` for every run and ``collection`` for every collection, as the commands do."""
    for run in runs:
        print(f"Building {run.name}")
        print(f"Wrote {site_module.build_site(run, Path(out_root) / run.name)}")
    for name in collections:
        print(f"Building the {name} index page")
        print(f"Wrote {collection_module.build(name, Path(out_root))}")


ROBOTS_META = '<meta name="robots" content="noindex, nofollow">'
ROBOTS_META_RE = re.compile(r'<meta name="robots" content="[^"]*">')
BANNER_STYLE = ("background:#fff3cd;color:#664d03;border-bottom:1px solid #e6c65c;padding:8px 16px;"
                "font:14px/1.4 system-ui,sans-serif;text-align:center;position:relative;z-index:2000")


def banner(label: str) -> str:
    return (f'<div class="ci-preview-banner" role="note" style="{BANNER_STYLE}"><strong>Preview</strong> of '
            f"{html.escape(label)}, built by CI from the published data. This is not the published page; "
            f'links to other runs open the live site at <a href="https://wafer.space/" style="color:inherit">'
            "wafer.space</a>.</div>")


def mark_preview(page: str, label: str) -> str:
    """A page marked as a preview: kept out of search engines, with a banner at the top of its body."""
    if ROBOTS_META_RE.search(page):
        page = ROBOTS_META_RE.sub(ROBOTS_META, page, count=1)
    else:
        page = re.sub(r"<head[^>]*>", lambda m: f"{m.group(0)}\n  {ROBOTS_META}", page, count=1)
    return re.sub(r"<body[^>]*>", lambda m: f"{m.group(0)}\n{banner(label)}", page, count=1)


def _index(entries: list, label: str) -> str:
    items = "\n".join(f'    <li><a href="{html.escape(href)}">{html.escape(title)}</a></li>' for title, href in entries)
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"utf-8\">\n"
            f"  <title>Preview of {html.escape(label)}</title>\n"
            "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n</head>\n"
            "<body style=\"font:16px/1.5 system-ui,sans-serif;margin:16px\">\n"
            f"  <h1>Preview of {html.escape(label)}</h1>\n  <ul>\n{items}\n  </ul>\n</body>\n</html>\n")


def preview(runs, collections, out_root: Path, dest: Path, label: str) -> Path:
    """Gather the built pages into ``dest`` as wafer.space serves them (``<repository>/<path>/``) and mark
    every page as a preview. Returns the index page listing them."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    entries = []
    for run in runs:
        target = dest / repo_name(run.repo) / run.path
        shutil.copytree(Path(out_root) / run.name / "site", target, dirs_exist_ok=True)
        entries.append((run.short_title, f"{target.relative_to(dest).as_posix()}/index.html"))
    for name in collections:
        info = collection_module.load(name)
        site_dir, target = Path(out_root) / name / "site", dest / repo_name(info.repo)
        target.mkdir(parents=True, exist_ok=True)
        # As publish_collection: the index page's own files; the folders belong to the runs.
        for path in site_dir.iterdir():
            if path.is_file():
                shutil.copy(path, target / path.name)
        if (site_dir / "images").is_dir():
            shutil.copytree(site_dir / "images", target / "images", dirs_exist_ok=True)
        entries.append((info.short_title, f"{repo_name(info.repo)}/index.html"))
    for page in dest.rglob("*.html"):
        page.write_text(mark_preview(page.read_text(encoding="utf-8"), label), encoding="utf-8")
    (dest / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    index = dest / "index.html"
    index.write_text(mark_preview(_index(sorted(entries, key=lambda e: e[1]), label), label), encoding="utf-8")
    return index


def _show(clone: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(clone), "show", "--format=", *args, "HEAD"],
                          check=True, capture_output=True, text=True).stdout


def deploy(runs, collections, out_root: Path, push: bool, allow_deletions: bool = False) -> list:
    """``publish <run> gh-pages`` for every run and ``collection --publish`` for every collection, from the
    pages built in ``out_root``, each committed in a scratch clone and, with ``push``, pushed before the next
    is cloned (the runs of a shared repository publish to one branch). A commit that deletes a file on
    gh-pages is not pushed unless ``allow_deletions``. Returns the names of those whose pages changed."""
    targets = [(run.name, lambda out_dir, run=run: publish.publish(run, out_dir, PAGES_BRANCH)) for run in runs]
    targets += [(name, lambda out_dir, name=name: publish.publish_collection(
        collection_module.load(name), out_dir / "site", out_dir)) for name in collections]
    changed = []
    for name, commit in targets:
        out_dir = Path(out_root) / name
        if not commit(out_dir):
            continue
        changed.append(name)
        clone = out_dir.resolve() / "publish" / PAGES_BRANCH
        deleted = _show(clone, "--diff-filter=D", "--name-only").split()
        print(f"  {name}: {_show(clone, '--shortstat').strip()}" + "".join(f"\n    deletes {p}" for p in deleted))
        if not push:
            continue
        if deleted and not allow_deletions:
            raise SystemExit(f"not pushing {name}: its pages would delete {len(deleted)} files from {PAGES_BRANCH} "
                             "(above); check them, then deploy again allowing deletions")
        publish.git("push", "origin", PAGES_BRANCH, cwd=clone)
        print(f"Pushed {name}")
    return changed


def main(args) -> None:
    """``ws-run-reports published``: fetch, build and optionally gather a preview; or publish what was built."""
    if args.list_repos:
        # For a CI matrix: one job per repository.
        print(json.dumps(site_repos(config.load_run(name) for name in config.available_runs())))
        return
    if not args.repos:
        raise SystemExit("published needs --repos DIR, the directory to clone the run repositories into")
    runs = load_runs(args.repos)
    known = set(site_repos(runs))
    unknown = sorted(set(args.repo or []) - known)
    if unknown:
        raise SystemExit(f"no run is published from {', '.join(unknown)}; the repositories are {', '.join(sorted(known))}")
    selected = set(args.repo) if args.repo else known
    out_root = args.out or Path("out")
    if args.publish_built:
        # A step of its own, so that the build's output can be checked before anything is published.
        built = [run for run in runs if run.repo in selected and (out_root / run.name / "site" / "index.html").exists()]
        if not built:
            raise SystemExit(f"no pages have been built in {out_root} for {', '.join(sorted(selected))}")
        collections = [name for name in collections_for(selected) if (out_root / name / "site" / "index.html").exists()]
        changed = deploy(built, collections, out_root, push=args.push, allow_deletions=args.allow_deletions)
        verb = "Pushed" if args.push else "Committed, not pushed:"
        print(f"{verb} {', '.join(changed)}" if changed else "No page changed; nothing to publish.")
        return
    found, missing = fetch(runs, args.repos, out_root, full_pages=selected)
    chosen = [run for run in found if run.repo in selected]
    if not chosen:
        raise SystemExit(f"nothing is published yet for any run of {', '.join(sorted(selected))}")
    collections = collections_for(selected)
    build(chosen, collections, out_root)
    print(f"Built {len(chosen)} runs: {', '.join(run.name for run in chosen)}")
    skipped = [run.name for run in missing if run.repo in selected]
    if skipped:
        print(f"Not built, as nothing is published for them yet: {', '.join(skipped)}")
    if args.preview:
        print(f"Wrote {preview(chosen, collections, out_root, args.preview, args.label)}")
