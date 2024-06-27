import pyparsing as pp
from pyparsing import pyparsing_common as ppc

from .cues import parse_color_definition, parse_cue_frame, parse_lightcue_definition

from .grammar import VAR_STRING_MAXLEN

"""
Grammar for GQC light cues
==========================

cue_definition = color_definition_section frame_definition+

color_definition_section = "colors" color_definitions
color_definitions = color_definition | "{" color_definition* "}"
color_definition = idenitifier ":=" string ";"

frame_definition = "frame" "{" frame_statement* "}"
frame_statement = frame_duration | frame_transition | frame_colors
frame_duration = "duration" "=" integer ";"
frame_transition = "transition" := string ";"
frame_colors = "colors" "{" color*5 "}"
frame_color = identifier|string ","
"""

def build_lightcue_parser():
    # Define the grammar
    gqc_lightcue = pp.Forward()
    # Basic tokens
    identifier = pp.Word(pp.alphas, pp.alphanums + "_").set_name("identifier")
    string = pp.QuotedString('"').setName("string")
    integer = pp.Word(pp.nums).setName("integer").set_parse_action(lambda t: int(t[0]))

    # Color definition section
    color_definition = pp.Group(identifier - pp.Suppress(":=") - string - pp.Suppress(";"))
    color_definitions = pp.Group(color_definition | pp.Suppress("{") - pp.ZeroOrMore(color_definition) - pp.Suppress("}"))
    color_definition_section = pp.Suppress("colors") - color_definitions
    color_definition.add_parse_action(parse_color_definition)

    # Frame definition
    frame_duration = pp.Group(pp.Keyword("duration") - pp.Suppress("=") - integer - pp.Suppress(";"))
    frame_transition = pp.Group(pp.Keyword("transition") - pp.Suppress(":=") - string - pp.Suppress(";"))
    frame_colors = pp.Group(pp.Keyword("colors") - pp.Suppress("{") - pp.DelimitedList(identifier, ',', min=5, max=5) - pp.Suppress("}"))
    frame_statement = frame_duration | frame_transition | frame_colors
    frame_definition = pp.Suppress("frame") - pp.Suppress("{") - pp.ZeroOrMore(frame_statement) - pp.Suppress("}")
    frame_definition.add_parse_action(parse_cue_frame)

    # Game cue file overall:
    gqc_lightcue << color_definition_section - pp.Group(pp.OneOrMore(frame_definition))
    gqc_lightcue.ignore(pp.cppStyleComment)
    gqc_lightcue.add_parse_action(parse_lightcue_definition)

    return gqc_lightcue
