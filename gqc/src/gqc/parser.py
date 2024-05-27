from dataclasses import dataclass

import pyparsing as pp

class Animation:
    pass

class AnimationTable:
    pass

class Variable:
    var_table = {}
    link_table = dict(persistent={}, volatile={})

    def __init__(self, datatype, name, value):
        self.datatype = datatype
        self.name = name
        self.value = value

        # TODO: set when the section is finished parsing
        self.storageclass = None

        if name in Variable.var_table:
            # TODO: parse error?
            raise ValueError("Variable {} already defined".format(name))

        self.addr = None # Set at link time

    def __str__(self) -> str:
        return "<{} {} {} = {}>@{}".format(self.storageclass if self.storageclass else 'unlinked', self.datatype, self.name, self.value, self.addr)
    
    def __repr__(self) -> str:
        return "<{} {} {} = {}>@{}".format(self.storageclass if self.storageclass else 'unlinked', self.datatype, self.name, self.value, self.addr)

    def set_storageclass(self, storageclass):
        assert storageclass in ["volatile", "persistent"]
        self.storageclass = storageclass
        Variable.link_table[storageclass][self.name] = self

def parse_variable_definition(toks):
    toks = toks[0]

    datatype = toks[0]
    name = toks[1]
    value = toks[2]
    return Variable(datatype, name, value)

def parse_variable_definition_storageclass(toks):
    toks = toks[0]
    storageclass = toks[0]

    # TODO: Parse errors?
    if storageclass not in ["volatile", "persistent"]:
        raise ValueError("Invalid storage class: {}".format(storageclass))
    
    if Variable.link_table[storageclass]:
        raise ValueError("Storage class {} already defined".format(storageclass))
    
    for var in toks[1]:
        var.set_storageclass(storageclass)
    
    # TODO: Needed?
    # return Variable.link_table[storageclass]

def parse(text):
    # Import here to avoid circular import
    from gqc import grammar

    gqc_game = grammar.build_game_parser()
    try:
        parsed = gqc_game.parse_file(text, parseAll=True)
        return parsed
    except pp.ParseBaseException as pe:
        print(pe.explain())
        print("column: {}".format(pe.column))
        exit(1)
