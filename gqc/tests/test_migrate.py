"""`gqc migrate` suite (gamequeer#432): flat-workspace -> game-as-directory
re-layout.

Drives the real `gqc migrate` CLI as a subprocess (`_run`, same convention
as test_game_layout.py's helper of the same name) against hand-built flat
workspace fixtures (`games/<name>.gq` + a shared `assets/animations`/
`assets/lighting` tree), so every test exercises the exact same code path
an author running the tool for real would.
"""

import pathlib
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CIRCLE_BMP = REPO_ROOT / "gqc" / "examples" / "skel" / "assets" / "animations" / "circle.bmp"
TEST_GQCUE = REPO_ROOT / "examples" / "assets" / "lighting" / "test.gqcue"

COMPILE_TIMEOUT_S = 120


def _run(cwd, args, timeout=COMPILE_TIMEOUT_S):
    proc = subprocess.run(
        [sys.executable, "-m", "gqc", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _write_flat_workspace(tmp_path, games: dict) -> pathlib.Path:
    """Build a flat workspace at tmp_path / "ws": games/<name>.gq for each
    (name, source) pair in `games`, plus a shared assets/animations and
    assets/lighting tree seeded with CIRCLE_BMP and TEST_GQCUE under every
    subdirectory any game's source string references (callers pass
    already-flat-style literals like "somedir/foo.bmp")."""
    ws = tmp_path / "ws"
    (ws / "games").mkdir(parents=True)
    (ws / "assets" / "animations").mkdir(parents=True)
    (ws / "assets" / "lighting").mkdir(parents=True)
    for name, source in games.items():
        (ws / "games" / f"{name}.gq").write_text(source)
    return ws


def _seed_asset(ws: pathlib.Path, section: str, rel: str, src: pathlib.Path):
    dest = ws / "assets" / section / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


GAME_HEADER = 'game {{ id = 1; title := "{title}"; author := "A"; starting_stage = start; }}\n'
STAGE = "stage start { event enter { } }\n"


# --- core migration: animations + lightcues + comment survival -------------


def test_migrate_moves_animations_lightcues_and_preserves_comments(tmp_path):
    source = (
        GAME_HEADER.format(title="T")
        + "// a leading comment on the animations block\n"
        + "animations {\n"
        + "    // circle sprite\n"
        + '    circ <- "mygame/circle.bmp" { w = 8; h = 8; }  // trailing comment\n'
        + "}\n"
        + "lightcues {\n"
        + '    c1 <- "mygame/test.gqcue"; // a cue\n'
        + "}\n"
        + STAGE
    )
    ws = _write_flat_workspace(tmp_path, {"mygame": source})
    _seed_asset(ws, "animations", "mygame/circle.bmp", CIRCLE_BMP)
    _seed_asset(ws, "lighting", "mygame/test.gqcue", TEST_GQCUE)

    exit_code, stdout, stderr = _run(tmp_path, ["migrate", "mygame", "--workspace", str(ws)])
    assert exit_code == 0, stderr
    assert "verified byte-identical" in stdout

    new_entry = ws / "mygame" / "mygame.gq"
    assert new_entry.exists()
    assert not (ws / "games" / "mygame.gq").exists()
    assert (ws / "mygame" / "assets" / "animations" / "circle.bmp").exists()
    assert (ws / "mygame" / "assets" / "lighting" / "test.gqcue").exists()

    new_source = new_entry.read_text()
    # Comments (leading, trailing, and standalone) all survive verbatim.
    assert "// a leading comment on the animations block" in new_source
    assert "// circle sprite" in new_source
    assert "// trailing comment" in new_source
    assert "// a cue" in new_source
    # The path literals themselves are flattened (no more per-game subdir).
    assert '"circle.bmp"' in new_source
    assert '"test.gqcue"' in new_source
    assert "mygame/circle.bmp" not in new_source
    assert "mygame/test.gqcue" not in new_source
    # Everything else -- alignment, braces, the rest of the source -- is
    # untouched: only the string-literal tokens themselves changed.
    assert "{ w = 8; h = 8; }" in new_source


def test_migrate_dry_run_makes_no_filesystem_changes(tmp_path):
    source = (
        GAME_HEADER.format(title="T")
        + 'animations { circ <- "mygame/circle.bmp"; }\n'
        + STAGE
    )
    ws = _write_flat_workspace(tmp_path, {"mygame": source})
    _seed_asset(ws, "animations", "mygame/circle.bmp", CIRCLE_BMP)

    flat_entry = ws / "games" / "mygame.gq"
    before = flat_entry.read_bytes()

    exit_code, stdout, stderr = _run(
        tmp_path, ["migrate", "mygame", "--workspace", str(ws), "--dry-run"]
    )
    assert exit_code == 0, stderr
    # The full plan (both the destination and every asset it would copy)
    # is printed, without touching anything.
    assert "mygame.gq" in stdout
    assert "circle.bmp" in stdout
    assert flat_entry.read_bytes() == before
    assert not (ws / "mygame").exists()


# --- idempotence -------------------------------------------------------------


def test_migrate_twice_is_a_clean_no_op(tmp_path):
    source = (
        GAME_HEADER.format(title="T")
        + 'animations { circ <- "mygame/circle.bmp"; }\n'
        + STAGE
    )
    ws = _write_flat_workspace(tmp_path, {"mygame": source})
    _seed_asset(ws, "animations", "mygame/circle.bmp", CIRCLE_BMP)

    exit_code, _, stderr = _run(tmp_path, ["migrate", "mygame", "--workspace", str(ws)])
    assert exit_code == 0, stderr

    new_entry = ws / "mygame" / "mygame.gq"
    before = new_entry.read_bytes()
    before_assets = sorted((ws / "mygame" / "assets").rglob("*"))

    exit_code, stdout, stderr = _run(tmp_path, ["migrate", "mygame", "--workspace", str(ws)])
    assert exit_code == 0, stderr
    assert "already migrated" in stdout
    assert new_entry.read_bytes() == before
    assert sorted((ws / "mygame" / "assets").rglob("*")) == before_assets


def test_migrate_dry_run_on_already_migrated_game_is_a_no_op(tmp_path):
    source = (
        GAME_HEADER.format(title="T")
        + 'animations { circ <- "mygame/circle.bmp"; }\n'
        + STAGE
    )
    ws = _write_flat_workspace(tmp_path, {"mygame": source})
    _seed_asset(ws, "animations", "mygame/circle.bmp", CIRCLE_BMP)
    _run(tmp_path, ["migrate", "mygame", "--workspace", str(ws)])

    exit_code, stdout, stderr = _run(
        tmp_path, ["migrate", "mygame", "--workspace", str(ws), "--dry-run"]
    )
    assert exit_code == 0, stderr
    assert "already migrated" in stdout


# --- failure leaves the original untouched ----------------------------------


def test_migrate_missing_asset_leaves_original_untouched(tmp_path):
    source = (
        GAME_HEADER.format(title="T")
        + 'animations { circ <- "mygame/nope.bmp"; }\n'
        + STAGE
    )
    ws = _write_flat_workspace(tmp_path, {"mygame": source})
    # Deliberately don't seed mygame/nope.bmp.

    flat_entry = ws / "games" / "mygame.gq"
    before = flat_entry.read_bytes()

    exit_code, stdout, stderr = _run(tmp_path, ["migrate", "mygame", "--workspace", str(ws)])
    assert exit_code != 0
    assert "Traceback" not in stderr
    assert "nope.bmp" in stderr
    assert flat_entry.exists()
    assert flat_entry.read_bytes() == before
    assert not (ws / "mygame").exists()


def test_migrate_absolute_source_rejected(tmp_path):
    source = GAME_HEADER.format(title="T") + 'animations { c <- "/etc/passwd"; }\n' + STAGE
    ws = _write_flat_workspace(tmp_path, {"mygame": source})

    exit_code, stdout, stderr = _run(tmp_path, ["migrate", "mygame", "--workspace", str(ws)])
    assert exit_code != 0
    assert "absolute path" in stderr
    assert (ws / "games" / "mygame.gq").exists()
    assert not (ws / "mygame").exists()


def test_migrate_parent_traversal_source_rejected(tmp_path):
    source = GAME_HEADER.format(title="T") + 'animations { c <- "../escape.bmp"; }\n' + STAGE
    ws = _write_flat_workspace(tmp_path, {"mygame": source})

    exit_code, stdout, stderr = _run(tmp_path, ["migrate", "mygame", "--workspace", str(ws)])
    assert exit_code != 0
    assert "escapes the shared asset tree" in stderr
    assert (ws / "games" / "mygame.gq").exists()
    assert not (ws / "mygame").exists()


def test_migrate_basename_collision_rejected(tmp_path):
    source = (
        GAME_HEADER.format(title="T")
        + 'animations { a <- "one/x.bmp"; b <- "two/x.bmp"; }\n'
        + STAGE
    )
    ws = _write_flat_workspace(tmp_path, {"mygame": source})
    _seed_asset(ws, "animations", "one/x.bmp", CIRCLE_BMP)
    _seed_asset(ws, "animations", "two/x.bmp", CIRCLE_BMP)

    exit_code, stdout, stderr = _run(tmp_path, ["migrate", "mygame", "--workspace", str(ws)])
    assert exit_code != 0
    assert "collide" in stderr
    assert (ws / "games" / "mygame.gq").exists()
    assert not (ws / "mygame").exists()


# --- shared assets: copy-into-game-dir, with duplication stats -------------


def test_migrate_shared_asset_is_copied_and_reported(tmp_path):
    # Two games reference the exact same shared "shared/circle.bmp" -- the
    # real-corpus pattern (queersafe.gq / queersafe-lite.gq both reference
    # a whole shared "queersafe/" subtree; see migrate.py's module
    # docstring).
    source_a = (
        GAME_HEADER.format(title="A")
        + 'animations { circ <- "shared/circle.bmp"; }\n'
        + STAGE
    )
    source_b = (
        GAME_HEADER.format(title="B")
        + 'animations { circ <- "shared/circle.bmp"; }\n'
        + STAGE
    )
    ws = _write_flat_workspace(tmp_path, {"gamea": source_a, "gameb": source_b})
    _seed_asset(ws, "animations", "shared/circle.bmp", CIRCLE_BMP)

    exit_code, stdout, stderr = _run(
        tmp_path, ["migrate", "gamea", "--workspace", str(ws), "--dry-run"]
    )
    assert exit_code == 0, stderr
    assert "shared with still-flat: gameb" in stdout
    assert "1 also referenced by at least one still-flat game" in stdout

    # Actually migrate gamea; gameb (still flat) and the shared source file
    # must both be completely untouched, and gamea gets its own copy.
    exit_code, stdout, stderr = _run(tmp_path, ["migrate", "gamea", "--workspace", str(ws)])
    assert exit_code == 0, stderr
    assert (ws / "games" / "gameb.gq").exists()
    assert (ws / "assets" / "animations" / "shared" / "circle.bmp").exists()
    assert (ws / "gamea" / "assets" / "animations" / "circle.bmp").exists()
    # The copy is a real, independent file (not e.g. a symlink whose
    # removal upstream would break gamea).
    assert not (ws / "gamea" / "assets" / "animations" / "circle.bmp").is_symlink()


def test_migrate_same_asset_referenced_twice_by_one_game_is_not_a_collision(tmp_path):
    # queersafe-lite.gq's aot/aot1/aot2 all reference the literal same
    # "queersafe/unlocked.bmp" -- a single underlying file, multiple
    # animation names. Must not be treated as a flatten collision.
    source = (
        GAME_HEADER.format(title="T")
        + "animations {\n"
        + '    a <- "mygame/circle.bmp";\n'
        + '    b <- "mygame/circle.bmp";\n'
        + "}\n"
        + STAGE
    )
    ws = _write_flat_workspace(tmp_path, {"mygame": source})
    _seed_asset(ws, "animations", "mygame/circle.bmp", CIRCLE_BMP)

    exit_code, stdout, stderr = _run(tmp_path, ["migrate", "mygame", "--workspace", str(ws)])
    assert exit_code == 0, stderr
    assert (ws / "mygame" / "assets" / "animations" / "circle.bmp").exists()
    # Only one physical file is copied even though two animations use it.
    assert len(list((ws / "mygame" / "assets" / "animations").iterdir())) == 1


# --- GAME resolution ----------------------------------------------------------


def test_migrate_unknown_game_reports_clean_error(tmp_path):
    ws = _write_flat_workspace(tmp_path, {})
    exit_code, stdout, stderr = _run(tmp_path, ["migrate", "nosuchgame", "--workspace", str(ws)])
    assert exit_code != 0
    assert "Traceback" not in stderr
    assert "nosuchgame" in stderr


def test_migrate_accepts_explicit_entry_path(tmp_path):
    source = (
        GAME_HEADER.format(title="T")
        + 'animations { circ <- "mygame/circle.bmp"; }\n'
        + STAGE
    )
    ws = _write_flat_workspace(tmp_path, {"mygame": source})
    _seed_asset(ws, "animations", "mygame/circle.bmp", CIRCLE_BMP)

    exit_code, stdout, stderr = _run(
        tmp_path,
        ["migrate", str(ws / "games" / "mygame.gq"), "--workspace", str(ws)],
    )
    assert exit_code == 0, stderr
    assert (ws / "mygame" / "mygame.gq").exists()
