"""Stage 0 prop generator for the Agent Central office redesign.

BUILD-TIME ASSET GENERATOR, not app runtime. Run manually:

    ./venv/Scripts/python.exe scripts/gen_props.py

Its PNG outputs (under agent_central/static/assets/props/) are the committed
artifacts; this script is the recipe that produced them. It draws two sprites:

  1. nameplate plaque (60x14), recolored once per agent by that agent's tint
  2. reception counter front (64x24), drawn once (Secretary's desk)

Palette rule: SAMPLED, never hand-typed. Tile colors are sampled from the
rixitic tilesets; the label navy and the three agent tints are read out of
index.html. Deal Hunter has no tint, so per the locked decision its plaque
accent is the sampled mid-grey wall (architecture id 5): structurally like the
others but reading neutral, since Deal Hunter is the dimmed/retired agent.

Also renders a review sheet to Downloads (props-review.png) for approval. No
antialiasing anywhere: hard pixels only, scaled with NEAREST.
"""
import os
import re
import struct
from collections import Counter

from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TILES = os.path.join(ROOT, "agent_central", "static", "assets", "tilesets",
                     "rixitic-sidescroller-office")
OBJECTS_PNG = os.path.join(TILES, "tileset_objects.png")
ARCH_PNG = os.path.join(TILES, "tileset_architecture.png")
INDEX_HTML = os.path.join(ROOT, "agent_central", "static", "index.html")
PROPS_DIR = os.path.join(ROOT, "agent_central", "static", "assets", "props")
DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")
REVIEW_PNG = os.path.join(DOWNLOADS, "props-review.png")

# Sprite target dimensions (native 1x; the office renders at 1.5x zoom).
PLAQUE_W, PLAQUE_H = 60, 22
COUNTER_W, COUNTER_H = 64, 24

# Contrast threshold (luminance) below which the counter lip is too close to
# the body to read as distinct, triggering the lighten-20% fallback.
LIP_CONTRAST_MIN = 18.0

# ----------------------------------------------------------------------------
# Color helpers (no hand-typed palette; only transforms of sampled values)
# ----------------------------------------------------------------------------
def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]

def darken(c, pct):
    return tuple(int(round(v * (1.0 - pct))) for v in c[:3])

def lighten(c, pct):
    return tuple(int(round(v + (255 - v) * pct)) for v in c[:3])

def hexstr(c):
    return "#%02x%02x%02x" % (c[0], c[1], c[2])

def opaque_pixels(img, rect):
    x, y, w, h = rect
    crop = img.crop((x, y, x + w, y + h)).convert("RGBA")
    return [(r, g, b) for (r, g, b, a) in crop.getdata() if a > 0], crop

def mode_color(pixels):
    return Counter(pixels).most_common(1)[0][0]

def darkest_dominant(pixels):
    """Dominant color among the darkest quartile (an outline/trim color)."""
    ordered = sorted(pixels, key=lum)
    q = max(1, len(ordered) // 4)
    return mode_color(ordered[:q])

def midband_dominant(pixels, lightest, outline_max_lum=20.0):
    """Most common desk color that is neither the near-black outline nor the
    lightest (lip) tone. Stays sample-driven: returns an actual tile color.

    A desk tile is outline-dominated (black legs/edges) with a light top, so
    the raw median lands on black; the true body is the dominant remaining
    mid-tone. We drop near-black pixels and the exact lightest color, then take
    the mode of what is left.
    """
    body_px = [p for p in pixels if lum(p) > outline_max_lum and p != lightest]
    if not body_px:  # degenerate tile; fall back to overall median
        ordered = sorted(pixels, key=lum)
        return ordered[len(ordered) // 2]
    return mode_color(body_px)

# ----------------------------------------------------------------------------
# Read hexes from index.html
# ----------------------------------------------------------------------------
def read_index_hexes():
    with open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()
    def hex6(pat):
        m = re.search(pat, html)
        if not m:
            raise SystemExit("could not find pattern in index.html: " + pat)
        return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    label_bg = hex6(r"backgroundColor:\s*'#([0-9a-fA-F]{6})'")
    label_fg = hex6(r"color:\s*'#([0-9a-fA-F]{6})'")
    secretary = hex6(r"SECRETARY_TINT\s*=\s*0x([0-9a-fA-F]{6})")
    job_scout = hex6(r"JOB_SCOUT_TINT\s*=\s*0x([0-9a-fA-F]{6})")
    job_analyst = hex6(r"JOB_ANALYST_TINT\s*=\s*0x([0-9a-fA-F]{6})")
    return label_bg, label_fg, secretary, job_scout, job_analyst

# ----------------------------------------------------------------------------
# Palette extraction
# ----------------------------------------------------------------------------
def build_palette():
    objects = Image.open(OBJECTS_PNG).convert("RGBA")
    arch = Image.open(ARCH_PNG).convert("RGBA")

    # Source rects (verified in the pre-code report).
    rect_desk_a = (48, 96, 16, 16)   # objects id 87
    rect_desk_b = (64, 96, 16, 16)   # objects id 88
    rect_frame = (128, 0, 16, 16)    # objects id 8  (dark outline)
    rect_wall_light = (0, 0, 16, 16)  # arch id 0
    rect_wall_mid = (80, 0, 16, 16)   # arch id 5

    desk_a, crop_desk = opaque_pixels(objects, rect_desk_a)
    desk_b, _ = opaque_pixels(objects, rect_desk_b)
    desk = desk_a + desk_b
    desk_sorted = sorted(desk, key=lum)
    counter_lip = desk_sorted[-1]                        # lightest
    # Body = dominant mid-band desk tone (outline-black and lip excluded), so
    # an outline-dominated tile does not yield a black body.
    counter_body = midband_dominant(desk, counter_lip)

    lip_fallback = abs(lum(counter_lip) - lum(counter_body)) < LIP_CONTRAST_MIN
    if lip_fallback:
        counter_lip = lighten(counter_body, 0.20)

    frame_px, crop_frame = opaque_pixels(objects, rect_frame)
    counter_dark = darkest_dominant(frame_px)

    wall_light_px, crop_wall_light = opaque_pixels(arch, rect_wall_light)
    wall_mid_px, crop_wall_mid = opaque_pixels(arch, rect_wall_mid)
    wall_bg = mode_color(wall_light_px)
    accent_deal_hunter = mode_color(wall_mid_px)

    label_bg, label_fg, secretary, job_scout, job_analyst = read_index_hexes()

    pal = {
        "PLAQUE_BASE": label_bg,
        "PLAQUE_BORDER": darken(label_bg, 0.35),
        "PLAQUE_HILITE": lighten(label_bg, 0.25),
        "ACCENT_secretary": secretary,
        "ACCENT_job_scout": job_scout,
        "ACCENT_job_analyst": job_analyst,
        "ACCENT_deal_hunter": accent_deal_hunter,
        "COUNTER_BODY": counter_body,
        "COUNTER_LIP": counter_lip,
        "COUNTER_DARK": counter_dark,
        "WALL_BG": wall_bg,
        "LABEL_FG": label_fg,
    }
    # Source-tile crops for the sampled (tile-derived) entries, for the
    # review sheet's sample chain.
    crops = {
        "COUNTER_BODY": crop_desk,
        "COUNTER_LIP": crop_desk,
        "COUNTER_DARK": crop_frame,
        "ACCENT_deal_hunter": crop_wall_mid,
        "WALL_BG": crop_wall_light,
    }
    meta = {"lip_fallback": lip_fallback,
            "lip_body_lum_gap": abs(lum(desk_sorted[-1]) - lum(counter_body))}
    return pal, crops, meta

# ----------------------------------------------------------------------------
# Draw sprites
# ----------------------------------------------------------------------------
def draw_plaque(pal, accent):
    img = Image.new("RGBA", (PLAQUE_W, PLAQUE_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    base = pal["PLAQUE_BASE"]
    border = pal["PLAQUE_BORDER"]
    hil = pal["PLAQUE_HILITE"]
    # base fill
    d.rectangle([0, 0, PLAQUE_W - 1, PLAQUE_H - 1], fill=base + (255,))
    # 1px border
    d.rectangle([0, 0, PLAQUE_W - 1, PLAQUE_H - 1], outline=border + (255,))
    # 1px top highlight line (inner)
    d.line([(1, 1), (PLAQUE_W - 2, 1)], fill=hil + (255,))
    # 4px accent strip along bottom inner edge (thicker so it registers at 1.5x)
    d.rectangle([1, PLAQUE_H - 5, PLAQUE_W - 2, PLAQUE_H - 2], fill=accent + (255,))
    # two corner "screw" dots in highlight color
    d.point([(2, 2), (PLAQUE_W - 3, 2)], fill=hil + (255,))
    # rows 2..PLAQUE_H-6 are a clear central band for the Phaser text (Stage 2).
    return img

def draw_counter(pal):
    """Reception counter: countertop lip, purple Secretary trim band, solid body
    with thin panel seams, recessed kick base. Not a hollow glass case."""
    W, H = COUNTER_W, COUNTER_H
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    body = pal["COUNTER_BODY"]
    lip = pal["COUNTER_LIP"]
    dark = pal["COUNTER_DARK"]
    purple = pal["ACCENT_secretary"]          # trim ties the counter to Secretary
    underside = darken(lip, 0.25)             # front edge / underside of the overhang
    kick = darken(body, 0.25)                 # recessed toe-kick
    seam = darken(body, 0.12)                 # thin front panel lines

    # solid body fill
    d.rectangle([0, 0, W - 1, H - 1], fill=body + (255,))
    # countertop lip (top 3px) + 1px underside line
    d.rectangle([0, 0, W - 1, 2], fill=lip + (255,))
    d.line([(0, 3), (W - 1, 3)], fill=underside + (255,))
    # purple trim band (2px) just below the countertop
    d.rectangle([0, 4, W - 1, 5], fill=purple + (255,))
    # thin vertical panel seams on the front (not a hollow rectangle)
    for sx in (W // 3, 2 * W // 3):
        d.line([(sx, 7), (sx, H - 5)], fill=seam + (255,))
    # recessed kick base: bottom 3px darker, inset ~2px each side
    d.rectangle([2, H - 4, W - 3, H - 2], fill=kick + (255,))
    # 1px border on the SIDES and BASE (#000000); top stays open (it is the lip)
    d.line([(0, 0), (0, H - 1)], fill=dark + (255,))
    d.line([(W - 1, 0), (W - 1, H - 1)], fill=dark + (255,))
    d.line([(0, H - 1), (W - 1, H - 1)], fill=dark + (255,))
    return img

# ----------------------------------------------------------------------------
# Review sheet
# ----------------------------------------------------------------------------
def font(size, bold=False):
    name = "consolab.ttf" if bold else "consola.ttf"
    try:
        return ImageFont.truetype("C:/Windows/Fonts/" + name, size)
    except Exception:
        return ImageFont.load_default()

def swatch(color, w, h):
    return Image.new("RGB", (w, h), color)

def scale_nn(img, factor):
    return img.resize((img.width * factor, img.height * factor), Image.NEAREST)

def render_review(pal, crops, meta, plaques, counter):
    PAGE_BG = (22, 24, 30)
    INK = (232, 234, 240)
    SUB = (150, 156, 170)
    HDR = (120, 200, 255)
    f = font(13)
    fb = font(15, bold=True)
    fs = font(11)

    # --- palette section layout ---
    order = ["PLAQUE_BASE", "PLAQUE_BORDER", "PLAQUE_HILITE",
             "ACCENT_secretary", "ACCENT_job_scout", "ACCENT_job_analyst",
             "ACCENT_deal_hunter", "COUNTER_BODY", "COUNTER_LIP",
             "COUNTER_DARK", "WALL_BG"]
    source_note = {
        "PLAQUE_BASE": "index.html label bg",
        "PLAQUE_BORDER": "derived: base -35%",
        "PLAQUE_HILITE": "derived: base +25%",
        "ACCENT_secretary": "index.html tint",
        "ACCENT_job_scout": "index.html tint",
        "ACCENT_job_analyst": "index.html tint",
        "ACCENT_deal_hunter": "arch id5 (mid wall)",
        "COUNTER_BODY": "desk 87/88 mid-band",
        "COUNTER_LIP": ("desk 87/88 lightest" if not meta["lip_fallback"]
                        else "fallback: body +20%"),
        "COUNTER_DARK": "objects id8 dark",
        "WALL_BG": "arch id0 (light wall)",
    }
    CROP = 96      # 16px tile shown at 6x in palette (legible, not huge)
    SWA = 96       # flat swatch width
    CELL_W = 132
    CELL_H = 200
    COLS = 6
    rows_pal = (len(order) + COLS - 1) // COLS

    # --- props section layout (each prop: 1.5x and 8x on WALL_BG) ---
    prop_items = [("counter_front", counter, COUNTER_W, COUNTER_H)]
    for key in ("secretary", "job_scout", "job_analyst", "deal_hunter"):
        prop_items.append(("nameplate_" + key, plaques[key], PLAQUE_W, PLAQUE_H))
    P15 = 3   # author at 1x, show "1.5x" as 3x here so it is legible on screen
    P8 = 8
    prop_row_h = max(COUNTER_H, PLAQUE_H) * P8 + 56
    prop_label_w = 150
    # widest prop row backing
    backing_w = max(w * P15 for _, _, w, _ in prop_items) + 24 \
        + max(w * P8 for _, _, w, _ in prop_items) + 24 + 48

    margin = 24
    pal_w = COLS * CELL_W
    page_w = margin * 2 + max(pal_w, prop_label_w + backing_w)
    pal_top = 64
    pal_h = rows_pal * CELL_H
    props_top = pal_top + pal_h + 56
    page_h = props_top + 40 + len(prop_items) * (prop_row_h + 16) + margin

    page = Image.new("RGB", (page_w, page_h), PAGE_BG)
    d = ImageDraw.Draw(page)
    d.text((margin, 18), "PROPS REVIEW  -  Stage 0 draft (sampled palette, 1x art)",
           fill=HDR, font=fb)

    # palette grid
    d.text((margin, pal_top - 22), "PALETTE  (source crop -> flat swatch -> hex)",
           fill=INK, font=fb)
    for i, key in enumerate(order):
        r, c = divmod(i, COLS)
        cx = margin + c * CELL_W
        cy = pal_top + r * CELL_H
        color = pal[key]
        if key in crops:
            crop8 = scale_nn(crops[key].convert("RGB"), CROP // 16)
            page.paste(crop8, (cx, cy))
        else:
            # no source tile (derived / from index.html): show enlarged swatch
            page.paste(swatch(color, CROP, CROP), (cx, cy))
            d.text((cx + 4, cy + 4), "(no tile)", fill=(20, 20, 20), font=fs)
        page.paste(swatch(color, SWA, 34), (cx, cy + CROP + 6))
        d.rectangle([cx, cy + CROP + 6, cx + SWA - 1, cy + CROP + 39],
                    outline=(60, 64, 76))
        d.text((cx, cy + CROP + 46), key, fill=INK, font=fs)
        d.text((cx, cy + CROP + 60), hexstr(color), fill=INK, font=f)
        d.text((cx, cy + CROP + 78), source_note[key], fill=SUB, font=fs)

    # props rows
    d.text((margin, props_top - 26),
           "PROPS  (left: ~1.5x in-office size  |  right: 8x detail  |  on WALL_BG)",
           fill=INK, font=fb)
    wall = pal["WALL_BG"]
    y = props_top + 8
    for name, img, w, h in prop_items:
        d.text((margin, y + prop_row_h // 2 - 8), name, fill=INK, font=f)
        bx = margin + prop_label_w
        backing = Image.new("RGB", (backing_w, prop_row_h), wall)
        page.paste(backing, (bx, y))
        d.rectangle([bx, y, bx + backing_w - 1, y + prop_row_h - 1],
                    outline=(60, 64, 76))
        small = scale_nn(img, P15)
        big = scale_nn(img, P8)
        sy = y + (prop_row_h - small.height) // 2
        by = y + (prop_row_h - big.height) // 2
        page.paste(small, (bx + 24, sy), small)
        d.text((bx + 24, y + prop_row_h - 22), "~1.5x", fill=(40, 40, 40), font=fs)
        gx = bx + 24 + small.width + 48
        page.paste(big, (gx, by), big)
        d.text((gx, y + prop_row_h - 22), "8x", fill=(40, 40, 40), font=fs)
        y += prop_row_h + 16

    if meta["lip_fallback"]:
        d.text((margin, page_h - 20),
               "NOTE: counter lip fell back to body +20%% (sampled lip too close; "
               "lum gap %.1f < %.0f)." % (meta["lip_body_lum_gap"], LIP_CONTRAST_MIN),
               fill=(255, 210, 120), font=f)
    page.save(REVIEW_PNG)

# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    os.makedirs(PROPS_DIR, exist_ok=True)
    pal, crops, meta = build_palette()

    plaques = {key: draw_plaque(pal, pal["ACCENT_" + key])
               for key in ("secretary", "job_scout", "job_analyst", "deal_hunter")}
    counter = draw_counter(pal)

    outputs = []
    for key, img in plaques.items():
        p = os.path.join(PROPS_DIR, "nameplate_%s.png" % key)
        img.save(p)
        outputs.append((p, img.size))
    cpath = os.path.join(PROPS_DIR, "counter_front.png")
    counter.save(cpath)
    outputs.append((cpath, counter.size))

    render_review(pal, crops, meta, plaques, counter)

    print("Sampled palette:")
    for k in ("PLAQUE_BASE", "PLAQUE_BORDER", "PLAQUE_HILITE", "ACCENT_secretary",
              "ACCENT_job_scout", "ACCENT_job_analyst", "ACCENT_deal_hunter",
              "COUNTER_BODY", "COUNTER_LIP", "COUNTER_DARK", "WALL_BG"):
        print("  %-20s %s" % (k, hexstr(pal[k])))
    print("Counter lip fallback used:", meta["lip_fallback"],
          "(lum gap %.1f, threshold %.0f)" % (meta["lip_body_lum_gap"], LIP_CONTRAST_MIN))
    print("\nProp PNGs written:")
    for p, sz in outputs:
        print("  %s  %dx%d" % (p, sz[0], sz[1]))
    print("\nReview sheet:", REVIEW_PNG)


if __name__ == "__main__":
    main()
