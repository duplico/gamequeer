import pyparsing as pp

from gqc import grammar

def parse(text):
    try:
        parsed = grammar.gqc_game.parse_file(text, parseAll=True)
        return parsed
    except pp.ParseBaseException as pe:
        print(pe.explain())
        print("column: {}".format(pe.column))
        exit(1)
