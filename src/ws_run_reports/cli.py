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
    # [measure] stdcell_prefixes adds libraries a run renamed, e.g. Tiny Tapeout GF 0.1's thin-oxide copies.
    prefixes = analyze.DEFAULT_STDCELL_PREFIXES + tuple(run.measure.get("stdcell_prefixes", []))
    analyze.analyze(layout, out_dir(args, run) / f"{OUTPUT_STEM}.csv", stdcell_prefixes=prefixes, jobs=args.jobs,
                    qualified_libraries=run.measure.get("library_names", "qualified") != "short",
                    measure=run.measure, slot_cells=run.slot_cells())


def cmd_metal(args, run):
    from . import metal
    path = metal.measure_layout(run.assemble_layout(), out_dir(args, run) / "reticle_metal_coverage.csv", run.measure,
                                slot_cells=run.slot_cells(), jobs=args.jobs)
    print(f"Wrote {path}")


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


def cmd_import(args, run):
    from . import projects
    if not args.platform:
        raise SystemExit("import needs --platform FILE (an export from platform.wafer.space)")
    path = projects.import_files(run, out_dir(args, run), args.platform, args.audit, args.precheck)
    print(f"Wrote {path}")


def cmd_cores(args, run):
    from . import cores
    path = cores.write(run, out_dir(args, run))
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
    "metal": (cmd_metal, "measure each metal layer's coverage, with and without dummy fill (data only)"),
    "report": (cmd_report, "write the Markdown density report from the CSV files"),
    "render": (cmd_render, "render images of the reticle and of every design"),
    "site": (cmd_site, "build the web page for the run"),
    "all": (cmd_all, "analyze, report, render and site in one go"),
    "import": (cmd_import, "import project details from a platform export and a repository licence audit"),
    "cores": (cmd_cores, "read each design's core area from its repository's LibreLane config"),
    "publish": (cmd_publish, "commit the results to a branch of the run repository"),
}


def cmd_collection(args):
    from . import collection, publish
    out = args.out or Path("out")
    path = collection.build(args.name, out)
    print(f"Wrote {path}")
    if args.publish:
        publish.publish_collection(collection.load(args.name), path.parent, out / args.name, push=args.push)


def cmd_tt_manifest(args):
    from . import tinytapeout
    n = tinytapeout.write_manifest(args.index, args.tt_repo, args.output, args.release_tag)
    print(f"Wrote {args.output} ({n} projects)")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ws-run-reports", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    tt = sub.add_parser("tt-manifest", help="write a Tiny Tapeout die's manifest from its release's shuttle index")
    tt.add_argument("--index", type=Path, required=True, help="shuttle_index.json from the tapeout release")
    tt.add_argument("--tt-repo", type=Path, required=True,
                    help="checkout of the Tiny Tapeout shuttle repository (it must contain the release commit)")
    tt.add_argument("--output", type=Path, required=True, help="manifest CSV to write (data/manifest.csv)")
    tt.add_argument("--release-tag", default="", help="the tapeout release tag; also writes data/tt_shuttle.json "
                    "(submissions close and release date) beside the manifest")
    for name, (_, help_text) in COMMANDS.items():
        p = sub.add_parser(name, help=help_text)
        p.add_argument("run", help=f"run name or path to a run .toml ({', '.join(config.available_runs())})")
        p.add_argument("--repo-dir", type=Path, help="checkout of the run repository (default: ../<run>)")
        p.add_argument("--out", type=Path, help="output directory (default: out/)")
        p.add_argument("--jobs", type=int, help="worker processes for the layout steps")
        p.add_argument("--only", nargs="+", metavar="CODE", help="render only these designs (for testing)")
        if name == "import":
            p.add_argument("--platform", type=Path, help="platform export: JSON list of public project records")
            p.add_argument("--audit", type=Path, help="repository licence audit: JSON list with licence files per project")
            p.add_argument("--precheck", type=Path, help="platform precheck export: a directory with "
                           "acceptance-checks.json, steps/ and logs/")
        if name == "publish":
            p.add_argument("target", choices=["density-report", "gh-pages"])
            p.add_argument("--push", action="store_true", help="push the branch after committing")
    col = sub.add_parser("collection", help="build the index page of a repository shared by several runs")
    col.add_argument("name", help="runs/collections/<name>.toml")
    col.add_argument("--out", type=Path, help="output directory (default: out/)")
    col.add_argument("--publish", action="store_true", help="commit the page to the root of the repository's gh-pages")
    col.add_argument("--push", action="store_true", help="push the gh-pages branch after committing")
    bench = sub.add_parser("benchmarks", help="theoretical maxima and what every measured design achieved, as YAML "
                           "for the website's _data/density.yml")
    bench.add_argument("--out", type=Path, help="output directory holding the run analyses (default: out/)")
    bench.add_argument("--output", type=Path, required=True, help="YAML file to write")
    pub = sub.add_parser("published", help="build every run's pages again from its published data and renders, "
                         "without the layout (for CI)")
    pub.add_argument("--repos", type=Path, help="directory to clone the run repositories into")
    pub.add_argument("--repo", action="append", metavar="OWNER/NAME",
                     help="only the pages published from this repository (repeat for more; default all)")
    pub.add_argument("--out", type=Path, help="output directory (default: out/)")
    pub.add_argument("--preview", type=Path, help="also gather the pages here, as wafer.space serves them, "
                     "marked as a preview")
    pub.add_argument("--label", default="these pages", help="what the preview's banner says it is a preview of")
    pub.add_argument("--list-repos", action="store_true", help="print the repositories as a JSON list and stop")
    pub.add_argument("--publish-built", action="store_true", help="instead of building, commit the pages already "
                     "built in --out to each repository's gh-pages, in scratch clones, as publish and collection "
                     "--publish do")
    pub.add_argument("--push", action="store_true", help="with --publish-built, push the pages that changed")
    pub.add_argument("--allow-deletions", action="store_true", help="with --push, also push pages that delete "
                     "files from gh-pages (otherwise refused)")
    args = parser.parse_args(argv)
    if args.command == "published" and args.push and not args.publish_built:
        parser.error("--push needs --publish-built")
    if args.command == "published":
        from . import published
        return published.main(args)
    if args.command == "tt-manifest":
        return cmd_tt_manifest(args)
    if args.command == "collection":
        return cmd_collection(args)
    if args.command == "benchmarks":
        from . import benchmarks
        print(f"Wrote {benchmarks.write(args.out or Path('out'), args.output)}")
        return
    run = config.load_run(args.run, args.repo_dir)
    COMMANDS[args.command][0](args, run)


if __name__ == "__main__":
    main()
