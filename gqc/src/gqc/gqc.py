import click
from gqc.parser import *

@click.command()
@click.argument('input', type=click.File('r'))
def gqc(input):
    parsed = parse(input)
    parsed.pprint()

if __name__ == '__main__':
    gqc()
