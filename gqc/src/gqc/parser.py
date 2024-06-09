import sys

import pyparsing as pp

from .datamodel import Animation, Game, Stage, Variable, Event
from .datamodel import Command, CommandDone, CommandPlayBg, CommandGoStage
from .datamodel import CommandSetVar
from .structs import EventType

class GqcParseError(Exception):
    def __init__(self, message, s, loc):
        # TODO: Show the actual line
        message = f"Error at line {pp.lineno(loc, s)}, column {pp.col(loc, s)}: {message}"
        super().__init__(message)

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
        events = []
    )

    for stage_option in toks[1]:
        if isinstance(stage_option, Event):
            stage_kwargs['events'].append(stage_option)
        elif stage_option[0] in stage_kwargs:
            raise GqcParseError(f"Duplicate option {stage_option[0]} for stage {name}", instring, loc)
        else:
            stage_kwargs[stage_option[0]] = stage_option[1]

    return Stage(name, **stage_kwargs)

def parse_event_definition(instring, loc, toks):
    toks = toks[0]

    event_type = None
    event_statements = None

    if toks[1] == 'bgdone':
        event_type = EventType.BGDONE
        event_statements = toks[2]
    elif toks[1] == 'input':
        event_inputs = {
            'A' : EventType.BUTTON_A,
            'B' : EventType.BUTTON_B,
            '->' : EventType.BUTTON_R,
            '<-' : EventType.BUTTON_L,
            '-' : EventType.BUTTON_CLICK
        }
        event_type = event_inputs[toks[2]]
        event_statements = toks[3]
    elif toks[1] == 'menu':
        raise NotImplementedError("Menu events not yet implemented")
    elif toks[1] == 'enter':
        event_type = EventType.ENTER
        event_statements = toks[2]
    
    return Event(event_type, event_statements)

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
        non_init_vars_present = False
        for var in Variable.storageclass_table[storageclass].values():
            if not var.name.endswith(".init"):
                non_init_vars_present = True
                break
        if non_init_vars_present:
            raise GqcParseError(f"Storage class {storageclass} already defined", instring, loc)
    
    for var in toks[1]:
        var.set_storageclass(storageclass)
    
    # TODO: Needed?
    # return Variable.link_table[storageclass]

def parse_assignment(instring, loc, toks):
    toks = toks[0]

    dst = toks[0]
    if toks[1] == "=":
        datatype = "int"
    elif toks[1] == ":=":
        datatype = "str"
    else:
        raise GqcParseError(f"Invalid assignment operator {toks[1]}", instring, loc)
    
    src = toks[2]

    return ['setvar', dst, src, datatype]

def parse_command(instring, loc, toks):
    toks = toks[0]

    command = toks[0]

    if command == "play":
        if toks[1] == 'bganim':
            return CommandPlayBg(instring, loc, toks[2])
        else:
            raise GqcParseError(f"Invalid play subcommand {command}", instring, loc)
    elif command == "gostage":
        return CommandGoStage(instring, loc, toks[1])
    elif command == 'setvar':
        return CommandSetVar(instring, loc, toks[1], toks[2], toks[3])
    else:
        raise GqcParseError(f"Invalid command {command}", instring, loc)

def parse(text):
    # Import here to avoid circular import
    from gqc import grammar

    gqc_game = grammar.build_game_parser()
    try:
        parsed = gqc_game.parse_file(text, parseAll=True)
        # TODO: Either do something with parsed or don't accept the return value.
        # print(parsed)
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
