import click
import pyparsing

@click.command()
def gqc():
    click.echo('Hello from GQC!')

if __name__ == '__main__':
    gqc()
