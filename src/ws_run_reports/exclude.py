"""Leave parts of each design out of the measurements.

A run can exclude whole groups of cells, for example the I/O pad ring or a
harness that every design on a shuttle shares, and keep measuring cells
below an excluded one. On a Caravel die the management SoC's standard cells
sit directly in ``caravel_core``, next to the user's ``user_project_wrapper``,
so the run excludes ``caravel_core`` and keeps ``user_project_wrapper``::

    [measure]
    exclude = ["pad_ring", "harness"]
    keep = ["user_project_wrapper"]
    core_cell = "user_project_wrapper"

    [measure.groups]
    harness = ["caravel_core", "caravel_power_routing", "chip_io"]

Patterns are shell globs on the cell name without KLayout's ``$<n>`` suffix.
They are also tried with a leading ``<CODE>_`` removed, so that the same
pattern matches in reticles that prefix every cell with its project code.
"""

import fnmatch
import re
from dataclasses import dataclass, field

import klayout.db as kdb

# Groups every run can name without defining them.
BUILTIN_GROUPS = {
    "pad_ring": ["gf180mcu_*_io__*"],
    "wafer_space_artwork": ["gf180mcu_ws_ip__*"],
}

CODE_PREFIX_RE = re.compile(r"^[A-Za-z0-9]{4}_")


def base_name(name: str) -> str:
    return name.split("$")[0]


def matches(name: str, patterns) -> bool:
    base = base_name(name)
    candidates = (base, CODE_PREFIX_RE.sub("", base))
    return any(fnmatch.fnmatchcase(c, p) for c in candidates for p in patterns)


@dataclass
class Selection:
    """Which cells the measurements skip, and which of their descendants they still count."""
    groups: dict = field(default_factory=dict)     # group name -> patterns, as applied
    keep: list = field(default_factory=list)
    core_cell: str = ""
    excluded: list = field(default_factory=list)   # cell indices
    kept: list = field(default_factory=list)

    @property
    def active(self) -> bool:
        return bool(self.excluded)

    def describe(self) -> dict:
        return {"exclude": self.groups, "keep": self.keep, "core_cell": self.core_cell}

    def iterator(self, layout, cell, layer, box=None):
        """A RecursiveShapeIterator over ``cell`` that honours the selection."""
        it = (kdb.RecursiveShapeIterator(layout, cell, layer, box) if box is not None
              else kdb.RecursiveShapeIterator(layout, cell, layer))
        if self.excluded:
            it.unselect_cells(self.excluded)
            it.select_cells(self.kept)
        return it

    def flat_counts(self, cell, leaf_key):
        """Flat placement counts of the leaf cells below ``cell``.

        ``leaf_key`` maps a cell index to the key it is counted under (and the
        walk stops there), or returns None to descend into the cell.
        """
        excluded, kept = set(self.excluded), set(self.kept)
        cache = {}

        def walk(c, included):
            ci = c.cell_index()
            if ci in excluded:
                included = False
            elif ci in kept:
                included = True
            if (ci, included) in cache:
                return cache[(ci, included)]
            counts = {}
            key = leaf_key(ci)
            if key is not None:
                if included:
                    counts[key] = 1
            else:
                for inst in c.each_inst():
                    n = inst.cell_inst.size()
                    for k, v in walk(inst.cell, included).items():
                        counts[k] = counts.get(k, 0) + v * n
            cache[(ci, included)] = counts
            return counts

        return walk(cell, True)


def selection_for(layout, measure: dict) -> Selection:
    """Resolve a run's ``[measure]`` table against the cells of a layout."""
    groups = {**BUILTIN_GROUPS, **measure.get("groups", {})}
    applied = {}
    for name in measure.get("exclude", []):
        if name not in groups:
            raise ValueError(f"[measure] exclude names unknown group {name!r}; known: {', '.join(sorted(groups))}")
        applied[name] = list(groups[name])
    patterns = [p for ps in applied.values() for p in ps]
    keep = list(measure.get("keep", []))
    selection = Selection(groups=applied, keep=keep, core_cell=measure.get("core_cell", ""))
    for cell in layout.each_cell():
        if patterns and matches(cell.name, patterns):
            selection.excluded.append(cell.cell_index())
        elif keep and matches(cell.name, keep):
            selection.kept.append(cell.cell_index())
    if patterns:
        print(f"  Excluding {len(selection.excluded)} cell definitions ({', '.join(applied)}), "
              f"keeping {len(selection.kept)} below them")
    return selection


def core_area_um2(layout, cell, pattern: str) -> float:
    """Total area of the placements of ``pattern`` cells below ``cell``, in um2."""
    targets = [c.cell_index() for c in layout.each_cell() if matches(c.name, [pattern])]
    if not targets:
        return 0.0
    it = kdb.RecursiveInstanceIterator(layout, cell)
    it.targets = targets
    area = 0.0
    for _ in it.each():
        box = it.inst_cell().bbox().transformed(it.trans() * it.inst_trans())
        area += box.width() * box.height() * layout.dbu * layout.dbu
    return area
