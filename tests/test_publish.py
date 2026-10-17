"""The publish step must only ever target the run's own repository."""

import subprocess
from types import SimpleNamespace

from ws_run_reports import publish


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_names_repo():
    repo = "wafer-space/ws-run1"
    assert publish._names_repo("git+ssh://github.com/wafer-space/ws-run1.git", repo)
    assert publish._names_repo("https://github.com/wafer-space/ws-run1", repo)
    assert publish._names_repo("git@github.com:wafer-space/ws-run1.git", repo)
    assert not publish._names_repo("git+ssh://github.com/wafer-space/ws-run-reports.git", repo)
    assert not publish._names_repo("git+ssh://github.com/wafer-space/ws-run1-cob.git", repo)
    assert not publish._names_repo("git+ssh://github.com/someone/ws-run1.git", repo)


def test_checkout_origin_is_used_when_it_is_the_run_repo(tmp_path):
    git("init", "-q", cwd=tmp_path)
    git("remote", "add", "origin", "https://github.com/wafer-space/ws-run1.git", cwd=tmp_path)
    run = SimpleNamespace(repo="wafer-space/ws-run1", repo_dir=tmp_path)
    assert publish._remote_url(run) == "https://github.com/wafer-space/ws-run1.git"


def test_copy_inside_another_repository_does_not_inherit_its_remote(tmp_path):
    """A plain copy of the run's files inside another repository reports that repository's origin."""
    git("init", "-q", cwd=tmp_path)
    git("remote", "add", "origin", "git+ssh://github.com/wafer-space/ws-run-reports.git", cwd=tmp_path)
    copy = tmp_path / "tmp" / "ws-run1-main"
    copy.mkdir(parents=True)
    run = SimpleNamespace(repo="wafer-space/ws-run1", repo_dir=copy)
    assert publish._remote_url(run) == "git+ssh://github.com/wafer-space/ws-run1.git"


def test_checkout_of_a_different_repository_is_not_trusted(tmp_path):
    git("init", "-q", cwd=tmp_path)
    git("remote", "add", "origin", "git+ssh://github.com/wafer-space/ws-run2.git", cwd=tmp_path)
    run = SimpleNamespace(repo="wafer-space/ws-run1", repo_dir=tmp_path)
    assert publish._remote_url(run) == "git+ssh://github.com/wafer-space/ws-run1.git"


def test_run_in_a_shared_repository(tmp_path):
    """A run in a folder of a shared repository publishes into that folder and links to it."""
    import subprocess
    from types import SimpleNamespace

    from ws_run_reports import config

    checkout = tmp_path / "tinytapeouts"
    folder = checkout / "ttgf0p3" / "ws-run2-t0p3"
    folder.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin",
                    "https://github.com/wafer-space/tinytapeouts.git"], check=True)
    run = SimpleNamespace(name="x", repo="wafer-space/tinytapeouts", path="ttgf0p3/ws-run2-t0p3", repo_dir=folder)
    assert publish._remote_url(run) == "https://github.com/wafer-space/tinytapeouts.git"

    toml = tmp_path / "t.toml"
    toml.write_text('title = "T"\nshuttle = "T0P3"\nslots = 1\nrepo = "wafer-space/tinytapeouts"\n'
                    'path = "ttgf0p3/ws-run2-t0p3"\n[layout]\nmd5 = "x"\n')
    loaded = config.load_run(str(toml))
    assert loaded.pages_url == "https://wafer.space/tinytapeouts/ttgf0p3/ws-run2-t0p3/"
    assert loaded.source_url == "https://github.com/wafer-space/tinytapeouts/tree/main/ttgf0p3/ws-run2-t0p3"
    assert loaded.report_url.endswith("/blob/density-report/ttgf0p3/ws-run2-t0p3/reticle_density_report.md")
    assert loaded.repo_dir.parts[-3:] == ("tinytapeouts", "ttgf0p3", "ws-run2-t0p3")


def test_pages_in_a_shared_repository_keep_the_other_runs(tmp_path):
    import subprocess
    from types import SimpleNamespace

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "gh-pages", str(remote)], check=True)
    seed = tmp_path / "seed"
    (seed / "ttgf26a" / "ws-run2-t26a").mkdir(parents=True)
    (seed / "ttgf26a" / "ws-run2-t26a" / "index.html").write_text("other die")
    (seed / "ttgf0p3" / "ws-run2-t0p3").mkdir(parents=True)
    (seed / "ttgf0p3" / "ws-run2-t0p3" / "stale.html").write_text("old page")
    for cmd in (["init", "-q", "-b", "gh-pages"], ["add", "-A"],
                ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed"],
                ["push", "-q", str(remote), "gh-pages"]):
        subprocess.run(["git", *cmd], cwd=seed, check=True)

    out = tmp_path / "out"
    (out / "site").mkdir(parents=True)
    (out / "site" / "index.html").write_text("new page")
    run = SimpleNamespace(name="t0p3", repo="wafer-space/tinytapeouts", path="ttgf0p3/ws-run2-t0p3")
    clone = out / "publish" / "gh-pages"
    publish.publish_pages(run, out, clone, str(remote))
    assert (clone / "ttgf26a" / "ws-run2-t26a" / "index.html").read_text() == "other die"
    assert (clone / "ttgf0p3" / "ws-run2-t0p3" / "index.html").read_text() == "new page"
    assert not (clone / "ttgf0p3" / "ws-run2-t0p3" / "stale.html").exists()
    assert (clone / ".nojekyll").exists()
