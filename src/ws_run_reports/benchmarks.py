"""Theoretical maxima and what designs achieved, across every measured run: the data behind the density section
of the wafer.space technology page (the website's ``_data/density.yml``).

``ws-run-reports benchmarks --out out --output density.yml`` writes it from the analyses in ``out/``.

* **Maxima** are hard upper bounds: one kind of cell (inverter, NAND gate, buffer, flip-flop) tiled edge to edge
  at its placement boundary with no wiring. Each standard cell library has its own (its smallest cell of that kind,
  from the whole library: :meth:`stats.RunStats.reference_cell`); the process maximum is the best of them. SRAM
  macros have theirs in bits per mm² of the macro.
* **Achieved** figures are every measured design's: logic cells, logic cells per mm² of core (averaged, and in the
  densest window), the share of the core covered by logic, the library and supply, SRAM bits, and where the
  design's repository records them the flow's target density and clock period.
* They are summarised by slot type (each wafer.space slot size, each Tiny Tapeout tile size, a Google shuttle's
  Caravel user area) and per mm², with the best and a typical design of each picked out.
"""

import re
import statistics
import subprocess
from datetime import date
from pathlib import Path

import yaml

from . import config, external, projects, related, report
from . import stats as stats_module
from .stats import REFERENCE_CELLS, THIN_OXIDE, library_label, library_voltage

RUNS_ROOT = Path.home() / "github" / "wafer-space" / "runs"
# Flow settings read from each design's own configuration.
FLOW_KEYS = {"PL_TARGET_DENSITY_PCT": "target_density_pct", "PL_TARGET_DENSITY": "target_density",
             "CLOCK_PERIOD": "clock_period_ns"}


def _run_kind(run) -> str:
    if run.site.get("kind") == "tiny-tapeout":
        return "tiny-tapeout"
    return "google" if run.name.startswith("google-") else "wafer.space"


def _slot_type(run, design) -> tuple[str, str] | None:
    """(group, label) of a design's slot, e.g. ("wafer.space", "1 × ½ slot"), or None for a die's own blocks."""
    kind = _run_kind(run)
    if kind == "tiny-tapeout":
        if run.site.get("terms"):  # GF 0.1: the slots are the die's blocks, not projects
            return None
        tiles = design.project.slot_size
        return "Tiny Tapeout", f"{tiles.replace('x', ' × ')} tile{'' if tiles == '1x1' else 's'}"
    if kind == "google":
        return "Google shuttles", "Caravel user area"
    return "wafer.space", f"{design.slot_label} slot"


def _flow_settings_ws(run_name: str, code: str, commit: str) -> dict:
    """Target density and clock from a wafer.space design's LibreLane config at the commit that was checked."""
    repo = RUNS_ROOT / run_name / code / "repo"
    if not commit or not (repo / ".git").exists():
        return {}
    for path in ("librelane/config.yaml", "librelane/config.json", "openlane/config.json"):
        text = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"], capture_output=True, text=True)
        if text.returncode == 0:
            return _flow_values(text.stdout)
    return {}


def _flow_values(text: str) -> dict:
    """The FLOW_KEYS values of a LibreLane / OpenLane config (YAML or JSON, which YAML reads too)."""
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return {}
    found = {}
    for key, name in FLOW_KEYS.items():
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            found[name] = float(value)
    if "target_density" in found and "target_density_pct" not in found:
        found["target_density_pct"] = found.pop("target_density") * 100
    found.pop("target_density", None)
    return found


def _flow_settings_tt(repository: str, commit: str, cache: dict) -> dict:
    """Target density and clock from a Tiny Tapeout project's src/config.json (or .yaml) at its commit."""
    m = re.match(r"https://github\.com/([^/]+/[^/]+)", repository or "")
    if not m or not commit:
        return {}
    key = f"{m.group(1)}@{commit}"
    if key not in cache:
        cache[key] = {}
        for path in ("src/config.json", "src/config.yaml", "src/config_merged.json"):
            try:
                cache[key] = _flow_values(external.fetch(f"https://raw.githubusercontent.com/{m.group(1)}/{commit}/{path}",
                                                         timeout=30).decode())
                break
            except Exception:  # missing file or unreachable: try the next, else nothing is recorded
                continue
    return cache[key]


def _library_maxima(all_stats: list) -> dict:
    """Library -> {kind label -> {"cell", "per_mm2", "transistors_per_mm2"}} for every library on any run."""
    libraries = sorted({lib for s in all_stats for lib in s.libraries if not lib.startswith(THIN_OXIDE)})
    out = {}
    for lib in libraries:
        entries = {}
        for label, _, pattern in REFERENCE_CELLS:
            best = None
            for s in all_stats:
                cell = s.reference_cell(lib, pattern)
                if cell and (best is None or cell.area_um2 < best.area_um2):
                    best = cell
            if not best:
                continue
            # A transistor count is measured, so it comes from a run that used the cell.
            measured = [s.library.get((lib, best.cell_type)) for s in all_stats]
            transistors = next((c.transistors for c in measured if c and c.transistors), 0)
            entries[label] = {"cell": best.cell_type, "per_mm2": round(best.per_mm2),
                              "width_um": best.width_um, "height_um": best.height_um,
                              "transistors_per_mm2": round(transistors * best.per_mm2) if transistors else None}
        if entries:
            out[lib] = entries
    return out


def _sram_maxima(all_stats: list) -> list:
    """Every SRAM macro on any run, densest first: bits, size and bits per mm² of the macro."""
    macros = {}
    for s in all_stats:
        for name, macro in s.macros.items():
            if macro.bits:
                macros[name] = macro
    return sorted(({"macro": m.short_name, "name": name, "bits": m.bits, "width_um": m.width_um, "height_um": m.height_um,
                    "bits_per_mm2": round(m.bits / m.area_mm2)} for name, m in macros.items()),
                  key=lambda m: -m["bits_per_mm2"])


def _design_row(run, design, s, details: dict, tt_cache: dict) -> dict:
    group, slot = _slot_type(run, design)
    lib = design.primary_library
    kind = _run_kind(run)
    label = (f"Google {run.site.get('short_name', run.heading[0])}" if kind == "google" else run.heading[0] if kind == "tiny-tapeout"
             else related.run_label(run))
    row = {"run": label,
           "run_url": run.pages_url, "kind": _run_kind(run), "code": design.code, "name": design.name,
           "url": f"{run.pages_url}projects/{design.code}.html", "group": group, "slot": slot,
           # The website's slots.yml id of a wafer.space slot ("1x0p5"), to join the two.
           "slot_id": design.project.slot_size if kind == "wafer.space" else "",
           "core_mm2": round(design.core_area_mm2, 4), "core_source": design.core_source,
           "logic_cells": design.logic_cells, "core_density": round(design.core_density),
           # Over all the silicon inside the seal ring, pad ring included, where the run has one (wafer.space).
           "usable_mm2": round(design.usable_area_mm2, 4) if design.seal_ring_mm else None,
           "usable_density": round(design.usable_density) if design.seal_ring_mm else None,
           "peak_density": round(design.peak_cells) if design.peak_cells >= design.core_density else None,
           "utilisation": round(design.utilisation, 3), "library": library_label(lib) if lib else "",
           "volts": library_voltage(lib) if lib else None, "sram_bits": design.sram_bits,
           "transistors": design.transistors, "digital": design.logic_cells >= report.MINIMAL_LOGIC_CELLS}
    info = details.get(design.code) or {}
    if row["kind"] == "wafer.space":
        commit = (info.get("licence") or {}).get("repo_commit", "")
        row.update(_flow_settings_ws(run.name, design.code, commit))
    elif row["kind"] == "tiny-tapeout":
        row.update(_flow_settings_tt(design.project.repository, design.project.extra.get("COMMIT", ""), tt_cache))
    return row


def _summary(rows: list, best_key: str = "logic_cells") -> dict:
    """Best and typical of a group of designs: counts, medians and the designs behind them."""
    digital = [r for r in rows if r["digital"]]
    pool = digital or rows
    best = max(pool, key=lambda r: r[best_key])
    densest = max(pool, key=lambda r: r["core_density"])
    median_cells = statistics.median(r["logic_cells"] for r in pool)
    median_density = statistics.median(r["core_density"] for r in pool)
    typical = min(pool, key=lambda r: abs(r["core_density"] - median_density))
    peaks = [r for r in pool if r["peak_density"]]
    usable = [r["usable_density"] for r in pool if r.get("usable_density")]
    return {"designs": len(rows), "digital": len(digital),
            "core_mm2": round(statistics.median(r["core_mm2"] for r in rows), 4),
            "usable_mm2": round(statistics.median(u), 4) if (u := [r["usable_mm2"] for r in rows if r.get("usable_mm2")]) else None,
            "median_logic_cells": round(median_cells), "median_density": round(median_density),
            "median_usable_density": round(statistics.median(usable)) if usable else None,
            "best_usable_density": max(usable) if usable else None,
            "median_utilisation": round(statistics.median(r["utilisation"] for r in pool), 3),
            "most_cells": _pick(best), "densest": _pick(densest), "typical": _pick(typical),
            "densest_window": _pick(max(peaks, key=lambda r: r["peak_density"])) if peaks else None}


def _pick(row: dict) -> dict:
    keep = ("run", "code", "name", "url", "slot", "core_mm2", "usable_mm2", "logic_cells", "core_density",
            "usable_density", "peak_density",
            "utilisation", "library", "volts", "target_density_pct", "clock_period_ns", "sram_bits")
    return {k: row[k] for k in keep if k in row and row[k] is not None}


def build(out: Path) -> dict:
    tt_cache_path = out / "benchmarks_flow_cache.yml"
    tt_cache = yaml.safe_load(tt_cache_path.read_text()) if tt_cache_path.exists() else {}
    all_stats, rows, seen = [], [], set()
    for name in config.available_runs():
        run = config.load_run(name)
        run_out = out / name
        if not (run_out / f"{stats_module.OUTPUT_STEM}.csv").exists():
            continue
        s = stats_module.load(run, run_out)
        all_stats.append(s)
        details = projects.load(run_out)
        for design in s.designs:
            if not (_slot_type(run, design) and design.logic_cells):
                continue
            # One project made twice from the same commit counts once: GF 0.2's two editions, TTP2 and the
            # power-gated TTPG, hold the same 52 projects.
            same = (design.project.repository, design.project.extra.get("COMMIT"), design.project.top)
            if _run_kind(run) == "tiny-tapeout" and same[1]:
                if same in seen:
                    continue
                seen.add(same)
            rows.append(_design_row(run, design, s, details, tt_cache))
    tt_cache_path.write_text(yaml.safe_dump(tt_cache, sort_keys=True))

    library = _library_maxima(all_stats)
    process = {}
    for label, what, _ in REFERENCE_CELLS:
        candidates = [(lib, e[label]) for lib, e in library.items() if label in e]
        if candidates:
            lib, best = max(candidates, key=lambda c: c[1]["per_mm2"])
            process[label] = {"what": what, "library": library_label(lib), **best}
    transistor_best = max(((lib, label, e) for lib, entries in library.items() for label, e in entries.items()
                           if e["transistors_per_mm2"]), key=lambda t: t[2]["transistors_per_mm2"])
    sram = _sram_maxima(all_stats)

    slots = {}
    for row in rows:
        slots.setdefault((row["group"], row["slot"]), []).append(row)
    order = {"wafer.space": 0, "Tiny Tapeout": 1, "Google shuttles": 2}
    by_slot = []
    for (group, slot), group_rows in sorted(slots.items(), key=lambda kv: (order[kv[0][0]], -statistics.median(
            r["core_mm2"] for r in kv[1]))):
        summary = _summary(group_rows)
        core = summary["core_mm2"]
        summary.update(group=group, slot=slot, slot_id=group_rows[0]["slot_id"],
                       max_cells={label: round(core * p["per_mm2"]) for label, p in process.items()})
        by_slot.append(summary)

    digital = [r for r in rows if r["digital"]]
    per_mm2 = {"all": _summary(digital, "core_density"), "by_library": [],
               "by_group": [{"group": g, **_summary(g_rows, "core_density")} for g in order
                            if (g_rows := [r for r in digital if r["group"] == g])]}
    for lib in sorted({r["library"] for r in digital}):
        lib_rows = [r for r in digital if r["library"] == lib]
        if len(lib_rows) >= 3:
            per_mm2["by_library"].append({"library": lib, **_summary(lib_rows, "core_density")})
    top = sorted(digital, key=lambda r: -r["core_density"])[:5]
    top_windows = sorted((r for r in digital if r["peak_density"]), key=lambda r: -r["peak_density"])[:5]
    return {"generated": date.today().isoformat(),
            "source": "https://github.com/wafer-space/ws-run-reports",
            "maxima": {"process": process,
                       "process_transistors_per_mm2": {"value": transistor_best[2]["transistors_per_mm2"],
                                                       "cell": transistor_best[2]["cell"],
                                                       "library": library_label(transistor_best[0])},
                       "libraries": [{"library": library_label(lib), "name": lib, "cells": entries}
                                     for lib, entries in library.items()],
                       "sram": sram},
            "achieved": {"designs": len(rows), "runs": sorted({r["run"] for r in rows}),
                         "with_flow_settings": sum(1 for r in rows if "target_density_pct" in r),
                         "by_slot": by_slot, "per_mm2": per_mm2,
                         "densest": [_pick(r) for r in top], "densest_windows": [_pick(r) for r in top_windows],
                         # Every digital design, densest first, for a chart of where they all fall.
                         "digital": [{k: r[k] for k in ("group", "run", "code", "name", "url", "slot", "library",
                                                        "core_density", "usable_density", "peak_density")
                                      if r.get(k) is not None}
                                     for r in sorted(digital, key=lambda r: -r["core_density"])]}}


def write(out: Path, output: Path) -> Path:
    data = build(out)
    output.write_text("# Generated by ws-run-reports benchmarks: theoretical maxima and what designs achieved.\n"
                      "# Do not edit by hand; regenerate from the run analyses.\n"
                      + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120))
    return output
