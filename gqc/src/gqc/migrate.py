"""`gqc migrate`: deterministic flat-workspace -> game-as-directory
re-layout (gamequeer#432, follow-on to #420/#427's game-as-directory layout
and #424/#429's CST).

Before #420, a workspace kept every game flat at `games/<name>.gq` and
resolved `animations{}`/`lightcues{}` sources against a *shared*,
top-level `assets/animations`/`assets/lighting` tree, keyed by a
hand-matched per-game subdirectory (e.g. `games/bricks.gq`'s
`"bricks/bg_title.png"` resolves against `assets/animations/bricks/...`).
#420 replaced that with a self-contained game directory
(`<name>/<name>.gq`) whose assets resolve directly against its own
`assets/animations`/`assets/lighting` (see `datamodel.Animation.src_path`
/ `parser.parse_lightcue_definition_section`) -- **relative to the entry
file's own parent directory, not the process CWD**. That's a real,
load-bearing behavior change, not just a style preference: a flat game
under `games/` no longer compiles at all against the current compiler
(its sources resolve against `games/assets/...`, which doesn't exist --
the shared tree sits one level up, next to `games/`, not inside it).
`gqc migrate` is the mechanical fix: it moves a flat game's entry file and
copies exactly the assets it references into the new self-contained
layout, rewriting each asset-path string literal to match (surgically,
via `gqc.cst`, so every comment and all of the surrounding formatting
survive byte-for-byte).

Design decisions
-----------------
- **Destination**: `<workspace>/<name>/<name>.gq`, a sibling of
  `<workspace>/games/`, matching `gqc new`'s own scaffold (its default
  `--out-dir` is the CWD) -- not nested inside `games/`. `games/` stays the
  home for whatever flat games haven't been migrated yet during the
  transition (see gamequeer#432); the workspace `Makefile`'s discovery of
  the new, sibling-of-`games/` layout is tracked separately (out of scope
  here -- lives in `gq-games`, not `gqc`).
- **Path rewriting, not verbatim copying**: a flat source like
  `"bricks/bg_title.png"` could, mechanically, be preserved unchanged and
  just copied to `<name>/assets/animations/bricks/bg_title.png` (still
  valid -- #420 doesn't require a flat `assets/animations/`, only that it
  resolve under the game's own directory). But #420's own issue text is
  explicit that the point of the change is dropping "the old top-level
  assets/animations + assets/lighting roots keyed by a hand-matched
  subdir" -- so migrate normalizes every reference down to its bare
  filename (flattening the now-redundant per-game subdirectory), matching
  `gqc new`'s own scaffold shape. A real, unresolvable filename collision
  within one game's animations (or lightcues) is a hard error -- migrate
  never silently disambiguates or overwrites.
- **Shared assets: copy, not cross-reference.** The corpus has real
  cross-game sharing today (e.g. `queersafe.gq` and `queersafe-lite.gq`
  both reference the entire `queersafe/` subtree; `2000svg.gq`/`boot.gq`/
  `retrovg.gq`/`meme.gq`/`pop.gq` all share `tvtuner/stock/rainbow.gqcue`).
  #420's own test suite (`test_game_layout.py`) only ever exercises
  resolution *within* the game's own directory, and its negative control
  (`test_animation_source_at_old_cwd_relative_location_is_not_found`)
  proves there's deliberately no fallback/search path outside it -- there's
  no sanctioned way to reference another game directory's assets, and nothing
  in the shipped code path or tests suggests `..`-escapes are intentional
  (they're simply unvalidated, not supported). So migrate always *copies*
  the referenced files into the migrated game's own `assets/` -- accepting
  duplication -- rather than inventing a cross-directory reference this
  layout was explicitly designed to retire. It reports how much of that
  duplication is with other *still-flat* games in `games/` (informational
  only) so an author can judge whether it's worth deduplicating by hand.
- **Never deletes shared originals.** Only the migrated game's own flat
  entry file (`games/<name>.gq`) is removed, and only after the
  byte-identical verification below passes. The shared `assets/` tree is
  left completely alone -- other, not-yet-migrated games may still need
  it (this is what makes migrating each in-flight branch independently,
  on its own author's timing, safe).

Acceptance property (load-bearing, gamequeer#432): before touching
anything, migrate compiles the *original* flat game (via a throwaway
symlink harness -- see `_compile_flat_baseline` -- since the flat form no
longer compiles in place against the current compiler, per the above) and
stages the migrated form in a separate temp directory, compiles that too,
and requires the two `.gqgame` outputs to be **byte-identical** before
committing anything to the workspace. Any mismatch (or either compile
failing) aborts loudly and leaves the original completely untouched.
gqc has exactly one asset-resolution rule (game-dir-relative, #420) and no
CWD-relative fallback for a flat entry file: a flat game genuinely does
not compile in place, so `_compile_flat_baseline`'s symlink harness is the
permanent way to establish the pre-migration baseline, not a stopgap.
"""

import dataclasses
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

from . import cst

COMPILE_TIMEOUT_S = 120

# gamequeer#420's grammar keyword for the mapping from an animations{}/
# lightcues{} section keyword to the asset-tree subdirectory it resolves
# against (see datamodel.Animation.src_path / parser.parse_lightcue_
# definition_section -- "lightcues" resolves against "lighting", not
# "lightcues").
_SECTION_ASSET_DIR = {
    "animations": "animations",
    "lightcues": "lighting",
}

# Every top-level keyword grammar.py's top_level_section alternation
# accepts (see grammar.py's module docstring) -- used only to track which
# section we're inside while scanning the CST, not to validate anything.
_SECTION_KEYWORDS = {
    "animations", "lightcues", "game", "volatile", "persistent",
    "menus", "stage", "const", "enum", "cohort",
}


class MigrateError(Exception):
    """A migrate precondition or verification failure. Always caught at
    the CLI boundary and reported as a clean, nonzero-exit message -- never
    a raw traceback -- and always raised before any destructive filesystem
    step, so the original flat game is left untouched."""


@dataclasses.dataclass
class AssetBinding:
    """One `name <- "source"` animation/lightcue file_assignment, located
    structurally in the CST (see `_find_asset_bindings`)."""

    section: str  # "animations" | "lightcues"
    name: str
    string_token: "cst.Token"
    literal: str  # decoded (unescaped, unquoted) source text


@dataclasses.dataclass
class AssetCopy:
    """One file that migration will copy into the new game directory."""

    section: str  # "animations" | "lightcues"
    old_literal: str  # original (possibly-nested) relative source text
    new_literal: str  # flattened (bare filename) relative source text
    src_path: pathlib.Path  # absolute path under the shared workspace assets tree
    binding_names: list  # animation/lightcue names that reference this file
    shared_with: list  # other still-flat games/*.gq (by stem) that also reference it


@dataclasses.dataclass
class MigrationPlan:
    game_name: str
    workspace: pathlib.Path
    entry_path: pathlib.Path
    already_migrated: bool
    new_game_dir: pathlib.Path
    new_entry_path: pathlib.Path
    rewritten_source: str
    asset_copies: list


@dataclasses.dataclass
class MigrationResult:
    plan: MigrationPlan
    pre_bytes: bytes
    post_bytes: bytes


def _decode_string_literal(text: str) -> str:
    """Reverse of `_encode_string_literal`: strip the surrounding quotes
    and undo the `\\`-escaping convention `gqc.cst`'s tokenizer documents
    (and grammar.py's `meta_string` -- `escChar='\\'` -- actually
    implements) for animation/lightcue `file_source` string literals."""
    assert text[0] == '"' and text[-1] == '"', f"not a quoted string literal: {text!r}"
    inner = text[1:-1]
    out = []
    i = 0
    n = len(inner)
    while i < n:
        c = inner[i]
        if c == "\\" and i + 1 < n:
            out.append(inner[i + 1])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _encode_string_literal(value: str) -> str:
    """Inverse of `_decode_string_literal`: re-quote `value` as a `.gq`
    string literal, escaping the same two characters `meta_string`'s
    `escChar='\\'` grammar (and `gqc.cst`'s matching tokenizer choice)
    ever need escaped."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _find_asset_bindings(tree: "cst.CstFile") -> list:
    """Locate every `name <- "source"` file_assignment/animation_assignment
    in `tree`, tagged with which top-level section it's in.

    Identification is purely structural, derived directly from
    grammar.py's shape for these two productions
    (`file_assignment`/`animation_assignment`, both
    `identifier - Suppress("<-") - file_source - ...`), not from what the
    string *looks like* (no `.gif`/`.png`/`.gqcue` extension sniffing):
    `<-` appears in exactly one other place in the grammar
    (`event_input_button`'s `input(<-)` form), and that occurrence is
    always sandwiched between `(` and `)` -- never followed by a string
    token. So the flat `(word, "<-", string)` triplet found directly
    below is unambiguous under the current grammar; if a future grammar
    change ever adds another `<-` production, this comment (and the
    unit test pinning the ambiguity claim) is the place to revisit.

    The triplet check runs *before* the section-keyword check: grammar.py's
    `identifier` (used for an animation/lightcue's own name) is a plain
    `Word`, not lexically reserved against any of `_SECTION_KEYWORDS` --
    a binding legitimately named `stage <- "foo.png";` is valid `.gq`
    source. Since the triplet shape is unambiguous on its own (see above),
    checking it first means such a name is always classified correctly as
    a binding, regardless of what its own text happens to be; only a bare
    word *not* immediately followed by `<-` and a string is ever treated
    as a section-keyword marker.
    """
    bindings = []

    def scan(children, section):
        i = 0
        n = len(children)
        while i < n:
            node = children[i]
            if (
                isinstance(node, cst.Token)
                and node.kind == "word"
                and i + 2 < n
                and isinstance(children[i + 1], cst.Token)
                and children[i + 1].kind == "punct"
                and children[i + 1].text == "<-"
                and isinstance(children[i + 2], cst.Token)
                and children[i + 2].kind == "string"
            ):
                if section in ("animations", "lightcues"):
                    string_token = children[i + 2]
                    bindings.append(
                        AssetBinding(
                            section=section,
                            name=node.text,
                            string_token=string_token,
                            literal=_decode_string_literal(string_token.text),
                        )
                    )
                i += 3
                continue
            if (
                isinstance(node, cst.Token)
                and node.kind == "word"
                and node.text in _SECTION_KEYWORDS
            ):
                section = node.text
                i += 1
                continue
            if isinstance(node, cst.Group):
                scan(node.children, section)
            i += 1

    scan(tree.children, None)
    return bindings


# A Windows drive-letter prefix ("C:", "c:...") -- pathlib.PurePosixPath
# doesn't treat this as absolute (only a leading "/" is), but a real
# pathlib.Path *does* on Windows, and Path.__truediv__ discards everything
# to its left when the right operand is absolute -- so `workspace / ... /
# literal` in `_resolve_flat_source` would silently escape the workspace
# on Windows if this weren't rejected here too.
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _validate_relative_asset_literal(literal: str, *, context: str) -> pathlib.PurePosixPath:
    # Every asset literal in the corpus (and everywhere else in this
    # module) uses "/" exclusively. PurePosixPath below never treats "\"
    # as a separator, so a backslash-containing literal like
    # "..\\..\\etc\\passwd" parses as one inert, non-".." path component
    # here and would sail through both checks below undetected -- but a
    # real pathlib.Path *does* split on "\" on Windows, so it would still
    # be a genuine parent-directory (or, combined with a leading "\\",
    # UNC-path) escape there. Reject outright rather than trying to
    # validate backslash-containing literals correctly on every platform.
    if "\\" in literal:
        raise MigrateError(
            f"{context}: asset source {literal!r} contains a backslash -- "
            "migrate's path literals are always '/'-separated; a "
            "backslash could hide a Windows-style '..' escape or UNC/"
            "absolute path from the checks below."
        )
    if _WINDOWS_DRIVE_RE.match(literal):
        raise MigrateError(
            f"{context}: asset source {literal!r} looks like a Windows "
            "drive-letter path -- migrate doesn't support relocating an "
            "asset outside the workspace's shared asset tree."
        )
    path = pathlib.PurePosixPath(literal)
    if path.is_absolute():
        raise MigrateError(
            f"{context}: asset source {literal!r} is an absolute path -- migrate "
            "doesn't support relocating an asset outside the workspace's shared "
            "asset tree."
        )
    if not path.parts or ".." in path.parts:
        raise MigrateError(
            f"{context}: asset source {literal!r} escapes the shared asset "
            "tree (empty path or a '..' component) -- migrate doesn't support "
            "relocating an asset outside the workspace's shared asset tree."
        )
    return path


def _resolve_flat_source(workspace: pathlib.Path, section: str, literal: str) -> pathlib.Path:
    asset_dir = _SECTION_ASSET_DIR[section]
    return workspace / "assets" / asset_dir / literal


def _require_in_workspace(
    resolved: pathlib.Path, workspace: pathlib.Path, game: str
) -> None:
    """Raise MigrateError unless RESOLVED (already followed through any
    symlinks, via `.resolve()`) sits inside WORKSPACE (also already
    resolved -- see `build_plan`).

    Guards every path `_resolve_entry_path` can return, not just an
    explicit GAME path: a symlink planted at either canonical location
    (`<name>/<name>.gq` or `games/<name>.gq`) resolves outside the
    workspace exactly as easily as an explicit `../escape.gq` would, and
    `execute()` unconditionally `unlink()`s whatever this function
    returns on success -- so a workspace-external file reached via either
    path shape must never be handed back."""
    if not resolved.is_relative_to(workspace):
        raise MigrateError(
            f"{game!r} resolves to {resolved}, outside workspace {workspace} "
            "(likely a symlink) -- migrate only operates on games inside "
            "--workspace."
        )


def _resolve_entry_path(game: str, workspace: pathlib.Path) -> pathlib.Path:
    """Resolve GAME (a bare game name, or a path to its `.gq` entry file)
    against WORKSPACE, whether the game is currently flat
    (`games/<name>.gq`) or already migrated (`<name>/<name>.gq`).

    An explicit path is only accepted if it resolves to exactly one of
    those two canonical, in-workspace locations -- migrate always ends by
    deleting the original entry file (see `execute`), so accepting an
    arbitrary existing file path here (e.g. `../elsewhere/foo.gq`, or an
    absolute path outside --workspace entirely) would let GAME name a file
    outside the workspace migrate is meant to operate on, which `execute`
    would then happily delete. Every returned path -- explicit, or found
    via a bare-name lookup -- is additionally required to actually resolve
    inside WORKSPACE (`_require_in_workspace`): a symlink at the canonical
    location is just as much an escape as an explicit `..` path."""
    candidate = pathlib.Path(game)
    name = candidate.name
    if name.endswith(".gq"):
        name = name[: -len(".gq")]

    directory_style = (workspace / name / f"{name}.gq").resolve()
    flat = (workspace / "games" / f"{name}.gq").resolve()

    if candidate.is_file():
        resolved = candidate.resolve()
        if resolved not in (directory_style, flat):
            raise MigrateError(
                f"{resolved} is not {name!r}'s entry file under workspace "
                f"{workspace} (expected {directory_style} or {flat}) -- "
                "migrate only operates on games inside --workspace."
            )
        _require_in_workspace(resolved, workspace, game)
        return resolved

    if directory_style.is_file():
        _require_in_workspace(directory_style, workspace, game)
        return directory_style
    if flat.is_file():
        _require_in_workspace(flat, workspace, game)
        return flat

    raise MigrateError(
        f"Could not find game {game!r} under workspace {workspace} "
        f"(looked for {directory_style} and {flat})."
    )


def _iter_sibling_flat_entries(workspace: pathlib.Path, exclude: pathlib.Path):
    games_dir = workspace / "games"
    if not games_dir.is_dir():
        return
    for path in sorted(games_dir.glob("*.gq")):
        if path.resolve() != exclude:
            yield path


def _flat_sources_for(gq_path: pathlib.Path) -> set:
    """The set of resolved absolute source paths a still-flat `<name>.gq`
    references, resolved against its workspace (`gq_path.parent.parent`,
    i.e. `games/../` -- this helper is only ever called on paths already
    known to be under a workspace's `games/` directory). Used only for
    migrate's informational shared-asset duplication stats: best-effort,
    so a sibling `.gq` file that fails to parse is silently skipped rather
    than aborting the migration it has nothing to do with."""
    try:
        source = gq_path.read_text(encoding="utf-8")
        tree = cst.parse_cst(source)
    except Exception:
        return set()

    workspace = gq_path.parent.parent
    sources = set()
    for binding in _find_asset_bindings(tree):
        try:
            _validate_relative_asset_literal(binding.literal, context=str(gq_path))
        except MigrateError:
            continue
        sources.add(_resolve_flat_source(workspace, binding.section, binding.literal))
    return sources


def _flatten_literals(bindings: list, *, section: str) -> dict:
    """Map each distinct old relative literal in `bindings` (already
    filtered to `section`) to its new, flattened (bare-filename) relative
    literal. Raises MigrateError on a real collision: two different old
    literals that would flatten to the same filename."""
    old_to_new = {}
    new_to_old = {}
    literals = sorted({b.literal for b in bindings})
    for literal in literals:
        basename = pathlib.PurePosixPath(literal).name
        if basename in new_to_old and new_to_old[basename] != literal:
            raise MigrateError(
                f"Cannot flatten {section} asset paths: both {new_to_old[basename]!r} "
                f"and {literal!r} would collide as {basename!r}. Rename one of the "
                "source assets (or the reference to it) before migrating."
            )
        new_to_old[basename] = literal
        old_to_new[literal] = basename
    return old_to_new


def build_plan(game: str, workspace: pathlib.Path) -> MigrationPlan:
    """Analyze GAME (read-only -- touches nothing on disk) and build the
    full migration plan: the rewritten source text and every asset that
    would be copied. Raises MigrateError on any precondition failure."""
    workspace = workspace.resolve()
    entry_path = _resolve_entry_path(game, workspace)
    game_name = entry_path.stem

    already_migrated = entry_path.parent.name == game_name
    new_game_dir = workspace / game_name
    new_entry_path = new_game_dir / f"{game_name}.gq"

    if already_migrated:
        # gamequeer#432's idempotence requirement: migrating an
        # already-migrated game is a clean no-op. Detected structurally
        # (entry file already sits at <name>/<name>.gq) rather than by
        # re-checking every asset literal is already a bare filename --
        # a hand-authored, legitimately-nested asset subpath inside an
        # already-directory-layout game is none of migrate's business to
        # "fix" after the fact.
        with open(entry_path, "r", encoding="utf-8", newline="") as f:
            rewritten_source = f.read()
        return MigrationPlan(
            game_name=game_name,
            workspace=workspace,
            entry_path=entry_path,
            already_migrated=True,
            new_game_dir=new_game_dir,
            new_entry_path=new_entry_path,
            rewritten_source=rewritten_source,
            asset_copies=[],
        )

    if new_game_dir.exists():
        raise MigrateError(
            f"{new_game_dir} already exists -- refusing to migrate {game_name!r} "
            "into it. Remove it first if this is stale output from a previous "
            "failed migration attempt."
        )

    # encoding='utf-8', newline='': same byte-fidelity rationale as `gqc
    # fmt` (gqc.py) -- open()'s platform defaults can silently misdecode or
    # re-translate line endings, which would break the exact-source
    # guarantee the CST round-trip depends on.
    with open(entry_path, "r", encoding="utf-8", newline="") as f:
        source = f.read()
    tree = cst.parse_cst(source)
    bindings = _find_asset_bindings(tree)

    # Parse every still-flat sibling exactly once (informational
    # shared-asset stats only -- see AssetCopy.shared_with) rather than
    # once per asset this game references, which would be an
    # O(n_assets * n_siblings) reparse for a corpus with many shared-asset
    # games (e.g. the queersafe/queersafe-lite pair, ~40 assets each).
    sibling_sources = {
        sibling: _flat_sources_for(sibling)
        for sibling in _iter_sibling_flat_entries(workspace, entry_path)
    }

    asset_copies = []
    for section in ("animations", "lightcues"):
        section_bindings = [b for b in bindings if b.section == section]
        old_to_new = _flatten_literals(section_bindings, section=section)

        for literal, new_literal in sorted(old_to_new.items()):
            _validate_relative_asset_literal(literal, context=f"{entry_path} ({section})")
            src_path = _resolve_flat_source(workspace, section, literal)
            if not src_path.is_file():
                raise MigrateError(
                    f"{entry_path}: {section} source {literal!r} resolves to "
                    f"{src_path}, which doesn't exist."
                )
            binding_names = sorted(
                b.name for b in section_bindings if b.literal == literal
            )
            shared_with = sorted(
                sibling.stem
                for sibling, sources in sibling_sources.items()
                if src_path in sources
            )
            copy = AssetCopy(
                section=section,
                old_literal=literal,
                new_literal=new_literal,
                src_path=src_path,
                binding_names=binding_names,
                shared_with=shared_with,
            )
            asset_copies.append(copy)

        # Rewrite every binding's string token in place, in this section,
        # to its flattened literal.
        for binding in section_bindings:
            binding.string_token.text = _encode_string_literal(old_to_new[binding.literal])

    rewritten_source = cst.to_source(tree)

    return MigrationPlan(
        game_name=game_name,
        workspace=workspace,
        entry_path=entry_path,
        already_migrated=False,
        new_game_dir=new_game_dir,
        new_entry_path=new_entry_path,
        rewritten_source=rewritten_source,
        asset_copies=asset_copies,
    )


def _run_compile(entry_path: pathlib.Path, out_dir: pathlib.Path, cwd: pathlib.Path) -> bytes:
    """Run the real `gqc compile` CLI as a subprocess (matching the
    project's existing test convention -- see tests/conftest.py's
    `compile_gq` -- and, more importantly here, running the *actual*
    shipped compiler rather than re-deriving any of its behavior) and
    return the resulting `.gqgame` bytes. Raises MigrateError with the
    compiler's own stderr on any failure."""
    cmd = [
        sys.executable, "-m", "gqc", "compile", "--no-mem-map",
        "-o", str(out_dir), str(entry_path),
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise MigrateError(
            f"gqc compile of {entry_path} did not finish within "
            f"{COMPILE_TIMEOUT_S}s (cmd={cmd!r})"
        ) from exc

    if proc.returncode != 0:
        raise MigrateError(f"gqc compile of {entry_path} failed:\n{proc.stderr}")

    cart_path = out_dir / f"{entry_path.stem}.gqgame"
    if not cart_path.is_file():
        raise MigrateError(
            f"gqc compile of {entry_path} exited 0 but produced no {cart_path.name}"
        )
    return cart_path.read_bytes()


def _compile_flat_baseline(plan: MigrationPlan) -> bytes:
    """Compile the *original*, untouched flat game and return its
    `.gqgame` bytes -- the "pre" side of the migration's byte-identical
    acceptance property.

    The flat entry file no longer compiles in place under the current
    compiler (see this module's docstring: its sources resolve relative to
    its own parent, `games/`, not the shared `assets/` tree one level up).
    So this builds a throwaway harness in a temp directory: an exact copy
    of the original entry file, sitting next to a symlink to the *real*
    shared `assets/` directory. That reconstructs precisely what compiling
    this exact, unmodified source would have produced under the workspace's
    old CWD-relative resolution -- the same bytes are read off disk either
    way -- without touching the real workspace or reviving any of the old
    resolution logic inside the compiler itself."""
    with tempfile.TemporaryDirectory(prefix="gqc-migrate-pre-") as tmp:
        tmp_path = pathlib.Path(tmp)
        tmp_entry = tmp_path / plan.entry_path.name
        # Both of these only ever touch the throwaway tmp_path harness (the
        # symlink's target, plan.workspace / "assets", is read, never
        # written) -- this whole function runs before execute()'s first
        # real workspace mutation, so there's nothing to roll back here,
        # just the same "clean MigrateError, never a raw traceback"
        # contract this module promises everywhere else (permissions, a
        # filesystem/OS without symlink support, ...).
        try:
            shutil.copyfile(plan.entry_path, tmp_entry)
            os.symlink(plan.workspace / "assets", tmp_path / "assets")
        except OSError as exc:
            raise MigrateError(
                f"{plan.game_name}: building the pre-migration compile "
                f"harness in {tmp_path} failed ({exc})"
            ) from exc
        return _run_compile(tmp_entry, tmp_path / "build", cwd=tmp_path)


def _stage_migrated_game(plan: MigrationPlan, dest_root: pathlib.Path) -> pathlib.Path:
    """Write the migrated game (rewritten entry file + copied assets)
    under `dest_root` (a temp staging directory, or -- once verified --
    the real workspace) and return its game directory."""
    game_dir = dest_root / plan.game_name
    for section_dir in ("animations", "lighting"):
        (game_dir / "assets" / section_dir).mkdir(parents=True, exist_ok=True)

    entry_path = game_dir / f"{plan.game_name}.gq"
    with open(entry_path, "w", encoding="utf-8", newline="") as f:
        f.write(plan.rewritten_source)

    for copy in plan.asset_copies:
        asset_dir = _SECTION_ASSET_DIR[copy.section]
        dest = game_dir / "assets" / asset_dir / copy.new_literal
        shutil.copy2(copy.src_path, dest)

    return game_dir


def execute(plan: MigrationPlan) -> MigrationResult:
    """Perform the migration for real: verify byte-identical compiled
    output between the original and the migrated form (in isolated temp
    directories -- nothing in the real workspace is touched yet), and only
    then commit the migrated game directory and remove the original flat
    entry file. Raises MigrateError (leaving the workspace exactly as it
    was) on any verification failure."""
    if plan.already_migrated:
        return MigrationResult(plan=plan, pre_bytes=b"", post_bytes=b"")

    pre_bytes = _compile_flat_baseline(plan)

    with tempfile.TemporaryDirectory(prefix="gqc-migrate-post-") as tmp:
        tmp_path = pathlib.Path(tmp)
        staged_game_dir = _stage_migrated_game(plan, tmp_path)
        staged_entry = staged_game_dir / f"{plan.game_name}.gq"
        post_bytes = _run_compile(staged_entry, tmp_path / "build", cwd=tmp_path)

        if post_bytes != pre_bytes:
            raise MigrateError(_byte_mismatch_message(plan, pre_bytes, post_bytes))

        # Verified -- now, and only now, touch the real workspace: move the
        # staged, byte-verified game directory into place, then remove the
        # original flat entry file. Never the shared assets/ tree -- other,
        # not-yet-migrated games may still reference it.
        #
        # build_plan() already rejected an existing new_game_dir up front,
        # but the two compiles in between can take a while -- re-check
        # right before the move narrows (doesn't eliminate; there's no
        # cross-platform atomic "move only if absent") the window where
        # something else creates new_game_dir in the meantime.
        # shutil.move(src, dst) treats an *existing* dst directory as "move
        # src inside dst", not "replace dst" -- so without this check the
        # staged game would land nested at new_game_dir/game_name/ instead
        # of new_game_dir/ itself, and the OSError handler's rollback below
        # would rmtree() whatever was already in that pre-existing
        # directory, not just what this migration wrote.
        if plan.new_game_dir.exists():
            raise MigrateError(
                f"{plan.new_game_dir} was created after this migration's "
                "precondition checks ran -- refusing to move the staged, "
                "verified game directory into it (that would nest it inside "
                "instead of replacing it). Remove it (if it's unrelated or "
                "stale) and re-run migrate; original flat game left in place."
            )

        try:
            shutil.move(str(staged_game_dir), str(plan.new_game_dir))
        except OSError as exc:
            # Same filesystem: os.rename is atomic, so this can only ever
            # fail all-or-nothing. Cross-filesystem (e.g. this temp
            # staging dir on /tmp vs. a real workspace on another mount)
            # shutil.move degrades to copytree+rmtree, and a mid-copy
            # failure (disk full, permissions, ...) can leave
            # new_game_dir partially populated in the *real* workspace
            # while the original flat entry file is still untouched.
            # Remove whatever landed so the workspace stays in exactly
            # one of its two valid states -- fully flat, never a
            # half-written migrated directory -- and report it as a
            # clean MigrateError, not a raw traceback (gqc.py's `migrate`
            # command only catches MigrateError/GqcParseError).
            shutil.rmtree(plan.new_game_dir, ignore_errors=True)
            raise MigrateError(
                f"{plan.game_name}: migrated directory verified and staged, "
                f"but moving it into place at {plan.new_game_dir} failed "
                f"({exc}) -- rolled back; original flat game left in place."
            ) from exc

    try:
        plan.entry_path.unlink()
    except OSError as exc:
        # The migrated directory is already in place and byte-verified, but
        # removing the original flat entry file failed (permissions, a
        # concurrent edit, ...). Roll back the move so the workspace always
        # ends up in exactly one of its two valid states -- fully flat, or
        # fully migrated -- never a hybrid with both present, which is what
        # this module's "leave the workspace untouched on failure" property
        # promises.
        shutil.rmtree(plan.new_game_dir, ignore_errors=True)
        raise MigrateError(
            f"{plan.game_name}: migrated directory verified and staged, but "
            f"removing the original {plan.entry_path} failed ({exc}) -- "
            "rolled back; original flat game left in place."
        ) from exc

    return MigrationResult(plan=plan, pre_bytes=pre_bytes, post_bytes=post_bytes)


def _byte_mismatch_message(plan: MigrationPlan, expected: bytes, actual: bytes) -> str:
    if len(expected) != len(actual):
        return (
            f"{plan.game_name}: migrated cart is {len(actual)} bytes, "
            f"original flat cart is {len(expected)} bytes -- aborting, "
            "original left untouched."
        )
    for offset, (exp_byte, act_byte) in enumerate(zip(expected, actual)):
        if exp_byte != act_byte:
            return (
                f"{plan.game_name}: first byte mismatch at offset {offset} "
                f"(original=0x{exp_byte:02x}, migrated=0x{act_byte:02x}), "
                f"{len(expected)} bytes total -- aborting, original left untouched."
            )
    return (
        f"{plan.game_name}: byte mismatch (could not localize -- lengths and "
        "content matched?) -- aborting, original left untouched."
    )


def report_plan(plan: MigrationPlan) -> str:
    if plan.already_migrated:
        return (
            f"{plan.game_name}: already migrated ({plan.entry_path} is already "
            "in the game-as-directory layout) -- nothing to do."
        )

    lines = [
        f"{plan.game_name}: migrate {plan.entry_path} -> {plan.new_entry_path}",
    ]
    by_section = {"animations": [], "lightcues": []}
    for copy in plan.asset_copies:
        by_section[copy.section].append(copy)

    shared_count = 0
    for section, label in (("animations", "animations"), ("lightcues", "lightcues")):
        copies = by_section[section]
        if not copies:
            continue
        lines.append(f"  {label} ({len(copies)} file(s)):")
        for copy in copies:
            names = ", ".join(copy.binding_names)
            asset_dir = _SECTION_ASSET_DIR[section]
            new_rel = f"assets/{asset_dir}/{copy.new_literal}"
            shared_note = ""
            if copy.shared_with:
                shared_count += 1
                shared_note = f" [shared with still-flat: {', '.join(copy.shared_with)}]"
            lines.append(
                f"    {copy.old_literal!r} -> {new_rel!r} (used by: {names}){shared_note}"
            )

    total = len(plan.asset_copies)
    lines.append(
        f"  {total} asset file(s) will be copied into {plan.new_game_dir}/assets/ "
        f"({shared_count} also referenced by at least one still-flat game -- "
        "duplicated by design, see gamequeer#432)."
    )
    return "\n".join(lines)


def report_result(result: MigrationResult) -> str:
    plan = result.plan
    if plan.already_migrated:
        return report_plan(plan)
    return (
        f"{plan.game_name}: migrated to {plan.new_entry_path} "
        f"({len(plan.asset_copies)} asset file(s) copied); "
        f"verified byte-identical {len(result.post_bytes)}-byte .gqgame output "
        "before and after migration; removed original "
        f"{plan.entry_path}."
    )
