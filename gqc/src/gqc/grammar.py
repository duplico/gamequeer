import pyparsing as pp

from .parser import parse_variable_definition, parse_variable_definition_storageclass
from .parser import parse_animation_definition, parse_stage_definition, parse_game_definition
from .parser import parse_event_definition, parse_command, parse_assignment, parse_lightcue_definition_section
from .parser import parse_menu_definition, parse_bound_menu, parse_play
from .parser import parse_int_expression, parse_int_operand, parse_str_literal, parse_if
from .parser import parse_str_expression, parse_string_cast_operand
from .parser import parse_badge_count_operand

"""
Grammar for GQC language
========================

program = game_definition_section declaration_section*
declaration_section = var_definition_section | animation_definition_section | lightcue_definition_section | menu_definition_section | stage_definition_section

game_definition_section = "game" "{" game_assignment* "}"
game_id_assignment = "id" "=" integer ";"
game_title_assignment = "title" ":=" string ";"
game_author_assignment = "author" ":=" string ";"
game_starting_stage_assignment = "starting_stage" "=" identifier ";"
game_assignment = game_id_assignment | game_title_assignment | game_author_assignment | game_starting_stage_assignment  # one of each, in any order

var_definition_section = ("volatile" | "persistent") var_definitions
var_definitions = var_definition | "{" var_definition* "}"
var_definition = string_definition | int_definition
string_definition = "str" identifier ":=" string ";" # | "str" identifier ";"
int_definition = "int" identifier "=" integer ";" # | "int" identifier ";"

animation_definition_section = "animations" animation_assignments
animation_assignments = animation_assignment | "{" animation_assignment* "}"
animation_assignment = identifier <-:" file_source ";" | identifier <-:" file_source animation_options
animation_options = animation_option | "{" animation_option* "}"
animation_option = "frame_rate" "=" integer ";" | "dithering" ":=" string ";" | "w" "=" integer ";" | "h" "=" integer ";" | "duration" "=" integer ";"

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
stage_option = stage_bganim | stage_bgcue | stage_menu | stage_event | stage_textmenu
stage_textmenu = "textmenu" ["prompt" STRING] ";"
stage_bganim = "bganim" identifier ";"
stage_bgcue = "bgcue" identifier ";"
stage_menu = "menu" identifier ";" | "menu" identifier "prompt" STRING ";"
stage_event = "event" event_type event_statement
event_type = "input" "(" event_input_button ")" | "bgdone" | "fgdone" "(" integer ")" | "menu" | "enter" | "timer"
event_input_button = "A" | "B" | "<-" | "->" | "-"
event_statements = event_statement | "{" event_statement* "}"
event_statement = play | cue | gostage | assignment_statement | if_statement | timer | continue | break | loop | badge_set | badge_clear
play = "play" ("bganim" | ("fganim" | "fgmask") "(" int ")") identifier ";"
cue = "cue" identifier ";"
gostage = "gostage" identifier ";"
timer = "timer" int_expression ";"
continue = "continue" ";"
break = "break" ";"
loop = "loop" event_statements
badge_set = "badge_set" int_expression ";"
badge_clear = "badge_clear" int_expression ";"

assignment_statement = int_assignment | string_assignment
int_assignment = identifier "=" int_expression ";"
# Tried whole-RHS-cast-first (only when immediately followed by ";", i.e.
# str(x) is the *entire* RHS) so a bare "s := str(x);" keeps its direct,
# no-intermediate-register lowering; falls back to string_expression
# (whose string_operand also accepts string_cast) for anything else,
# including str(x) appearing inside a "+" chain (gamequeer#386).
string_assignment = identifier ":=" ((string_cast &";") | string_expression) ";"

int_operand = badge_count_call | identifier | integer
string_cast = 'str' '(' int_expression ')'
string_operand = identifier | string | string_cast

# badge_count() is a nullary popcount intrinsic over the 320-bit
# badges-seen bitfield (gamequeer#387): "how many distinct badges has this
# badge seen?" It always lowers to a runtime loop over the existing
# badge_get opcode (QCGET) -- there's no argument to type-check, so unlike
# badge_get it takes an empty, mandatory parameter list, not a bare operand
# form.
badge_count_call = "badge_count" "(" ")"

# Shorthand; see https://stackoverflow.com/a/23956778
# badge_get is a right-associative unary prefix operator, e.g. badge_get(x).
int_expression = pp.infixNotation(int_operand, [
    (pp.oneOf('! - ~ badge_get'), 1, pp.opAssoc.RIGHT),
    (pp.oneOf('* / %'), 2, pp.opAssoc.LEFT),
    (pp.oneOf('+ -'), 2, pp.opAssoc.LEFT),
    (pp.oneOf('<< >>'), 2, pp.opAssoc.LEFT),
    (pp.oneOf('< > <= >='), 2, pp.opAssoc.LEFT),
    ('&', 2, pp.opAssoc.LEFT),
    ('^', 2, pp.opAssoc.LEFT),
    ('|', 2, pp.opAssoc.LEFT),
    (pp.oneOf('== !='), 2, pp.opAssoc.LEFT),
    (pp.oneOf('&& ||'), 2, pp.opAssoc.LEFT),
])

string_expression = string_operand | string_operand '+' string_expression

if_statement = "if" "(" int_expression ")" event_statements ("else" event_statements)?

"""

VAR_STRING_MAXLEN = 21

def build_game_parser():
    # Define the grammar
    gqc_game = pp.Forward()
    gqc_game.enable_left_recursion()

    # Basic tokens
    identifier = pp.Word(pp.alphas, pp.alphanums + "_").set_name("identifier")
    string = pp.QuotedString('"').setName("string")
    meta_string = pp.QuotedString('"', escChar='\\').setName("meta_string")
    integer = pp.Combine(pp.Optional('-') + pp.Word(pp.nums)).setName("integer").set_parse_action(lambda t: int(t[0]))

    int_type = pp.Keyword("int").setName("int")
    str_type = pp.Keyword("str").setName("str")

    # Game definition section
    game_id_assignment = pp.Group(pp.Keyword("id") - pp.Suppress("=") - integer - pp.Suppress(";")).set_name("id")
    game_title_assignment = pp.Group(pp.Keyword("title") - pp.Suppress(":=") - string - pp.Suppress(";")).set_name("title")
    game_author_assignment = pp.Group(pp.Keyword("author") - pp.Suppress(":=") - string - pp.Suppress(";")).set_name("author")
    game_starting_stage_assignment = pp.Group(pp.Keyword("starting_stage") - pp.Suppress("=") - identifier - pp.Suppress(";")).set_name("starting_stage")
    game_assignment = pp.Group(game_id_assignment & game_title_assignment & game_author_assignment & game_starting_stage_assignment)
    game_definition_section = pp.Group(pp.Keyword("game") - pp.Suppress("{") - game_assignment - pp.Suppress("}"))
    game_definition_section.set_parse_action(parse_game_definition)

    # Variable sections
    int_definition = pp.Group(int_type - identifier - pp.Suppress("=") - integer - pp.Suppress(";"))
    string_definition = pp.Group(str_type - identifier - pp.Suppress(":=") - string - pp.Suppress(";"))
    var_definition = int_definition | string_definition
    var_definitions = var_definition | pp.Suppress("{") - pp.ZeroOrMore(var_definition) - pp.Suppress("}")
    var_definition_section = pp.Group((pp.Keyword("volatile") | pp.Keyword("persistent")) - pp.Group(var_definitions))

    var_definition.set_parse_action(parse_variable_definition)
    var_definition_section.set_parse_action(parse_variable_definition_storageclass)

    # File assignments for animations and lightcues
    file_source = meta_string
    file_assignment = pp.Group(identifier - pp.Suppress("<-") - file_source - pp.Suppress(";"))
    file_assignments = pp.Group(file_assignment | pp.Suppress("{") - pp.ZeroOrMore(file_assignment) - pp.Suppress("}"))

    # Animation sections
    animation_option = pp.Group(pp.Keyword("frame_rate") - pp.Suppress("=") - integer - pp.Suppress(";") | pp.Keyword("dithering") - pp.Suppress(":=") - string - pp.Suppress(";")) | pp.Group(pp.Keyword("w") - pp.Suppress("=") - integer - pp.Suppress(";") | pp.Keyword("h") - pp.Suppress("=") - integer - pp.Suppress(";")) | pp.Group(pp.Keyword("duration") - pp.Suppress("=") - integer - pp.Suppress(";"))
    animation_options = pp.Group(pp.Suppress(";") | animation_option | pp.Suppress("{") - pp.ZeroOrMore(animation_option) - pp.Suppress("}"))
    animation_assignment = pp.Group(identifier - pp.Suppress("<-") - file_source - animation_options)
    animation_assignments = pp.Group(animation_assignment | pp.Suppress("{") - pp.ZeroOrMore(animation_assignment) - pp.Suppress("}"))
    animation_definition_section = pp.Group(pp.Keyword("animations") - animation_assignments)

    animation_assignment.set_parse_action(parse_animation_definition)

    # Light cue sections
    lightcue_definition_section = pp.Suppress(pp.Keyword("lightcues")) - file_assignments
    lightcue_definition_section.set_parse_action(parse_lightcue_definition_section)

    # Menu sections
    menu_option = pp.Group(integer - pp.Suppress(":") - string - pp.Suppress(";"))
    menu_options = pp.Group(menu_option | pp.Suppress("{") - pp.ZeroOrMore(menu_option) - pp.Suppress("}"))
    menu_definition = identifier - menu_options
    menu_definitions = pp.Group(menu_definition | pp.Suppress("{") - pp.ZeroOrMore(menu_definition) - pp.Suppress("}"))
    menu_definition_section = pp.Group(pp.Keyword("menus") - menu_definitions)

    menu_definition.set_parse_action(parse_menu_definition)

    ### Stage sections ###
    event_statements = pp.Forward()
    
    # Assignments and expressions
    # badge_count() -- a nullary popcount intrinsic over the badges-seen
    # bitfield (gamequeer#387). Keyword("badge_count"), not a bare string,
    # so it doesn't swallow a `badge_count`-prefixed identifier
    # (gamequeer#354's badge_get/badge_getter fix, same reasoning). The `-`
    # after the Keyword commits once "badge_count" itself has matched, so
    # e.g. `badge_count(5)` fails with a clean, source-located
    # ParseSyntaxException at the unexpected "5" rather than silently
    # falling through to some other (wrong) interpretation.
    badge_count_call = pp.Group(pp.Keyword("badge_count") - pp.Suppress("(") - pp.Suppress(")")).set_name("badge_count_call")
    badge_count_call.set_parse_action(parse_badge_count_operand)

    int_operand = badge_count_call | identifier | integer
    int_operand.set_parse_action(parse_int_operand)
    int_expression = pp.infix_notation(int_operand, [
        (pp.Keyword('badge_get') | pp.one_of('! - ~'), 1, pp.opAssoc.RIGHT),
        (pp.one_of('* / %'), 2, pp.opAssoc.LEFT),
        (pp.one_of('+ -'), 2, pp.opAssoc.LEFT),
        (pp.one_of('<< >>'), 2, pp.opAssoc.LEFT),
        (pp.one_of('< > <= >='), 2, pp.opAssoc.LEFT),
        ('&', 2, pp.opAssoc.LEFT),
        ('^', 2, pp.opAssoc.LEFT),
        ('|', 2, pp.opAssoc.LEFT),
        (pp.one_of('== !='), 2, pp.opAssoc.LEFT),
        (pp.one_of('&& ||'), 2, pp.opAssoc.LEFT),
    ])
    int_expression.set_parse_action(parse_int_expression)
    int_assignment = pp.Keyword("=") - int_expression - pp.Suppress(";")

    string_literal = pp.QuotedString('"').setName("string_literal")
    string_literal.set_parse_action(parse_str_literal)
    # `str(<int_expression>)`, valid both as the entire RHS of a `:=` (see
    # string_assignment below) and, since gamequeer#386, as one operand of a
    # `+` concatenation chain (via string_operand). Keyword("str") -- not a
    # bare "str" literal -- so a `str`-prefixed identifier like `str_scratch`
    # isn't swallowed (gamequeer#354).
    string_cast = pp.Group(pp.Suppress(pp.Keyword("str")) - pp.Suppress("(") - int_expression - pp.Suppress(")"))
    string_cast.set_parse_action(parse_string_cast_operand)
    string_operand = string_cast | identifier | string_literal
    string_expression = pp.infix_notation(string_operand, [
        ('+', 2, pp.opAssoc.LEFT),
    ])
    string_expression.set_parse_action(parse_str_expression)

    # Try the whole-RHS cast form first (only followed by ";", never a `+`)
    # so a bare `s := str(x);` keeps its existing direct-to-`dst` lowering
    # (CommandCastStr with no intermediate register -- see
    # parser.parse_assignment) instead of always routing through
    # string_expression's register-allocating machinery. If str(...) isn't
    # the entire RHS (e.g. it's followed by `+`), FollowedBy(";") fails and
    # this MatchFirst falls back to string_expression, whose string_operand
    # now accepts string_cast inline.
    string_assignment = pp.Keyword(":=") - ((string_cast + pp.FollowedBy(";")) | string_expression) - pp.Suppress(";")

    assignment_statement = pp.Group(identifier - (string_assignment | int_assignment))
    assignment_statement.add_parse_action(parse_assignment)

    # Flow control
    if_statement = pp.Suppress(pp.Keyword("if")) - pp.Suppress("(") - int_expression - pp.Suppress(")") - event_statements - pp.Optional(pp.Suppress(pp.Keyword("else")) - event_statements)
    if_statement.set_parse_action(parse_if)

    loop_statement = pp.Group(pp.Keyword("loop") - event_statements)
    continue_statement = pp.Group(pp.Keyword("continue") - pp.Suppress(";"))
    break_statement = pp.Group(pp.Keyword("break") - pp.Suppress(";"))

    # Other commands
    badge_set = pp.Group(pp.Keyword("badge_set") - int_expression - pp.Suppress(";"))
    badge_clear = pp.Group(pp.Keyword("badge_clear") - int_expression - pp.Suppress(";"))

    play_type = pp.Group(pp.Keyword("bganim") | (pp.Keyword("fganim") | pp.Keyword("fgmask")) - pp.Suppress("(") - integer - pp.Suppress(")"))
    play = pp.Group(pp.Keyword("play") - play_type - identifier - pp.Suppress(";"))

    play.set_parse_action(parse_play)

    cue = pp.Group(pp.Keyword("cue") - identifier - pp.Suppress(";"))
    gostage = pp.Group(pp.Keyword("gostage") - identifier - pp.Suppress(";"))
    timer = pp.Group(pp.Keyword("timer") - int_expression - pp.Suppress(";"))

    event_statement = badge_set | badge_clear | play | cue | gostage | timer | if_statement | continue_statement | break_statement | loop_statement | assignment_statement
    event_statements << (pp.Group(event_statement | pp.Suppress("{") - pp.ZeroOrMore(event_statement) - pp.Suppress("}")))

    event_statement.set_parse_action(parse_command)

    # Event types
    event_input_button = pp.Keyword("A") | pp.Keyword("B") | pp.Keyword("<-") | pp.Keyword("->") | pp.Keyword("-")
    event_type = pp.Keyword("input") - pp.Suppress("(") - event_input_button - pp.Suppress(")") | pp.Keyword("timer") | pp.Keyword("bgdone") | pp.Keyword("menu") | pp.Keyword("enter") | pp.Keyword("fgdone") - pp.Suppress("(") - integer - pp.Suppress(")")

    # General stage definition and options
    stage_bganim = pp.Group(pp.Keyword("bganim") - identifier - pp.Suppress(";"))
    stage_bgcue = pp.Group(pp.Keyword("bgcue") - identifier - pp.Suppress(";"))
    stage_menu = pp.Suppress(pp.Keyword("menu")) - identifier - pp.Optional(pp.Suppress(pp.Keyword("prompt")) - string_operand) - pp.Suppress(";")
    stage_textmenu = pp.Group(pp.Keyword("textmenu") - pp.Optional(pp.Keyword("prompt") - string_operand) - pp.Suppress(";"))
    stage_event = pp.Group(pp.Keyword("event") - event_type - event_statements)
    stage_option = stage_bganim | stage_bgcue | stage_menu | stage_event | stage_textmenu
    stage_options = pp.Group(stage_option | pp.Suppress("{") - pp.ZeroOrMore(stage_option) - pp.Suppress("}"))
    stage_definition_section = pp.Group(pp.Suppress(pp.Keyword("stage")) - identifier - stage_options)

    stage_menu.set_parse_action(parse_bound_menu)
    stage_event.set_parse_action(parse_event_definition)

    stage_definition_section.set_parse_action(parse_stage_definition)

    # Finish up
    gqc_game << game_definition_section - pp.ZeroOrMore(animation_definition_section | lightcue_definition_section | var_definition_section | menu_definition_section | stage_definition_section)
    gqc_game.ignore(pp.cppStyleComment)

    return gqc_game
