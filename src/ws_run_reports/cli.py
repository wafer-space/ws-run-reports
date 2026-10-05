"""Command line entry point: ``ws-run-reports <command> <run>``."""

import argparse
from pathlib import Path

from . import config

OUTPUT_STEM = "reticle_analysis"


def out_dir(args, run) -> Path:
    return (args.out or Path("out")) / run.name


def cmd_assemble(args, run):
    print(run.assemble_layout())


def cmd_analyze(args, run):
    from . import analyze
    layout = run.assemble_layout()
    analyze.analyze(layout, out_dir(args, run) / f"{OUTPUT_STEM}.csv", jobs=args.jobs)


def cmd_report(args, run):
    from . import report
    path = report.write_report(run, out_dir(args, run))
    print(f"Wrote {path}")


def cmd_render(args, run):
    from . import render
    render.render_run(run, out_dir(args, run), jobs=args.jobs, only=args.only)


def cmd_site(args, run):
    from . import site
    path = site.build_site(run, out_dir(args, run))
    print(f"Wrote {path}")


def cmd_publish(args, run):
    from . import publish
    publish.publish(run, out_dir(args, run), args.target, push=args.push)


def cmd_all(args, run):
    for step in (cmd_analyze, cmd_report, cmd_render, cmd_site):
        step(args, run)


COMMANDS = {
    "assemble": (cmd_assemble, "join the split layout parts and verify the md5"),
    "analyze": (cmd_analyze, "measure the layout and write the analysis CSV files"),
    "report": (cmd_report, "write the Markdown density report from the CSV files"),
    "render": (cmd_render, "render images of the reticle and of every design"),
    "site": (cmd_site, "build the web page for the run"),
    "all": (cmd_all, "analyze, report, render and site in one go"),
    "publish": (cmd_publish, "commit the results to a branch of the run repository"),
}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ws-run-reports", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        p = sub.add_parser(name, help=help_text)
        p.add_argument("run", help=f"run name or path to a run .toml ({', '.join(config.available_runs())})")
        p.add_argument("--repo-dir", type=Path, help="checkout of the run repository (default: ../<run>)")
        p.add_argument("--out", type=Path, help="output directory (default: out/)")
        p.add_argument("--jobs", type=int, help="worker processes for the layout steps")
        p.add_argument("--only", nargs="+", metavar="CODE", help="render only these designs (for testing)")
        if name == "publish":
            p.add_argument("target", choices=["density-report", "gh-pages"])
            p.add_argument("--push", action="store_true", help="push the branch after committing")
    args = parser.parse_args(argv)
    run = config.load_run(args.run, args.repo_dir)
    COMMANDS[args.command][0](args, run)


if __name__ == "__main__":
    main()
