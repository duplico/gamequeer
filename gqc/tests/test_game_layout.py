"""Game-as-directory layout suite for gqc (gamequeer#420, part of the DEF
CON sprint epic gamequeer#419).

Covers the two structural pieces #420 delivers (multi-file source
concat/merge is explicitly out of scope here -- that's gamequeer#401):

  - `game{}` may now appear anywhere in the top-level section stream,
    instead of being structurally locked to first -- with "exactly one"
    enforced semantically: a second one is still rejected by
    Game.__init__'s existing "Game already defined" check (unchanged from
    before #420), and a missing one is now rejected by a new check in
    parser.parse() (previously impossible: the grammar itself required
    game_definition_section as the first, mandatory token).

  - `animations{}`/`lightcues{}` asset sources resolve relative to the
    game's own directory (the entry `.gq` file's parent -- gqc.py's
    `compile` sets Game.game_dir from it), not the process CWD, so a game
    directory is self-contained regardless of where `gqc compile` is
    invoked from. `gqc new` scaffolds a fresh game directory in that shape.

The "anywhere" cases also exercise order-dependency traps that moving game{}
out of its fixed first slot exposed (see datamodel.py's Stage,
Game.__init__/add_stage, and parser.parse_fw_version_operand/
parse_random_operand): Stage.__init__ used to call Game.game.add_stage(self)
unconditionally, and parse_fw_version_operand/parse_random_operand used to
write straight to Game.game.needs_fw_probe/Game.game.needs_random -- all
three would crash with AttributeError on `NoneType` if the stage in question
was parsed before game{} itself.

gqc has exactly one asset-resolution rule: `animations{}`/`lightcues{}`
sources always resolve relative to the entry file's own parent directory
(`Game.game_dir = input.parent`), i.e. the game-as-directory layout only.
There is no CWD-relative fallback for a flat entry file -- see
test_animation_source_at_old_cwd_relative_location_is_not_found and its
lightcue counterpart below, and migrate.py's `gqc migrate` for moving an
old flat-layout game onto this layout.
"""

import io
import pathlib
import shutil
import subprocess
import sys

import pytest
from PIL import Image

from gqc import parser
from gqc.datamodel import Game

from .support import reset_compiler_state

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CIRCLE_BMP = REPO_ROOT / "gqc" / "examples" / "skel" / "assets" / "animations" / "circle.bmp"
TEST_GQCUE = REPO_ROOT / "examples" / "assets" / "lighting" / "test.gqcue"

GAME_HEADER = 'game { id = 1; title := "T"; author := "A"; starting_stage = start; }\n'
STAGE = "stage start { event enter { } }\n"

COMPILE_TIMEOUT_S = 60


def _run(cwd, args, timeout=COMPILE_TIMEOUT_S):
    proc = subprocess.run(
        [sys.executable, "-m", "gqc", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stderr, proc.stdout


def _unwrapped(stderr: str) -> str:
    # `parser.parse`'s error path prints via `rich.print`, which soft- (and,
    # for a single long token like an absolute resolved path, hard-) wraps
    # output to the console width whenever stderr isn't a real terminal --
    # always true here, under a capture_output subprocess. That can inject a
    # bare "\n" in the *middle* of a path component (e.g. "animatio\nns"),
    # so a substring check against the raw text is flaky depending on the
    # tmp_path's length. Stripping newlines recovers the original text,
    # since rich's hard-wrap never inserts a space, only "\n".
    return stderr.replace("\n", "")


# --- game{}: anywhere in the top-level section stream (accept) --------------


def test_game_block_after_stage_accepts(compile_gq):
    source = STAGE + GAME_HEADER
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_game_block_between_other_sections_accepts(compile_gq):
    source = "volatile { int x = 0; }\n" + GAME_HEADER + STAGE
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_game_block_last_accepts(compile_gq):
    source = STAGE + "volatile { int x = 0; }\n" + GAME_HEADER
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr


def test_starting_stage_defined_before_game_block_resolves(compile_gq):
    # Regression guard: Stage.__init__ used to call Game.game.add_stage(self)
    # unconditionally -- an AttributeError on `NoneType` if `stage start`
    # (the game's own declared starting_stage) was parsed before game{}
    # existed. A clean (exit 0) compile here also proves Game.starting_stage
    # actually ended up resolved: Game.to_bytes() raises a hard
    # "Starting stage not defined" ValueError otherwise, which would surface
    # as a non-zero exit / traceback, not a clean compile.
    source = STAGE + GAME_HEADER
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr
    assert "Traceback" not in stderr


def test_fw_version_call_before_game_block_accepts(compile_gq):
    # Regression guard: parse_fw_version_operand used to write straight to
    # Game.game.needs_fw_probe -- an AttributeError on `NoneType` if the
    # calling stage was parsed before game{} existed (see
    # Game.needs_fw_probe_seen in datamodel.py, which makes this order-
    # independent).
    source = (
        "stage start { event enter { x = fw_version(); } }\n"
        + GAME_HEADER
        + "volatile { int x = 0; }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr
    assert "Traceback" not in stderr


def test_random_call_before_game_block_accepts(compile_gq):
    # Regression guard (gamequeer#427, Copilot finding): parse_random_operand
    # used to write straight to Game.game.needs_random -- an AttributeError
    # on `NoneType` if the calling stage was parsed before game{} existed,
    # same hazard as fw_version() above (see Game.needs_random_seen in
    # datamodel.py, which makes this order-independent too).
    source = (
        "stage start { event enter { x = random(0, 10); } }\n"
        + GAME_HEADER
        + "volatile { int x = 0; }\n"
    )
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code == 0, stderr
    assert "Traceback" not in stderr


# --- game{}: exactly-one cardinality (reject) --------------------------------


def test_duplicate_game_blocks_reject(compile_gq):
    # Two separate game{} sections (as opposed to test_grammar.py's
    # test_game_block_duplicate_key_rejects, which is a duplicate *key*
    # inside a single game{} block -- an unrelated case). Still caught
    # structurally by Game.__init__, unchanged by gamequeer#420.
    source = GAME_HEADER + STAGE + GAME_HEADER
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "Game already defined" in stderr


def test_missing_game_block_rejects(compile_gq):
    # No game{} block anywhere. Before gamequeer#420 this was impossible to
    # reach cleanly: the grammar itself required game_definition_section
    # first, so this failed as a raw pyparsing ParseSyntaxException instead
    # of the dedicated check parser.parse() now performs once top-level
    # parsing otherwise succeeds.
    source = STAGE
    exit_code, stderr, _ = compile_gq(source)
    assert exit_code != 0
    assert "game" in stderr.lower()
    assert "Traceback" not in stderr


# --- animations{}/lightcues{}: game-directory-relative asset resolution -----


def _write_game_dir(base_dir: pathlib.Path, name: str, decls: str) -> pathlib.Path:
    game_dir = base_dir / name
    game_dir.mkdir(parents=True)
    (game_dir / f"{name}.gq").write_text(
        f"{GAME_HEADER}{decls}\n{STAGE}"
    )
    return game_dir


def test_animation_source_resolves_relative_to_game_dir_not_cwd(tmp_path):
    # The game directory (mygame/) is *not* the invocation CWD (tmp_path,
    # its parent) -- only Game.game_dir (derived from the entry file's own
    # path, gqc.py's `compile`) should matter for resolving `<- "circle.bmp"`.
    game_dir = _write_game_dir(
        tmp_path, "mygame", 'animations { c <- "circle.bmp"; }\n'
    )
    assets_dir = game_dir / "assets" / "animations"
    assets_dir.mkdir(parents=True)
    shutil.copyfile(CIRCLE_BMP, assets_dir / "circle.bmp")

    out_dir = tmp_path / "build"
    exit_code, stderr, _ = _run(
        tmp_path,
        ["compile", "-o", str(out_dir), str(game_dir / "mygame.gq")],
    )
    assert exit_code == 0, stderr


def test_animation_source_at_old_cwd_relative_location_is_not_found(tmp_path):
    # Negative control for the case above: an asset sitting at the *old*
    # CWD-relative assets/animations/ location (the invocation CWD, not the
    # game directory) must no longer be found -- pins that gamequeer#420
    # actually changed the resolution root rather than just adding a
    # fallback.
    game_dir = _write_game_dir(
        tmp_path, "mygame", 'animations { c <- "circle.bmp"; }\n'
    )
    old_style_assets_dir = tmp_path / "assets" / "animations"
    old_style_assets_dir.mkdir(parents=True)
    shutil.copyfile(CIRCLE_BMP, old_style_assets_dir / "circle.bmp")

    out_dir = tmp_path / "build"
    exit_code, stderr, _ = _run(
        tmp_path,
        ["compile", "-o", str(out_dir), str(game_dir / "mygame.gq")],
    )
    assert exit_code != 0
    unwrapped = _unwrapped(stderr)
    assert "circle.bmp" in unwrapped
    # gqc has no CWD-relative fallback, so this is exactly the "old flat
    # game, assets not moved yet" case the migrate hint below exists for.
    assert "gqc migrate mygame" in unwrapped


def test_lightcue_source_resolves_relative_to_game_dir_not_cwd(tmp_path):
    game_dir = _write_game_dir(
        tmp_path, "mygame", 'lightcues { c1 <- "test.gqcue"; }\n'
    )
    assets_dir = game_dir / "assets" / "lighting"
    assets_dir.mkdir(parents=True)
    shutil.copyfile(TEST_GQCUE, assets_dir / "test.gqcue")

    out_dir = tmp_path / "build"
    exit_code, stderr, _ = _run(
        tmp_path,
        ["compile", "-o", str(out_dir), str(game_dir / "mygame.gq")],
    )
    assert exit_code == 0, stderr


def test_lightcue_source_at_old_cwd_relative_location_is_not_found(tmp_path):
    game_dir = _write_game_dir(
        tmp_path, "mygame", 'lightcues { c1 <- "test.gqcue"; }\n'
    )
    old_style_assets_dir = tmp_path / "assets" / "lighting"
    old_style_assets_dir.mkdir(parents=True)
    shutil.copyfile(TEST_GQCUE, old_style_assets_dir / "test.gqcue")

    out_dir = tmp_path / "build"
    exit_code, stderr, _ = _run(
        tmp_path,
        ["compile", "-o", str(out_dir), str(game_dir / "mygame.gq")],
    )
    assert exit_code != 0
    unwrapped = _unwrapped(stderr)
    assert "test.gqcue" in unwrapped
    assert "gqc migrate mygame" in unwrapped


# --- missing-asset diagnostic: `gqc migrate` hint ---------------------------


def test_missing_animation_asset_mentions_resolved_path_and_migrate_hint(compile_gq):
    # compile_gq puts the entry file directly at its hermetic CWD (no
    # "assets/" subdirectory created), so this is the plain missing-asset
    # case -- no relocation trickery needed to trigger it.
    exit_code, stderr, _ = compile_gq(
        GAME_HEADER + 'animations { c <- "circle.bmp"; }\n' + STAGE,
        game_name="mygame",
    )
    assert exit_code != 0
    unwrapped = _unwrapped(stderr)
    # The resolved (game-dir-relative) path, not just the bare filename --
    # an author needs to see *where* gqc looked.
    assert str(pathlib.Path("assets") / "animations" / "circle.bmp") in unwrapped
    assert "does not exist" in unwrapped
    assert "gqc migrate mygame" in unwrapped


def test_missing_lightcue_asset_mentions_resolved_path_and_migrate_hint(compile_gq):
    exit_code, stderr, _ = compile_gq(
        GAME_HEADER + 'lightcues { c1 <- "test.gqcue"; }\n' + STAGE,
        game_name="mygame",
    )
    assert exit_code != 0
    unwrapped = _unwrapped(stderr)
    assert str(pathlib.Path("assets") / "lighting" / "test.gqcue") in unwrapped
    assert "not found" in unwrapped
    assert "gqc migrate mygame" in unwrapped


def test_missing_lightcue_asset_migrate_hint_falls_back_when_game_name_unset(
    tmp_path, monkeypatch, capsys
):
    # Regression guard (Copilot-suppressed finding on #437, not surfaced as
    # an inline review comment): _migrate_hint interpolates Game.game_name
    # into the "gqc migrate <name>" hint, but gqc.py's `compile` command is
    # the only thing that ever sets it -- an in-process caller that drives
    # parser.parse() directly via support.reset_compiler_state() (as
    # test_assets.py and others do) leaves it at its class default of None.
    # Confirms the hint degrades to generic phrasing instead of rendering
    # the literal string "None" into the message.
    monkeypatch.chdir(tmp_path)
    reset_compiler_state()
    source = GAME_HEADER + 'lightcues { c1 <- "test.gqcue"; }\n' + STAGE

    with pytest.raises(SystemExit) as exc_info:
        parser.parse(io.StringIO(source))
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    unwrapped = captured.err.replace("\n", "")
    assert "None" not in unwrapped
    assert "this game" in unwrapped
    assert "gqc migrate <name>" in unwrapped


def test_lightcue_open_failure_after_exists_check_gives_clean_diagnostic(
    tmp_path, monkeypatch, capsys
):
    # Regression guard (Copilot review, gamequeer#437): the lightcue
    # exists() check doesn't guard the open() right below it -- an
    # unreadable path (or one removed between the check and the open) used
    # to surface as a raw, unhandled OSError traceback instead of the same
    # kind of clean diagnostic a plain "not found" gets. A directory
    # sitting at the lightcue source path reproduces this deterministically
    # without needing to race anything: Path.exists() is True for a
    # directory, but open(dir_path, "r") raises IsADirectoryError.
    monkeypatch.chdir(tmp_path)
    reset_compiler_state()
    Game.game_name = "mygame"
    (tmp_path / "assets" / "lighting" / "test.gqcue").mkdir(parents=True)
    source = GAME_HEADER + 'lightcues { c1 <- "test.gqcue"; }\n' + STAGE

    with pytest.raises(SystemExit) as exc_info:
        parser.parse(io.StringIO(source))
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    unwrapped = _unwrapped(captured.err)
    assert "Traceback" not in unwrapped
    assert "could not be opened" in unwrapped


def test_missing_asset_diagnostic_is_silent_when_asset_present(compile_gq):
    # Companion positive control: the hint text is specific to a missing
    # asset, not appended to every compile's stderr unconditionally.
    exit_code, stderr, _ = compile_gq(
        GAME_HEADER + 'animations { c <- "circle.bmp"; }\n' + STAGE,
        assets={"assets/animations/circle.bmp": CIRCLE_BMP},
        game_name="mygame",
    )
    assert exit_code == 0, stderr
    assert "gqc migrate" not in stderr


def test_missing_animation_asset_after_digest_cache_hit_gives_diagnostic_not_traceback(
    compile_gq, tmp_path
):
    # Regression guard (gamequeer#437 review): Animation.__init__'s
    # digest-cache *hit* branch (build/ is CWD-relative, independent of -o
    # -- see its dst_path) reads self.digest(), which opens self.src_path
    # directly, without going through anim.make_animation's own existence
    # check -- that's only reached on a cache *miss*. Recompiling against a
    # stale cache after the source asset has moved or been deleted (e.g. a
    # still-flat game whose assets were never migrated) used to surface as
    # a raw, unhandled FileNotFoundError traceback instead of the same
    # GqcAssetNotFoundError + `gqc migrate` diagnostic a fresh (no-cache)
    # compile gets.
    source = GAME_HEADER + 'animations { c <- "circle.bmp"; }\n' + STAGE
    asset_path = tmp_path / "assets" / "animations" / "circle.bmp"

    # First compile succeeds and leaves a digest cache behind.
    exit_code, stderr, _ = compile_gq(
        source,
        assets={"assets/animations/circle.bmp": CIRCLE_BMP},
        game_name="mygame",
    )
    assert exit_code == 0, stderr
    assert asset_path.exists()

    # Remove the asset and recompile with the stale cache still present.
    asset_path.unlink()
    exit_code, stderr, _ = compile_gq(source, game_name="mygame")
    assert exit_code != 0
    unwrapped = _unwrapped(stderr)
    assert "Traceback" not in unwrapped
    assert "does not exist" in unwrapped
    assert "gqc migrate mygame" in unwrapped


# --- `gqc new`: scaffolding a fresh game-as-directory game -------------------


def test_new_scaffolds_entry_file_and_asset_subdirs(tmp_path):
    exit_code, stderr, _ = _run(tmp_path, ["new", "mygame"])
    assert exit_code == 0, stderr

    game_dir = tmp_path / "mygame"
    assert (game_dir / "mygame.gq").exists()
    assert (game_dir / "assets" / "animations").is_dir()
    assert (game_dir / "assets" / "lighting").is_dir()


def test_new_scaffolded_entry_file_compiles(tmp_path):
    exit_code, stderr, _ = _run(tmp_path, ["new", "mygame"])
    assert exit_code == 0, stderr

    out_dir = tmp_path / "build"
    exit_code, stderr, _ = _run(
        tmp_path,
        ["compile", "-o", str(out_dir), str(tmp_path / "mygame" / "mygame.gq")],
    )
    assert exit_code == 0, stderr
    assert (out_dir / "mygame.gqgame").exists()


def test_new_refuses_to_overwrite_existing_game_without_force(tmp_path):
    exit_code, _, _ = _run(tmp_path, ["new", "mygame"])
    assert exit_code == 0

    entry_path = tmp_path / "mygame" / "mygame.gq"
    entry_path.write_text("MODIFIED")

    exit_code, stderr, stdout = _run(tmp_path, ["new", "mygame"])
    assert exit_code == 0  # click command itself doesn't fail; it just declines
    assert entry_path.read_text() == "MODIFIED"
    assert "already exists" in stdout + stderr


def test_new_force_overwrites_existing_game(tmp_path):
    exit_code, _, _ = _run(tmp_path, ["new", "mygame"])
    assert exit_code == 0

    entry_path = tmp_path / "mygame" / "mygame.gq"
    entry_path.write_text("MODIFIED")

    exit_code, stderr, _ = _run(tmp_path, ["new", "mygame", "--force"])
    assert exit_code == 0, stderr
    assert entry_path.read_text() != "MODIFIED"


# --- `gqc init-dir` / `gqc update-makefile-local`: workspace scaffolding ----
#
# Both commands used to only know the flat games/**/*.gq convention
# (`makefile_src.py`'s generated Makefile shelled out to
# `find $(BASE_DIR)/games -name "*.gq"`; `update_makefile_local` recursively
# scanned the same `games/` subtree) -- a workspace scaffolded with
# `init-dir` couldn't actually build a `gqc new`-scaffolded game without a
# hand-maintained Makefile (see gq-games's own Makefile, gq-games#54, for
# the worked example this now mirrors). Both now discover the
# game-as-directory convention (gamequeer#420) directly: any top-level
# `<name>/<name>.gq` under the workspace root is a game.


def _require_make():
    if shutil.which("make") is None:
        pytest.skip("make not found on PATH")


def _make(cwd, *args, timeout=COMPILE_TIMEOUT_S):
    _require_make()
    proc = subprocess.run(
        ["make", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_init_dir_scaffolds_no_flat_games_dir(tmp_path):
    exit_code, stderr, _ = _run(tmp_path, ["init-dir", str(tmp_path)])
    assert exit_code == 0, stderr

    assert not (tmp_path / "games").exists()
    assert not (tmp_path / "assets").exists()
    assert (tmp_path / "build").is_dir()
    assert (tmp_path / "Makefile").exists()
    assert (tmp_path / ".gitignore").exists()
    # The generated Makefile is self-sufficient (discovers games live via
    # GNU Make) -- no stub Makefile.local is dropped alongside it.
    assert not (tmp_path / "Makefile.local").exists()


def test_init_dir_makefile_discovers_directory_layout_not_flat_games_glob(tmp_path):
    exit_code, stderr, _ = _run(tmp_path, ["init-dir", str(tmp_path)])
    assert exit_code == 0, stderr

    makefile = (tmp_path / "Makefile").read_text()
    assert "games -name" not in makefile
    assert "$(wildcard $(BASE_DIR)/*/)" in makefile
    assert "update-makefile-local" not in makefile


def test_init_dir_then_make_on_empty_workspace_is_a_sane_noop(tmp_path):
    exit_code, stderr, _ = _run(tmp_path, ["init-dir", str(tmp_path)])
    assert exit_code == 0, stderr

    exit_code, stdout, stderr = _make(tmp_path)
    assert exit_code == 0, stderr
    assert not list((tmp_path / "build").iterdir())


def test_init_dir_new_and_make_builds_the_scaffolded_game(tmp_path):
    # End-to-end: `gqc init-dir`, then `gqc new` a game inside the
    # scaffolded workspace, then a real `make` (no gqc invocation at all)
    # must discover and compile it.
    exit_code, stderr, _ = _run(tmp_path, ["init-dir", str(tmp_path)])
    assert exit_code == 0, stderr

    exit_code, stderr, _ = _run(tmp_path, ["new", "demo"])
    assert exit_code == 0, stderr

    exit_code, stdout, stderr = _make(tmp_path)
    assert exit_code == 0, stderr

    gqgame = tmp_path / "build" / "demo" / "demo.gqgame"
    assert gqgame.exists()

    # Re-running `make` with nothing changed does no work (the .gqgame is
    # already up to date relative to its one tracked prerequisite).
    exit_code, stdout, stderr = _make(tmp_path)
    assert exit_code == 0, stderr
    assert "Nothing to be done" in stdout or "up to date" in stdout


def test_init_dir_make_ignores_non_game_top_level_directories(tmp_path):
    # A top-level directory that isn't itself a game (no same-named .gq
    # inside it) must be silently skipped, not mistaken for one.
    exit_code, stderr, _ = _run(tmp_path, ["init-dir", str(tmp_path)])
    assert exit_code == 0, stderr

    (tmp_path / "tools" / "common").mkdir(parents=True)
    (tmp_path / "tools" / "common" / "helper.py").write_text("# not a game\n")

    exit_code, stderr, _ = _run(tmp_path, ["new", "demo"])
    assert exit_code == 0, stderr

    exit_code, stdout, stderr = _make(tmp_path)
    assert exit_code == 0, stderr
    assert (tmp_path / "build" / "demo" / "demo.gqgame").exists()
    assert not (tmp_path / "build" / "tools").exists()


def test_update_makefile_local_discovers_directory_layout(tmp_path):
    exit_code, stderr, _ = _run(tmp_path, ["new", "demo"])
    assert exit_code == 0, stderr

    exit_code, stderr, _ = _run(tmp_path, ["update-makefile-local", str(tmp_path)])
    assert exit_code == 0, stderr

    makefile_local = (tmp_path / "Makefile.local").read_text()
    assert "build/demo/demo.gqgame: demo/demo.gq" in makefile_local
    assert "games/" not in makefile_local


def test_update_makefile_local_on_workspace_with_no_games_is_sane(tmp_path):
    exit_code, stderr, _ = _run(tmp_path, ["update-makefile-local", str(tmp_path)])
    assert exit_code == 0, stderr

    makefile_local = tmp_path / "Makefile.local"
    assert makefile_local.exists()
    assert makefile_local.read_text().strip().endswith("all:")

    # A plain `make -f` against the generated fragment must not error just
    # because there's nothing to build.
    exit_code, stdout, stderr = _make(tmp_path, "-f", "Makefile.local")
    assert exit_code == 0, stderr


def test_update_makefile_local_on_nonexistent_dir_gives_clean_diagnostic(tmp_path):
    # Regression guard (Copilot review, PR #444): BASE_DIR previously had no
    # exists=True check, so a typo'd/nonexistent path raised a raw
    # FileNotFoundError from `(base_dir / 'Makefile.local').open('w')`
    # instead of click's normal usage-error diagnostic.
    missing = tmp_path / "does-not-exist"
    exit_code, stderr, _ = _run(tmp_path, ["update-makefile-local", str(missing)])
    assert exit_code != 0
    assert "does not exist" in stderr
    assert "Traceback" not in stderr


def test_init_dir_makefile_clean_targets_base_dir_not_cwd(tmp_path):
    # Regression guard (Copilot review, PR #444): `clean`'s `-rm -rf build/*`
    # used to be relative to whatever directory `make` was invoked from,
    # not $(BASE_DIR) -- inconsistent with every other rule in the file,
    # which is BASE_DIR-rooted so it works regardless of invocation CWD.
    exit_code, stderr, _ = _run(tmp_path, ["init-dir", str(tmp_path)])
    assert exit_code == 0, stderr

    exit_code, stderr, _ = _run(tmp_path, ["new", "demo"])
    assert exit_code == 0, stderr

    exit_code, stdout, stderr = _make(tmp_path)
    assert exit_code == 0, stderr
    gqgame = tmp_path / "build" / "demo" / "demo.gqgame"
    assert gqgame.exists()

    # Invoke `clean` from an unrelated CWD via `-f <path>` (not `-C`, which
    # would just chdir into tmp_path first and mask the bug); it must still
    # remove tmp_path's own build/ output, not create/empty a bogus one
    # relative to the unrelated CWD.
    other_cwd = tmp_path.parent
    exit_code, stdout, stderr = _make(other_cwd, "-f", str(tmp_path / "Makefile"), "clean")
    assert exit_code == 0, stderr
    assert not gqgame.exists()
    assert not (other_cwd / "build").exists()
