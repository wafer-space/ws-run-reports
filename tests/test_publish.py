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
