"""Regenerate the procedural assets for the perf test carts.

These carts (perf_mask.gq, perf_flat.gq, perf_dither.gq, perf_text.gq,
perf_menu_choice.gq, perf_menu_text.gq) deliberately drive specific renderer
paths for hardware performance profiling and Stage-2 (grlib row-major
rewrite) regression coverage (epics duplico/qc2024#45, duplico/qc2024#47).
The assets are committed, so you normally do not need to run this; it exists
to document and reproduce exactly how they were made.

Usage (from the examples/ directory, inside the gamequeer builder container
which provides Pillow):

    python games/perf/gen_perf_assets.py assets/animations

Encoding intent (verified via map.txt's .frame section after `gqc compile`):
  * perf_mask_fg.gif / perf_mask_mask.gif frames -> RLE7 (flat, mask cart --
                                             both animated in lockstep so the
                                             badge redraws every frame advance,
                                             not just once on `enter`)
  * perf_flat.gif   frames -> RLE7          (flat / fast decode path)
  * perf_dither.gif frames -> UNCOMPRESSED  (dense noise / slow decode path,
                                             once compiled with
                                             `dithering := "floyd_steinberg"`)
The text and menu carts (perf_text.gq, perf_menu_choice.gq,
perf_menu_text.gq) use no image assets at all -- they exercise
Graphics_drawString / menu.c purely through labels, menus, and strings.
"""
import sys

from PIL import Image, ImageDraw

OUT = sys.argv[1] if len(sys.argv) > 1 else "."


def save_gif(frames, path, duration_ms=200):
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        disposal=2,
    )
    print("wrote", path, f"({len(frames)} frames)")


# ---- Mask-cart assets: animated fg + mask, in lockstep ----------------------
# perf_mask.gq needs the badge to redraw every tick (a static single frame
# only draws once on `enter` and then idles -- nothing to perf-measure), so
# both the sprite and its mask are multi-frame animations with identical
# frame counts and timing, kept paired via `fgdone(1)` replay in the .gq
# event code. gq_draw_image_with_mask() only composites while BOTH slot N and
# slot N's mask are `in_use` with matching width/height (gamequeer.c
# draw_animation_stack()), so mismatched frame counts would silently fall
# back to an unmasked draw once the shorter one finishes -- identical frame
# counts/timing for both GIFs avoids that here.
#
# Foreground: a pulsing filled circle (radius 40<->60) -- stays large/flat
# every frame -> RLE7.
MASK_FRAMES = 6
fg_frames = []
for i in range(MASK_FRAMES):
    im = Image.new("L", (128, 128), 0)
    d = ImageDraw.Draw(im)
    # Triangle-wave radius across the cycle: 40, 48, 56, 60, 56, 48 (wraps).
    r = 40 + int(20 * abs(((i / MASK_FRAMES) * 2) % 2 - 1))
    d.ellipse((64 - r, 64 - r, 64 + r, 64 + r), fill=255)
    fg_frames.append(im)
save_gif(fg_frames, f"{OUT}/perf_mask_fg.gif")

# Mask: horizontal bands, marching downward one frame at a time (wraps
# cleanly via modulo -- no partial-band edge cases) -- long horizontal runs
# every frame -> RLE7. White = show sprite pixel.
mask_frames = []
for i in range(MASK_FRAMES):
    im = Image.new("L", (128, 128), 0)
    px = im.load()
    shift = i * (32 // MASK_FRAMES)
    row = bytearray(255 if ((y + shift) % 32) < 16 else 0 for y in range(128))
    for y in range(128):
        for x in range(128):
            px[x, y] = row[y]
    mask_frames.append(im)
save_gif(mask_frames, f"{OUT}/perf_mask_mask.gif")


# ---- Flat animation: multi-frame, large solid regions -> RLE7 ---------------
flat_frames = []
for i in range(8):
    im = Image.new("L", (128, 128), 0)
    d = ImageDraw.Draw(im)
    y = (i * 16) % 128
    d.rectangle((0, y, 127, min(y + 31, 127)), fill=255)  # moving solid bar
    flat_frames.append(im)
save_gif(flat_frames, f"{OUT}/perf_flat.gif")


# ---- Dithered animation: multi-frame grayscale gradient -> UNCOMPRESSED ------
# A diagonal gradient shifted per frame; Floyd-Steinberg dithering at compile
# time turns the mid-tones into dense per-pixel noise -> UNCOMPRESSED (slow).
dith_frames = []
for i in range(8):
    im = Image.new("L", (128, 128), 0)
    px = im.load()
    off = i * 16
    for y in range(128):
        for x in range(128):
            px[x, y] = ((x + y + off) * 2) % 256
    dith_frames.append(im)
save_gif(dith_frames, f"{OUT}/perf_dither.gif")
