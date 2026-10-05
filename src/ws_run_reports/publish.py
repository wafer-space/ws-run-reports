"""Commit generated results to a branch of the run repository.

Two targets:

``density-report``
    The run repository's ``main`` plus the analysis CSV files and the Markdown
    report in the top directory, as first published for ws-run1.

``gh-pages``
    The web page only. GitHub Pages serves it at ``https://wafer.space/<run>/``.

Both work in a scratch clone under the output directory, so the checkout the
layout was read from is never modified. Nothing is pushed unless asked.
"""

import shutil
import subprocess
from pathlib import Path

from . import report
from . import stats as stats_module

GENERATOR_URL = "https://github.com/wafer-space/ws-run-reports"


def git(*args, cwd, capture=False):
    print("  $ git", " ".join(str(a) for a in args))
    result = subprocess.run(["git", *args], cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def _remote_url(run) -> str:
    """URL to publish to: the run checkout's origin if it is the run repository, else GitHub over ssh.

    The checkout's origin is only trusted when the directory is the top of its
    own git repository and the URL names the run repository. A plain copy of
    the run's files kept inside another repository would otherwise report that
    other repository's remote.
    """
    default = f"git+ssh://github.com/{run.repo}.git"
    try:
        top = Path(git("rev-parse", "--show-toplevel", cwd=run.repo_dir, capture=True)).resolve()
        url = git("remote", "get-url", "origin", cwd=run.repo_dir, capture=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return default
    if top != run.repo_dir.resolve() or not _names_repo(url, run.repo):
        return default
    return url


def _names_repo(url: str, repo: str) -> bool:
    path = url.removesuffix("/").removesuffix(".git")
    return path.endswith("/" + repo) or path.endswith(":" + repo)


def _remote_has(url: str, branch: str) -> bool:
    out = subprocess.run(["git", "ls-remote", "--heads", url, branch], check=True, text=True, capture_output=True)
    return bool(out.stdout.strip())


def _generator_version() -> str:
    here = Path(__file__).resolve().parent
    try:
        return git("describe", "--tags", "--always", "--dirty", cwd=here, capture=True)
    except subprocess.CalledProcessError:
        return "unknown"


def _commit(clone: Path, message: str) -> bool:
    git("add", "-A", cwd=clone)
    if not git("status", "--porcelain", cwd=clone, capture=True):
        print("  nothing changed")
        return False
    git("commit", "-q", "-m", message, cwd=clone)
    return True


def publish_density_report(run, out_dir: Path, clone: Path, url: str):
    branch = "density-report"
    # Blobs are fetched on demand, which avoids downloading the layout history.
    git("clone", "-q", "--filter=blob:none", "--no-checkout", url, str(clone), cwd=out_dir)
    if _remote_has(url, branch):
        git("checkout", "-q", branch, cwd=clone)
        git("merge", "-q", "--no-edit", "-m", f"Merge main into {branch}", "origin/HEAD", cwd=clone)
    else:
        git("checkout", "-q", "-b", branch, "origin/HEAD", cwd=clone)

    files = sorted(out_dir.glob(f"{stats_module.OUTPUT_STEM}*.csv")) + [out_dir / report.REPORT_NAME]
    for path in files:
        shutil.copy(path, clone / path.name)
    return branch, (
        "Update standard cell and SRAM density report\n\n"
        f"Regenerated from {Path(run.layout['file']).name} (md5 {run.layout['md5']})\n"
        f"with {GENERATOR_URL} {_generator_version()}."
    )


def publish_pages(run, out_dir: Path, clone: Path, url: str):
    branch = "gh-pages"
    site = out_dir / "site"
    if not (site / "index.html").exists():
        raise FileNotFoundError(f"{site}/index.html not found; run 'ws-run-reports site {run.name}' first")
    if _remote_has(url, branch):
        git("clone", "-q", "--single-branch", "--branch", branch, url, str(clone), cwd=out_dir)
        for path in clone.iterdir():
            if path.name != ".git":
                shutil.rmtree(path) if path.is_dir() else path.unlink()
    else:
        clone.mkdir(parents=True)
        git("init", "-q", "-b", branch, cwd=clone)
        git("remote", "add", "origin", url, cwd=clone)
    shutil.copytree(site, clone, dirs_exist_ok=True)
    return branch, (
        f"Update the {run.name} web page\n\n"
        f"Generated with {GENERATOR_URL} {_generator_version()}."
    )


def publish(run, out_dir: Path, target: str, push: bool = False):
    out_dir = out_dir.resolve()
    clone = out_dir / "publish" / target
    if clone.exists():
        shutil.rmtree(clone)
    clone.parent.mkdir(parents=True, exist_ok=True)
    url = _remote_url(run)
    if not _names_repo(url, run.repo):
        raise ValueError(f"refusing to publish {run.name} to {url}: it is not {run.repo}")
    print(f"Preparing {target} for {run.repo} ({url}) in {clone}")
    builder = publish_density_report if target == "density-report" else publish_pages
    branch, message = builder(run, out_dir, clone, url)
    committed = _commit(clone, message)
    if not push:
        print(f"Committed locally in {clone}; re-run with --push to publish." if committed else "Nothing to publish.")
        return
    if committed:
        git("push", "origin", branch, cwd=clone)
        print(f"Pushed {branch} to {url}")
