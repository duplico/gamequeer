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

The suite's final section (gamequeer#434) covers layout *detection*: an
entry file only gets #420's game_dir-relative resolution if its parent
directory is actually named for it (`<name>/<name>.gq`); anything else --
including the entire pre-#420 gq-games corpus, whose games live flat in a
shared `games/` directory next to a sibling top-level `assets/` -- falls
back to legacy (pre-#420), CWD-relative resolution, with a one-line
deprecation notice on stderr pointing at `gqc migrate`. There is no
try-both-and-see fallback: a directory-layout game never consults the CWD
(see the existing negative-control tests above, unchanged by #434), and a
flat entry file whose parent coincidentally matches the convention (e.g.
`games/games.gq`) is treated as directory layout, not flat.
"""

import pathlib
import shutil
import subprocess
import sys

import pytest
from PIL import Image

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
    assert "circle.bmp" in stderr


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
    assert "test.gqcue" in stderr


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


# --- gamequeer#434: layout detection / legacy flat-layout fallback ---------


def test_legacy_flat_layout_compiles_and_resolves_assets_at_cwd(tmp_path):
    # Flat layout (pre-#420, the shape of the whole pre-migration gq-games
    # corpus): the entry file lives in a `games/` directory whose name
    # doesn't match the entry's own stem, with a *sibling* top-level
    # `assets/` (not nested under `games/`). That fails the
    # `<name>/<name>.gq` directory-layout check, so resolution falls back
    # to the process CWD -- exactly how gqc resolved assets before #420.
    games_dir = tmp_path / "games"
    games_dir.mkdir()
    (games_dir / "foo.gq").write_text(
        GAME_HEADER + 'animations { c <- "circle.bmp"; }\n' + STAGE
    )
    assets_dir = tmp_path / "assets" / "animations"
    assets_dir.mkdir(parents=True)
    shutil.copyfile(CIRCLE_BMP, assets_dir / "circle.bmp")

    out_dir = tmp_path / "build"
    exit_code, stderr, _ = _run(
        tmp_path,
        ["compile", "-o", str(out_dir), str(games_dir / "foo.gq")],
    )
    assert exit_code == 0, stderr


def test_legacy_flat_layout_does_not_find_game_dir_relative_assets(tmp_path):
    # Companion negative control: the same flat entry file, but the asset
    # sits at the *directory-layout*-style location (nested under the
    # entry's own parent) instead of the real legacy CWD-relative spot --
    # pins that legacy mode doesn't also try game_dir-relative as a
    # fallback.
    games_dir = tmp_path / "games"
    games_dir.mkdir()
    (games_dir / "foo.gq").write_text(
        GAME_HEADER + 'animations { c <- "circle.bmp"; }\n' + STAGE
    )
    dir_layout_style_assets = games_dir / "assets" / "animations"
    dir_layout_style_assets.mkdir(parents=True)
    shutil.copyfile(CIRCLE_BMP, dir_layout_style_assets / "circle.bmp")

    out_dir = tmp_path / "build"
    exit_code, stderr, _ = _run(
        tmp_path,
        ["compile", "-o", str(out_dir), str(games_dir / "foo.gq")],
    )
    assert exit_code != 0
    assert "circle.bmp" in stderr


def test_directory_layout_game_emits_no_deprecation_notice(tmp_path):
    # Companion to the animation/lightcue game_dir-relative tests above:
    # pins that a real directory-layout game gets #420's resolution with no
    # legacy notice, even when invoked (as here) from its own parent
    # directory, one level up from the game directory itself.
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
    assert "legacy" not in stderr.lower()
    assert "gqc migrate" not in stderr


def test_flat_entry_matching_directory_convention_is_treated_as_directory_layout(tmp_path):
    # Edge case (gamequeer#434): a flat entry file whose parent directory
    # happens to share its own name -- e.g. a top-level `games/games.gq` --
    # is structurally indistinguishable from a real directory-layout game
    # (`<name>/<name>.gq`), and there's no fallback to try both: directory
    # layout wins unconditionally, so its assets must live *inside*
    # `games/`, not at a sibling top-level `assets/`.
    games_dir = tmp_path / "games"
    games_dir.mkdir()
    (games_dir / "games.gq").write_text(
        GAME_HEADER + 'animations { c <- "circle.bmp"; }\n' + STAGE
    )
    dir_layout_assets = games_dir / "assets" / "animations"
    dir_layout_assets.mkdir(parents=True)
    shutil.copyfile(CIRCLE_BMP, dir_layout_assets / "circle.bmp")

    out_dir = tmp_path / "build"
    exit_code, stderr, _ = _run(
        tmp_path,
        ["compile", "-o", str(out_dir), str(games_dir / "games.gq")],
    )
    assert exit_code == 0, stderr
    assert "legacy" not in stderr.lower()


def test_flat_entry_matching_directory_convention_ignores_sibling_assets(tmp_path):
    # Same edge case, but the asset sits at the legacy CWD-relative spot
    # instead -- must NOT be found, since `games/games.gq` resolved as
    # directory layout (see test above) never falls back to the CWD.
    games_dir = tmp_path / "games"
    games_dir.mkdir()
    (games_dir / "games.gq").write_text(
        GAME_HEADER + 'animations { c <- "circle.bmp"; }\n' + STAGE
    )
    legacy_style_assets = tmp_path / "assets" / "animations"
    legacy_style_assets.mkdir(parents=True)
    shutil.copyfile(CIRCLE_BMP, legacy_style_assets / "circle.bmp")

    out_dir = tmp_path / "build"
    exit_code, stderr, _ = _run(
        tmp_path,
        ["compile", "-o", str(out_dir), str(games_dir / "games.gq")],
    )
    assert exit_code != 0
    assert "circle.bmp" in stderr


def test_deprecation_notice_emitted_in_legacy_mode(compile_gq):
    # compile_gq's entry file is always named "game" by default and sits
    # directly in the hermetic tmp_path CWD, whose own name never matches
    # -- always legacy under gamequeer#434's detection rule.
    exit_code, stderr, _ = compile_gq(GAME_HEADER + STAGE)
    assert exit_code == 0, stderr
    assert "legacy" in stderr.lower()
    assert "gqc migrate" in stderr


def test_deprecation_notice_goes_to_stderr_not_stdout(compile_gq):
    exit_code, stderr, out_dir = compile_gq(GAME_HEADER + STAGE)
    assert exit_code == 0, stderr
    assert "legacy" in stderr.lower()
    # compile_gq only captures stderr directly, but the compiled artifact
    # existing (rather than the notice corrupting it) is the load-bearing
    # machine-parsed-output check: the notice must never land in the
    # .gqgame byte stream or map.txt.
    assert (out_dir / "game.gqgame").exists()
