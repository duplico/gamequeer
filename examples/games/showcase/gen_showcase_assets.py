"""Generate the procedural assets for the 20 FPS showcase cart (showcase.gq).

The showcase cart tours every renderer content class at frame_rate 20
(5 ticks/frame): flat/RLE7, dithered/UNCOMPRESSED, and masked with both
streams UNCOMPRESSED (the animation-p100 class), plus a 4 FPS contrast
stage that reuses the dithered asset. The assets are committed, so you
normally do not need to run this; it exists to document and reproduce
exactly how they were made.

Usage (from the examples/ directory, inside the gamequeer builder container
which provides Pillow):

    python games/showcase/gen_showcase_assets.py assets/animations

Encoding intent (verified via map.txt's .frame section after `gqc compile`):
  * showcase_flat.gif    frames -> RLE7        (solid bouncing box, flat /
                                                fast decode path)
  * showcase_dither.gif  frames -> UNCOMPRESSED (scrolling continuous-tone
                                                gradient, dense noise once
                                                compiled with
                                                `dithering := "floyd_steinberg"`;
                                                also bound a second time at
                                                frame_rate 4 by the contrast
                                                stage)
  * showcase_mask_fg.gif / showcase_mask_mask.gif frames -> UNCOMPRESSED
                                               (dense noise on BOTH streams of
                                                the masked blit -- the
                                                animation-p100 content class;
                                                identical frame counts/timing
                                                so the fg/mask pairing holds
                                                for the whole loop)

Every source is authored at 20 FPS (50 ms/frame) with a seamless loop:
N trajectory frames plus one duplicate of frame 0, because gqc's internal
ffmpeg fps resample tends to drop one frame -- with the duplicate tail the
loop seam stays clean whether the extra frame survives or not. Verify final
frame counts in map.txt.
"""
import math
import sys

from PIL import Image, ImageDraw

OUT = sys.argv[1] if len(sys.argv) > 1 else "."


def save_gif(frames, path, duration_ms=50):
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        disposal=2,
    )
    print("wrote", path, f"({len(frames)} frames @ {duration_ms} ms)")


def tri(t, period, lo, hi):
    """Triangle wave: lo -> hi -> lo over `period` steps, seamless at wrap."""
    phase = (t % period) / period * 2
    frac = phase if phase <= 1 else 2 - phase
    return lo + (hi - lo) * frac


# ---- Flat stage: bouncing solid box -> RLE7 ---------------------------------
# Large solid regions every frame keep RLE7 the smaller encoding. 40
# trajectory frames = a 2 s loop at 20 FPS; triangle-wave periods 40/20
# (one horizontal traversal, two vertical bounces) wrap seamlessly.
FLAT_FRAMES = 40
BOX = 36
flat_frames = []
for t in range(FLAT_FRAMES + 1):
    im = Image.new("L", (128, 128), 0)
    d = ImageDraw.Draw(im)
    bx = tri(t, FLAT_FRAMES, 2, 126 - BOX)
    by = tri(t, FLAT_FRAMES // 2, 2, 126 - BOX)
    d.rectangle((bx, by, bx + BOX, by + BOX), fill=255)
    flat_frames.append(im)
save_gif(flat_frames, f"{OUT}/showcase_flat.gif")


# ---- Dither stage: scrolling gradient -> UNCOMPRESSED -----------------------
# A diagonal continuous-tone gradient scrolled 8 gray-levels per frame;
# 32 frames x 8 = 256 = one full gradient period, so the loop wraps
# seamlessly. Floyd-Steinberg dithering at compile time turns the mid-tones
# into dense per-pixel noise -> every frame UNCOMPRESSED.
DITHER_FRAMES = 32
dither_frames = []
for t in range(DITHER_FRAMES + 1):
    im = Image.new("L", (128, 128), 0)
    px = im.load()
    off = 8 * t
    for y in range(128):
        for x in range(128):
            px[x, y] = ((x + y) * 2 + off) % 256
    dither_frames.append(im)
save_gif(dither_frames, f"{OUT}/showcase_dither.gif")


# ---- Masked stage: dithered fg through dithered mask (both UNCOMPRESSED) ----
# The animation-p100 content class: gq_draw_image_with_mask() with both
# streams UNCOMPRESSED, full-screen. Foreground: a radial gradient pulsing
# outward (shift 16 gray-levels/frame, 16 x 16 = 256 = seamless). Mask: an
# anti-diagonal gradient scrolling the other way, same period. Both dither
# to dense noise -> UNCOMPRESSED. Identical frame counts and timing keep
# the fg/mask pair in lockstep for the whole loop (a mismatched pair
# silently falls back to an unmasked draw once the shorter one finishes).
MASK_FRAMES = 16
mask_fg_frames = []
for t in range(MASK_FRAMES + 1):
    im = Image.new("L", (128, 128), 0)
    px = im.load()
    off = 16 * t
    for y in range(128):
        for x in range(128):
            r = math.hypot(x - 64, y - 64)
            px[x, y] = (int(r * 3) - off) % 256
    mask_fg_frames.append(im)
save_gif(mask_fg_frames, f"{OUT}/showcase_mask_fg.gif")

mask_mask_frames = []
for t in range(MASK_FRAMES + 1):
    im = Image.new("L", (128, 128), 0)
    px = im.load()
    off = 16 * t
    for y in range(128):
        for x in range(128):
            px[x, y] = ((x - y) * 2 + off) % 256
    mask_mask_frames.append(im)
save_gif(mask_mask_frames, f"{OUT}/showcase_mask_mask.gif")
