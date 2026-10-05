"""Group the projects of a run into categories.

A project's category is decided, in order, by:

1. an explicit entry in the run configuration (``[categories]`` in
   ``runs/<run>.toml``), which always wins;
2. the first keyword rule in :data:`RULES` that matches the project's name or
   description;
3. what was measured in the layout, for projects whose description says
   nothing useful.
"""

import re

# (category, regex matched against "<name> <details>", case-insensitive).
# Order matters: the first match wins, so the specific rules come first and
# the broad ones ("risc-v", "soc") come last.
RULES = [
    ("Multi-project die", r"tiny ?tapeout|multi[- ]?project|multiple (users|projects)|\bprojects from\b"),
    ("Art and logos", r"\blogo\b|artwork|\bmeme\b"),
    ("FPGA", r"\bfpga\b|fabulous"),
    ("Security", r"crypt|cipher|tamper|unclonable|\bpuf\b|side[- ]channel"),
    ("Memory test chip", r"sram (test|blocks|macros|characteri)|\bsram test\b|efuse|test chip for the .*sram"),
    ("Analog and mixed-signal", r"\badc\b|\bdac\b|\bpll\b|\bdco\b|\btdc\b|analog|op-?amp|charge pump|floating[- ]gate"
                                r"|mosbius|chipathon|synth\b|eurosynth|bandgap"),
    ("Test structures", r"test structure|test passives|leakage|pad test|flip chip|characteri[sz]ation|peripherals"),
    ("Retro computing", r"\bz80\b|6502|\bsid\b|8-bit cpu|games? console|riscboy|ray ?cast|raybox|\bvga\b"),
    ("Accelerators", r"accelerator|\btpu\b|machine learning|\bml\b|neural|logic gate network|chess|cordic|path-tracing"
                     r"|ethernet"),
    ("RISC-V and CPUs", r"risc-?v|rv32|picosoc|serv\b|\bcpu\b|\bsoc\b|processor|\balu\b|transport triggered"),
]

FALLBACK_DIGITAL = "Other digital"
FALLBACK_CUSTOM = "Analog and mixed-signal"
FALLBACK_UNKNOWN = "Uncategorised"

# Order used when listing categories that have the same number of projects.
CATEGORY_ORDER = [category for category, _ in RULES] + [FALLBACK_DIGITAL, FALLBACK_UNKNOWN]


def classify(design, overrides=None) -> str:
    """Return the category name for a :class:`~ws_run_reports.stats.Design`.

    ``overrides`` maps project codes to categories and comes from the run configuration.
    """
    if overrides and design.code in overrides:
        return overrides[design.code]

    text = f"{design.project.name} {design.project.details}"
    for category, pattern in RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return category
    return classify_by_layout(design)


def classify_by_layout(design) -> str:
    """Category for a project whose description matched no keyword rule.

    TODO(mithro): this is the judgement call worth owning. The description
    told us nothing, so all we have is what is physically on the die:

      design.logic_cells          logic standard cells (0 for hand-drawn layouts)
      design.custom_transistors   transistors outside standard cells and SRAM macros
      design.transistors          all transistors
      design.sram_macros          SRAM macros
      design.utilisation          share of the core covered by logic cells (0..1)

    The default below calls a die "analog" when most of its transistors are
    hand-placed, and "digital" otherwise.
    """
    if design.transistors == 0:
        return FALLBACK_UNKNOWN
    if design.logic_cells == 0 or design.custom_transistors > 0.5 * design.transistors:
        return FALLBACK_CUSTOM
    return FALLBACK_DIGITAL
