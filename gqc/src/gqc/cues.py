import sys
import pathlib
import webcolors

import pyparsing as pp
from rich.progress import Progress
from rich import print

from . import GqcParseError
from .datamodel import CueColor, LightCueFrame, LightCue

def parse_cue(text) -> LightCue:
    # Import here to avoid circular import
    from gqc import grammar_gqcue

    gqc_cue = grammar_gqcue.build_lightcue_parser()

    try:
        parsed = gqc_cue.parse_file(text, parseAll=True)
    except pp.ParseBaseException as pe:
        print(pe.explain(), file=sys.stderr)
        exit(1)
    except GqcParseError as ge:
        print(ge, file=sys.stderr)
        exit(1)

    return parsed[0]

def parse_color_definition(instring, loc, toks):
    toks = toks[0]

    color_name = toks[0]
    color_value = toks[1]

    try:
        color = webcolors.name_to_rgb(color_value)
    except ValueError:
        try:
            color = webcolors.hex_to_rgb(color_value)
        except ValueError:
            raise GqcParseError(f"Invalid color value {color_value}", instring, loc)

    return CueColor(color_name, color.red, color.green, color.blue)

def parse_cue_frame(instring, loc, toks):
    colors = []
    kwargs = dict()
    
    for tok in toks:
        if tok[0] == 'colors':
            # Note: The number of colors is enforced by pyparsing
            for color in tok[1:6]:
                colors.append(color)
        elif tok[0] not in kwargs:
            val = tok[1]
            if tok[0] == 'duration' and tok[1] % 4 != 0:
                val = (val//4) * 4
                print(f"[red][bold]WARNING[/bold][/red]: duration {tok[1]} not a multiple of 4; rounding to {val}", file=sys.stderr)
            kwargs[tok[0]] = val
        else:
            raise GqcParseError(f"Duplicate frame parameter {tok[0]}", instring, loc)
    try:
        return LightCueFrame(colors, **kwargs)
    except ValueError as e:
        raise GqcParseError(str(e), instring, loc)

def parse_lightcue_definition(instring, loc, toks):
    if len(toks) == 1:
        colors = []
        frames = toks[0]
    else:
        colors = toks[0]
        frames = toks[1]

    cue = LightCue(colors)
    for frame in frames:
        try:
            frame.add_to_cue(cue)
        except ValueError as e:
            raise GqcParseError(str(e), instring, loc)
    return cue

def make_cue(progress : Progress, src_path : pathlib.Path, output_dir : pathlib.Path):
    task = progress.add_task(f"Parsing light cue '{src_path}'", total=1)
    # Set up the output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    # Check whether the source file exists and raise a value error if it doesn't
    if not src_path.exists():
        raise ValueError(f"Light cue source file {src_path} does not exist")
    
    with open(src_path, 'r') as f:
        parsed_cue = parse_cue(f)
    
    # Write the output
    parsed_cue.serialize(output_dir / f"{src_path.stem}.gqcue")
    progress.update(task, completed=1, total=1)
