import pathlib

from collections import namedtuple

import click
from . import parser
from . import anim
from . import makefile_src

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
    anim.make_animation(src_path, out_path, dither, frame_rate)

@gqc_cli.command()
@click.option('--out-path', '-o', type=click.Path(file_okay=False, dir_okay=True, writable=True, path_type=pathlib.Path), default='out.gqgame')
@click.argument('input', type=click.File('r'))
def compile(input, out_path : pathlib.Path):
    # Parse the game file
    parsed = parser.parse(input)

    # TODO: next step, not just printing
    parsed.pprint()

    # TODO: animation processing

    # TODO: lightcue processing

    # TODO: Code generation

    # TODO: Linker

@gqc_cli.command()
@click.argument('base_dir', type=click.Path(file_okay=False, dir_okay=True, writable=True, path_type=pathlib.Path))
@click.option('--force', '-f', is_flag=True)
def init_dir(base_dir : pathlib.Path, force : bool):
    directory_tree = [
        'assets',
        'assets/animations/',
        'assets/lightcues/',
        'build',
        'build/assets',
        'build/assets/animations',
        'build/assets/lightcues',
        'games'
    ]

    git_ignore = [
        'build/',
        'Makefile.local',
    ]

    create_files = [
        'Makefile',
        'Makefile.local',
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

    game_dir = base_dir / 'games'

    # Get the complete relative path of all .gq files in the games directory, recursively
    game_src_paths = [game for game in game_dir.rglob('*.gq')]
    game_paths = []
    for path in game_src_paths:
        g = GamePath(path.stem, path.parents[0].relative_to(game_dir))
        game_paths.append(g)

    # Populate the Makefile with the game destinations, and create
    #  the build directory tree for games as well.
    with makefile_path.open('w') as f:
        f.write('# Auto-generated Makefile.local\n\n')
        f.write('GQC_CMD := python -m gqc\n\n')
        f.write('.PHONY: all\n')
        f.write('.DEFAULT_GOAL := all\n\n')
        all_list = []
        for game_path in game_paths:
            src_file = game_dir / (game_path.relpath) / f'{game_path.name}.gq'
            dest_dir = base_dir / 'build' / (game_path.relpath)
            dest_file = dest_dir / f'{game_path.name}.gqgame'
            f.write(f'{dest_file.relative_to(base_dir)}: {src_file.relative_to(base_dir)}\n')
            f.write(f'\t$(GQC_CMD) compile -o $@ $<\n\n')
            all_list.append(f'{dest_file.relative_to(base_dir)}')
        f.write('all: ' + ' '.join(all_list) + '\n')

if __name__ == '__main__':
    gqc_cli()
