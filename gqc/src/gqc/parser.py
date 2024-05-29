import sys
import struct
from typing import Iterable

import pyparsing as pp

from .anim import Animation
from . import structs

class GqcParseError(Exception):
    def __init__(self, message, s, loc):
        # TODO: Show the actual line
        message = f"Error at line {pp.lineno(loc, s)}, column {pp.col(loc, s)}: {message}"
        super().__init__(message)

class Game:
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7
    game = None

    def __init__(self, id : int, title : str, author : str, starting_stage : str = 'start'):
        self.addr = 0x00000000 # Set at link time
        self.stages = []
        self.animations = []
        self.variables = []

        self.starting_stage = None
        self.starting_stage_name = starting_stage

        if Game.game is not None:
            raise ValueError("Game already defined")
        Game.game = self

        self.id = id
        self.title = title
        self.author = author

    def add_stage(self, stage):
        self.stages.append(stage)
        if stage.name == self.starting_stage_name:
            self.starting_stage = stage

    def add_animation(self, animation):
        self.animations.append(animation)

    def add_variable(self, variable):
        self.variables.append(variable)

    def pprint(self):
        print("Stages:")
        for stage in self.stages:
            print(stage)
        print("Animations:")
        for anim in self.animations:
            print(anim)
        print("Variables:")
        for var in self.variables:
            print(var)
    
    def __repr__(self) -> str:
        return f"Game({self.id}, {repr(self.title)}, {repr(self.author)})"
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Game.link_table[self.addr] = self
    
    def size(self):
        return structs.GQ_HEADER_SIZE

    def to_bytes(self):
        if self.starting_stage is None:
            raise ValueError("Starting stage not defined")
        header = structs.GqHeader(
            magic=structs.GQ_MAGIC,
            id=self.id,
            title=self.title.encode('ascii')[:structs.GQ_STR_SIZE-1],
            anim_count=len(self.animations),
            stage_count=len(self.stages),
            starting_stage_ptr=self.starting_stage.addr,
            flags=0,
            crc16=0
        )
        return struct.pack(structs.GQ_HEADER_FORMAT, *header)

class Stage:
    stage_table = {}
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7

    def __init__(self, name : str, bganim : str = None, menu : str = None, event_statements : Iterable = []):
        self.addr = 0x00000000 # Set at link time
        self.id = len(Stage.stage_table)
        self.resolved = False
        self.name = name
        self.bganim_name = bganim
        self.menu_name = menu
        self.event_statements = event_statements
        self.unresolved_symbols = []

        if name in Stage.stage_table:
            raise ValueError(f"Stage {name} already defined")
        Stage.stage_table[name] = self

        self.resolve()

        # TODO: what?
        Game.game.add_stage(self)

    def resolve(self) -> bool:
        # Don't bother trying to resolve symbols if we've already done so.
        if self.resolved:
            return True
        
        self.unresolved_symbols = []
        resolved = True

        # Attempt to resolve background animation
        if self.bganim_name is None:
            self.bganim = None
        elif self.bganim_name in Animation.anim_table:
            self.bganim = Animation.anim_table[self.bganim_name]
        else:
            self.unresolved_symbols.append(self.bganim_name)
            resolved = False

        # TODO: Attempt to resolve menu

        # TODO: Anything to do with event statements here?

        # Return whether the resolution of all symbols is complete.
        self.resolved = resolved
        return resolved

    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Stage.link_table[self.addr] = self
    
    def size(self):
        return structs.GQ_STAGE_SIZE

    def __repr__(self) -> str:
        return f"Stage({self.name})"
    
    def to_bytes(self):
        stage = structs.GqStage(
            id=self.id,
            anim_bg_pointer=self.bganim.addr if self.bganim else 0,
            menu_pointer=0,
            events_code_pointer=0,
            events_code_size=0
        )
        return struct.pack(structs.GQ_STAGE_FORMAT, *stage)
        

class Variable:
    var_table = {}
    storageclass_table = dict(persistent={}, volatile={})
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7

    def __init__(self, datatype : str, name : str, value, storageclass : str =None):
        self.addr = 0x00000000 # Set at link time
        self.datatype = datatype
        self.name = name
        self.value = value

        # TODO: set when the section is finished parsing
        self.storageclass = None

        if name in Variable.var_table:
            raise ValueError(f"Duplicate definition of {name}")
        Variable.var_table[name] = self

        if datatype == "int":
            if not isinstance(value, int):
                raise ValueError(f"Invalid value {value} for int variable {name}")
        elif datatype == "str":
            if not isinstance(value, str):
                raise ValueError(f"Invalid value {value} for str variable {name}")
            if len(value) > structs.GQ_STR_SIZE-1:
                raise ValueError(f"String {name} length {len(value)} exceeds maximum of {structs.GQ_STR_SIZE-1}")

        # TODO: needed?
        Game.game.add_variable(self)

    def __str__(self) -> str:
        return "<{} {} {} = {}>@{}".format(
            self.storageclass if self.storageclass else 'unlinked', 
            self.datatype, 
            self.name, 
            self.value, 
            self.addr
        )
    
    def __repr__(self) -> str:
        return f"Variable({repr(self.datatype)}, {repr(self.name)}, {self.value}, storageclass={repr(self.storageclass)})"

    def set_storageclass(self, storageclass):
        assert storageclass in ["volatile", "persistent"]
        self.storageclass = storageclass
        Variable.storageclass_table[storageclass][self.name] = self
    
    def to_bytes(self):
        if self.datatype == "int":
            # TODO: Extract constant int size and put it in structs.py
            return self.value.to_bytes(4, 'little')
        elif self.datatype == "str":
            strlen = len(self.value)
            if strlen > structs.GQ_STR_SIZE-1: # -1 for null terminator
                raise ValueError(f"String {self.name} length {strlen} exceeds maximum of {structs.GQ_STR_SIZE-1}")
        else:
            raise ValueError(f"Invalid datatype {self.datatype}")
    
    def size(self):
        if self.datatype == "int":
            return 4
        elif self.datatype == "str":
            return structs.GQ_STR_SIZE
        else:
            raise ValueError(f"Invalid datatype {self.datatype}")
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Variable.link_table[self.addr] = self

def parse_game_definition(instring, loc, toks):
    toks = toks[0]

    # Note: if we're already here, the parser has already enforced that each of the key
    #       parameters for the game are uniquely defined.
    # TODO: if we add optional parameters, this will need to be updated.
    id = None
    title = None
    author = None
    starting_stage = None

    try:
        for assignment in toks[1]:
            if assignment[0] == "id":
                id = assignment[1]
            elif assignment[0] == "title":
                title = assignment[1]
            elif assignment[0] == "author":
                author = assignment[1]
            elif assignment[0] == "starting_stage":
                starting_stage = assignment[1]
            else:
                raise ValueError(f"Invalid assignment {assignment[0]}")
        
        return Game(id, title, author, starting_stage)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse_stage_definition(instring, loc, toks):
    toks = toks[0]

    name = toks[0]

    stage_kwargs = dict(
        event_statements = []
    )

    for stage_options in toks[1]:
        if stage_options[0] == 'event':
            stage_kwargs['event_statements'].append(stage_options[1])
        elif stage_options[0] in stage_kwargs:
            raise GqcParseError(f"Duplicate option {stage_options[0]} for stage {name}", instring, loc)
        else:
            stage_kwargs[stage_options[0]] = stage_options[1]

    return Stage(name, **stage_kwargs)

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
    
    if Variable.storageclass_table[storageclass]:
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
    except pp.ParseBaseException as pe:
        print(pe.explain(), file=sys.stderr)
        exit(1)
    except GqcParseError as ge:
        print(ge, file=sys.stderr)
        exit(1)
    
    for stage in Stage.stage_table.values():
        if not stage.resolve():
            print(f"FATAL: Unresolved symbols remain in Stage `{stage.name}`: {', '.join(stage.unresolved_symbols)}", file=sys.stderr)
            exit(1)

    return parsed
