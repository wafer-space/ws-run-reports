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
from PIL import Image, ImageChops, ImageEnhance, ImageOps

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


def render_scales(site: dict) -> dict:
    """Pixels per mm for the design renders, their thumbnails and the reticle overview.

    A run of small designs, such as the projects in a Tiny Tapeout die, sets
    ``[site.render] design_px_per_mm``, ``thumb_px_per_mm`` and
    ``reticle_px_per_mm``, and can cap a design render's and a thumbnail's
    long side with ``design_max_px`` and ``thumb_max_px``.
    """
    render = site.get("render", {})
    return {"design": float(render.get("design_px_per_mm", PX_PER_MM)),
            "thumb": float(render.get("thumb_px_per_mm", THUMB_PX_PER_MM)),
            "reticle": float(render.get("reticle_px_per_mm", RETICLE_PX_PER_MM)),
            "design_max_px": render.get("design_max_px"), "thumb_max_px": render.get("thumb_max_px")}


def _scale(box, px_per_mm, max_px):
    """px per mm for a box, reduced if its long side would exceed max_px."""
    long_mm = max(box.width(), box.height()) / 1000
    return min(px_per_mm, max_px / long_mm) if max_px and long_mm else px_per_mm


def _render_design(task):
    cell_index, code, out_dir = task
    layout = _STATE["layout"]
    view = _STATE["view"]
    scales = _STATE["scales"]
    cell = layout.cell(cell_index)
    view.active_cellview().cell = cell
    view.max_hier()
    box = cell.dbbox()
    px_per_mm = _scale(box, scales["design"], scales["design_max_px"])
    width = max(16, round(box.width() / 1000 * px_per_mm))
    height = max(16, round(box.height() / 1000 * px_per_mm))

    coverages = {key: _render_layer(view, key, box, width, height) for key in LAYERS}
    files = {}
    for style in STYLES:
        image = compose(coverages, style)
        name = f"{code}_{style}.webp"
        image.save(Path(out_dir) / name, "WEBP", quality=82, method=6)
        files[style] = name
        if style == "full":
            thumb_px = _scale(box, scales["thumb"], scales["thumb_max_px"])
            thumb = image.resize((max(8, round(box.width() / 1000 * thumb_px)),
                                  max(8, round(box.height() / 1000 * thumb_px))), Image.LANCZOS)
            thumb.save(Path(out_dir) / f"{code}_thumb.webp", "WEBP", quality=80, method=6)
            files["thumb"] = f"{code}_thumb.webp"
            reticle_tile = image.resize((max(8, round(box.width() / 1000 * scales["reticle"])),
                                         max(8, round(box.height() / 1000 * scales["reticle"]))), Image.LANCZOS)
            reticle_tile.save(Path(out_dir) / f".{code}_tile.png")
    info = {"width_px": width, "height_px": height, "width_mm": box.width() / 1000,
            "height_mm": box.height() / 1000, "files": files}
    if px_per_mm != PX_PER_MM:
        info["px_per_mm"] = px_per_mm
    return code, info


def render_run(run, out_dir: Path, jobs=None, only=None) -> Path:
    """Render every design of a run into ``out_dir/site/renders`` and write ``renders.json``."""
    renders_dir = out_dir / "site" / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    layout_path = run.assemble_layout()
    print(f"Loading {layout_path}...")
    layout = kdb.Layout()
    layout.read(str(layout_path))
    dbu = layout.dbu
    top_cell = max(layout.top_cells(), key=lambda c: c.bbox().area())
    slots = enumerate_slots(top_cell, run.slot_cells())
    reticle_box = top_cell.bbox()

    # Placements relative to the reticle's lower left corner, whatever the
    # reticle's size, origin or number of slots.
    unique = {}
    placements = []
    for cell_name, cell, trans in slots:
        code = extract_slot_id(cell_name)
        unique.setdefault(code, cell)
        bbox = cell.bbox().transformed(trans)
        placements.append({"code": code, "x_mm": (bbox.left - reticle_box.left) * dbu / 1000,
                           "y_mm": (bbox.bottom - reticle_box.bottom) * dbu / 1000,
                           "width_mm": bbox.width() * dbu / 1000, "height_mm": bbox.height() * dbu / 1000})

    scales = render_scales(run.site)
    _STATE.update(layout=layout, view=_make_view(layout), scales=scales)
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
    reticle_w_mm = reticle_box.width() * dbu / 1000
    reticle_h_mm = reticle_box.height() * dbu / 1000
    reticle_px_per_mm = scales["reticle"]
    reticle_px = (round(reticle_w_mm * reticle_px_per_mm), round(reticle_h_mm * reticle_px_per_mm))
    # A run can draw a small reticle in the top left of a larger frame
    # ([site] reticle_frame_mm), so that its dies appear at the same scale as
    # other runs' do. The rest of the frame is transparent.
    frame_w_mm, frame_h_mm = run.site.get("reticle_frame_mm", (reticle_w_mm, reticle_h_mm))
    frame_w_mm, frame_h_mm = max(frame_w_mm, reticle_w_mm), max(frame_h_mm, reticle_h_mm)
    if (frame_w_mm, frame_h_mm) == (reticle_w_mm, reticle_h_mm):
        overview = Image.new("RGB", reticle_px, (10, 12, 20))
    else:
        overview = Image.new("RGBA", (round(frame_w_mm * reticle_px_per_mm), round(frame_h_mm * reticle_px_per_mm)),
                             (0, 0, 0, 0))
        overview.paste(Image.new("RGBA", reticle_px, (10, 12, 20, 255)), (0, 0))
    if run.site.get("render", {}).get("reticle_background"):
        # The whole reticle, dimmed, under the designs: for a Tiny Tapeout die,
        # its pads, multiplexer, controller and fill around the projects.
        view = _STATE["view"]
        view.active_cellview().cell = top_cell
        view.max_hier()
        box = top_cell.dbbox()
        background = compose({key: _render_layer(view, key, box, *reticle_px) for key in LAYERS}, "full")
        overview.paste(ImageEnhance.Brightness(background).enhance(0.55), (0, 0))
    for p in placements:
        if p["code"] not in designs:
            continue
        tile = Image.open(renders_dir / f".{p['code']}_tile.png")
        x = round(p["x_mm"] * reticle_px_per_mm)
        y = reticle_px[1] - round((p["y_mm"] + p["height_mm"]) * reticle_px_per_mm)
        overview.paste(tile, (x, y))
    overview.save(renders_dir / "reticle.webp", "WEBP", quality=85, method=6)
    for code in designs:
        (renders_dir / f".{code}_tile.png").unlink()

    manifest = {
        "px_per_mm": PX_PER_MM if scales["design"] == PX_PER_MM else scales["design"],
        "reticle": {"file": "reticle.webp", "width_mm": reticle_w_mm, "height_mm": reticle_h_mm,
                    "frame_width_mm": frame_w_mm, "frame_height_mm": frame_h_mm,
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
