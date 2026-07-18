"""Test-only helpers for driving gqc directly, in-process.

`gqc` keeps essentially all of its compiled-program state in class-level
registries (name tables, link tables, id counters, warn-once flags) rather
than passing it through function arguments or an instance, because the CLI
is only meant to be invoked once per process. The grammar suite in this
package doesn't need any of that: it drives `python -m gqc compile` as a
subprocess per test (see `compile_gq` in conftest.py), which gets fresh
state for free.

`reset_compiler_state()` exists for *future* tests that want to compile
in-process (e.g. to inspect intermediate objects instead of just exit code
and stderr) more than once per pytest session. It is additive only: nothing
in this file changes any production behavior, and nothing in the current
suite calls it.
"""

from gqc import structs
from gqc.commands import Command
from gqc.datamodel import (
    Animation,
    Event,
    Frame,
    FrameData,
    Game,
    LightCue,
    LightCueFrame,
    Menu,
    Stage,
    Variable,
)


def reset_compiler_state():
    """Clear every class-level compiler registry back to its startup state."""
    Game.link_table.clear()
    Game.game_name = None
    Game.game = None

    Event.event_table.clear()
    Event.link_table.clear()

    Stage.stage_table.clear()
    Stage.link_table.clear()

    Variable.var_table.clear()
    for storageclass_table in Variable.storageclass_table.values():
        storageclass_table.clear()
    Variable.link_table.clear()
    Variable.heap_table.clear()
    Variable.str_literals.clear()

    Animation.anim_table.clear()
    Animation.link_table.clear()
    Animation.next_id = 0

    Frame.link_table.clear()
    FrameData.link_table.clear()

    Menu.menu_table.clear()
    Menu.link_table.clear()

    LightCue.link_table.clear()
    LightCue.cue_table.clear()
    LightCueFrame.link_table.clear()

    Command.command_list.clear()

    # Module-level warn-once flags (gqc.structs), not class attributes.
    structs.namespace_overflow_warned = False
    structs.addr_wrong_namespace_warned = False
