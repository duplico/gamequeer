"""Asset-pipeline test suite: Frame encoders, mkanim, mkcue (gamequeer#336,
part of the test-suite epic gamequeer#329).

Frame encoder cases are pure unit tests against tiny synthetic in-memory PIL
images -- no ffmpeg, no filesystem, no shared compiler state.

mkanim and mkcue cases drive the real grammar/parser code paths in-process
(see tests/support.py's reset_compiler_state(), reused from the pattern
established for gamequeer#361/#362) rather than reimplementing gqc's asset
logic, so that e.g. `Animation.anim_table["name"]` or a parsed `LightCue`'s
frames can be inspected directly. A couple of CLI (subprocess) cases are
included for the `mkanim`/`mkcue` commands themselves, matching the
black-box style of `compile_gq` in conftest.py.

Anything that actually shells out to ffmpeg (i.e. any animation source that
isn't a single still image, since `make_animation_from_image` is pure PIL)
is marked `ffmpeg` so it auto-skips without a real ffmpeg binary on PATH
(see conftest.py). ffmpeg's *byte* output isn't assumed portable across
environments here -- only frame *counts* and gqc's own control flow are
asserted; byte-exact golden compiles are gamequeer#333's job.
"""

import io
import pickle
import struct
import subprocess
import sys

import pytest
from PIL import Image

from gqc import anim, cues, linker, parser, structs
from gqc.datamodel import Animation, Frame, Game

from .support import reset_compiler_state

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'
STAGE = "stage start { event enter { } }\n"


def _make_gif(path, frame_count, frame_ms, size=(8, 8), invert=False):
    """Write a tiny synthetic alternating-frame GIF at a controlled native
    frame duration, so ffmpeg's `fps` resampling filter has an unambiguous
    frame count to work from (`frame_ms` well above the ~20ms threshold
    where some GIF decoders clamp short delays -- see the module docstring
    in test history / PR discussion for gamequeer#336)."""
    first, second = (0, 255) if invert else (255, 0)
    frames = [
        Image.new("L", size, color=first if i % 2 == 0 else second).convert("RGB")
        for i in range(frame_count)
    ]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=frame_ms, loop=0)


def _make_still(path, size=(8, 8), color=1):
    Image.new("1", size, color=color).save(path)


def _parse_in_process(tmp_path, monkeypatch, decls):
    """Parse a minimal game (with the given top-level `decls`, e.g. an
    `animations { ... }` block) in-process, from a hermetic cwd matching
    what `gqc compile` sets up, so `Animation.anim_table` etc. can be
    inspected directly afterward."""
    monkeypatch.chdir(tmp_path)
    reset_compiler_state()
    linker.create_reserved_variables()
    Game.game_name = "g"
    source = f"{GAME_HEADER}{decls}\n{STAGE}"
    parser.parse(io.StringIO(source))


def _run_cli(tmp_path, args, timeout=60):
    proc = subprocess.run(
        [sys.executable, "-m", "gqc", *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stderr


# --- Frame encoders: uncompressed_bytes() ------------------------------------


def test_uncompressed_bytes_pads_each_row_to_its_own_byte():
    # width=3 doesn't divide evenly into a byte, so each of the 2 rows must
    # start a fresh output byte rather than packing continuously across the
    # row boundary (row0 = 1,0,0 -> 0x80; row1 = 1,1,0 -> 0xc0).
    im = Image.new("1", (3, 2), 0)
    im.putpixel((0, 0), 1)
    im.putpixel((0, 1), 1)
    im.putpixel((1, 1), 1)

    frame = Frame(img=im)
    assert frame.uncompressed_bytes() == bytes([0x80, 0xC0])


# --- Frame encoders: rle_bytes(7) --------------------------------------------


def test_rle7_bytes_seeds_run_value_from_first_pixel():
    # First pixel is black (0) and seeds `val`; the remaining 4 white (1)
    # pixels close out that seeded black run (length 0) before starting
    # their own run.
    im = Image.new("1", (5, 1), 1)
    im.putpixel((0, 0), 0)

    frame = Frame(img=im)
    assert frame.rle_bytes(7) == bytes([0x00, 0x07])


def test_rle7_bytes_splits_runs_longer_than_127():
    # 300 identical (white) pixels: a run byte is emitted every 128 pixels
    # (127 counted after the seed pixel, per the `run == run_max` check
    # firing on the 128th same-valued pixel), each worth run=127 -> 0xff,
    # with the remaining 300 - 2*128 = 44 pixels (43 after the seed) as a
    # final short run -> (43 << 1) + 1 = 0x57.
    im = Image.new("1", (300, 1), 1)

    frame = Frame(img=im)
    assert frame.rle_bytes(7) == bytes([0xFF, 0xFF, 0x57])


# --- Frame encoders: RLE7-vs-UNCOMP selection --------------------------------


def test_frame_selects_rle7_for_low_entropy_content():
    im = Image.new("1", (64, 8), 1)  # solid: one giant run
    frame = Frame(img=im)
    assert frame.compression_type_name == "IMAGE_FMT_1BPP_COMP_RLE7"
    assert len(frame.bytes) < len(frame.uncompressed_bytes())


def test_frame_selects_uncompressed_for_high_entropy_content():
    im = Image.new("1", (64, 8))
    px = im.load()
    for y in range(8):
        for x in range(64):
            px[x, y] = (x + y) % 2  # checkerboard: worst case for RLE

    frame = Frame(img=im)
    assert frame.compression_type_name == "IMAGE_FMT_1BPP_UNCOMP"
    assert len(frame.bytes) < len(frame.rle_bytes(7))


def test_image_formats_contains_exactly_rle7_and_uncompressed():
    # Pins gamequeer#277: RLE4 is fully implemented (image_rle4_bytes()
    # exists) but deliberately excluded from image_formats/the format
    # selection, and so is unreachable via Frame's public interface.
    assert Frame.image_formats == {
        "IMAGE_FMT_1BPP_COMP_RLE7": 0x71,
        "IMAGE_FMT_1BPP_UNCOMP": 0x01,
    }


# --- mkanim: frame-rate resampling -------------------------------------------


@pytest.mark.ffmpeg
def test_frame_rate_resamples_frame_count(tmp_path, monkeypatch):
    assets_dir = tmp_path / "assets" / "animations"
    assets_dir.mkdir(parents=True)
    _make_gif(assets_dir / "src.gif", frame_count=40, frame_ms=50)  # 2s @ 20fps native

    _parse_in_process(
        tmp_path, monkeypatch,
        'animations { a1 <- "src.gif" { frame_rate = 10; dithering := "none"; } }',
    )
    count_at_10 = len(Animation.anim_table["a1"].frames)

    _parse_in_process(
        tmp_path, monkeypatch,
        'animations { a2 <- "src.gif" { frame_rate = 5; dithering := "none"; } }',
    )
    count_at_5 = len(Animation.anim_table["a2"].frames)

    assert count_at_10 == 20  # 2s @ 10fps
    assert count_at_5 == 10  # 2s @ 5fps


@pytest.mark.ffmpeg
def test_non_factor_of_100_frame_rate_warns_and_floors(tmp_path, monkeypatch, capsys):
    assets_dir = tmp_path / "assets" / "animations"
    assets_dir.mkdir(parents=True)
    _make_gif(assets_dir / "src.gif", frame_count=40, frame_ms=50)

    _parse_in_process(
        tmp_path, monkeypatch,
        'animations { a1 <- "src.gif" { frame_rate = 7; dithering := "none"; } }',
    )

    animation = Animation.anim_table["a1"]
    assert animation.ticks_per_frame == 100 // 7  # floor division, not rounded: 14

    captured = capsys.readouterr()
    assert "not a factor of 100" in captured.out + captured.err


# --- mkanim: single-still `duration` override --------------------------------


def test_single_still_duration_overrides_frame_rate_ticks(tmp_path, monkeypatch):
    assets_dir = tmp_path / "assets" / "animations"
    assets_dir.mkdir(parents=True)
    _make_still(assets_dir / "still.png")

    _parse_in_process(
        tmp_path, monkeypatch,
        'animations { a1 <- "still.png" { frame_rate = 5; duration = 77; } }',
    )

    animation = Animation.anim_table["a1"]
    assert len(animation.frames) == 1
    assert animation.ticks_per_frame == 77


# --- mkanim: still-image dither restriction ----------------------------------


def test_still_image_bayer_dither_rejected(tmp_path, monkeypatch):
    assets_dir = tmp_path / "assets" / "animations"
    assets_dir.mkdir(parents=True)
    _make_still(assets_dir / "still.png")

    with pytest.raises(SystemExit) as exc_info:
        _parse_in_process(
            tmp_path, monkeypatch,
            'animations { a1 <- "still.png" { dithering := "bayer"; } }',
        )
    assert exc_info.value.code == 1


@pytest.mark.parametrize("dithering", ["none", "floyd_steinberg"])
def test_still_image_supported_dither_accepted(tmp_path, monkeypatch, dithering):
    assets_dir = tmp_path / "assets" / "animations"
    assets_dir.mkdir(parents=True)
    _make_still(assets_dir / "still.png")

    _parse_in_process(
        tmp_path, monkeypatch,
        f'animations {{ a1 <- "still.png" {{ dithering := "{dithering}"; }} }}',
    )
    assert len(Animation.anim_table["a1"].frames) == 1


# --- mkanim: digest cache -----------------------------------------------------


@pytest.mark.ffmpeg
def test_digest_cache_skips_ffmpeg_on_unchanged_source(tmp_path, monkeypatch):
    assets_dir = tmp_path / "assets" / "animations"
    assets_dir.mkdir(parents=True)
    _make_gif(assets_dir / "src.gif", frame_count=40, frame_ms=50)
    decls = 'animations { a1 <- "src.gif" { frame_rate = 10; dithering := "none"; } }'

    _parse_in_process(tmp_path, monkeypatch, decls)
    first_bytes = [f.bytes for f in Animation.anim_table["a1"].frames]

    calls = []
    original_make_animation = anim.make_animation

    def _spy(*args, **kwargs):
        calls.append(1)
        return original_make_animation(*args, **kwargs)

    monkeypatch.setattr("gqc.datamodel.make_animation", _spy)

    _parse_in_process(tmp_path, monkeypatch, decls)
    second_bytes = [f.bytes for f in Animation.anim_table["a1"].frames]

    assert not calls, "digest cache hit should skip re-running ffmpeg"
    assert first_bytes == second_bytes


@pytest.mark.ffmpeg
def test_digest_cache_invalidated_by_source_touch(tmp_path, monkeypatch):
    assets_dir = tmp_path / "assets" / "animations"
    assets_dir.mkdir(parents=True)
    gif_path = assets_dir / "src.gif"
    _make_gif(gif_path, frame_count=40, frame_ms=50)
    decls = 'animations { a1 <- "src.gif" { frame_rate = 10; dithering := "none"; } }'

    _parse_in_process(tmp_path, monkeypatch, decls)
    first_bytes = [f.bytes for f in Animation.anim_table["a1"].frames]

    # Same name/rate/dithering, different pixel content -> digest must change.
    _make_gif(gif_path, frame_count=40, frame_ms=50, invert=True)

    _parse_in_process(tmp_path, monkeypatch, decls)
    second_bytes = [f.bytes for f in Animation.anim_table["a1"].frames]

    assert first_bytes != second_bytes


def test_still_image_digest_cache_is_never_reused(tmp_path, monkeypatch):
    # Pins a currently-observed bug (not fixed here -- this test suite is
    # test-only; filed as gamequeer#376): Animation.digest() depends on
    # self.ticks_per_frame, which is computed from `frame_rate` *before*
    # frames are counted, then silently overwritten with `duration` right
    # after (the single-still override) -- but *before* the digest is
    # written to `.digest`. So the digest checked against the cache file on
    # a later run (pre-override value) can never match the one that was
    # stored (post-override value) for any still image, and the cache
    # always misses. This doesn't need ffmpeg either way, since the still
    # path never calls it regardless of cache outcome.
    assets_dir = tmp_path / "assets" / "animations"
    assets_dir.mkdir(parents=True)
    _make_still(assets_dir / "still.png")
    decls = 'animations { a1 <- "still.png" { frame_rate = 5; duration = 77; } }'

    _parse_in_process(tmp_path, monkeypatch, decls)

    calls = []
    original_make_animation = anim.make_animation

    def _spy(*args, **kwargs):
        calls.append(1)
        return original_make_animation(*args, **kwargs)

    monkeypatch.setattr("gqc.datamodel.make_animation", _spy)

    _parse_in_process(tmp_path, monkeypatch, decls)

    assert calls, (
        "if this starts failing, the still-image digest-cache bug this "
        "test pins has been fixed -- update/remove it accordingly"
    )


# --- mkanim: CLI (black-box) --------------------------------------------------


def test_mkanim_cli_still_image_writes_single_frame(tmp_path):
    _make_still(tmp_path / "still.png")
    out_dir = tmp_path / "build" / "anim"

    exit_code, stderr = _run_cli(
        tmp_path, ["mkanim", "-o", str(out_dir), "-i", str(tmp_path / "still.png")]
    )

    assert exit_code == 0, stderr
    frame_paths = sorted(out_dir.glob("frame*.bmp"))
    assert len(frame_paths) == 1


# --- mkcue: duration rounding -------------------------------------------------


def test_cue_duration_rounds_to_multiple_of_4_with_warning(capsys):
    source = (
        "frame {\n"
        "    duration = 101;\n"
        "    colors { red, orange, yellow, green, blue }\n"
        "}\n"
    )
    cue = cues.parse_cue(io.StringIO(source))

    assert cue.frames[0].duration == 100
    captured = capsys.readouterr()
    assert "not a multiple of 4" in captured.out + captured.err


def test_cue_duration_already_multiple_of_4_has_no_warning(capsys):
    source = (
        "frame {\n"
        "    duration = 100;\n"
        "    colors { red, orange, yellow, green, blue }\n"
        "}\n"
    )
    cue = cues.parse_cue(io.StringIO(source))

    assert cue.frames[0].duration == 100
    captured = capsys.readouterr()
    assert "not a multiple of 4" not in captured.out + captured.err


def test_cue_frame_duration_exceeding_max_exits():
    source = (
        "frame {\n"
        "    duration = 70000;\n"
        "    colors { red, orange, yellow, green, blue }\n"
        "}\n"
    )
    with pytest.raises(SystemExit) as exc_info:
        cues.parse_cue(io.StringIO(source))
    assert exc_info.value.code == 1


# --- mkcue: smooth transition flag bit ---------------------------------------


def test_cue_frame_smooth_transition_sets_flag_bit():
    source = (
        "frame {\n"
        '    duration = 100;\n'
        '    transition := "smooth";\n'
        "    colors { red, orange, yellow, green, blue }\n"
        "}\n"
    )
    cue = cues.parse_cue(io.StringIO(source))
    frame = cue.frames[0]
    frame.resolve()

    flags = struct.unpack(structs.GQ_LEDCUE_FRAME_FORMAT, frame.to_bytes())[1]
    assert flags == structs.LedCueFrameFlags.TRANSITION_SMOOTH


def test_cue_frame_default_transition_leaves_flag_clear():
    source = (
        "frame {\n"
        "    duration = 100;\n"
        "    colors { red, orange, yellow, green, blue }\n"
        "}\n"
    )
    cue = cues.parse_cue(io.StringIO(source))
    frame = cue.frames[0]
    frame.resolve()

    flags = struct.unpack(structs.GQ_LEDCUE_FRAME_FORMAT, frame.to_bytes())[1]
    assert flags == 0


# --- mkcue: frame color-count enforcement ------------------------------------


def test_cue_frame_rejects_four_colors():
    source = (
        "frame {\n"
        "    duration = 100;\n"
        "    colors { red, orange, yellow, green }\n"
        "}\n"
    )
    with pytest.raises(SystemExit) as exc_info:
        cues.parse_cue(io.StringIO(source))
    assert exc_info.value.code == 1


def test_cue_frame_rejects_six_colors():
    source = (
        "frame {\n"
        "    duration = 100;\n"
        "    colors { red, orange, yellow, green, blue, red }\n"
        "}\n"
    )
    with pytest.raises(SystemExit) as exc_info:
        cues.parse_cue(io.StringIO(source))
    assert exc_info.value.code == 1


# --- mkcue: named vs. hex color resolution -----------------------------------


def test_cue_named_and_hex_color_resolution():
    source = (
        "colors {\n"
        '    red := "red";\n'
        '    orange := "#ff2010";\n'
        "}\n"
        "frame {\n"
        "    duration = 100;\n"
        "    colors { red, orange, yellow, green, blue }\n"
        "}\n"
    )
    cue = cues.parse_cue(io.StringIO(source))
    frame = cue.frames[0]
    frame.resolve()

    resolved = {c.name: (c.r, c.g, c.b) for c in frame.colors}
    assert resolved["red"] == (255, 0, 0)  # named color-block entry ("red")
    assert resolved["orange"] == (255, 32, 16)  # hex color-block entry (#ff2010)
    assert resolved["yellow"] == (255, 255, 0)  # bare webcolors name, no block entry


# --- mkcue: CLI (black-box) ---------------------------------------------------


def test_mkcue_cli_writes_serialized_cue(tmp_path):
    source = (
        "frame {\n"
        "    duration = 100;\n"
        "    colors { red, orange, yellow, green, blue }\n"
        "}\n"
    )
    src_path = tmp_path / "cue.gqcue"
    src_path.write_text(source)
    out_dir = tmp_path / "build" / "cue"

    exit_code, stderr = _run_cli(tmp_path, ["mkcue", "-o", str(out_dir), "-i", str(src_path)])
    assert exit_code == 0, stderr

    out_file = out_dir / "cue.gqcue"
    assert out_file.exists()
    with open(out_file, "rb") as f:
        cue = pickle.load(f)
    assert len(cue.frames) == 1


def test_mkcue_cli_exits_nonzero_on_duration_over_max(tmp_path):
    source = (
        "frame {\n"
        "    duration = 70000;\n"
        "    colors { red, orange, yellow, green, blue }\n"
        "}\n"
    )
    src_path = tmp_path / "cue.gqcue"
    src_path.write_text(source)
    out_dir = tmp_path / "build" / "cue"

    exit_code, stderr = _run_cli(tmp_path, ["mkcue", "-o", str(out_dir), "-i", str(src_path)])
    assert exit_code != 0
    assert "65535" in stderr
