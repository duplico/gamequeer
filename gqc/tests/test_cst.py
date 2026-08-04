"""CST / `gqc fmt` round-trip suite (gamequeer#424 step 1, DEF CON sprint
follow-on epic gamequeer#419).

This is deliberately not a grammar-acceptance suite like test_grammar.py --
`gqc.cst` doesn't know or care about gqc's grammar rules (see its module
docstring for what kind of CST it is), so there's no "reject" side to test
here: any text that lexes (balanced brackets, terminated strings/comments,
only recognized characters) produces a CST, whether or not it would also
compile. What matters here is the round-trip/losslessness guarantee itself:

  - `to_source(parse_cst(text)) == text` for arbitrary/synthetic snippets
    exercising every trivia kind (line comment, block comment, whitespace
    runs, blank lines).
  - The same guarantee holds byte-for-byte on every real, committed `.gq`
    example/golden game in the repo (not just synthetic snippets) --
    that's the strongest form of the issue's "byte-stability" ask, and a
    stronger property than the "fmt(fmt(x)) == fmt(x)" idempotence the
    issue specifically calls for (which follows immediately once fmt(x) ==
    x for a step 1 whose `render` is an identity transform -- see
    `gqc.cst.render`'s docstring).
  - Comments specifically survive (both round-tripped verbatim in place,
    and individually recoverable via `iter_comments`).
  - The `gqc fmt` CLI itself round-trips end to end, including its
    `--check`/`--write` flags and its handling of a file that fails to
    lex.
"""

import os
import pathlib

import pytest
from click.testing import CliRunner

from gqc import cst
from gqc import gqc as gqc_module
from gqc import GqcParseError

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# A representative subset of the repo's real, committed .gq games (per the
# task's ask for "a representative subset of the committed example .gq
# games"): the richest showcase game (multi-stage, both // and /* */
# comments, animations{}), a menu-heavy game, a tutorial sample, and the C
# VM's own edge_coverage.gq golden fixture (deliberately exercises a wide
# grammar spread). test_all_gq_examples_round_trip below additionally
# sweeps every .gq file in the repo, so this list is just the "headline"
# subset with individual, separately-named test IDs.
REPRESENTATIVE_GAMES = [
    REPO_ROOT / "examples" / "showcase" / "showcase.gq",
    REPO_ROOT / "examples" / "perf_menu_text" / "perf_menu_text.gq",
    REPO_ROOT / "examples" / "tutorial_1" / "tutorial_1.gq",
    REPO_ROOT / "gqc" / "examples" / "skel" / "games" / "working_samples" / "sample_working.gq",
    REPO_ROOT / "gamequeer" / "tests" / "golden" / "edge_coverage.gq",
]

ALL_GQ_FILES = sorted(
    p for p in REPO_ROOT.glob("**/*.gq") if "node_modules" not in p.parts
)


# --- synthetic snippets: every trivia kind ----------------------------------


def test_round_trip_is_byte_identical_for_simple_game():
    source = (
        'game { id = 1; title := "T"; author := "A"; starting_stage = s; }\n'
        "stage s { event enter { } }\n"
    )
    tree = cst.parse_cst(source)
    assert cst.to_source(tree) == source


def test_round_trip_preserves_line_comment():
    source = "game { // a comment\n id = 1; }\n"
    tree = cst.parse_cst(source)
    assert cst.to_source(tree) == source


def test_round_trip_preserves_block_comment():
    source = "/* header\n   comment */\ngame { id = 1; }\n"
    tree = cst.parse_cst(source)
    assert cst.to_source(tree) == source


def test_round_trip_preserves_trailing_comment_after_last_token():
    source = "game { id = 1; } // trailing\n"
    tree = cst.parse_cst(source)
    assert cst.to_source(tree) == source
    # The trailing comment (and the newline after it) has no *following*
    # token to attach to as leading trivia -- it lands in the file's own
    # trailing_trivia instead. Nothing here is dropped either way (see the
    # round-trip assertion above); this documents *where* it ends up.
    assert [t.text for t in tree.trailing_trivia if t.kind != "whitespace"] == ["// trailing"]


def test_round_trip_preserves_blank_lines_between_sections():
    source = "game { id = 1; }\n\n\nstage s { event enter { } }\n"
    tree = cst.parse_cst(source)
    assert cst.to_source(tree) == source


def test_round_trip_preserves_windows_line_endings():
    source = 'game {\r\n id = 1; // note\r\n}\r\n'
    tree = cst.parse_cst(source)
    assert cst.to_source(tree) == source


# --- comment survival, specifically -----------------------------------------


def test_comments_are_individually_recoverable():
    source = (
        "/* block */\n"
        "game { id = 1; } // line one\n"
        "stage s { event enter { } } // line two\n"
    )
    tree = cst.parse_cst(source)
    comment_texts = [t.text for t in cst.iter_comments(tree)]
    assert comment_texts == ["/* block */", "// line one", "// line two"]


def test_iter_comments_excludes_whitespace_trivia():
    source = "game {\n\n    id = 1;\n}\n"
    tree = cst.parse_cst(source)
    assert list(cst.iter_comments(tree)) == []


# --- structural nesting -----------------------------------------------------


def test_braces_and_parens_nest_into_groups():
    source = "stage s { event input(A) { gostage other; } }\n"
    tree = cst.parse_cst(source)
    # top-level: word("stage"), word("s"), Group({...})
    assert [c.text if isinstance(c, cst.Token) else None for c in tree.children[:2]] == ["stage", "s"]
    stage_group = tree.children[2]
    assert isinstance(stage_group, cst.Group)
    assert stage_group.open.text == "{" and stage_group.close.text == "}"
    # event input(A) { ... } is itself word/word/Group(paren)/Group(brace)
    event_paren_group = next(c for c in stage_group.children if isinstance(c, cst.Group) and c.open.text == "(")
    assert [t.text for t in event_paren_group.children] == ["A"]


def test_iter_tokens_is_flat_document_order():
    source = "game { id = 1; }\n"
    tree = cst.parse_cst(source)
    texts = [t.text for t in cst.iter_tokens(tree)]
    assert texts == ["game", "{", "id", "=", "1", ";", "}"]


# --- lex errors --------------------------------------------------------------


@pytest.mark.parametrize(
    "source,expected_fragment",
    [
        ("game { id = 1;", "Unterminated '{'"),
        ("game { id = 1; } }", "Unexpected closing"),
        ("game { id = 1 ( ; }", "Mismatched bracket"),
        ('str x := "unterminated', "Unterminated string literal"),
        ("/* unterminated", "Unterminated block comment"),
        ("game @ { }", "Unrecognized character"),
    ],
)
def test_lex_errors_are_located_gqc_parse_errors(source, expected_fragment):
    with pytest.raises(GqcParseError) as excinfo:
        cst.parse_cst(source)
    assert expected_fragment in str(excinfo.value)
    # Same "Error at line N, column N: ..." shape as every other
    # GqcParseError in gqc (see __init__.py).
    assert str(excinfo.value).startswith("Error at line ")


# --- real, committed .gq games -----------------------------------------------


@pytest.mark.parametrize("path", REPRESENTATIVE_GAMES, ids=lambda p: p.name)
def test_representative_game_round_trips_byte_identical(path):
    source = path.read_text()
    tree = cst.parse_cst(source)
    assert cst.to_source(tree) == source


@pytest.mark.parametrize("path", REPRESENTATIVE_GAMES, ids=lambda p: p.name)
def test_representative_game_render_is_idempotent(path):
    source = path.read_text()
    once = cst.render(cst.parse_cst(source))
    twice = cst.render(cst.parse_cst(once))
    assert twice == once


@pytest.mark.parametrize("path", REPRESENTATIVE_GAMES, ids=lambda p: p.name)
def test_representative_game_comments_survive(path):
    source = path.read_text()
    tree = cst.parse_cst(source)
    rendered = cst.render(tree)
    for comment in cst.iter_comments(tree):
        assert comment.text in rendered


def test_all_committed_gq_files_round_trip_byte_identical():
    """Sweeps every .gq file actually committed in the repo (examples/,
    the C VM's golden fixtures, and gqc's own skel samples -- including the
    intentionally-invalid "nonworking_samples", which are lexically fine
    even though they're rejected at compile time for semantic reasons this
    module doesn't know about), not just the headline REPRESENTATIVE_GAMES
    subset above."""
    assert len(ALL_GQ_FILES) >= 30, "sanity check: did the repo glob find the games?"
    failures = []
    for path in ALL_GQ_FILES:
        source = path.read_text()
        try:
            tree = cst.parse_cst(source)
        except GqcParseError as ge:
            failures.append(f"{path}: failed to lex: {ge}")
            continue
        rendered = cst.to_source(tree)
        if rendered != source:
            failures.append(f"{path}: round-trip mismatch")
    assert not failures, "\n".join(failures)


# --- `gqc fmt` CLI -----------------------------------------------------------


def test_fmt_default_prints_formatted_source_to_stdout(fmt_gq):
    source = 'game { id = 1; title := "T"; author := "A"; starting_stage = s; }\nstage s { event enter { } }\n'
    exit_code, stdout, stderr, _ = fmt_gq(source)
    assert exit_code == 0, stderr
    assert stdout == source


def test_fmt_preserves_comments_through_the_cli(fmt_gq):
    source = "game { // note\n id = 1; title := \"T\"; author := \"A\"; starting_stage = s; }\nstage s { event enter { } }\n"
    exit_code, stdout, stderr, _ = fmt_gq(source)
    assert exit_code == 0, stderr
    assert "// note" in stdout
    assert stdout == source


def test_fmt_check_accepts_already_formatted_file(fmt_gq):
    source = 'game { id = 1; title := "T"; author := "A"; starting_stage = s; }\nstage s { event enter { } }\n'
    exit_code, stdout, stderr, _ = fmt_gq(source, extra_args=["--check"])
    assert exit_code == 0, stderr
    assert stdout == ""


def test_fmt_write_updates_the_file_in_place(fmt_gq):
    source = 'game { id = 1; title := "T"; author := "A"; starting_stage = s; }\nstage s { event enter { } }\n'
    exit_code, stdout, stderr, src_path = fmt_gq(source, extra_args=["--write"])
    assert exit_code == 0, stderr
    assert stdout == ""
    assert src_path.read_text() == source


def test_fmt_write_preserves_crlf_line_endings_on_disk(fmt_gq):
    """gamequeer#429 review: `open(input)`/`os.fdopen(fd, 'w')` without an
    explicit `newline=''` enable universal-newline translation, which would
    silently rewrite a CRLF-terminated INPUT to LF on the way through
    --write -- exactly the byte-for-byte round-trip guarantee this module
    exists to prove. Checked via raw bytes on disk (not `src_path.read_text()`
    or the subprocess's captured stdout, both of which do their own
    newline-translation that would mask the bug)."""
    source = (
        'game {\r\n id = 1; title := "T"; author := "A"; starting_stage = s;\r\n}\r\n'
        "stage s { event enter { } }\r\n"
    )
    exit_code, stdout, stderr, src_path = fmt_gq(source, extra_args=["--write"])
    assert exit_code == 0, stderr
    assert src_path.read_bytes() == source.encode("utf-8")


def test_fmt_rejects_write_and_check_together(fmt_gq):
    source = 'game { id = 1; title := "T"; author := "A"; starting_stage = s; }\nstage s { event enter { } }\n'
    exit_code, stdout, stderr, _ = fmt_gq(source, extra_args=["--write", "--check"])
    assert exit_code != 0
    assert "mutually exclusive" in stderr


def test_fmt_of_fmt_output_is_a_fixed_point(fmt_gq, tmp_path):
    """The issue's own idempotence phrasing: fmt(fmt(x)) == fmt(x)."""
    source = REPRESENTATIVE_GAMES[0].read_text()
    exit_code, once, stderr, _ = fmt_gq(source)
    assert exit_code == 0, stderr
    exit_code, twice, stderr, _ = fmt_gq(once, game_name="game2")
    assert exit_code == 0, stderr
    assert twice == once


def test_fmt_reports_a_clean_error_on_unlexable_input(fmt_gq):
    exit_code, stdout, stderr, _ = fmt_gq("game { id = 1;")
    assert exit_code != 0
    assert "Traceback" not in stderr
    assert "Unterminated" in stderr


def test_fmt_reports_a_clean_error_on_non_utf8_input(tmp_path):
    """gamequeer#429 review: the initial `open(input).read()` used to sit
    outside fmt's try/except, so non-UTF-8 input surfaced as a raw
    `UnicodeDecodeError` traceback instead of the same clean CLI error
    style used for unlexable (but decodable) input."""
    src_path = tmp_path / "game.gq"
    src_path.write_bytes(b"game { id = 1; title := \"\xff\xfe bad utf-8\"; }")

    result = CliRunner().invoke(gqc_module.fmt, [str(src_path)])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "cannot decode as UTF-8" in result.output


def test_fmt_write_failure_leaves_source_intact_and_no_temp_leak(tmp_path, monkeypatch):
    """gamequeer#429 review: `fmt --write` used to `open(input, 'w')`
    directly, which truncates INPUT the instant it's opened -- a failure
    anywhere between that open and a completed write destroys the source
    with no way back. It now writes to a sibling temp file and
    `os.replace()`s it into place, so a mid-write failure must leave INPUT
    byte-for-byte untouched and must not leak the temp file. Simulated here
    by monkeypatching `os.fdopen` (used internally by the write path) to
    hand back a file object whose `write` raises partway through."""
    original = (
        'game { id = 1; title := "T"; author := "A"; starting_stage = s; }\n'
        "stage s { event enter { } }\n"
    )
    src_path = tmp_path / "game.gq"
    src_path.write_text(original)

    real_fdopen = os.fdopen

    def boom_fdopen(fd, *args, **kwargs):
        f = real_fdopen(fd, *args, **kwargs)

        def boom_write(*_args, **_kwargs):
            raise OSError("simulated mid-write failure")

        f.write = boom_write
        return f

    monkeypatch.setattr(os, "fdopen", boom_fdopen)

    result = CliRunner().invoke(gqc_module.fmt, [str(src_path), "--write"])

    assert result.exit_code != 0
    assert src_path.read_text() == original, "a failed write must not corrupt the original source"
    leaked = [p for p in tmp_path.iterdir() if p != src_path]
    assert leaked == [], f"temp file(s) leaked: {leaked}"
