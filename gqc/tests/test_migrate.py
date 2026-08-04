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

from gqc import migrate

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
    (name, source) pair in `games`, plus an empty shared assets/animations
    and assets/lighting tree. Callers seed whatever specific asset files
    their source literals reference with `_seed_asset` below."""
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


def test_migrate_binding_named_like_a_section_keyword_is_not_misclassified(tmp_path):
    # grammar.py's `identifier` (an animation/lightcue's own name) is a
    # plain Word, not lexically reserved against "stage"/"game"/etc. -- a
    # binding literally named "stage" is valid .gq source and must still
    # be recognized as a binding, not misread as a stage_definition_section
    # marker that would make everything after it disappear from the
    # animations{} section's scan.
    source = (
        GAME_HEADER.format(title="T")
        + "animations {\n"
        + '    stage <- "mygame/circle.bmp";\n'
        + '    after  <- "mygame/circle.bmp";\n'
        + "}\n"
        + STAGE
    )
    ws = _write_flat_workspace(tmp_path, {"mygame": source})
    _seed_asset(ws, "animations", "mygame/circle.bmp", CIRCLE_BMP)

    exit_code, stdout, stderr = _run(
        tmp_path, ["migrate", "mygame", "--workspace", str(ws), "--dry-run"]
    )
    assert exit_code == 0, stderr
    assert "used by: after, stage" in stdout

    exit_code, stdout, stderr = _run(tmp_path, ["migrate", "mygame", "--workspace", str(ws)])
    assert exit_code == 0, stderr
    new_source = (ws / "mygame" / "mygame.gq").read_text()
    assert 'stage <- "circle.bmp"' in new_source
    assert 'after  <- "circle.bmp"' in new_source


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


def test_migrate_rejects_explicit_path_outside_workspace(tmp_path):
    # An existing .gq file that isn't actually GAME's canonical entry
    # location under --workspace must be rejected outright, not read (and,
    # on success, deleted -- see execute()'s final plan.entry_path.unlink())
    # from wherever it happens to sit on disk.
    outside = tmp_path / "elsewhere.gq"
    outside.write_text(
        GAME_HEADER.format(title="T") + STAGE
    )
    ws = _write_flat_workspace(tmp_path, {})

    exit_code, stdout, stderr = _run(
        tmp_path, ["migrate", str(outside), "--workspace", str(ws)]
    )
    assert exit_code != 0
    assert "Traceback" not in stderr
    assert "--workspace" in stderr
    assert outside.exists()
    assert outside.read_bytes()  # untouched, still has content


@pytest.mark.skipif(
    sys.platform == "win32", reason="os.symlink needs elevated privileges on Windows"
)
def test_migrate_rejects_bare_name_resolving_through_symlink_outside_workspace(tmp_path):
    # A symlink planted at the canonical already-migrated location
    # (<name>/<name>.gq) pointing outside --workspace must be rejected just
    # like an explicit out-of-workspace path is: _resolve_entry_path's
    # bare-name branches (directory_style.is_file() / flat.is_file())
    # returned a `.resolve()`d path -- which follows the symlink -- with no
    # boundary check at all, and `execute()` unconditionally unlink()s
    # whatever this function returns on success.
    ws = _write_flat_workspace(tmp_path, {})
    outside = tmp_path / "outside.gq"
    outside.write_text(GAME_HEADER.format(title="T") + STAGE)

    (ws / "mygame").mkdir()
    (ws / "mygame" / "mygame.gq").symlink_to(outside)

    exit_code, stdout, stderr = _run(tmp_path, ["migrate", "mygame", "--workspace", str(ws)])
    assert exit_code != 0
    assert "Traceback" not in stderr
    assert "outside workspace" in stderr
    assert outside.exists()
    assert outside.read_text()  # untouched, still has content


@pytest.mark.skipif(
    sys.platform == "win32", reason="os.symlink needs elevated privileges on Windows"
)
def test_migrate_rejects_explicit_path_at_symlinked_canonical_location(tmp_path):
    # Even the explicit-path branch's existing membership check (`resolved
    # in (directory_style, flat)`) is trivially satisfied when GAME names
    # the canonical <name>/<name>.gq location *and* that location is itself
    # a symlink escaping the workspace -- both sides resolve through the
    # identical symlink to the identical external target. Same escape as
    # the bare-name case above, reached via an explicit path instead.
    ws = _write_flat_workspace(tmp_path, {})
    outside = tmp_path / "outside.gq"
    outside.write_text(GAME_HEADER.format(title="T") + STAGE)

    (ws / "mygame").mkdir()
    symlinked_entry = ws / "mygame" / "mygame.gq"
    symlinked_entry.symlink_to(outside)

    exit_code, stdout, stderr = _run(
        tmp_path, ["migrate", str(symlinked_entry), "--workspace", str(ws)]
    )
    assert exit_code != 0
    assert "Traceback" not in stderr
    assert "outside workspace" in stderr
    assert outside.exists()
    assert outside.read_text()  # untouched, still has content


# --- execute(): filesystem-failure rollback (in-process, monkeypatched) ----
#
# These two drive gqc.migrate's functions directly (build_plan/execute)
# rather than the CLI subprocess: the failure modes below (a mid-copy
# shutil.move failure, an unlink() failure) need to be injected
# deterministically, which isn't reachable by shaping fixture source/inputs
# alone.


def _build_single_game_plan(tmp_path):
    source = (
        GAME_HEADER.format(title="T")
        + 'animations { circ <- "mygame/circle.bmp"; }\n'
        + STAGE
    )
    ws = _write_flat_workspace(tmp_path, {"mygame": source})
    _seed_asset(ws, "animations", "mygame/circle.bmp", CIRCLE_BMP)
    return migrate.build_plan("mygame", ws.resolve())


def test_migrate_move_failure_rolls_back_and_raises_migrate_error(tmp_path, monkeypatch):
    # execute()'s final shutil.move(staged_game_dir, plan.new_game_dir) was
    # unguarded: cross-filesystem (this temp staging dir on one mount, a
    # real workspace on another) shutil.move degrades to copytree+rmtree,
    # so a mid-copy failure can leave new_game_dir partially populated in
    # the real workspace, with a raw OSError escaping gqc.py's `migrate`
    # command (which only catches MigrateError/GqcParseError) as a
    # traceback. The patched shutil.move below writes a partial destination
    # before failing, mimicking what a real copytree failure would leave
    # behind.
    plan = _build_single_game_plan(tmp_path)
    entry_before = plan.entry_path.read_bytes()

    def failing_move(src, dst):
        dst_path = pathlib.Path(dst)
        dst_path.mkdir(parents=True)
        (dst_path / "partial.gq").write_text("incomplete")
        raise OSError("simulated cross-filesystem move failure mid-copy")

    monkeypatch.setattr(migrate.shutil, "move", failing_move)

    with pytest.raises(migrate.MigrateError, match="moving it into place"):
        migrate.execute(plan)

    assert not plan.new_game_dir.exists()
    assert plan.entry_path.exists()
    assert plan.entry_path.read_bytes() == entry_before


def test_migrate_destination_created_after_build_plan_is_not_clobbered(tmp_path):
    # build_plan() rejects an existing new_game_dir up front, but the two
    # compiles execute() runs in between can take a while -- if something
    # else creates new_game_dir before the final move, shutil.move(src,
    # existing_dir) moves src *inside* dst rather than replacing it (so the
    # migrated game would land nested at new_game_dir/game_name/, not
    # new_game_dir/, and be unreachable at its expected canonical
    # location), and the OSError-handler's rollback would rmtree() whatever
    # was already in that directory -- not just what this migration wrote.
    # execute() must re-check immediately before the move and refuse
    # cleanly, leaving both the original and the pre-existing directory's
    # own content untouched.
    plan = _build_single_game_plan(tmp_path)
    entry_before = plan.entry_path.read_bytes()

    plan.new_game_dir.mkdir()
    preexisting = plan.new_game_dir / "unrelated_preexisting_file.txt"
    preexisting.write_text("do not delete me")

    with pytest.raises(migrate.MigrateError, match="was created after"):
        migrate.execute(plan)

    assert preexisting.read_text() == "do not delete me"
    assert sorted(p.name for p in plan.new_game_dir.iterdir()) == [preexisting.name]
    assert plan.entry_path.exists()
    assert plan.entry_path.read_bytes() == entry_before


def test_migrate_unlink_failure_rolls_back_move_and_raises_migrate_error(tmp_path, monkeypatch):
    # The *existing* rollback for execute()'s final plan.entry_path.unlink()
    # -- the migrated directory is already verified and moved into place,
    # but removing the original flat entry file then fails -- had no test
    # coverage at all. Pin it down the same way as the move-failure case
    # above.
    plan = _build_single_game_plan(tmp_path)
    entry_before = plan.entry_path.read_bytes()

    real_unlink = pathlib.Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self == plan.entry_path:
            raise OSError("simulated unlink failure")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", failing_unlink)

    with pytest.raises(migrate.MigrateError, match="removing the original"):
        migrate.execute(plan)

    assert not plan.new_game_dir.exists()
    assert plan.entry_path.exists()
    assert plan.entry_path.read_bytes() == entry_before


# --- malformed source: clean error, not a raw traceback --------------------


def test_migrate_unparseable_source_reports_clean_error(tmp_path):
    ws = _write_flat_workspace(tmp_path, {})
    # An unterminated string literal is a GqcParseError straight out of
    # gqc.cst.parse_cst (called from build_plan), not a MigrateError --
    # exercises gqc.py's migrate command catching both cleanly.
    (ws / "games" / "broken.gq").write_text('animations { c <- "unterminated;\n')

    exit_code, stdout, stderr = _run(tmp_path, ["migrate", "broken", "--workspace", str(ws)])
    assert exit_code != 0
    assert "Traceback" not in stderr
