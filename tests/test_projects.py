"""Importing project details from the platform export and the licence audit."""

from ws_run_reports import projects


def record(code, **extra):
    base = {"run": "ws-run1", "code": code, "name": f"Project {code}", "description": "Line 1\r\nLine 2",
            "repository_url": f"https://example.com/{code} ", "license": "Apache-2.0", "license_type_raw": "apache",
            "slot_size": "1x1", "chip_on_board": False, "submitted_at": "2026-01-01T00:00:00+00:00",
            "project_uuid": "secret-uuid", "is_public": True, "_note": "internal",
            "check": {"id": "7", "created_at": "2026-08-02T01:24:16+00:00", "status": "finished",
                      "is_manufacturable": True, "precheck_version": "1.7.3", "docker_exit_code": 0,
                      "artefacts": {"log_file": "projects/secret-uuid/x.log",
                                    "sha256": {"log_file": "aa", "runs_archive": "bb"}}}}
    base.update(extra)
    return base


def audit(code, files=(), headers=(), head="abc123", status="cloned"):
    return {"run": "ws-run1", "code": code, "status": status, "head": head, "repo_url": f"https://example.com/{code}",
            "license": {"files": [{"file": "LICENSE", "spdx": f} for f in files], "spdx_headers": list(headers)}}


def test_build_keeps_public_fields_only():
    built = projects.build([record("AAAA")], [audit("AAAA", files=["Apache-2.0"])], "ws-run1")
    entry = built["AAAA"]
    text = repr(entry)
    assert "secret-uuid" not in text and "_note" not in text and "is_public" not in text
    assert entry["description"] == "Line 1\nLine 2"
    assert entry["repository"] == "https://example.com/AAAA"
    assert entry["precheck"]["precheck_version"] == "1.7.3"
    assert entry["precheck"]["artefact_sha256"] == {"log_file": "aa", "runs_archive": "bb"}
    assert entry["licence"]["status"] == "match"


def test_licence_status():
    assert projects.licence_status("GPL-3.0-only", ["GPL-3.0"], [], True) == "match"
    assert projects.licence_status("BSD-3-Clause", ["Apache-2.0"], [], True) == "mismatch"
    assert projects.licence_status("proprietary", ["Apache-2.0"], [], True) == "mismatch"
    assert projects.licence_status("Apache-2.0", [], ["Apache-2.0"], True) == "match"
    assert projects.licence_status("Apache-2.0", [], [], True) == "no licence file"
    assert projects.licence_status("Apache-2.0", [], [], False) == "no repository"


def test_missing_check_and_audit():
    built = projects.build([record("BBBB", check=None)], None, "ws-run1")
    assert built["BBBB"]["precheck"] is None
    assert "status" not in built["BBBB"]["licence"]


def test_minimal_run_config(tmp_path):
    """A run needs only a title, shuttle, slot count and layout checksum; the rest has defaults."""
    from ws_run_reports import config

    path = tmp_path / "example-run.toml"
    path.write_text('title = "Example"\nshuttle = "EX01"\nslots = 4\n[layout]\nmd5 = "0" \n')
    run = config.load_run(str(path), repo_dir=tmp_path)
    assert run.name == "example-run"
    assert run.repo == "wafer-space/example-run"
    assert run.layout == {"md5": "0", "parts": "layout/EX01-part-*", "file": "layout/EX01.oas"}
    assert run.manifest == {"csv": "data/manifest.csv"}
    assert run.process == "GF180MCU"
    assert run.heading == ["Example"] and run.short_title == "Example"


def test_every_run_config_loads():
    from ws_run_reports import config

    for name in config.available_runs():
        run = config.load_run(name)
        assert run.name == name


def test_stale_assembled_layout_is_rebuilt(tmp_path):
    import hashlib

    from ws_run_reports import config

    (tmp_path / "layout").mkdir()
    (tmp_path / "layout" / "EX01-part-aa").write_bytes(b"new ")
    (tmp_path / "layout" / "EX01-part-ab").write_bytes(b"layout")
    (tmp_path / "layout" / "EX01.oas").write_bytes(b"old layout")
    path = tmp_path / "ex.toml"
    path.write_text(f'title = "Ex"\nshuttle = "EX01"\nslots = 1\n[layout]\nmd5 = "{hashlib.md5(b"new layout").hexdigest()}"\n')
    run = config.load_run(str(path), repo_dir=tmp_path)
    assert run.assemble_layout().read_bytes() == b"new layout"


def test_import_precheck(tmp_path):
    import gzip
    import json

    export = tmp_path / "export"
    (export / "steps" / "ws-run1").mkdir(parents=True)
    (export / "logs" / "ws-run1").mkdir(parents=True)

    def check(cid, role, same=None, present=True):
        suffix = ".acceptance" if role == "acceptance" else ""
        return {"check_id": cid, "created_at": "2025-12-10T18:16:37+00:00", "trigger": "initial",
                "is_manufacturable": True, "precheck_version": "", "same_as_latest": same,
                "steps_file": f"steps/ws-run1/AB12{suffix}.json" if present else None,
                "log_file": f"logs/ws-run1/AB12{suffix}.precheck.log" if present else None}

    steps = {"flow_complete": True, "pad_mask_check": "passed",
             "final_metrics": {"klayout__drc_error__count": 0, "magic__drc_error__count": 14},
             "steps": [{"id": "KLayout.CheckPadMask", "result": "passed", "messages": []},
                       {"id": "Checker.MagicDRC", "result": "warning", "messages": ["14 Magic DRC errors found."]}]}
    (export / "steps" / "ws-run1" / "AB12.json").write_text(json.dumps(steps))
    (export / "logs" / "ws-run1" / "AB12.precheck.log").write_text("log text\n")
    rows = [
        {"run": "ws-run1", "code": "AB12", "latest": check("9", "latest"), "acceptance": check("3", "acceptance",
                                                                                                 False, present=False)},
        {"run": "ws-run1", "code": "CD34", "latest": None, "acceptance": None},
        {"run": "ws-run2", "code": "EF56", "latest": check("5", "latest"), "acceptance": None},
    ]
    (export / "acceptance-checks.json").write_text(json.dumps(rows))

    out = tmp_path / "out"
    checks = projects.import_precheck(export, "ws-run1", out)
    assert set(checks) == {"AB12"}
    latest, accepted = checks["AB12"]["latest"], checks["AB12"]["accepted"]
    assert latest["steps"] == [["KLayout.CheckPadMask", "passed"], ["Checker.MagicDRC", "warning"]]
    assert (latest["magic_drc_errors"], latest["klayout_drc_errors"], latest["pad_mask_check"]) == (14, 0, "passed")
    assert gzip.decompress((out / latest["log_file"]).read_bytes()) == b"log text\n"
    assert (out / latest["steps_file"]).exists()
    # The platform no longer has the acceptance check's run: its date and trigger only.
    assert accepted["id"] == "3" and accepted["details"] is False and "steps" not in accepted
    # Writing the log again gives the same bytes, so republishing changes nothing.
    first = (out / latest["log_file"]).read_bytes()
    projects.import_precheck(export, "ws-run1", out)
    assert (out / latest["log_file"]).read_bytes() == first
