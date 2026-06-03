"""Stage 1a office background renderer + validation.

BUILD-TIME TOOLING, not app runtime (like gen_props.py). Run manually:

    ./venv/Scripts/python.exe scripts/render_office.py

It parses example.tmx and composites the office background from the three
rixitic tilesets, then PROVES itself by diffing the render against the file
the app actually loads (example-transparent.png). Once this reproduces the
original with zero VISIBLE differences, tile edits in Stage 1b are trustworthy.

Outputs (to ~/Downloads):
  office-rebuild-check.png   our render of the unmodified map
  office-rebuild-diff.png    visible differences in magenta over dimmed original
  office-grid.png            3x render with a 16px grid + col/row labels

Tiled conventions implemented:
  - gid flip bits masked off (no flips are present in this map, but masking is
    defensive and free).
  - each tileset cropped at its OWN tile size (objects/architecture 16x16,
    elevator 32x48).
  - oversized tiles anchored BOTTOM-LEFT to their cell (the elevator 32x48).
"""
import os
import struct
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TILES = os.path.join(ROOT, "agent_central", "static", "assets", "tilesets",
                     "rixitic-sidescroller-office")
TMX = os.path.join(TILES, "example.tmx")
ORIGINAL = os.path.join(TILES, "example-transparent.png")
DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")
CHECK_PNG = os.path.join(DOWNLOADS, "office-rebuild-check.png")
DIFF_PNG = os.path.join(DOWNLOADS, "office-rebuild-diff.png")
GRID_PNG = os.path.join(DOWNLOADS, "office-grid.png")

# Tiled gid flip bits (top 3 bits) and the gid mask (low 29 bits).
FLIP_H = 0x80000000
FLIP_V = 0x40000000
FLIP_D = 0x20000000
GID_MASK = 0x1FFFFFFF


def _parse_tilesets(root):
    """Return [(firstgid, image, tile_w, tile_h, columns)] sorted by firstgid."""
    out = []
    for t in root.findall("tileset"):
        fg = int(t.get("firstgid"))
        tw = int(t.get("tilewidth"))
        th = int(t.get("tileheight"))
        cols = int(t.get("columns"))
        src = t.find("image").get("source")
        img = Image.open(os.path.join(TILES, src)).convert("RGBA")
        out.append((fg, img, tw, th, cols))
    out.sort(key=lambda r: r[0])
    return out


def _tileset_for(gid, tilesets):
    """Map a masked gid to (image, local_index, tile_w, tile_h, columns)."""
    chosen = None
    for fg, img, tw, th, cols in tilesets:
        if gid >= fg:
            chosen = (fg, img, tw, th, cols)
        else:
            break
    fg, img, tw, th, cols = chosen
    return img, gid - fg, tw, th, cols


def _crop_tile(img, local, tw, th, cols):
    col = local % cols
    row = local // cols
    return img.crop((col * tw, row * th, col * tw + tw, row * th + th))


def render_map(tmx_path=TMX):
    """Composite the office background; returns an RGBA image (656x320)."""
    root = ET.parse(tmx_path).getroot()
    mw = int(root.get("width"))
    mh = int(root.get("height"))
    gw = int(root.get("tilewidth"))
    gh = int(root.get("tileheight"))
    tilesets = _parse_tilesets(root)

    canvas = Image.new("RGBA", (mw * gw, mh * gh), (0, 0, 0, 0))

    for layer in root.findall("layer"):
        data = layer.find("data")
        vals = [int(x) for x in data.text.replace("\n", "").split(",")
                if x.strip() != ""]
        for idx, raw in enumerate(vals):
            if raw == 0:
                continue
            gid = raw & GID_MASK   # mask flip bits (none present, but defensive)
            img, local, tw, th, cols = _tileset_for(gid, tilesets)
            tile = _crop_tile(img, local, tw, th, cols)
            if raw & (FLIP_H | FLIP_V | FLIP_D):
                if raw & FLIP_D:
                    tile = tile.transpose(Image.TRANSPOSE)
                if raw & FLIP_H:
                    tile = tile.transpose(Image.FLIP_LEFT_RIGHT)
                if raw & FLIP_V:
                    tile = tile.transpose(Image.FLIP_TOP_BOTTOM)
            col = idx % mw
            row = idx // mw
            # Tiled tile-layer anchor: tile's BOTTOM-LEFT sits at the cell's
            # bottom-left. For grid-sized tiles this is the cell origin; for
            # oversized tiles (elevator 32x48) it shifts the top up by (th-gh).
            px = col * gw
            py = (row + 1) * gh - th
            canvas.alpha_composite(tile, (px, py))
    return canvas


# Published-art pipeline (reverse-engineered and proven in Stage 1a):
#   example.png            = layered render flattened over an OPAQUE WHITE canvas
#                            (the alpha-128 window glass reads light over white;
#                            the opaque-black void tile stays black).
#   example-transparent.png = example.png with pure-black (0,0,0) keyed to alpha 0
#                            (this is the file the app actually loads).
# Reproducing both steps makes the render match example-transparent.png exactly.
# This is the real publishing behavior, not a hardcoded nudge.
WHITE = (255, 255, 255, 255)


def publish(raw):
    """Flatten the transparent tile render over white, then key black -> alpha 0.

    The flatten uses integer FLOOR blending, not rounding: the original exporter
    truncated, so glass (120,153,165,a128) over white yields (187,203,209), not
    Pillow alpha_composite's rounded (187,204,210). Matching the floor blend is
    what makes the translucent window glass reproduce bit-for-bit.
    """
    out = Image.new("RGBA", raw.size, WHITE)
    src = raw.load()
    dst = out.load()
    w, h = raw.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = src[x, y]
            if a == 0:
                rr, gg, bb = 255, 255, 255          # over white
            elif a == 255:
                rr, gg, bb = r, g, b
            else:                                    # floor "over white" blend
                inv = 255 - a
                rr = (r * a + 255 * inv) // 255
                gg = (g * a + 255 * inv) // 255
                bb = (b * a + 255 * inv) // 255
            if (rr, gg, bb) == (0, 0, 0):
                dst[x, y] = (0, 0, 0, 0)             # black-key -> transparent
            else:
                dst[x, y] = (rr, gg, bb, 255)
    return out


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------
def _png_dims(path):
    with open(path, "rb") as f:
        head = f.read(26)
    return struct.unpack(">II", head[16:24])


def validate(render):
    original = Image.open(ORIGINAL).convert("RGBA")
    assert render.size == original.size, (render.size, original.size)
    w, h = render.size
    rp = render.load()
    op = original.load()

    strict_diffs = 0          # any RGBA channel differs
    visible_diffs = 0         # either side opaque, or alpha differs
    alpha0_rgb_only = 0       # both fully transparent but RGB differs (benign)
    minx = miny = 10 ** 9
    maxx = maxy = -1
    vis_mask = Image.new("1", (w, h), 0)
    vm = vis_mask.load()

    for y in range(h):
        for x in range(w):
            r = rp[x, y]
            o = op[x, y]
            if r == o:
                continue
            strict_diffs += 1
            ra, oa = r[3], o[3]
            if ra == 0 and oa == 0:
                alpha0_rgb_only += 1   # invisible: both transparent
                continue
            # visible: either pixel is (partly) opaque, or alpha differs
            visible_diffs += 1
            vm[x, y] = 1
            minx, miny = min(minx, x), min(miny, y)
            maxx, maxy = max(maxx, x), max(maxy, y)

    bbox = None if maxx < 0 else (minx, miny, maxx, maxy)
    return {
        "strict_diffs": strict_diffs,
        "visible_diffs": visible_diffs,
        "alpha0_rgb_only": alpha0_rgb_only,
        "bbox": bbox,
        "vis_mask": vis_mask,
        "original": original,
    }


def write_diff_image(res):
    original = res["original"].convert("RGBA")
    dimmed = Image.new("RGBA", original.size, (0, 0, 0, 255))
    dimmed = Image.blend(Image.new("RGBA", original.size, (20, 20, 26, 255)),
                         original, 0.35).convert("RGBA")
    px = dimmed.load()
    vm = res["vis_mask"].load()
    w, h = original.size
    for y in range(h):
        for x in range(w):
            if vm[x, y]:
                px[x, y] = (255, 0, 255, 255)
    dimmed.save(DIFF_PNG)


# ----------------------------------------------------------------------------
# Grid-annotated image
# ----------------------------------------------------------------------------
def write_grid_image(render, scale=3, cell=16, label_every=4):
    base = render.convert("RGBA").resize(
        (render.width * scale, render.height * scale), Image.NEAREST)
    margin_l, margin_t = 28, 18
    W = base.width + margin_l + 4
    H = base.height + margin_t + 4
    page = Image.new("RGBA", (W, H), (24, 26, 32, 255))
    page.alpha_composite(base, (margin_l, margin_t))
    d = ImageDraw.Draw(page)
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 11)
    except Exception:
        f = ImageFont.load_default()

    cols = render.width // cell
    rows = render.height // cell
    grid = (120, 200, 255)
    faint = (255, 255, 255, 40)
    overlay = Image.new("RGBA", page.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for c in range(cols + 1):
        x = margin_l + c * cell * scale
        major = (c % label_every == 0)
        od.line([(x, margin_t), (x, margin_t + base.height)],
                fill=(grid + (150,)) if major else faint, width=1)
        if major:
            d.text((x - 6, 3), str(c), fill=grid, font=f)
    for r in range(rows + 1):
        y = margin_t + r * cell * scale
        major = (r % label_every == 0)
        od.line([(margin_l, y), (margin_l + base.width, y)],
                fill=(grid + (150,)) if major else faint, width=1)
        if major:
            d.text((2, y - 6), str(r), fill=grid, font=f)
    page.alpha_composite(overlay)
    page.convert("RGB").save(GRID_PNG)


def main():
    print("original example-transparent.png dims:", "%dx%d" % _png_dims(ORIGINAL))
    raw = render_map()                 # faithful tile render (transparent surround)
    render = publish(raw)              # flatten over white + black-key (app's format)
    render.save(CHECK_PNG)
    print("render dims:", "%dx%d" % render.size, "-> wrote", CHECK_PNG)

    res = validate(render)
    print("\nVALIDATION")
    print("  strict RGBA-identical:", "YES" if res["strict_diffs"] == 0 else
          "NO (%d differing pixels)" % res["strict_diffs"])
    print("  visible differences:", res["visible_diffs"])
    print("  alpha-0 RGB-only (invisible) deltas:", res["alpha0_rgb_only"])
    if res["bbox"]:
        print("  visible-diff bbox (x0,y0,x1,y1):", res["bbox"])
    write_diff_image(res)
    print("  wrote", DIFF_PNG)

    write_grid_image(render)
    print("  wrote", GRID_PNG)

    pass_cond = res["visible_diffs"] == 0
    print("\nPASS" if pass_cond else "\nFAIL", "(judged on visible differences)")
    return pass_cond


if __name__ == "__main__":
    main()
