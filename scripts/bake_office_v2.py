"""Stage 1b-structure: Direction 2 room SHELL bake (additive, no app change).

BUILD-TIME TOOLING (like render_office.py / gen_props.py). Run manually:

    ./venv/Scripts/python.exe scripts/bake_office_v2.py

It imports the validated Stage 1a primitives (render_map, publish) and applies
ADDITIVE edits on top of the faithful tile render -- example.tmx remains the
untouched source; v2 is a bake layered over it. This pass builds the room shell
only: flat sky behind the upper-right windows, two glass partitions, and a
dim over the Deal Hunter corner. NO props, NO monitor bank, NO nameplates.

Outputs:
  agent_central/.../example-v2-transparent.png   (Variant A = full-height; default file)
  ~/Downloads/office-v2-shell-review.png          (BOTH variants over the shell grey)

The original example-transparent.png is never overwritten.
"""
import os

from PIL import Image, ImageDraw, ImageFont

import render_office as RO

T = RO.TILES
OBJECTS_PNG = os.path.join(T, "tileset_objects.png")
OUT_V2 = os.path.join(T, "example-v2-transparent.png")
REVIEW = os.path.join(os.path.expanduser("~"), "Downloads", "office-v2-fix-review.png")

# --- locked design constants (verified anchors from the Stage 1b report) ---
SKY = (2, 141, 253, 255)               # world-bg-v2 top-band azure, flat (no clouds)
WINDOW_BBOX = (480, 48, 608, 112)      # cols 30-37, rows 3-6 (x0,y0,x1,y1)
SHELL = (128, 128, 128)                # representative building-shell grey (#808080)

# Partition stack tiles (objects gids): 62 top cap, 76 frosted-glass mid, 90 base.
# Pilot locks Variant B (half-height, matching the existing cubicle dividers).
VARIANT_B = [
    (10, 5, 62), (10, 6, 76), (10, 7, 90),
    (16, 15, 62), (16, 16, 76), (16, 17, 90),
]

# Job Scout monitor bay: single row at grid row 14 (bases seat on cubicle tops
# at row 15). id 9 = monitor screen ON (cyan, gid 69); id 23 = monitor OFF
# (dark, gid 83); id 22 = server rack (gid 82) as a single end-cap at col 31.
# Pillar cols 23 and 30 are intentionally skipped so the wall clusters with gaps.
MON_ON, MON_OFF, RACK = 69, 83, 82
MONITOR_BANK = [
    (21, 14, MON_ON), (22, 14, MON_OFF),
    # col 23 pillar -> skipped
    (24, 14, MON_ON), (25, 14, MON_OFF), (26, 14, MON_ON),
    (27, 14, MON_OFF), (28, 14, MON_ON), (29, 14, MON_OFF),
    # col 30 pillar -> skipped
    (31, 14, RACK),                    # single end-cap rack
]

# Secretary reception: redesigned counter (lip + purple trim + kick base). Seat
# it so the opaque kick base sits on the floor surface strip and the black base
# border keys away in the floor's transparent underside (no grey seam). Exact
# top y derived empirically and pixel-verified below. Chair dropped this pass.
COUNTER_XY = (11 * 16, 271)            # cols 11-14; top y271 (kick bottom ~y293)

# Job Analyst desk clutter (sparse): mug + small green tray on the right desk
# front (sit at r6 base so they rest on the r7 desk surface). id 18 dropped
# (it is a wall panel with sticky notes, not loose papers).
CLUTTER = [
    (31, 6, 146),                      # green tray/plant (id 86)
    (33, 6, 145),                      # mug (id 85)
]

# All four nameplates, mounted directly over the cluster each labels.
PROPS_DIR = os.path.join(RO.ROOT, "agent_central", "static", "assets", "props")
# 60x22 plaques. Two use pixel-y offsets (not whole rows) to clear neighbors:
# job_scout lifted so its bottom sits at the r13/r14 boundary just above the
# monitors; job_analyst shifted left to cols 9-12 to clear the whiteboard and
# the ceiling lights (the col-10 partition is at r5-7, below, so it does not
# block). deal_hunter and secretary keep their cells (clear at 22px).
NAMEPLATES = {
    "deal_hunter": (3 * 16, 3 * 16),   # (48, 48)  cols 3-6, r3  (home dock)
    "job_analyst": (9 * 16, 3 * 16),   # (144, 48) cols 9-12, r3 (chart-room entrance)
    "job_scout":   (24 * 16, 202),     # (384, 202) cols 24-27, bottom just above monitors
    "secretary":   (11 * 16, 13 * 16), # (176, 208) cols 11-14, r13 (over the counter)
}

_OBJ = Image.open(OBJECTS_PNG).convert("RGBA")


def _otile(gid, cols=14, ts=16):
    local = gid - 60
    c, r = local % cols, local // cols
    return _OBJ.crop((c * ts, r * ts, c * ts + ts, r * ts + ts))


def build_base():
    """raw tile render with flat azure sky behind the upper-right windows.

    Sky UNDER the glass: fill the window bbox with azure, then composite raw on
    top so the alpha-128 glass shows the sky through it (no hardcoded glass
    colors). No dim overlay in the pilot.
    """
    raw = RO.render_map()                       # faithful transparent render
    base = Image.new("RGBA", raw.size, (0, 0, 0, 0))
    ImageDraw.Draw(base).rectangle(
        [WINDOW_BBOX[0], WINDOW_BBOX[1], WINDOW_BBOX[2] - 1, WINDOW_BBOX[3] - 1],
        fill=SKY)
    base.alpha_composite(raw)
    return base


def _check_plaque(path):
    """Confirm a nameplate has no pure-#000000 opaque pixel (would key away)."""
    im = Image.open(path).convert("RGBA")
    blacks = sum(1 for p in im.getdata() if p[3] > 0 and p[:3] == (0, 0, 0))
    return im, blacks


def build_furnished(base):
    """Variant B shell + all four rooms furnished + all four nameplates."""
    img = base.copy()

    for col, row, gid in VARIANT_B:             # partitions
        img.alpha_composite(_otile(gid), (col * 16, row * 16))
    for col, row, gid in MONITOR_BANK:          # Job Scout monitor wall
        img.alpha_composite(_otile(gid), (col * 16, row * 16))
    for col, row, gid in CLUTTER:               # Job Analyst desk clutter
        img.alpha_composite(_otile(gid), (col * 16, row * 16))

    # Secretary reception: counter only (chair dropped this pass).
    counter = Image.open(os.path.join(PROPS_DIR, "counter_front.png")).convert("RGBA")
    img.alpha_composite(counter, COUNTER_XY)

    # All four nameplates (navy plaques, survive the black-key).
    for who, xy in NAMEPLATES.items():
        plaque, blacks = _check_plaque(os.path.join(PROPS_DIR, "nameplate_%s.png" % who))
        print("  nameplate_%-12s pure-#000 px: %d %s" % (
            who, blacks, "(OK)" if blacks == 0 else "(WARNING: will key transparent!)"))
        img.alpha_composite(plaque, xy)

    return RO.publish(img)                       # flatten over white + black-key


# ----------------------------------------------------------------------------
# Review (over the shell grey, NOT a transparency checker)
# ----------------------------------------------------------------------------
def _font(sz):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/consola.ttf", sz)
    except Exception:
        return ImageFont.load_default()


def _over_shell(rgba):
    bg = Image.new("RGB", rgba.size, SHELL)
    bg.paste(rgba, (0, 0), rgba)
    return bg


def _grid_panel(shell_rgb, scale=3, cell=16, every=4):
    base = shell_rgb.resize((shell_rgb.width * scale, shell_rgb.height * scale), Image.NEAREST)
    ml, mt = 28, 18
    panel = Image.new("RGB", (base.width + ml + 4, base.height + mt + 4), (24, 26, 32))
    panel.paste(base, (ml, mt))
    d = ImageDraw.Draw(panel)
    ov = Image.new("RGBA", panel.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    f = _font(11)
    grid = (120, 200, 255)
    cols = shell_rgb.width // cell
    rows = shell_rgb.height // cell
    for c in range(cols + 1):
        x = ml + c * cell * scale
        major = c % every == 0
        od.line([(x, mt), (x, mt + base.height)], fill=grid + (150,) if major else (255, 255, 255, 40))
        if major:
            d.text((x - 6, 3), str(c), fill=grid, font=f)
    for r in range(rows + 1):
        y = mt + r * cell * scale
        major = r % every == 0
        od.line([(ml, y), (ml + base.width, y)], fill=grid + (150,) if major else (255, 255, 255, 40))
        if major:
            d.text((2, y - 6), str(r), fill=grid, font=f)
    panel.paste(Image.alpha_composite(panel.convert("RGBA"), ov).convert("RGB"), (0, 0))
    return panel


def render_furnished_review(final):
    """Whole office over the shell grey: 3x with grid, then 1.5x without."""
    fb = _font(16)
    fs = _font(13)
    shell = _over_shell(final)
    g = _grid_panel(shell)                           # 3x + grid
    small = shell.resize((int(shell.width * 1.5), int(shell.height * 1.5)), Image.NEAREST)

    pad = 20
    width = max(g.width, small.width) + pad * 2
    height = pad + 24 + g.height + 12 + 20 + small.height + pad
    page = Image.new("RGB", (width, height), (18, 20, 26))
    d = ImageDraw.Draw(page)
    d.text((pad, 2),
           "OFFICE v2 FIX  (over shell grey #808080)  -  redesigned counter, 60x22 plaques, chair dropped",
           fill=(120, 200, 255), font=fb)
    y = pad + 6
    d.text((pad, y), "Counter: lip + purple trim + kick base. Plaques 60x22: DealHunter dock, "
           "Analyst entrance (cols9-12), JobScout lifted over monitors, Secretary over counter.",
           fill=(235, 236, 240), font=fs)
    y += 24
    page.paste(g, (pad, y)); y += g.height + 12
    d.text((pad, y), "1.5x (actual app scale, no grid):", fill=(150, 156, 170), font=fs)
    y += 20
    page.paste(small, (pad, y))
    page.save(REVIEW)


def main():
    base = build_base()
    final = build_furnished(base)
    final.save(OUT_V2)                                # full furnished Direction 2 office
    print("wrote", OUT_V2, final.size, "(Variant B shell + all rooms furnished)")
    render_furnished_review(final)
    print("wrote", REVIEW)
    print("original example-transparent.png untouched.")


if __name__ == "__main__":
    main()
