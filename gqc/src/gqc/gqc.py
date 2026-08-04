import os
import sys
import pathlib
from collections import namedtuple

import click
from rich.progress import Progress

from . import parser
from . import anim, cues
from . import cst
from . import makefile_src
from . import linker
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
    with open(input, 'r') as f:
        source = f.read()

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
        with open(input, 'w') as f:
            f.write(formatted)
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
    directory_tree = [
        'assets',
        'assets/animations/',
        'assets/lighting/',
        'build',
        'games'
    ]

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

    # Drop the empty Makefile.local file
    with (base_dir / 'Makefile.local').open('w') as f:
        f.write('')
    
    # Drop the Makefile from makefile_src.py
    makefile_contents = makefile_src.makefile_skel.replace('GQCCMD', "python -m gqc")
    with (base_dir / 'Makefile').open('w') as f:
        f.write(makefile_contents)

@gqc_cli.command()
@click.argument('base_dir', type=click.Path(file_okay=False, dir_okay=True, writable=True, path_type=pathlib.Path))
def update_makefile_local(base_dir : pathlib.Path):
    makefile_path = base_dir / 'Makefile.local'

    GamePath = namedtuple('game_path', ['name', 'relpath'])

    games_src_dir = base_dir / 'games'

    # Get the complete relative path of all .gq files in the games directory, recursively
    game_src_paths = [game for game in games_src_dir.rglob('*.gq')]
    game_paths = []
    for path in game_src_paths:
        # For example, for a file at games/foo/bar/gamename.gq, we want to store:
        #  GamePath('gamename', 'foo/bar')
        game_paths.append(GamePath(path.stem, path.parents[0].relative_to(games_src_dir)))

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
            # Get the source directory and build a destination directory path under build/
            src_file = games_src_dir / (game_path.relpath) / f'{game_path.name}.gq'
            dest_dir = base_dir / 'build' / (game_path.relpath) / game_path.name
            dest_file = dest_dir / f'{game_path.name}.gqgame'
            # Create a Makefile target for the .gqgame file for the game
            f.write(f'{dest_file.relative_to(base_dir)}: {src_file.relative_to(base_dir)}\n')
            f.write(f'\t$(GQC_CMD) compile -o {dest_dir} $<\n\n')
            all_list.append(f'{dest_file.relative_to(base_dir)}')
        f.write('all: ' + ' '.join(all_list) + '\n')

if __name__ == '__main__':
    gqc_cli()
