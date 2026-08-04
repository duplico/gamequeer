"""Golden byte-regression suite for gamequeer#333 (epic #329).

Recompiles every committed golden fixture under `gamequeer/tests/golden/*.gq`
(enumerated dynamically, so a new fixture is picked up with no edit here)
plus `examples/tutorial_1/tutorial_1.gq`, and byte-compares the result
against the already-committed `.gqgame` next to each source. This is the same
guarantee `make golden-fixture` gives a human running it by hand, just
automated and run on every PR -- it catches any gqc behavior change the
C-side pixel/CSV golden suites (gamequeer#268/#270/#275/#339) can't see (they
only run against whatever `.gqgame` happens to be checked in), and it also
catches source/cart drift: someone editing a `.gq` fixture without
regenerating its `.gqgame`.

Each fixture is compiled as a subprocess (`python -m gqc compile`), matching
test_grammar.py's `compile_gq` fixture: gqc keeps its compiled-program state
in class-level registries meant to be used once per process (see
tests/support.py), so a subprocess per fixture is the simplest way to get
fresh state without reimplementing that reset logic here. Unlike
`compile_gq`, this suite compiles the real committed sources in place
(read-only) rather than copying a source string into a hermetic tmp_path,
because gqc resolves `<- "foo.gif"` / `<- "foo.png"` animation sources and
`<- "foo.gqcue"` lightcue sources relative to `<input.gq>`'s own parent
directory (gamequeer#420/#440), not the process CWD -- but a relative
`<input.gq>` argument (used here, see `cmd` below) itself resolves against
the subprocess's CWD, so the effect is the same: each fixture is compiled
with `cwd` set to its own directory (`gamequeer/tests/golden` for the C-VM
fixtures, `examples/tutorial_1` for tutorial_1.gq -- both game-as-directory-
shaped). Only the *output* directory is a tmp_path -- the committed
`.gqgame` files themselves are never overwritten by a test run.

ffmpeg-gating: `gqc/src/gqc/anim.py` only routes an animation source through
its `ffmpeg-python` binding when the source isn't a still image (`.bmp`,
`.png`, `.jpg`, `.jpeg`, handled by Pillow instead) -- in practice that means
`.gif` sources. The `.gqgame` bytes for a `.gif`-sourced fixture were
captured against the gamequeer-builder image's pinned ffmpeg build (Debian
bullseye's apt package, 4.3.9-0+deb11u2 as of this writing) -- a different
ffmpeg build (a bare CI runner's newer apt package, a developer's own
workstation build) decodes/dithers that same source slightly differently
and produces a harmlessly different, but still byte-different, cart. PNG
(and other Pillow-handled) sources have no such dependency and always run.
Rather than have the per-PR CI leg's pytest invocation carry a
`-m "not (golden and ffmpeg)"` deselection someone has to remember to keep
in sync with this file, each `.gif`-sourced case here is individually
`skipif`-gated on the ffmpeg build actually detected on PATH: it only runs
the byte-compare when that build is bullseye's 4.3.x, and skips (rather than
false-reds) everywhere else, including the existing per-PR `gqc-tests` CI
job, which already installs a newer ffmpeg via apt for the unrelated
`ffmpeg`-marked grammar tests in test_grammar.py. The nightly job (see
ci.yml) runs entirely inside the gamequeer-builder image, so these cases
execute -- and byte-compare -- there.
"""

import functools
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.golden

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "gamequeer" / "tests" / "golden"
EXAMPLES_DIR = REPO_ROOT / "examples"

COMPILE_TIMEOUT_S = 120

# Matches gqc's animation-source syntax when the source is a format
# anim.py routes through ffmpeg rather than Pillow, e.g.
# `hearts <- "heart_anim.gif";`. `.png`/`.jpg`/`.jpeg`/`.bmp` animation
# sources and `.gqcue` lightcue sources deliberately don't match: neither
# pipeline touches ffmpeg (see anim.py's `make_animation`).
_FFMPEG_ASSET_REF_RE = re.compile(r'<-\s*"[^"]+\.gif"', re.IGNORECASE)

_FFMPEG_VERSION_RE = re.compile(r"^ffmpeg version (\S+)")
_BUILDER_FFMPEG_MAJOR_MINOR = "4.3"


def _references_ffmpeg_asset(gq_path: pathlib.Path) -> bool:
    return bool(_FFMPEG_ASSET_REF_RE.search(gq_path.read_text()))


@functools.lru_cache(maxsize=1)
def _ffmpeg_version() -> str | None:
    """The `ffmpeg -version` first-line version token for whatever ffmpeg
    is on PATH, or None if there isn't one. Cached: the ffmpeg on PATH
    doesn't change mid-run, and this is called once per ffmpeg-referencing
    fixture during collection (plus once more per case to build its skip
    reason) -- no need to re-spawn `ffmpeg -version` each time."""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return None
    try:
        out = subprocess.run(
            [ffmpeg_path, "-version"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = _FFMPEG_VERSION_RE.match(out)
    return match.group(1) if match else None


def _has_builder_ffmpeg() -> bool:
    version = _ffmpeg_version()
    return version is not None and version.startswith(_BUILDER_FFMPEG_MAJOR_MINOR)


def _fixture_param(gq_path: pathlib.Path, cwd: pathlib.Path):
    marks = [pytest.mark.golden]
    if _references_ffmpeg_asset(gq_path):
        detected = _ffmpeg_version() or "no ffmpeg on PATH"
        marks += [
            pytest.mark.ffmpeg,
            pytest.mark.skipif(
                not _has_builder_ffmpeg(),
                reason=(
                    "byte-exact golden compare needs the gamequeer-builder "
                    f"image's pinned ffmpeg {_BUILDER_FFMPEG_MAJOR_MINOR}.x "
                    f"build (found {detected}); see this module's docstring"
                ),
            ),
        ]
    return pytest.param(gq_path, cwd, id=gq_path.stem, marks=marks)


def _golden_fixture_params() -> list:
    params = [_fixture_param(p, GOLDEN_DIR) for p in sorted(GOLDEN_DIR.glob("*.gq"))]
    tutorial_1_dir = EXAMPLES_DIR / "tutorial_1"
    params.append(_fixture_param(tutorial_1_dir / "tutorial_1.gq", tutorial_1_dir))
    return params


def _mismatch_message(gq_path: pathlib.Path, expected: bytes, actual: bytes) -> str:
    if len(expected) != len(actual):
        return (
            f"{gq_path.name}: recompiled cart is {len(actual)} bytes, "
            f"committed cart is {len(expected)} bytes"
        )
    for offset, (exp_byte, act_byte) in enumerate(zip(expected, actual)):
        if exp_byte != act_byte:
            return (
                f"{gq_path.name}: first byte mismatch at offset {offset} "
                f"(committed=0x{exp_byte:02x}, recompiled=0x{act_byte:02x}), "
                f"{len(expected)} bytes total"
            )
    return f"{gq_path.name}: byte mismatch (could not localize -- lengths and content matched?)"


@pytest.mark.parametrize("gq_path, cwd", _golden_fixture_params())
def test_golden_compile_byte_exact(gq_path, cwd, tmp_path):
    committed_cart = gq_path.with_suffix(".gqgame")
    assert committed_cart.exists(), f"no committed golden cart at {committed_cart}"

    out_dir = tmp_path / "build"
    cmd = [
        sys.executable,
        "-m",
        "gqc",
        "compile",
        "--no-mem-map",
        "-o",
        str(out_dir),
        str(gq_path.relative_to(cwd)),
    ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            f"gqc compile did not finish within {COMPILE_TIMEOUT_S}s "
            f"(cmd={cmd!r}); stdout so far: {exc.stdout!r}; "
            f"stderr so far: {exc.stderr!r}"
        )

    assert proc.returncode == 0, f"{gq_path.name}: gqc compile failed:\n{proc.stderr}"

    recompiled_cart = out_dir / f"{gq_path.stem}.gqgame"
    assert recompiled_cart.exists(), (
        f"{gq_path.name}: gqc compile exited 0 but produced no "
        f"{recompiled_cart.name}"
    )

    expected = committed_cart.read_bytes()
    actual = recompiled_cart.read_bytes()
    assert actual == expected, _mismatch_message(gq_path, expected, actual)
