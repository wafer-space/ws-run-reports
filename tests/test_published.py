"""Building the pages from what is published, for CI (published.py)."""

import subprocess
from types import SimpleNamespace

import pytest

from ws_run_reports import config, published, stats


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def run(name, repo, path=""):
    return SimpleNamespace(name=name, repo=repo, path=path, short_title=name)


def test_preview_pages_are_not_indexed_and_say_what_they_are():
    page = "<!DOCTYPE html>\n<html>\n<head>\n  <title>Run 2</title>\n</head>\n<body>\n  <p>Run 2</p>\n</body>\n</html>"
    marked = published.mark_preview(page, "pull request #12 <b>")
    head, body = marked.split("<body>")
    assert published.ROBOTS_META in head
    assert body.lstrip().startswith('<div class="ci-preview-banner"')
    assert "pull request #12 &lt;b&gt;" in body
    assert body.count("ci-preview-banner") == 1


def test_a_page_already_kept_out_of_search_engines_gets_one_robots_tag():
    page = '<html><head>\n<meta name="robots" content="noindex">\n</head><body class="embed"></body></html>'
    marked = published.mark_preview(page, "a test")
    assert marked.count('name="robots"') == 1
    assert published.ROBOTS_META in marked
    assert '<body class="embed">\n<div class="ci-preview-banner"' in marked


def test_pages_patterns_name_each_runs_folder():
    runs = [run("ws-run1", "wafer-space/ws-run1")]
    assert published.pages_patterns(runs, full=True) == ["/renders/", "/photos/"]
    assert published.pages_patterns(runs, full=False) == ["/renders/renders.json", "/photos/"]
    shared = [run("t0p3", "wafer-space/tinytapeouts", "ttgf0p3/ws-run2-t0p3")]
    assert published.pages_patterns(shared, full=True) == ["/ttgf0p3/ws-run2-t0p3/renders/",
                                                           "/ttgf0p3/ws-run2-t0p3/photos/"]


def test_run_repositories_are_looked_for_where_the_environment_says(tmp_path, monkeypatch):
    monkeypatch.setenv(config.REPOS_ENV, str(tmp_path))
    assert config.load_run("ws-run2").repo_dir == (tmp_path / "ws-run2").resolve()
    tt = config.load_run("tinytapeouts-ttgf0p3-ws-run2-t0p3")
    assert tt.repo_dir == (tmp_path / "tinytapeouts" / "ttgf0p3" / "ws-run2-t0p3").resolve()
    monkeypatch.delenv(config.REPOS_ENV)
    assert config.load_run("ws-run2").repo_dir == (config.RUNS_DIR.parent.parent / "ws-run2").resolve()


def test_core_areas_are_published_with_the_data(tmp_path):
    for name in ("reticle_analysis.csv", "projects.json", "core_areas.json", "notes.txt"):
        (tmp_path / name).write_text("x")
    assert [p.name for p in stats.data_files(tmp_path)] == ["reticle_analysis.csv", "projects.json", "core_areas.json"]


def _remote(tmp_path, repo, branches):
    """A repository at ``tmp_path/remotes/<repo>`` with each branch holding the files {path: text}."""
    remote = tmp_path / "remotes" / repo
    remote.mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=remote)
    git("config", "user.email", "test@example.com", cwd=remote)
    git("config", "user.name", "Test", cwd=remote)
    git("config", "uploadpack.allowFilter", "true", cwd=remote)
    for branch, files in branches.items():
        git("checkout", "-q", "--orphan", branch, cwd=remote)
        git("rm", "-rqf", "--ignore-unmatch", ".", cwd=remote)
        for path, text in files.items():
            (remote / path).parent.mkdir(parents=True, exist_ok=True)
            (remote / path).write_text(text)
        git("add", "-A", cwd=remote)
        git("commit", "-qm", branch, cwd=remote)
    return remote


def test_fetch_lays_out_the_published_data_as_analyze_and_render_would(tmp_path):
    _remote(tmp_path, "wafer-space/ws-run9", {
        "density-report": {"data/manifest.csv": "CODE\n", "layout/G809-part-aa": "big", "reticle_analysis.csv": "a",
                           "reticle_analysis_meta.json": "{}", "projects.json": "{}", "core_areas.json": "{}",
                           "reticle_density_report.md": "# Report", "precheck/AB01.json": "{}"},
        "gh-pages": {"index.html": "old page", "renders/renders.json": "{}", "renders/AB01.webp": "image",
                     "photos/AB01.webp": "photo", "projects/AB01.html": "old"}})
    _remote(tmp_path, "wafer-space/shared", {
        "density-report": {"die/a/reticle_analysis.csv": "a", "die/a/layout/A-part-aa": "big", "die/b/README.md": "b"},
        "gh-pages": {"index.html": "index", "die/a/renders/renders.json": "{}", "die/a/renders/a.webp": "image"}})
    runs = [run("ws-run9", "wafer-space/ws-run9"), run("a", "wafer-space/shared", "die/a"),
            run("b", "wafer-space/shared", "die/b")]
    repos, out = tmp_path / "repos", tmp_path / "out"
    found, missing = published.fetch(runs, repos, out, full_pages={"wafer-space/ws-run9"},
                                     url=f"file://{tmp_path}/remotes/{{repo}}")
    assert [r.name for r in found] == ["a", "ws-run9"]
    assert [r.name for r in missing] == ["b"]

    # The run's own files are where config.load_run looks for them, without the layout.
    assert (repos / "ws-run9" / "data" / "manifest.csv").exists()
    assert not (repos / "ws-run9" / "layout").exists()
    assert not (repos / "shared" / "die" / "a" / "layout").exists()
    # The analysis where site reads it.
    assert sorted(p.name for p in (out / "ws-run9").iterdir()) == [
        "core_areas.json", "precheck", "projects.json", "reticle_analysis.csv", "reticle_analysis_meta.json",
        "reticle_density_report.md", "site"]
    assert (out / "ws-run9" / "precheck" / "AB01.json").exists()
    # The renders and photographs, but not the pages they are rebuilt into.
    site = out / "ws-run9" / "site"
    assert sorted(p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()) == [
        "photos/AB01.webp", "renders/AB01.webp", "renders/renders.json"]
    # Of a repository whose pages are not being built, only what another run's pages need.
    assert [p.name for p in (out / "a" / "site" / "renders").iterdir()] == ["renders.json"]


def test_preview_puts_each_run_where_wafer_space_serves_it(tmp_path):
    out = tmp_path / "out"
    for name in ("ws-run9", "a"):
        (out / name / "site" / "projects").mkdir(parents=True)
        (out / name / "site" / "index.html").write_text(f"<html><head></head><body>{name}</body></html>")
        (out / name / "site" / "projects" / "AB01.html").write_text("<html><head></head><body>AB01</body></html>")
    runs = [run("ws-run9", "wafer-space/ws-run9"), run("a", "wafer-space/shared", "die/a")]
    index = published.preview(runs, [], out, tmp_path / "preview", "a test")
    dest = tmp_path / "preview"
    assert (dest / "ws-run9" / "index.html").exists()
    assert (dest / "shared" / "die" / "a" / "projects" / "AB01.html").exists()
    assert (dest / "robots.txt").read_text() == "User-agent: *\nDisallow: /\n"
    for page in dest.rglob("*.html"):
        assert published.ROBOTS_META in page.read_text(), page
        assert page.read_text().count("ci-preview-banner") == 1, page
    text = index.read_text()
    assert 'href="shared/die/a/index.html"' in text and 'href="ws-run9/index.html"' in text
    # The built pages themselves are left as they are, for publishing.
    assert "ci-preview-banner" not in (out / "ws-run9" / "site" / "index.html").read_text()


def test_missing_core_areas_matter_only_where_densities_are_over_the_core(tmp_path):
    meta = tmp_path / "reticle_analysis_meta.json"
    meta.write_text('{"top_cell": "G802"}')            # a wafer.space run: the template's 442 µm pad ring
    assert published.needs_core_areas(tmp_path)
    meta.write_text('{"pad_ring_um": 0}')              # a Tiny Tapeout die: every project is all core
    assert not published.needs_core_areas(tmp_path)
    meta.write_text('{"top_cell": "G802"}')
    (tmp_path / "core_areas.json").write_text("{}")
    assert not published.needs_core_areas(tmp_path)


def test_deploy_publishes_the_built_pages_once(tmp_path, monkeypatch):
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "Test")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "test@example.com")
    remote = _remote(tmp_path, "wafer-space/ws-run9", {
        "gh-pages": {"index.html": "old", "renders/AB01.webp": "image", "gone.html": "removed page"}})
    git("checkout", "-q", "--detach", cwd=remote)   # so that its gh-pages can be pushed to
    checkout = tmp_path / "repos" / "ws-run9"
    subprocess.run(["git", "clone", "-q", f"file://{remote}", str(checkout)], check=True)
    site = tmp_path / "out" / "ws-run9" / "site"
    (site / "renders").mkdir(parents=True)
    (site / "index.html").write_text("new")
    (site / "renders" / "AB01.webp").write_text("image")
    target = SimpleNamespace(name="ws-run9", repo="wafer-space/ws-run9", path="", repo_dir=checkout)

    # Without pushing, a dry run: committed in the scratch clone only.
    assert published.deploy([target], [], tmp_path / "out", push=False) == ["ws-run9"]
    show = subprocess.run(["git", "show", "gh-pages:index.html"], cwd=remote, capture_output=True, text=True)
    assert show.stdout == "old"

    # gone.html is no longer built: its deletion is not pushed unless allowed.
    with pytest.raises(SystemExit, match="would delete 1 files"):
        published.deploy([target], [], tmp_path / "out", push=True)
    show = subprocess.run(["git", "show", "gh-pages:index.html"], cwd=remote, capture_output=True, text=True)
    assert show.stdout == "old"

    assert published.deploy([target], [], tmp_path / "out", push=True, allow_deletions=True) == ["ws-run9"]
    files =subprocess.run(["git", "ls-tree", "-r", "--name-only", "gh-pages"], cwd=remote, capture_output=True,
                           text=True).stdout.split()
    assert files == ["index.html", "renders/AB01.webp"]
    show = subprocess.run(["git", "show", "gh-pages:index.html"], cwd=remote, capture_output=True, text=True)
    assert show.stdout == "new"
    # Nothing changed since: nothing is committed or pushed.
    assert published.deploy([target], [], tmp_path / "out", push=True) == []


def test_pushing_needs_publish_built():

    from ws_run_reports import cli
    with pytest.raises(SystemExit):
        cli.main(["published", "--repos", "x", "--push"])


def test_deploy_script_refuses_to_push_without_a_token(tmp_path):
    script = config.RUNS_DIR.parent / "scripts" / "ci-deploy-pages"
    env = {"PATH": "/usr/bin:/bin", "WORK": str(tmp_path)}
    result = subprocess.run([str(script), "wafer-space/ws-run2", "--push"], env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert "RUN_PAGES_TOKEN is not set" in result.stderr
    assert not (tmp_path / "build.log").exists()
