"""Render images of every design on a reticle.

Each mask layer is drawn on its own as solid white on black, with
oversampling so that a pixel's brightness is the fraction of it the layer
covers. The layers are then tinted and combined with a screen blend, which
keeps dense areas readable where KLayout's stipple patterns turn to noise.

Every design is rendered at the same number of pixels per millimetre, so the
reticle overview is simply the design renders pasted at their positions.
"""

import io
import json
import multiprocessing
import os
from pathlib import Path

import klayout.db as kdb
import klayout.lay as lay
from PIL import Image, ImageChops, ImageOps

from .analyze import enumerate_slots, extract_slot_id

PX_PER_MM = 400          # design renders: 2.5 um per pixel
THUMB_PX_PER_MM = 60
RETICLE_PX_PER_MM = 100
OVERSAMPLING = 3

# GF180MCU mask layers as (name, GDS layers, RGB tint). Dummy fill (datatype 4)
# is part of the mask and is drawn with its layer.
LAYERS = {
    "nwell": ("Nwell", [(21, 0)], (40, 44, 70)),
    "comp": ("Diffusion", [(22, 0), (22, 4)], (60, 190, 90)),
    "poly": ("Polysilicon", [(30, 0), (30, 4)], (235, 70, 70)),
    "metal1": ("Metal 1", [(34, 0), (34, 4)], (60, 120, 255)),
    "metal2": ("Metal 2", [(36, 0), (36, 4)], (200, 80, 230)),
    "metal3": ("Metal 3", [(42, 0), (42, 4)], (50, 210, 220)),
    "metal4": ("Metal 4", [(46, 0), (46, 4)], (240, 200, 60)),
    "metal5": ("Metal 5", [(81, 0), (81, 4)], (245, 140, 50)),
    "metaltop": ("Top metal", [(53, 0), (53, 4)], (230, 230, 235)),
    "pad": ("Pad openings", [(37, 0)], (255, 255, 255)),
}

# Named views: which layers are blended together, bottom first.
STYLES = {
    "full": ("All layers", ["nwell", "comp", "poly", "metal1", "metal2", "metal3", "metal4", "metal5", "metaltop"]),
    "devices": ("Transistors", ["nwell", "comp", "poly"]),
    "routing": ("Signal routing", ["metal1", "metal2", "metal3"]),
    "power": ("Power and pads", ["metal4", "metal5", "metaltop", "pad"]),
}

# Opacity of each layer in the "full" view, where layers are stacked bottom to
# top as translucent films. The upper metals carry wide power straps and fill,
# so they are kept thin enough to see the logic underneath.
FULL_OPACITY = {"nwell": 0.9, "comp": 0.85, "poly": 0.85, "metal1": 0.6, "metal2": 0.5, "metal3": 0.42,
                "metal4": 0.32, "metal5": 0.26, "metaltop": 0.22}

_STATE = {}


def _make_view(layout):
    view = lay.LayoutView()
    view.show_layout(layout, False)
    view.set_config("background-color", "#000000")
    view.set_config("grid-visible", "false")
    view.set_config("text-visible", "false")
    view.set_config("guiding-shape-visible", "false")
    view.max_hier()
    return view


def _show_layers(view, gds_layers):
    """Replace the view's layer list with the given layers, drawn solid white."""
    view.clear_layers()
    for layer, datatype in gds_layers:
        props = lay.LayerProperties()
        props.source = f"{layer}/{datatype}@1"
        props.fill_color = props.frame_color = 0xFFFFFF
        props.dither_pattern = 0
        props.width = 0
        props.visible = True
        props.transparent = False
        view.insert_layer(view.end_layers(), props)


def _render_layer(view, key, box, width, height):
    _show_layers(view, LAYERS[key][1])
    pixels = view.get_pixels_with_options(width, height, 1, OVERSAMPLING, 1.0, box)
    return Image.open(io.BytesIO(pixels.to_png_data())).convert("L")


def _tint(coverage, colour):
    return ImageOps.colorize(coverage, (0, 0, 0), colour)


def compose(coverages, style):
    """Blend per-layer coverage images into one RGB image."""
    _, keys = STYLES[style]
    size = next(iter(coverages.values())).size
    image = Image.new("RGB", size)
    for key in keys:
        colour = LAYERS[key][2]
        if style == "full":
            opacity = FULL_OPACITY[key]
            mask = coverages[key].point(lambda v, o=opacity: int(v * o))
            image = Image.composite(Image.new("RGB", size, colour), image, mask)
        else:
            image = ImageChops.screen(image, _tint(coverages[key], colour))
    return image


def _render_design(task):
    cell_index, code, out_dir = task
    layout = _STATE["layout"]
    view = _STATE["view"]
    cell = layout.cell(cell_index)
    view.active_cellview().cell = cell
    view.max_hier()
    box = cell.dbbox()
    width = max(16, round(box.width() / 1000 * PX_PER_MM))
    height = max(16, round(box.height() / 1000 * PX_PER_MM))

    coverages = {key: _render_layer(view, key, box, width, height) for key in LAYERS}
    files = {}
    for style in STYLES:
        image = compose(coverages, style)
        name = f"{code}_{style}.webp"
        image.save(Path(out_dir) / name, "WEBP", quality=82, method=6)
        files[style] = name
        if style == "full":
            thumb = image.resize((max(8, round(box.width() / 1000 * THUMB_PX_PER_MM)),
                                  max(8, round(box.height() / 1000 * THUMB_PX_PER_MM))), Image.LANCZOS)
            thumb.save(Path(out_dir) / f"{code}_thumb.webp", "WEBP", quality=80, method=6)
            files["thumb"] = f"{code}_thumb.webp"
            reticle_tile = image.resize((max(8, round(box.width() / 1000 * RETICLE_PX_PER_MM)),
                                         max(8, round(box.height() / 1000 * RETICLE_PX_PER_MM))), Image.LANCZOS)
            reticle_tile.save(Path(out_dir) / f".{code}_tile.png")
    return code, {"width_px": width, "height_px": height, "width_mm": box.width() / 1000,
                  "height_mm": box.height() / 1000, "files": files}


def render_run(run, out_dir: Path, jobs=None, only=None) -> Path:
    """Render every design of a run into ``out_dir/site/renders`` and write ``renders.json``."""
    renders_dir = out_dir / "site" / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    layout_path = run.assemble_layout()
    print(f"Loading {layout_path}...")
    layout = kdb.Layout()
    layout.read(str(layout_path))
    dbu = layout.dbu
    top_cell = layout.top_cells()[0]
    slots = enumerate_slots(top_cell)

    unique = {}
    placements = []
    for cell_name, cell, trans in slots:
        code = extract_slot_id(cell_name)
        unique.setdefault(code, cell)
        bbox = cell.bbox()
        placements.append({"code": code, "x_mm": trans.disp.x * dbu / 1000, "y_mm": trans.disp.y * dbu / 1000,
                           "width_mm": bbox.width() * dbu / 1000, "height_mm": bbox.height() * dbu / 1000})

    _STATE.update(layout=layout, view=_make_view(layout))
    tasks = [(cell.cell_index(), code, str(renders_dir))
             for code, cell in sorted(unique.items(), key=lambda kv: -kv[1].bbox().area())
             if not only or code in only]
    jobs = max(1, min(jobs or min(4, os.cpu_count() or 1), len(tasks)))
    print(f"Rendering {len(tasks)} designs with {jobs} worker(s)...")
    designs = {}
    if jobs == 1:
        iterator = map(_render_design, tasks)
    else:
        pool = multiprocessing.get_context("fork").Pool(jobs)
        iterator = pool.imap_unordered(_render_design, tasks)
    for code, info in iterator:
        designs[code] = info
        print(f"  [{len(designs)}/{len(tasks)}] {code}: {info['width_px']} x {info['height_px']} px", flush=True)
    if jobs > 1:
        pool.close()
        pool.join()

    # Reticle overview: paste the design tiles at their placements. Layout y
    # runs upwards, image y runs downwards.
    reticle_box = top_cell.bbox()
    reticle_w_mm = reticle_box.width() * dbu / 1000
    reticle_h_mm = reticle_box.height() * dbu / 1000
    overview = Image.new("RGB", (round(reticle_w_mm * RETICLE_PX_PER_MM), round(reticle_h_mm * RETICLE_PX_PER_MM)),
                         (10, 12, 20))
    for p in placements:
        if p["code"] not in designs:
            continue
        tile = Image.open(renders_dir / f".{p['code']}_tile.png")
        x = round(p["x_mm"] * RETICLE_PX_PER_MM)
        y = overview.height - round((p["y_mm"] + p["height_mm"]) * RETICLE_PX_PER_MM)
        overview.paste(tile, (x, y))
    overview.save(renders_dir / "reticle.webp", "WEBP", quality=85, method=6)
    for code in designs:
        (renders_dir / f".{code}_tile.png").unlink()

    manifest = {
        "px_per_mm": PX_PER_MM,
        "reticle": {"file": "reticle.webp", "width_mm": reticle_w_mm, "height_mm": reticle_h_mm,
                    "width_px": overview.width, "height_px": overview.height},
        "styles": {key: label for key, (label, _) in STYLES.items()},
        "layers": {key: {"label": label, "colour": "#%02x%02x%02x" % colour}
                   for key, (label, _, colour) in LAYERS.items()},
        "placements": placements,
        "designs": {code: designs[code] for code in sorted(designs)},
    }
    path = renders_dir / "renders.json"
    path.write_text(json.dumps(manifest, indent=1))
    print(f"Wrote {path}")
    return path
