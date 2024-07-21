import sys
import pathlib
from collections import namedtuple

import pyparsing as pp
from rich import print

from .datamodel import Animation, Game, Stage, Variable, Event, Menu, LightCue
from .datamodel import IntExpression, GqcIntOperand
from .commands import CommandPlay, CommandGoStage, CommandCue
from .commands import CommandSetStr, CommandSetInt
from .commands import CommandTimer, CommandIf, CommandGoto, CommandLoop, Command
from .structs import EventType
from . import structs

class GqcParseError(Exception):
    def __init__(self, message, s, loc):
        message = f"Error at line {pp.lineno(loc, s)}, column {pp.col(loc, s)}: {message}"
        super().__init__(message)

def parse_game_definition(instring, loc, toks):
    toks = toks[0]

    # Note: if we're already here, the parser has already enforced that each of the key
    #       parameters for the game are uniquely defined.
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

def parse_bound_menu(instring, loc, toks):
    menu_name = toks[0]
    menu_prompt = ''
    if len(toks) == 2:
        menu_prompt = toks[1]
    
    return Stage.BoundMenu(menu_name, menu_prompt)

def parse_stage_definition(instring, loc, toks):
    toks = toks[0]

    name = toks[0]

    stage_kwargs = dict(
        events = []
    )

    for stage_option in toks[1]:
        if isinstance(stage_option, Event):
            stage_kwargs['events'].append(stage_option)
        elif isinstance(stage_option, Stage.BoundMenu):
            if 'menu' in stage_kwargs:
                raise GqcParseError(f"Duplicate menu definition for stage {name}", instring, loc)
            stage_kwargs['menu'] = stage_option
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
        event_type = EventType.MENU
        event_statements = toks[2]
    elif toks[1] == 'enter':
        event_type = EventType.ENTER
        event_statements = toks[2]
    elif toks[1] == 'timer':
        event_type = EventType.TIMER
        event_statements = toks[2]
    elif toks[1] == 'fgdone':
        if toks[2] == 1:
            event_type = EventType.FGDONE1
        elif toks[2] == 2:
            event_type = EventType.FGDONE2
        else:
            raise GqcParseError(f"Invalid fgdone number {toks[2]}: expected 1 or 2", instring, loc)
        event_statements = toks[3]
    
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
            if opt[0] in kwargs:
                raise GqcParseError(f"Duplicate option {opt[0]} for animation {name}", instring, loc)
            kwargs[opt[0]] = opt[1]

    try:
        return Animation(name, source, **kwargs)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse_menu_definition(instring, loc, toks):
    menu_name = toks[0]
    menu_options = dict()
    for val, label in toks[1]:
        menu_options[label] = val
    
    try:
        return Menu(menu_name, menu_options)
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
    
    if Variable.storageclass_table[storageclass]:
        non_init_vars_present = False
        for var in Variable.storageclass_table[storageclass].values():
            if not var.name in structs.GQ_REGISTERS_INT and not var.name.endswith(".init") and not var.name.endswith(".strlit"):
                non_init_vars_present = True
                break
        if non_init_vars_present:
            raise GqcParseError(f"Storage class {storageclass} already defined by {var.name}", instring, loc)
    
    for var in toks[1]:
        var.set_storageclass(storageclass)

def parse_lightcue_definition_section(instring, loc, toks):
    # Import here to avoid circular import
    from .cues import parse_cue
    toks = toks[0]

    for cue in toks:
        cue_name = cue[0]
        cue_source = pathlib.Path() / 'assets' / 'lighting' / cue[1]

        print(f"[blue]Light cue [italic]{cue_name}[/italic][/blue] from [underline]{cue_source}[/underline]")
        with open(cue_source, 'r') as f:
            parsed_cue = parse_cue(f)
        try:
            parsed_cue.set_name(cue_name)
        except ValueError as ve:
            raise GqcParseError(str(ve), instring, loc)

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

    return [['setvar', dst, src, datatype]]

def parse_int_operand(instring, loc, toks):
    if isinstance(toks[0], GqcIntOperand):
        return toks[0]
    elif isinstance(toks[0], int):
        return GqcIntOperand(True, toks[0])
    else:
        return GqcIntOperand(False, toks[0])

def parse_int_expression(instring, loc, toks):
    toks = toks[0]
    if isinstance(toks, GqcIntOperand):
        return toks

    return IntExpression(toks, instring, loc)

def parse_str_literal(instring, loc, toks):
    return Variable.get_str_literal(toks[0])

def parse_if(instring, loc, toks):
    condition = toks[0]
    true_block = toks[1]
    false_block = toks[2] if len(toks) == 3 else None

    return CommandIf(instring, loc, condition, true_block, false_cmds=false_block)

def parse_play(instring, loc, toks):
    toks = toks[0]
    _, anim_type, anim_name = toks
    
    if anim_type[0] == 'bganim':
        anim_index = 0
    elif anim_type[0] == 'fganim':
        anim_index = 1 + (anim_type[1]-1) * 2 # 1 -> 1; 2 -> 3
    elif anim_type[0] == 'fgmask':
        anim_index = 2 + (anim_type[1]-1) * 2 # 1 -> 2; 2 -> 4
    
    if anim_index > 4: # TODO: Constant
        raise GqcParseError(f"Animation type/number out of bounds!", instring, loc)
    
    return CommandPlay(instring, loc, anim_name, anim_index)

def parse_command(instring, loc, toks):
    toks = toks[0]

    # If the command has already been fully parsed, just pass it through:
    if isinstance(toks, Command):
        return toks

    # Otherwise, parse it:
    command = toks[0]

    if command == "cue":
        if toks[1] not in LightCue.cue_table:
            raise GqcParseError(f"Undefined cue {toks[1]}", instring, loc)
        return CommandCue(instring, loc, toks[1])
    elif command == "gostage":
        return CommandGoStage(instring, loc, toks[1])
    elif command == 'setvar':
        _, dst, src, datatype = toks
        if datatype == 'str':
            return CommandSetStr(instring, loc, dst, src)
        else:
            if isinstance(src, int):
                src = GqcIntOperand(is_literal=True, value=src)
            else:
                assert isinstance(src, GqcIntOperand) or isinstance(src, IntExpression)
                return CommandSetInt(instring, loc, dst, src)
    elif command == 'timer':
        return CommandTimer(instring, loc, toks[1])
    elif command in ['break', 'continue']:
        return CommandGoto(instring, loc, form=command)
    elif command == 'loop':
        return CommandLoop(instring, loc, toks[1])
    else:
        raise GqcParseError(f"Invalid command {command}", instring, loc)

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
