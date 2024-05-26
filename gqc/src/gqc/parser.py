import pyparsing as pp

"""
Grammar for GQC language
========================

program = declaration_section*
declaration_section = var_definition_section | animation_definition_section | lightcue_definition_section | menu_definition_section | stage_definition_section

var_definition_section = ("volatile" | "persistent") var_definitions
var_definitions = var_definition | "{" var_definition* "}"
var_definition = string_definition | int_definition
string_definition = "str" identifier ":=" string ";" # | "str" identifier ";"
int_definition = "int" identifier "=" integer ";" # | "int" identifier ";"

animation_definition_section = "animations" animation_assignments
animation_assignments = animation_assignment | "{" animation_assignment* "}"
animation_assignment = identifier <-:" file_source ";" | identifier <-:" file_source animation_options
animation_options = animation_option | "{" animation_option* "}"
animation_option = "frame_rate" "=" integer ";" | "dithering" ":=" string ";"

lightcue_definition_section = "lightcues" file_assignments

file_assignments = file_assignment | "{" file_assignment* "}"
file_assignment = identifier <-:" file_source ";"
file_source = STRING

menu_definition_section = "menus" menu_definitions
menu_definitions = menu_definition | "{" menu_definition* "}"
menu_definition = identifier menu_options
menu_options = menu_option | "{" menu_option* "}"
menu_option = INT ":" STRING ";"

stage_definition_section = "stage" identifier stage_options
stage_options = stage_option | "{" stage_option* "}"
stage_option = stage_bganim | stage_menu | stage_event
stage_bganim = "bganim" identifier ";"
stage_menu = "menu" identifier ";" | "menu" identifier "prompt" STRING ";"
stage_event = "event" event_type event_statements
event_type = "input" "(" event_input_button ")" | "bgdone" | "menu"
event_input_button = "A" | "B" | "<-" | "->"
event_statements = event_statement | "{" event_statement* "}"
event_statement = play | gostage
play = "play" "bganim" identifier ";"
gostage = "gostage" identifier ";"
"""

# Define the grammar
program = pp.Forward()

# Basic tokens
identifier = pp.Word(pp.alphas, pp.alphanums + "_").setName("identifier")
string = pp.QuotedString('"').setName("string")
integer = pp.Word(pp.nums).setName("integer").setParseAction(lambda t: int(t[0]))

int_type = pp.Keyword("int").setName("int")
str_type = pp.Keyword("str").setName("str")

# Variable sections
int_definition = pp.Group(int_type - identifier - pp.Suppress("=") - integer - pp.Suppress(";"))
string_definition = pp.Group(str_type - identifier - pp.Suppress(":=") - string - pp.Suppress(";"))
var_definition = int_definition | string_definition
var_definitions = var_definition | pp.Suppress("{") - pp.ZeroOrMore(var_definition) - pp.Suppress("}")
var_definition_section = pp.Group((pp.Keyword("volatile") | pp.Keyword("persistent")) - pp.Group(var_definitions))

# File assignments for animations and lightcues
file_source = string
file_assignment = pp.Group(identifier - pp.Suppress("<-") - file_source - pp.Suppress(";"))
file_assignments = pp.Group(file_assignment | pp.Suppress("{") - pp.ZeroOrMore(file_assignment) - pp.Suppress("}"))

# Animation sections
animation_option = pp.Group(pp.Keyword("frame_rate") - pp.Suppress("=") - integer - pp.Suppress(";") | pp.Keyword("dithering") - pp.Suppress(":=") - string - pp.Suppress(";"))
animation_options = pp.Group(pp.Suppress(";") | animation_option | pp.Suppress("{") - pp.ZeroOrMore(animation_option) - pp.Suppress("}"))
animation_assignment = pp.Group(identifier - pp.Suppress("<-") - file_source - animation_options)
animation_assignments = pp.Group(animation_assignment | pp.Suppress("{") - pp.ZeroOrMore(animation_assignment) - pp.Suppress("}"))
animation_definition_section = pp.Group(pp.Keyword("animations") - animation_assignments)

# Light cue sections
lightcue_definition_section = pp.Group(pp.Keyword("lightcues") - file_assignments)

# # Menu sections
menu_option = pp.Group(integer - pp.Suppress(":") - string - pp.Suppress(";"))
menu_options = pp.Group(menu_option | pp.Suppress("{") - pp.ZeroOrMore(menu_option) - pp.Suppress("}"))
menu_definition = pp.Group(identifier - menu_options)
menu_definitions = pp.Group(menu_definition | pp.Suppress("{") - pp.ZeroOrMore(menu_definition) - pp.Suppress("}"))
menu_definition_section = pp.Group(pp.Keyword("menus") - menu_definitions)

# ### Stage sections ###
# # Commands
play = pp.Group(pp.Keyword("play") - pp.Keyword("bganim") - identifier - pp.Suppress(";"))
gostage = pp.Group(pp.Keyword("gostage") - identifier - pp.Suppress(";"))

event_statement = play | gostage
event_statements = pp.Group(event_statement | pp.Suppress("{") - pp.ZeroOrMore(event_statement) - pp.Suppress("}"))

# # Event types
event_input_button = pp.Keyword("A") | pp.Keyword("B") | pp.Keyword("<-") | pp.Keyword("->")
event_type = pp.Keyword("input") - pp.Suppress("(") - event_input_button - pp.Suppress(")") | pp.Keyword("bgdone") | pp.Keyword("menu")

# # General stage definition and options
stage_bganim = pp.Group(pp.Keyword("bganim") - identifier - pp.Suppress(";"))
stage_menu = pp.Group(pp.Keyword("menu") - identifier - pp.Suppress(";") | pp.Keyword("menu") - identifier - pp.Keyword("prompt") - string - pp.Suppress(";"))
stage_event = pp.Group(pp.Keyword("event") - event_type - event_statements)
stage_option = stage_bganim | stage_menu | stage_event
stage_options = pp.Group(stage_option | pp.Suppress("{") - pp.ZeroOrMore(stage_option) - pp.Suppress("}"))
stage_definition_section = pp.Group(pp.Keyword("stage") - identifier - stage_options)

# # Finish up
program << pp.ZeroOrMore(animation_definition_section | lightcue_definition_section | var_definition_section | menu_definition_section | stage_definition_section)
program.ignore(pp.cppStyleComment)

test_text = """\
volatile { int x = 10; str y := "hello"; }
"""

def parse(text):
    try:
        parsed = program.parse_file(text, parseAll=True)
        return parsed
    except pp.ParseBaseException as pe:
        print(pe.explain())
        print("column: {}".format(pe.column))
        exit(1)
