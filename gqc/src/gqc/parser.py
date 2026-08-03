import sys
from collections import namedtuple

import pyparsing as pp
from rich import print

from .datamodel import Animation, Game, Stage, Variable, Event, Menu, LightCue, StrExpression
from .datamodel import IntExpression, GqcIntOperand, GqcStrCastOperand, GqcBadgeCountOperand
from .datamodel import GqcRandomOperand, GqcMinMaxOperand, GqcClampOperand, GqcAbsOperand
from .datamodel import fold_constant_int_expression, Constant, Enum
from .datamodel import Cohort, GqcHaveMetOperand, GqcInCohortOperand, GqcCountSeenRangeOperand
from .commands import CommandPlay, CommandGoStage, CommandCue, CommandCastStr
from .commands import CommandSetStr, CommandSetInt, CommandWithIntExpressionArgument
from .commands import CommandTimer, CommandIf, CommandGoto, CommandLoop, Command, CommandType
from .structs import EventType
from . import structs, GqcParseError

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
    menu_prompt = None
    if len(toks) == 2:
        menu_prompt = toks[1]
    
    try:
        return Stage.BoundMenu(menu_name, menu_prompt)
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
        elif isinstance(stage_option, Stage.BoundMenu):
            if 'menu' in stage_kwargs:
                raise GqcParseError(f"Duplicate menu definition for stage {name}", instring, loc)
            stage_kwargs['menu'] = stage_option
        elif stage_option[0] == 'textmenu':
            if 'textmenu' in stage_kwargs:
                raise GqcParseError(f"Duplicate textmenu definition for stage {name}", instring, loc)
            stage_kwargs['textentry'] = True
            if len(stage_option) == 3:
                stage_kwargs['textentry_prompt'] = stage_option[2]
        elif stage_option[0] in stage_kwargs:
            raise GqcParseError(f"Duplicate option {stage_option[0]} for stage {name}", instring, loc)
        else:
            stage_kwargs[stage_option[0]] = stage_option[1]

    try:
        return Stage(name, **stage_kwargs)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

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
    
    try:
        return Event(event_type, event_statements)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse_animation_definition(instring, loc, toks):
    toks = toks[0]

    name = toks[0]
    source = toks[1]

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
        non_init_var = None
        for var in Variable.storageclass_table[storageclass].values():
            if not var.name in structs.GQ_REGISTERS_INT and not var.name in structs.GQ_REGISTERS_STR and not var.name.endswith(".init") and not var.name.endswith(".strlit") and not var.name.endswith(".builtin"):
                non_init_var = var
                break
        if non_init_var is not None:
            raise GqcParseError(f"Storage class {storageclass} already defined by {non_init_var.name}", instring, loc)
    
    for var in toks[1]:
        var.set_storageclass(storageclass)

def parse_const_definition(instring, loc, toks):
    # gamequeer#421: `const NAME = <int-expression>;`. `value` is whatever
    # int_expression's own parse action already produced -- a literal
    # GqcIntOperand if the RHS folded to a compile-time constant (gamequeer
    # #385's fold_constant_int_expression, reused as-is via int_expression),
    # or an IntExpression if it didn't (e.g. it references a variable, or a
    # not-yet-defined name that reads as one -- see Constant's docstring in
    # datamodel.py for why forward references aren't supported). Either way,
    # a `const` has no runtime representation to fall back to, so anything
    # short of an already-folded literal is rejected right here.
    toks = toks[0]
    name = toks[1]
    value_operand = toks[2]

    if not (isinstance(value_operand, GqcIntOperand) and value_operand.is_literal):
        raise GqcParseError(
            f"Constant {name} must be initialized with a compile-time "
            "constant integer expression",
            instring, loc,
        )

    try:
        Constant.define(name, value_operand.value)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse_enum_definition(instring, loc, toks):
    # gamequeer#421: `enum Name { A, B, C }`, auto-numbered from 0 in
    # declaration order. Enum.define does the actual work (including
    # registering each member into Constant.const_table under
    # "Name.Member", see its docstring), so it can share the same
    # duplicate-name and range-checking machinery as a plain `const`.
    toks = toks[0]
    name = toks[1]
    members = list(toks[2])

    try:
        Enum.define(name, members)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse_lightcue_definition_section(instring, loc, toks):
    # Import here to avoid circular import
    from .cues import parse_cue
    toks = toks[0]

    for cue in toks:
        cue_name = cue[0]
        # gamequeer#420: resolved relative to the game's own directory
        # (Game.game_dir), not the process CWD -- see the matching comment
        # on Animation.src_path in datamodel.py.
        cue_source = Game.game_dir / 'assets' / 'lighting' / cue[1]

        print(f"[blue]Light cue [italic]{cue_name}[/italic][/blue] from [underline]{cue_source}[/underline]")
        
        if not cue_source.exists():
            raise GqcParseError(f"Light cue {cue_name} source {cue_source} not found", instring, loc)
        
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

def parse_badge_count_operand(instring, loc, toks):
    # badge_count() (gamequeer#387) never carries any data of its own -- it
    # always lowers to the same fixed loop-over-badge_get shape (see
    # IntExpression._emit_badge_count) -- so the sentinel returned here is
    # just a marker for parse_int_operand/parse_int_expression/
    # IntExpression.get_result_symbol to recognize, not a value container.
    return GqcBadgeCountOperand()

def parse_fw_version_operand(instring, loc, toks):
    # fw_version() (gamequeer#411) carries no data of its own: unlike
    # badge_count() (which builds a real runtime loop at every call site),
    # it's pure sugar for a reference to the hidden volatile int that the
    # compiler-injected probe stage (see linker.inject_fw_version_probe)
    # writes its result into -- exactly what parse_int_operand would already
    # build for a bare identifier reference to that variable. Setting
    # needs_fw_probe here is what tells gqc.py to actually call
    # inject_fw_version_probe after parsing: a game that never calls
    # fw_version() gets no probe stage, and pays none of its ~1s cost on
    # original firmware.
    #
    # gamequeer#420: game{} may not have been parsed yet (it's no longer
    # required to be the first top-level section), so Game.game can still be
    # None here -- record the flag on the class itself either way;
    # Game.__init__ seeds a not-yet-constructed instance's needs_fw_probe
    # from it, and it's still applied directly to Game.game when that
    # instance already exists (the common case).
    Game.needs_fw_probe_seen = True
    if Game.game is not None:
        Game.game.needs_fw_probe = True
    return GqcIntOperand(False, structs.GQ_FW_PROBE_RESULT_VAR)

def parse_enum_member_operand(instring, loc, toks):
    # `Name.Member` (gamequeer#421): resolved to its int value right here,
    # at parse time, same as badge_count() above is resolved to its
    # sentinel here -- by the time int_operand's own parse action
    # (parse_int_operand, below) sees this, it's already a literal
    # GqcIntOperand, indistinguishable from a bare int literal.
    enum_name, member_name = toks[0]
    try:
        value = Enum.get_member_value(enum_name, member_name)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)
    return GqcIntOperand(is_literal=True, value=value)

def parse_random_operand(instring, loc, toks):
    # random(lo, hi) (gamequeer#422): toks[0] is random_call's own pp.Group,
    # holding exactly its two already-parsed int_expression arguments (the
    # "random" keyword itself is suppressed in the grammar, same as
    # string_cast's "str" -- see parse_string_cast_operand). Setting
    # needs_random here (mirroring parse_fw_version_operand's needs_fw_probe
    # above) is what tells gqc.py to call
    # linker.create_random_state_variables after parsing: a game that never
    # calls random() gets no hidden LCG state/counter variables.
    Game.game.needs_random = True
    lo, hi = toks[0]
    return GqcRandomOperand(lo, hi)

def parse_min_operand(instring, loc, toks):
    a, b = toks[0]
    return GqcMinMaxOperand(a, b, False)

def parse_max_operand(instring, loc, toks):
    a, b = toks[0]
    return GqcMinMaxOperand(a, b, True)

def parse_clamp_operand(instring, loc, toks):
    x, lo, hi = toks[0]
    return GqcClampOperand(x, lo, hi)

def parse_abs_operand(instring, loc, toks):
    x = toks[0][0]
    return GqcAbsOperand(x)

# The social vocabulary (gamequeer#423, DEF CON sprint epic gamequeer#419).
# Each parse action below produces one of the datamodel.py marker
# namedtuples documented there, following the exact same
# parse_int_operand/parse_int_expression/IntExpression.get_result_symbol/
# fold_constant_int_expression recognition pattern parse_badge_count_operand
# and GqcBadgeCountOperand already established for gamequeer#387.

def parse_have_met_operand(instring, loc, toks):
    # toks[0] is have_met_call's own pp.Group: ['have_met', arg], where arg
    # is whatever this call's own int_expression sub-rule already reduced
    # the argument to (a GqcIntOperand or IntExpression).
    return GqcHaveMetOperand(id_operand=toks[0][1])

def parse_in_cohort_operand(instring, loc, toks):
    # toks[0] is in_cohort_call's own pp.Group: ['in_cohort', cohort_name, id].
    _, cohort_name, id_operand = toks[0]

    if cohort_name not in Cohort.cohort_table:
        raise GqcParseError(f"Undefined cohort {cohort_name}", instring, loc)
    cohort = Cohort.cohort_table[cohort_name]

    return GqcInCohortOperand(id_operand=id_operand, lo=cohort.lo, hi=cohort.hi)

def parse_count_seen_operand(instring, loc, toks):
    # toks[0] is count_seen_call's own pp.Group: either ['count_seen']
    # (the bare-call form) or ['count_seen', cohort_name].
    toks = toks[0]

    if len(toks) == 1:
        # count_seen() with no argument is badge_count() itself
        # (gamequeer#423) -- the same marker, same lowering, same op-stream.
        return GqcBadgeCountOperand()

    cohort_name = toks[1]
    if cohort_name not in Cohort.cohort_table:
        raise GqcParseError(f"Undefined cohort {cohort_name}", instring, loc)
    cohort = Cohort.cohort_table[cohort_name]

    return GqcCountSeenRangeOperand(lo=cohort.lo, hi=cohort.hi)

def parse_cohort_definition(instring, loc, toks):
    toks = toks[0]
    _, name, lo, hi = toks

    try:
        return Cohort(name, lo, hi)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse_seen_self(instring, loc):
    # seen_self() (gamequeer#423) desugars to the copy-pasted-verbatim idiom
    # "if (badge_get(GQI_PLAYER_ID)==0) badge_set GQI_PLAYER_ID;" -- built
    # by hand here rather than via the grammar (there's no source text for
    # it to parse), mirroring the manual Command construction
    # IntExpression._emit_badge_count already does for badge_count()'s own
    # fixed shape.
    id_operand = GqcIntOperand(is_literal=False, value='GQI_PLAYER_ID')
    condition = IntExpression(
        [['badge_get', id_operand], '==', GqcIntOperand(is_literal=True, value=0)],
        instring, loc,
    )
    true_cmds = [CommandWithIntExpressionArgument(CommandType.QCSET, instring, loc, id_operand)]

    return CommandIf(instring, loc, condition, true_cmds)

# Every intrinsic/social-vocabulary operand marker (see datamodel.py) that
# parse_int_operand/parse_int_expression need to pass through unchanged
# rather than wrap in a GqcIntOperand -- the same role GqcBadgeCountOperand
# already plays for badge_count(). Combines gamequeer#422's math intrinsics
# (random/min/max/clamp/abs) and gamequeer#423's social vocabulary
# (have_met/in_cohort/count_seen).
_INTRINSIC_OPERAND_MARKER_TYPES = (
    GqcBadgeCountOperand, GqcRandomOperand, GqcMinMaxOperand, GqcClampOperand, GqcAbsOperand,
    GqcHaveMetOperand, GqcInCohortOperand, GqcCountSeenRangeOperand,
)

def parse_int_operand(instring, loc, toks):
    if isinstance(toks[0], (GqcIntOperand,) + _INTRINSIC_OPERAND_MARKER_TYPES):
        return toks[0]
    elif isinstance(toks[0], int):
        return GqcIntOperand(True, toks[0])
    elif toks[0] in Constant.const_table:
        # A bare `const NAME` reference (gamequeer#421) -- substitute its
        # value immediately, same as a literal int would parse. Must be
        # declared earlier in the file (see Constant's docstring in
        # datamodel.py); anything not already in the table by now is
        # treated as an ordinary (possibly forward-declared) variable
        # reference, exactly as before this feature existed.
        return GqcIntOperand(True, Constant.const_table[toks[0]])
    else:
        return GqcIntOperand(False, toks[0])

def parse_int_expression(instring, loc, toks):
    toks = toks[0]
    if isinstance(toks, GqcIntOperand):
        return toks
    if isinstance(toks, IntExpression):
        # A fully-parenthesized (sub)expression used as a bare operand with
        # no sibling operator at its own nesting level, e.g. the entire RHS
        # of "x = (1 + 2);" or any of the parenthesized groups nested inside
        # it, is already reduced to an IntExpression by the recursive parse
        # of its own parens. pyparsing's infix_notation still re-invokes
        # this parse action once more for the enclosing bare-atom match, so
        # pass the already-built expression through unchanged instead of
        # re-folding/re-constructing it (which would double-alloc its
        # registers -- see gamequeer#345).
        return toks
    if isinstance(toks, _INTRINSIC_OPERAND_MARKER_TYPES):
        # badge_count() (gamequeer#387), one of gamequeer#422's math
        # intrinsics (random/min/max/clamp/abs), or one of gamequeer#423's
        # social-vocabulary markers (have_met/in_cohort/count_seen) as the
        # *entire* RHS, e.g. "x = badge_count();" or "x = min(3, 7);" --
        # with no sibling operator at this nesting level, infix_notation
        # hands this back as a bare atom rather than a [operand, op,
        # operand] token group.
        #
        # min()/max()/clamp()/abs() (unlike badge_count()/random()/
        # have_met()/count_seen(), which never fold -- see
        # fold_constant_int_expression) fold to a single literal here too
        # when their own arguments do, and in_cohort(NAME, id) folds
        # whenever `id` itself does (it's a pure range compare, no badge
        # state involved) -- this is the *only* place a bare-atom marker
        # like this reaches fold_constant_int_expression directly; the
        # generic fold attempt further down only ever sees a real
        # [operand, op, operand] node, so without this a whole-RHS
        # "x = min(3, 7);" (or "x = in_cohort(NAME, 5);") would never fold
        # even though "x = min(3, 7) + 1;" already does (via that generic
        # path recursing into the marker as one of its two operands).
        folded = fold_constant_int_expression(toks)
        if folded is not None:
            return GqcIntOperand(is_literal=True, value=folded)

        # Otherwise, every one of these always emits real commands (a
        # popcount loop, LCG arithmetic, a compare-and-conditionally-
        # overwrite, a badge_get delegation, or a bare comparison -- see
        # IntExpression._emit_badge_count/_emit_random/_emit_minmax/
        # _emit_clamp/_emit_abs/_emit_count_seen_range and the
        # GqcHaveMetOperand/GqcInCohortOperand branches of
        # get_result_symbol), so each needs an IntExpression wrapper even
        # here; get_result_symbol recognizes the same markers to build that
        # lowering.
        try:
            return IntExpression([toks], instring, loc)
        except ValueError as ve:
            raise GqcParseError(str(ve), instring, loc)

    # pyparsing's infix_notation hands us a flat token list [a, op1, b, op2,
    # c, ...] for a chain of same-precedence (opAssoc.LEFT) operators. Fold
    # it so the left operand accumulates, e.g. "10 - 5 - 2" compiles as
    # (10 - 5) - 2, not 10 - (5 - 2).
    if len(toks) > 3:
        ltoks = [toks[:-2]]
        last_op = toks[-2]
        last_operand = toks[-1]
        toks = [parse_int_expression(instring, loc, ltoks), last_op, last_operand]

    # A compile-time-constant (sub)expression -- e.g. the entire RHS of
    # "x = (1 + 2);", or "(1 + 2 + 3 + 4)" after the left-fold above --
    # folds to a single literal instead of an IntExpression, matching the
    # bare-atom shape a plain "x = 3;" would already produce (gamequeer#385).
    # Mirrors the IntExpression passthrough above: this only ever sees a
    # fully-parenthesized or outermost group, since a non-parenthesized
    # nested precedence group (e.g. the "2*3" in "2*3+x") never reaches
    # parse_int_expression as its own invocation -- that case is folded by
    # IntExpression.get_result_symbol instead.
    folded = fold_constant_int_expression(toks)
    if folded is not None:
        return GqcIntOperand(is_literal=True, value=folded)

    try:
        return IntExpression(toks, instring, loc)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse_str_literal(instring, loc, toks):
    try:
        return Variable.get_str_literal(toks[0])
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse_string_cast_operand(instring, loc, toks):
    # toks[0] is string_cast's own pp.Group, wrapping exactly the parsed
    # int_expression (a GqcIntOperand or IntExpression -- int_expression's
    # own parse action, parse_int_expression, has already run and already
    # folded a compile-time-constant argument to a literal GqcIntOperand,
    # gamequeer#385).
    int_expr = toks[0][0]

    if isinstance(int_expr, GqcIntOperand) and int_expr.is_literal:
        # str() of a compile-time-constant argument is itself a compile-time
        # constant (gamequeer#386): emit it as an ordinary string literal
        # instead of a runtime cast. Python's str(int) matches the VM's
        # gq_itoa decimal formatting (sign + digits, no leading zeros) for
        # the whole t_gq_int range, and the longest possible result
        # ("-2147483648", 11 chars) is always well under the
        # GQ_STR_SIZE-1 = 21 char literal limit, so this can't raise.
        try:
            return Variable.get_str_literal(str(int_expr.value))
        except ValueError as ve:
            raise GqcParseError(str(ve), instring, loc)

    return GqcStrCastOperand(int_expr)

def parse_str_expression(instring, loc, toks):
    toks = toks[0]
    if isinstance(toks, str):
        return toks
    if isinstance(toks, StrExpression):
        # Same already-reduced-atom re-invocation as parse_int_expression;
        # pass a fully-parenthesized (sub)expression through unchanged.
        return toks

    # Same left-fold as parse_int_expression. String `+` is associative
    # (concatenation), so this doesn't change the resulting string value —
    # it just makes the accumulation order consistent with int expressions.
    if len(toks) > 3:
        ltoks = [toks[:-2]]
        last_op = toks[-2]
        last_operand = toks[-1]
        toks = [parse_str_expression(instring, loc, ltoks), last_op, last_operand]

    try:
        return StrExpression(toks, instring, loc)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse_if(instring, loc, toks):
    condition = toks[0]
    true_block = toks[1]
    false_block = toks[2] if len(toks) == 3 else None

    try:
        return CommandIf(instring, loc, condition, true_block, false_cmds=false_block)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

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
    
    try:
        return CommandPlay(instring, loc, anim_name, anim_index)
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse_command(instring, loc, toks):
    toks = toks[0]

    # If the command has already been fully parsed, just pass it through:
    if isinstance(toks, Command):
        return toks

    # Otherwise, parse it:
    command = toks[0]

    try:

        if command == "cue":
            if toks[1] not in LightCue.cue_table:
                raise GqcParseError(f"Undefined cue {toks[1]}", instring, loc)
            return CommandCue(instring, loc, toks[1])
        elif command == "gostage":
            return CommandGoStage(instring, loc, toks[1])
        elif command == 'setvar':
            _, dst, src, datatype = toks
            if datatype == 'str':
                if isinstance(src, str) or isinstance(src, StrExpression):
                    return CommandSetStr(instring, loc, dst, src)
                elif isinstance(src, GqcStrCastOperand):
                    # The whole-RHS `str(x)` form (parse_string_cast_operand
                    # only returns this wrapper for a non-foldable argument;
                    # a literal one is already a plain str above) -- cast
                    # straight into dst, no intermediate register.
                    return CommandCastStr(instring, loc, dst, src.int_expr)
                else:
                    raise GqcParseError(f"Invalid source {src} for string variable {dst}", instring, loc)
            else:
                if isinstance(src, int):
                    # Not currently reachable: parse_int_operand's parse
                    # action wraps every bare int atom in a GqcIntOperand
                    # before it ever gets here, so `src` arrives as a
                    # GqcIntOperand or IntExpression already. Kept explicit
                    # (rather than silently falling through with no return,
                    # gamequeer#338) so a future grammar change that lets a
                    # bare int through doesn't drop the setvar statement.
                    src = GqcIntOperand(is_literal=True, value=src)
                assert isinstance(src, GqcIntOperand) or isinstance(src, IntExpression)
                return CommandSetInt(instring, loc, dst, src)
        elif command == 'timer':
            return CommandTimer(instring, loc, toks[1])
        elif command in ['break', 'continue']:
            return CommandGoto(instring, loc, form=command)
        elif command == 'loop':
            return CommandLoop(instring, loc, toks[1])
        elif command == 'badge_set':
            return CommandWithIntExpressionArgument(CommandType.QCSET, instring, loc, toks[1])
        elif command == 'badge_clear':
            return CommandWithIntExpressionArgument(CommandType.QCCLR, instring, loc, toks[1])
        elif command == 'seen_self':
            return parse_seen_self(instring, loc)
        else:
            raise GqcParseError(f"Invalid command {command}", instring, loc)
        
    except ValueError as ve:
        raise GqcParseError(str(ve), instring, loc)

def parse(text):
    # Import here to avoid circular import
    from gqc import grammar

    gqc_game = grammar.build_game_parser()
    try:
        parsed = gqc_game.parse_file(text, parseAll=True)
    except pp.ParseBaseException as pe:
        print(pe.explain(depth=0), file=sys.stderr)
        exit(1)
    except GqcParseError as ge:
        print(ge, file=sys.stderr)
        exit(1)
    except RecursionError:
        # Deeply nested parenthesized expressions can exceed pyparsing's
        # packrat-memoized recursive descent before codegen is ever reached
        # (gamequeer#345). There's no source location to point at (the
        # RecursionError can strike mid-raise, before pyparsing attaches
        # one), so just fail cleanly instead of dumping a Python traceback.
        print(
            "Error: expression nesting is too deep for gqc to parse. "
            "Split it into intermediate variables.",
            file=sys.stderr,
        )
        exit(1)

    # gamequeer#420: game{} is no longer structurally locked to being the
    # first top-level section (it's just one more alternative in the
    # top-level section repetition in grammar.py), so the grammar alone
    # can no longer enforce "exactly one" -- a *second* game{} block is
    # still caught structurally (Game.__init__ raises "Game already
    # defined", surfaced as a GqcParseError above), but *zero* game{}
    # blocks parses cleanly with nothing left to reject it. Check for that
    # here instead, once parsing is otherwise known to have succeeded.
    if Game.game is None:
        print(
            "Error: no `game { ... }` block found (exactly one is required).",
            file=sys.stderr,
        )
        exit(1)

    return parsed
