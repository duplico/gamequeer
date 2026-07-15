"""Regenerate the procedural assets for the perf test carts.

These carts (perf_mask.gq, perf_flat.gq, perf_dither.gq) deliberately drive
specific renderer paths for hardware performance profiling (epic
duplico/qc2024#45). The assets are committed, so you normally do not need to
run this; it exists to document and reproduce exactly how they were made.

Usage (from the examples/ directory, inside the gamequeer builder container
which provides Pillow):

    python games/perf/gen_perf_assets.py assets/animations

Encoding intent (verified via map.txt's .frame section after `gqc compile`):
  * perf_fg_circle.png / perf_mask_bands.png -> RLE7  (flat, mask cart)
  * perf_flat.gif   frames -> RLE7          (flat / fast decode path)
  * perf_dither.gif frames -> UNCOMPRESSED  (dense noise / slow decode path,
                                             once compiled with
                                             `dithering := "floyd_steinberg"`)
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


# ---- Mask-cart assets: full-screen static PNGs ------------------------------
# Foreground sprite: big solid white filled circle on black -> large flat
# regions -> RLE7 (fast) encoding.
sprite = Image.new("L", (128, 128), 0)
d = ImageDraw.Draw(sprite)
d.ellipse((8, 8, 119, 119), fill=255)
sprite.save(f"{OUT}/perf_fg_circle.png")
print("wrote perf_fg_circle.png")

# Mask: horizontal bands (draw / don't-draw). Long horizontal runs -> RLE7.
# White (255) = show sprite pixel; black (0) = leave background.
mask = Image.new("L", (128, 128), 0)
d = ImageDraw.Draw(mask)
for y0 in range(0, 128, 32):
    d.rectangle((0, y0, 127, y0 + 15), fill=255)  # 16px on, 16px off bands
mask.save(f"{OUT}/perf_mask_bands.png")
print("wrote perf_mask_bands.png")


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
