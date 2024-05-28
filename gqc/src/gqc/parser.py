from dataclasses import dataclass

import pyparsing as pp

from . import anim

class GqcParseError(Exception):
    def __init__(self, message, s, loc):
        # TODO: Show the actual line
        message = f"Error at line {pp.lineno(loc, s)}, column {pp.col(loc, s)}: {message}"
        super().__init__(message)

class Stage:
    stage_table = {}

    def __init__(self, name):
        self.name = name
        self.bganim = None
        self.menu = None
        self.events = []

        if name in Stage.stage_table:
            raise ValueError(f"Stage {name} already defined")
        Stage.stage_table[name] = self

    def __repr__(self) -> str:
        return f"Stage({self.name})"

class Animation:
    anim_table = {}
    link_table = None
    
    def __init__(self, name, source, frame_rate=None, dithering=None):
        self.name = name
        self.source = source
        self.frame_rate = frame_rate
        self.dithering = dithering

        if name in Animation.anim_table:
            raise ValueError("Animation {} already defined".format(name))
        Animation.anim_table[name] = self
    
    def __repr__(self) -> str:
        return f"Animation({self.name}, {self.source}, {self.frame_rate}, {repr(self.dithering)})"

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
            raise ValueError(f"Duplicate definition of {name}")
        Variable.var_table[name] = self

        self.addr = None # Set at link time

    def __str__(self) -> str:
        return "<{} {} {} = {}>@{}".format(
            self.storageclass if self.storageclass else 'unlinked', 
            self.datatype, 
            self.name, 
            self.value, 
            self.addr
        )
    
    def __repr__(self) -> str:
        return f"Variable({self.datatype}, {self.name}, {self.value})"

    def set_storageclass(self, storageclass):
        assert storageclass in ["volatile", "persistent"]
        self.storageclass = storageclass
        Variable.link_table[storageclass][self.name] = self

def parse_animation_definition(instring, loc, toks):
    toks = toks[0]

    name = toks[0]
    source = toks[1]

    frame_rate = None
    dithering = None

    kwargs = dict()

    if toks[2]:
        for opt in toks[2]:
            if opt[0] == "frame_rate":
                if frame_rate in kwargs:
                    raise GqcParseError(f"Duplicate frame_rate for animation {name}", instring, loc)
                kwargs['frame_rate'] = opt[1]
            elif opt[0] == "dithering":
                if dithering in kwargs:
                    raise GqcParseError(f"Duplicate dithering for animation {name}", instring, loc)
                kwargs["dithering"] = opt[1]

    try:
        return Animation(name, source, **kwargs)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse_variable_definition(instring, loc, toks):
    toks = toks[0]

    datatype = toks[0]
    name = toks[1]
    value = toks[2]
    try:
        return Variable(datatype, name, value)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse_variable_definition_storageclass(instring, loc, toks):
    toks = toks[0]
    storageclass = toks[0]

    # TODO: Is this needed?
    if storageclass not in ["volatile", "persistent"]:
        raise GqcParseError(f"Invalid storage class: {storageclass}", instring, loc)
    
    if Variable.link_table[storageclass]:
        raise GqcParseError(f"Storage class {storageclass} already defined", instring, loc)
    
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
    except GqcParseError as ge:
        print(ge)
        exit(1)
