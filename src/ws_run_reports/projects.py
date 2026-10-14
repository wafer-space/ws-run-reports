"""Project details from outside the layout: the submission platform and the project repositories.

``ws-run-reports import <run> --platform FILE [--audit FILE]`` reads

* an export from platform.wafer.space (one record per public project: name,
  description, declared licence, chip-on-board option and the latest
  finished precheck), and
* optionally a licence audit of the projects' repositories (the licence
  files and SPDX headers found at a given commit),

and writes ``projects.json`` to the run's output directory. Only fields that
are meant to be public are kept: no platform user data, no internal UUIDs
or storage paths.
"""

import json
import re
from pathlib import Path

PROJECTS_NAME = "projects.json"

CHECK_FIELDS = ["id", "created_at", "status", "is_manufacturable", "docker_exit_code", "precheck_version",
                "docker_image", "docker_image_digest", "tool_versions", "trigger"]


def _spdx_base(spdx: str) -> str:
    """'GPL-3.0-only' and 'GPL-3.0-or-later' compare equal to a detected 'GPL-3.0'."""
    return re.sub(r"-(only|or-later)$", "", (spdx or "").strip())


def licence_status(declared: str, repo_files: list, repo_headers: list, has_repository: bool) -> str:
    """How the licence declared on the platform compares with what the repository contains.

    One of 'match', 'mismatch', 'no licence file' or 'no repository'.
    """
    if not has_repository:
        return "no repository"
    found = repo_files or repo_headers
    if not found:
        return "no licence file"
    return "match" if _spdx_base(declared) in {_spdx_base(f) for f in found} else "mismatch"


def _check(record: dict) -> dict | None:
    check = record.get("check")
    if not check:
        return None
    kept = {key: check[key] for key in CHECK_FIELDS if key in check}
    # Checksums identify the artefacts without revealing where the platform stores them.
    sha256 = (check.get("artefacts") or {}).get("sha256") or {}
    kept["artefact_sha256"] = {k: v for k, v in sha256.items() if k in ("log_file", "runs_archive", "output_gds")}
    return kept


def build(platform: list, audit: list | None, run_name: str) -> dict:
    """Code -> public project details for one run."""
    audit_by_code = {a["code"]: a for a in (audit or []) if a.get("run") == run_name}
    projects = {}
    for record in sorted(platform, key=lambda r: r["code"]):
        if record.get("run", run_name) != run_name:
            continue
        repository = (record.get("repository_url") or "").strip()
        licence = {"declared": record.get("license") or "", "declared_raw": record.get("license_type_raw") or ""}
        entry = audit_by_code.get(record["code"])
        if entry is not None:
            files = sorted({f["spdx"] for f in (entry.get("license") or {}).get("files", []) if f.get("spdx")})
            headers = sorted(set((entry.get("license") or {}).get("spdx_headers") or []))
            licence.update(repo_files=files, repo_headers=headers, repo_commit=entry.get("head") or "",
                           repo_checked=entry.get("repo_url") or repository,
                           status=licence_status(licence["declared"], files, headers,
                                                 bool(entry.get("head")) and entry.get("status") == "cloned"))
        projects[record["code"]] = {
            "name": record.get("name") or "",
            "description": (record.get("description") or "").replace("\r\n", "\n").strip(),
            "repository": repository,
            "slot_size": record.get("slot_size") or "",
            "licence": licence,
            "chip_on_board": bool(record.get("chip_on_board")),
            "submitted_at": record.get("submitted_at") or "",
            "precheck": _check(record),
        }
    return projects


def import_files(run, out_dir: Path, platform_file: Path, audit_file: Path | None = None) -> Path:
    platform = json.loads(Path(platform_file).read_text())
    audit = json.loads(Path(audit_file).read_text()) if audit_file else None
    projects = build(platform, audit, run.name)
    missing = sorted(set(run.projects()) - set(projects))
    if missing:
        print(f"  warning: no platform record for {', '.join(missing)}")
    path = out_dir / PROJECTS_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run": run.name, "projects": projects}, indent=1, sort_keys=True) + "\n")
    return path


def load(out_dir: Path) -> dict:
    """Code -> project details, or {} when nothing has been imported."""
    path = out_dir / PROJECTS_NAME
    return json.loads(path.read_text())["projects"] if path.exists() else {}
