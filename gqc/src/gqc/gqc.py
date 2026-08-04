import os
import sys
import pathlib
import tempfile
from collections import namedtuple

import click
from rich.progress import Progress

from . import parser
from . import anim, cues
from . import cst
from . import makefile_src
from . import linker
from . import migrate as migrate_mod
from . import GqcParseError
from .datamodel import Game

DITHER_CHOICES = ('none', 'bayer', 'heckbert', 'floyd_steinberg', 'sierra2', 'sierra2_4a')

@click.group()
def gqc_cli():
    pass

@gqc_cli.command()
@click.option('--out-path', '-o', type=click.Path(file_okay=False, dir_okay=True, writable=True, path_type=pathlib.Path), required=True)
@click.option('--src-path', '-i', type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True, path_type=pathlib.Path), required=True)
@click.option('--dither', '-d', type=click.Choice(DITHER_CHOICES), default=DITHER_CHOICES[0])
@click.option('--frame-rate', '-f', type=int, default=24)
def mkanim(out_path : pathlib.Path, src_path : pathlib.Path, dither : str, frame_rate : int):
    with Progress() as progress:
        anim.make_animation(progress, src_path, out_path, dither, frame_rate)

@gqc_cli.command()
@click.option('--out-path', '-o', type=click.Path(file_okay=False, dir_okay=True, writable=True, path_type=pathlib.Path), required=True)
@click.option('--src-path', '-i', type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True, path_type=pathlib.Path), required=True)
def mkcue(out_path : pathlib.Path, src_path : pathlib.Path):
    with Progress() as progress:
        cues.make_cue(progress, src_path, out_path)

@gqc_cli.command()
@click.argument('input', type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True, path_type=pathlib.Path), required=True)
@click.option('--write', '-w', is_flag=True, help="Write the formatted output back to INPUT instead of printing it to stdout.")
@click.option('--check', is_flag=True, help="Don't write anything; exit nonzero if INPUT isn't already formatted.")
def fmt(input : pathlib.Path, write : bool, check : bool):
    """Parse INPUT to gqc's comment- and layout-preserving CST (gqc.cst)
    and re-emit it, proving the CST round-trips (gamequeer#424 step 1).

    This step's `render` is an identity transform -- no reindentation or
    other pretty-printing happens yet (that's explicitly deferred to a
    follow-on step; see gqc.cst's module docstring) -- so today this is
    mainly useful as a `--check` round-trip/lossless-parse validator, and
    as the CST's own proof of concept."""
    if write and check:
        click.echo("--write and --check are mutually exclusive", err=True)
        raise SystemExit(1)

    # encoding='utf-8': gqc source is UTF-8 (see the UnicodeDecodeError
    # handling below); without an explicit encoding, open() falls back to
    # locale.getpreferredencoding(), which varies by platform/locale and can
    # silently misdecode non-UTF-8 bytes instead of raising. newline='':
    # disables universal-newline translation, so a CRLF- or CR-terminated
    # INPUT is read (and, on --write, written back out) exactly as-is --
    # required for the byte-for-byte round-trip guarantee this module exists
    # to prove (see test_round_trip_preserves_windows_line_endings).
    try:
        with open(input, 'r', encoding='utf-8', newline='') as f:
            source = f.read()
    except UnicodeDecodeError as ue:
        click.echo(f"{input}: cannot decode as UTF-8: {ue}", err=True)
        raise SystemExit(1)

    try:
        tree = cst.parse_cst(source)
    except GqcParseError as ge:
        click.echo(str(ge), err=True)
        raise SystemExit(1)

    formatted = cst.render(tree)

    if check:
        if formatted != source:
            click.echo(f"{input} is not formatted", err=True)
            raise SystemExit(1)
        return

    if write:
        # Write to a sibling temp file and os.replace() it into place instead
        # of truncating INPUT in place (`open(input, 'w')`) -- the latter
        # destroys the source the instant it's opened, so any failure between
        # open and a completed write (disk full, process killed, ...) leaves
        # INPUT empty/truncated with no way back. os.replace() is atomic on
        # the same filesystem, so INPUT is either untouched or fully
        # replaced, never partially written.
        fd, tmp_path = tempfile.mkstemp(prefix=f'.{input.name}.', suffix='.tmp', dir=input.parent)
        try:
            # Same encoding='utf-8', newline='' rationale as the read above.
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
                f.write(formatted)
            os.replace(tmp_path, input)
        except BaseException:
            os.unlink(tmp_path)
            raise
    else:
        click.echo(formatted, nl=False)

@gqc_cli.command()
@click.option('--no-mem-map', '-n', is_flag=True)
@click.option('--out-dir', '-o', type=click.Path(file_okay=False, dir_okay=True, writable=True, path_type=pathlib.Path), default=None)
@click.argument('input', type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True, path_type=pathlib.Path), required=True)
def compile(input : pathlib.Path, no_mem_map : bool, out_dir : pathlib.Path):
    Game.game_name = input.stem
    # gamequeer#420: animations{}/lightcues{} asset sources resolve relative
    # to the game's own directory (the entry file's parent), not the
    # process CWD -- see Animation.src_path/parse_lightcue_definition_section.
    # This is what makes `gqc compile some/other/dir/foo.gq` work correctly
    # from outside that directory, and is a no-op for the common case where
    # the entry file is already at the top of the invocation directory.
    #
    # gqc expects the game-as-directory layout everywhere (`<name>/<name>.gq`
    # with its assets nested underneath) -- there is no CWD-relative
    # fallback for a flat entry file. A game still on the old flat layout
    # should be moved onto this layout with `gqc migrate` (see migrate.py).
    Game.game_dir = input.parent

    # output_path is the directory where the output of the project will be placed
    if out_dir is None:
        out_dir = pathlib.Path.cwd() / 'build' / Game.game_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # We'll create the following, unless told not to:
    #  out_path/
    #  ├── assets/
    #  │   ├── animations/
    #  │   └── lighting/
    #  ├── map.txt
    #  └── <game_name>.gqgame

    # Load all our builtin variables
    linker.create_reserved_variables()

    # Parse the game file, implemented almost entirely in side effects
    with open(input, 'r') as f:
        parsed = parser.parse(f)

    # If the game calls fw_version() anywhere (gamequeer#411), splice the
    # compiler-synthesized firmware-detection probe stage in ahead of its
    # declared starting stage. Games that never call fw_version() skip this
    # entirely -- no probe stage, no extra boot delay.
    if Game.game.needs_fw_probe:
        linker.inject_fw_version_probe()

    # Same zero-footprint-when-unused convention for random() (gamequeer#422):
    # only create its hidden LCG state/counter variables if the game
    # actually calls random() somewhere.
    if Game.game.needs_random:
        linker.create_random_state_variables()

    # Place symbols into the symbol table
    mem_map_path = out_dir / 'map.txt'
    cmd_asm_path = out_dir / 'cmds.gqasm'
    if no_mem_map:
        mem_map_path = os.devnull
        cmd_asm_path = os.devnull

    with open(mem_map_path, 'w') as map_file, open(cmd_asm_path, 'w') as cmd_asm_file:
        symbol_table = linker.create_symbol_table(table_dest=map_file, cmd_dest=cmd_asm_file)

    # Code generation
    output_code = linker.generate_code(parsed, symbol_table)
    with open(out_dir / f'{Game.game_name}.gqgame', 'wb') as out_file:
        out_file.write(output_code)

# gamequeer#420: the game-as-directory layout convention -- a game is a
# directory whose entry file is `<dirname>/<dirname>.gq`, with its own
# `assets/animations/`/`assets/lighting/` subdirectories that
# animations{}/lightcues{} sources resolve against (see
# Animation.src_path / parser.parse_lightcue_definition_section), instead
# of a shared top-level `assets/` root. `new` scaffolds exactly that shape
# so a freshly-created game is born correctly-structured.
GAME_SKEL = """\
game {
    // TODO: pick a real cart id (unique per physical cartridge).
    id = 0;
    title := "GQC_NEW_TITLE";
    author := "Your Name";
    starting_stage = start;
}

stage start {
    event enter {
    }
}
"""

@gqc_cli.command()
@click.argument('name', type=str, required=True)
@click.option('--out-dir', '-o', type=click.Path(file_okay=False, dir_okay=True, writable=True, path_type=pathlib.Path), default=None)
@click.option('--force', '-f', is_flag=True)
def new(name : str, out_dir : pathlib.Path, force : bool):
    """Scaffold a new game directory NAME in the game-as-directory layout
    (gamequeer#420): NAME/NAME.gq (a starter game{} block and a placeholder
    `start` stage) plus NAME/assets/animations/ and NAME/assets/lighting/.

    NAME's own directory is created under --out-dir (default: the current
    directory)."""
    base_dir = (out_dir if out_dir is not None else pathlib.Path.cwd()) / name
    entry_path = base_dir / f'{name}.gq'

    directory_tree = [
        'assets/animations',
        'assets/lighting',
    ]

    # Check to see if the game directory or entry file already exist
    if base_dir.exists() and not force:
        click.echo(f"Directory {base_dir} already exists; aborting.")
        return
    if entry_path.exists() and not force:
        click.echo(f"File {entry_path} already exists; aborting.")
        return

    # Create the directory tree
    for dir in directory_tree:
        (base_dir / dir).mkdir(parents=True, exist_ok=True)

    # Drop the starter entry file, unless one's already there and --force
    # wasn't passed (checked above).
    entry_path.write_text(GAME_SKEL.replace('GQC_NEW_TITLE', name))

    click.echo(f"Created new game {name!r} at {base_dir}")

@gqc_cli.command()
@click.argument('base_dir', type=click.Path(file_okay=False, dir_okay=True, writable=True, path_type=pathlib.Path))
@click.option('--force', '-f', is_flag=True)
def init_dir(base_dir : pathlib.Path, force : bool):
    """Scaffold a fresh gqc workspace at BASE_DIR: a `build/` output
    directory, a `.gitignore`, and a self-sufficient `Makefile`
    (`makefile_src.py`) that discovers the game-as-directory layout
    (gamequeer#420) natively in GNU Make. There's no top-level `games/` or
    shared `assets/` directory here -- each game brings its own
    `<name>/assets/` when scaffolded with `gqc new <name>`."""
    directory_tree = [
        'build',
    ]

    # Makefile.local isn't written or referenced by the generated Makefile
    # above (GNU Make discovers games live), but a workspace may still hand-
    # maintain a Makefile that -includes one via `gqc update-makefile-local`,
    # so it stays ignored.
    git_ignore = [
        'build/',
        'Makefile.local',
    ]

    create_files = [
        'Makefile',
        '.gitignore',
    ]

    # Check to see if any of the directory tree already exist
    for dir in directory_tree:
        if (base_dir / dir).exists():
            if force:
                click.echo(f"INFO: Directory {dir} already exists")
            else:
                click.echo(f"Directory {dir} already exists; aborting.")
                return

    # Check to see if any of the files already exist
    for file in create_files:
        if (base_dir / file).exists():
            if force:
                click.echo(f"WARN: File {file} already exists; overwriting.")
            else:
                click.echo(f"File {file} already exists; aborting.")
                return

    # Create the directory tree
    for dir in directory_tree:
        (base_dir / dir).mkdir(parents=True, exist_ok=True)

    # Drop the gitignore file
    with (base_dir / '.gitignore').open('w') as f:
        f.write('\n'.join(git_ignore))

    # Drop the Makefile from makefile_src.py
    makefile_contents = makefile_src.makefile_skel.replace('GQCCMD', "python -m gqc")
    with (base_dir / 'Makefile').open('w') as f:
        f.write(makefile_contents)

@gqc_cli.command()
@click.argument('base_dir', type=click.Path(file_okay=False, dir_okay=True, writable=True, path_type=pathlib.Path))
def update_makefile_local(base_dir : pathlib.Path):
    """Regenerate BASE_DIR/Makefile.local for the game-as-directory layout
    (gamequeer#420): every top-level directory directly under BASE_DIR
    whose own name matches a `.gq` file inside it (`<name>/<name>.gq`) is
    treated as a game, mirroring the discovery the generated `Makefile`
    (`gqc init-dir`, `makefile_src.py`) does natively in GNU Make.

    The generated `Makefile` no longer -includes or invokes this command
    -- it computes the game list live with $(wildcard)/$(foreach). This
    remains for a hand-maintained Makefile that still wants a
    Makefile.local fragment to -include."""
    makefile_path = base_dir / 'Makefile.local'

    GamePath = namedtuple('game_path', ['name', 'dir'])

    # Every top-level directory whose own name matches a .gq file directly
    # inside it -- not a recursive scan, and not the old flat games/*.gq
    # convention.
    game_paths = []
    if base_dir.is_dir():
        for entry in sorted(base_dir.iterdir()):
            if entry.is_dir() and (entry / f'{entry.name}.gq').is_file():
                game_paths.append(GamePath(entry.name, entry))

    # Populate the Makefile with the game destinations, and create
    #  the build directory tree for games as well.
    with makefile_path.open('w') as f:
        f.write('# Auto-generated Makefile.local\n\n')
        f.write('GQC_CMD := python -m gqc\n\n')
        f.write('.PHONY: all\n')
        f.write('.DEFAULT_GOAL := all\n\n')
        all_list = []
        # For every detected game,
        for game_path in game_paths:
            # Get the source file and build a destination directory path under build/
            src_file = game_path.dir / f'{game_path.name}.gq'
            dest_dir = base_dir / 'build' / game_path.name
            dest_file = dest_dir / f'{game_path.name}.gqgame'
            # Create a Makefile target for the .gqgame file for the game
            f.write(f'{dest_file.relative_to(base_dir)}: {src_file.relative_to(base_dir)}\n')
            f.write(f'\t$(GQC_CMD) compile -o {dest_dir} $<\n\n')
            all_list.append(f'{dest_file.relative_to(base_dir)}')
        f.write('all: ' + ' '.join(all_list) + '\n')

@gqc_cli.command()
@click.argument('game', type=str, required=True)
@click.option(
    '--workspace', '-w',
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=pathlib.Path),
    default=pathlib.Path('.'),
    help="Workspace root (contains games/ and assets/). Defaults to the current directory.",
)
@click.option('--dry-run', '-n', is_flag=True, help="Print the migration plan without touching anything.")
def migrate(game : str, workspace : pathlib.Path, dry_run : bool):
    """Migrate GAME from the flat workspace layout (games/GAME.gq + a
    shared assets/ tree) to the self-contained game-as-directory layout
    (gamequeer#420): GAME/GAME.gq, with only the assets it actually
    references copied into GAME/assets/ and their path literals rewritten
    to match (surgically, via gqc.cst -- comments and formatting survive
    untouched).

    GAME may be a bare game name (looked up under --workspace) or a path
    to its entry .gq file directly. Idempotent: migrating an
    already-migrated game is a no-op. Verifies the migrated game compiles
    to byte-identical .gqgame output before committing anything -- on any
    failure, the original flat game is left completely untouched. See
    gqc.migrate's module docstring for the full design rationale
    (destination layout, path-flattening, and the shared-asset policy)."""
    try:
        plan = migrate_mod.build_plan(game, workspace)
    except migrate_mod.MigrateError as me:
        click.echo(str(me), err=True)
        raise SystemExit(1)
    except GqcParseError as ge:
        # GAME's entry file doesn't tokenize cleanly (gqc.cst.parse_cst,
        # called from build_plan) -- same clean-error convention as `gqc
        # fmt` above, rather than a raw traceback.
        click.echo(str(ge), err=True)
        raise SystemExit(1)

    click.echo(migrate_mod.report_plan(plan))

    if dry_run or plan.already_migrated:
        return

    try:
        result = migrate_mod.execute(plan)
    except migrate_mod.MigrateError as me:
        click.echo(str(me), err=True)
        raise SystemExit(1)

    click.echo(migrate_mod.report_result(result))

if __name__ == '__main__':
    gqc_cli()
