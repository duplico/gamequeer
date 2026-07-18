import pathlib
import shutil
import subprocess
import sys

import pytest

COMPILE_TIMEOUT_S = 60


def pytest_collection_modifyitems(config, items):
    """Skip `ffmpeg`-marked tests when there's no real ffmpeg binary on
    PATH, rather than letting them fail with a raw FileNotFoundError.
    CI installs ffmpeg explicitly for this job (see ci.yml) so this only
    bites local runs without it."""
    if shutil.which("ffmpeg"):
        return
    skip_no_ffmpeg = pytest.mark.skip(reason="ffmpeg not found on PATH")
    for item in items:
        if "ffmpeg" in item.keywords:
            item.add_marker(skip_no_ffmpeg)


@pytest.fixture
def compile_gq(tmp_path):
    """Compile a .gq source string with `python -m gqc compile`, run as a
    subprocess in a hermetic temp CWD.

    gqc keeps all of its compiled-program state (symbol tables, name
    registries, etc.) in class-level attributes rather than passing it
    through function arguments, because the CLI is only ever invoked once
    per process. Driving the real CLI as a subprocess sidesteps that
    entirely: every call gets a fresh interpreter and therefore fresh
    state, at the cost of one process spawn (~0.3-0.5s) per test.

    Returns a `(exit_code, stderr, out_dir)` tuple. `out_dir` is the
    directory gqc was told to write its build output to (it may not exist,
    or may be incomplete, if compilation failed).

    The subprocess is bounded by a `COMPILE_TIMEOUT_S`-second timeout; a
    hung compile fails the test via `pytest.fail` instead of hanging the
    whole suite (and CI) indefinitely.

    Args:
        source: the .gq source text to compile.
        assets: optional dict mapping a path relative to the hermetic CWD
            (e.g. "assets/animations/foo.gif") to a source file to copy
            into that location before compiling. Needed for anything that
            references an animation or lightcue file, since gqc resolves
            those relative to its CWD.
        game_name: base name for the source file and output directory;
            doesn't need to match anything in the source itself.
        extra_args: additional CLI arguments appended after the input file.
    """

    def _compile_gq(
        source: str,
        assets: dict[str, pathlib.Path] | None = None,
        game_name: str = "game",
        extra_args: list[str] | None = None,
    ) -> tuple[int, str, pathlib.Path]:
        src_path = tmp_path / f"{game_name}.gq"
        src_path.write_text(source)

        for rel_path, asset_src in (assets or {}).items():
            dest_path = tmp_path / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(asset_src, dest_path)

        out_dir = tmp_path / "build" / game_name
        cmd = [sys.executable, "-m", "gqc", "compile", "-o", str(out_dir), str(src_path)]
        if extra_args:
            cmd.extend(extra_args)

        try:
            proc = subprocess.run(
                cmd,
                cwd=tmp_path,
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

        return proc.returncode, proc.stderr, out_dir

    return _compile_gq
