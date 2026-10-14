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
