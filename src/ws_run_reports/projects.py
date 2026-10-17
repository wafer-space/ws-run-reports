"""Project details from outside the layout: the submission platform and the project repositories.

``ws-run-reports import <run> --platform FILE [--audit FILE] [--precheck DIR]`` reads

* an export from platform.wafer.space (one record per public project: name,
  description, declared licence, chip-on-board option and the latest
  finished precheck),
* optionally a licence audit of the projects' repositories (the licence
  files and SPDX headers found at a given commit), and
* optionally the platform's precheck results: ``acceptance-checks.json``
  (the check each design was accepted on, and its latest re-run), the steps
  of each of those checks parsed from its LibreLane run directory
  (``steps/<run>/<CODE>[.acceptance].json``) and its precheck log
  (``logs/<run>/<CODE>[.acceptance].precheck.log``),

and writes ``projects.json`` to the run's output directory, with the step
files and gzipped logs in ``precheck/`` beside it. Only fields that are
meant to be public are kept: no platform user data, no internal UUIDs or
storage paths.
"""

import gzip
import json
import re
import shutil
from pathlib import Path

from .config import https_url

PROJECTS_NAME = "projects.json"
PRECHECK_DIR = "precheck"

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


def _check_summary(row: dict, steps: dict | None, files: dict) -> dict:
    """One precheck run as the pages show it: when, why, the result, and each step's outcome.

    ``row`` is the check from ``acceptance-checks.json``; ``steps`` its parsed
    run directory, or None when the platform no longer has it.
    """
    summary = {"id": row["check_id"], "created_at": row["created_at"], "trigger": row["trigger"],
               "is_manufacturable": row["is_manufacturable"], "precheck_version": row["precheck_version"],
               "details": steps is not None, **files}
    if steps is not None:
        metrics = steps.get("final_metrics") or {}
        summary.update(
            flow_complete=steps["flow_complete"],
            pad_mask_check=steps["pad_mask_check"],
            klayout_drc_errors=metrics.get("klayout__drc_error__count"),
            magic_drc_errors=metrics.get("magic__drc_error__count"),
            steps=[[step["id"], step["result"]] for step in steps["steps"]],
        )
    return summary


def _write_log(source: Path, target: Path):
    """Gzip a precheck log, without a timestamp so that an unchanged log gives an unchanged file."""
    with open(source, "rb") as f, open(target, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        shutil.copyfileobj(f, gz)


def import_precheck(export: Path, run_name: str, out_dir: Path) -> dict:
    """Code -> {"accepted": ..., "latest": ...} from the platform's precheck export.

    Copies each check's step file and gzipped log into ``out_dir/precheck``.
    """
    export = Path(export)
    target = out_dir / PRECHECK_DIR
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    checks = {}
    for row in json.loads((export / "acceptance-checks.json").read_text()):
        if row["run"] != run_name or not row["latest"]:
            continue
        code, entry = row["code"], {}
        for role, suffix in (("latest", ""), ("accepted", ".acceptance")):
            check = row["latest" if role == "latest" else "acceptance"]
            if check is None:
                continue
            if role == "accepted" and check["same_as_latest"]:
                entry["accepted"] = dict(entry["latest"], same_as_latest=True)
                continue
            files, steps = {}, None
            if check["steps_file"]:
                steps = json.loads((export / check["steps_file"]).read_text())
                files["steps_file"] = f"{PRECHECK_DIR}/{code}{suffix}.json"
                shutil.copy(export / check["steps_file"], out_dir / files["steps_file"])
            if check["log_file"]:
                files["log_file"] = f"{PRECHECK_DIR}/{code}{suffix}.precheck.log.gz"
                _write_log(export / check["log_file"], out_dir / files["log_file"])
            entry[role] = _check_summary(check, steps, files)
        checks[code] = entry
    return checks


def build(platform: list, audit: list | None, run_name: str) -> dict:
    """Code -> public project details for one run."""
    audit_by_code = {a["code"]: a for a in (audit or []) if a.get("run") == run_name}
    projects = {}
    for record in sorted(platform, key=lambda r: r["code"]):
        if record.get("run", run_name) != run_name:
            continue
        repository = https_url(record.get("repository_url"))
        licence = {"declared": record.get("license") or "", "declared_raw": record.get("license_type_raw") or ""}
        entry = audit_by_code.get(record["code"])
        if entry is not None:
            files = sorted({f["spdx"] for f in (entry.get("license") or {}).get("files", []) if f.get("spdx")})
            headers = sorted(set((entry.get("license") or {}).get("spdx_headers") or []))
            # Each licence file found, so that the pages can link to it at the commit checked.
            paths = sorted(({"file": f["file"], "spdx": f.get("spdx") or ""}
                            for f in (entry.get("license") or {}).get("files", []) if f.get("file")),
                           key=lambda f: f["file"])
            licence.update(repo_files=files, repo_headers=headers, repo_licence_files=paths,
                           repo_commit=entry.get("head") or "",
                           repo_checked=https_url(entry.get("repo_url")) or repository,
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


def import_files(run, out_dir: Path, platform_file: Path, audit_file: Path | None = None,
                 precheck_dir: Path | None = None) -> Path:
    platform = json.loads(Path(platform_file).read_text())
    audit = json.loads(Path(audit_file).read_text()) if audit_file else None
    projects = build(platform, audit, run.name)
    if precheck_dir:
        checks = import_precheck(precheck_dir, run.name, out_dir)
        for code, entry in projects.items():
            entry["checks"] = checks.get(code, {})
            latest = entry["checks"].get("latest")
            if latest and entry["precheck"] and latest["id"] != str(entry["precheck"]["id"]):
                print(f"  warning: {code}: the platform export's latest check is {entry['precheck']['id']}, "
                      f"the precheck export's is {latest['id']}")
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
