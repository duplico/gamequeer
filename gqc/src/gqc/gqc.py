import pathlib

import click
import gqc.parser
import gqc.anim

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
    gqc.anim.make_animation(src_path, out_path, dither, frame_rate)

@gqc_cli.command()
@click.argument('input', type=click.File('r'))
def compile(input):
    # Parse the game file
    parsed = gqc.parser.parse(input)

    # TODO: next step, not just printing
    parsed.pprint()

    # TODO: animation processing

    # TODO: lightcue processing

    # TODO: Code generation

    # TODO: Linker

if __name__ == '__main__':
    gqc_cli()
