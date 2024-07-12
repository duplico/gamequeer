import sys
import typing
from collections import namedtuple

from tabulate import tabulate
from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn

from .datamodel import Game, Stage, Variable, Animation, Frame, FrameData, Event, Menu
from .datamodel import Command, CommandDone, LightCue, LightCueFrame

from . import structs

def create_reserved_variables():
    for gq_var in structs.GQ_RESERVED_VARIABLES:
        var = Variable(gq_var.type, gq_var.name, gq_var.description, 'builtin')
        var.set_addr(gq_var.addr, namespace=structs.GQ_PTR_BUILTIN)

def create_symbol_table(table_dest = sys.stdout):
    # Output order:
    # header (fixed size)
    # animations (fixed size by count)
    # stages (fixed size by count)
    # frames (fixed size by count)
    # frame data (variable size)
    # menus (variable size)
    # variable area (variable size)
    # initialization code (variable size)
    # events code (variable size)

    frame_count = sum([len(anim.frames) for anim in Animation.anim_table.values()])

    heap_ptr_start = structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_HEAP, 0x000000)
    heap_ptr_offset = 0

    cart_ptr_start = structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_CART, 0x000000)
    header_ptr_start = cart_ptr_start
    anim_ptr_start = header_ptr_start + structs.GQ_HEADER_SIZE
    stage_ptr_start = anim_ptr_start + len(Animation.anim_table) * structs.GQ_ANIM_SIZE
    frames_ptr_start = stage_ptr_start + len(Stage.stage_table) * structs.GQ_STAGE_SIZE
    frame_data_ptr_start = frames_ptr_start + frame_count * structs.GQ_ANIM_FRAME_SIZE

    # The starting locations of the variable tables need to be calculated based
    #  on the size of the frame data table, so we'll do that a little later.

    # Start with the game metadata header.
    Game.game.set_addr(header_ptr_start)

    # Start with placing the frame data into the frame data table, their corresponding
    #  frames into the frames table (setting the frame's data_pointer), and then the
    #  animations into the animation table, setting their frame pointer.

    anim_ptr_offset = 0
    frames_ptr_offset = 0
    frame_data_ptr_offset = 0
    for anim in Animation.anim_table.values():
        for frame in anim.frames:
            # Place the frame's data bytes into the frame_data table, set the enclosing frame's
            #  reference to it, and increment the frame data offset.
            frame.frame_data.set_addr(frame_data_ptr_start + frame_data_ptr_offset)
            frame_data_ptr_offset += len(frame.bytes)

            # Then place the frame itself into the frame table, updating the pointer offsets.
            frame.set_addr(frames_ptr_start + frames_ptr_offset)
            frames_ptr_offset += structs.GQ_ANIM_FRAME_SIZE
        
        # Point the animation to its first frame in the frame table
        anim.set_frame_pointer(anim.frames[0].addr)
        # Place the animation into the animation table, updating the pointer offsets.
        anim.set_addr(anim_ptr_start + anim_ptr_offset)
        anim_ptr_offset += structs.GQ_ANIM_SIZE
    
    # The lighting cues and their frames are placed next.
    cues_ptr_start = frame_data_ptr_start + frame_data_ptr_offset
    cues_ptr_offset = 0
    cuedata_ptr_start = cues_ptr_start + len(LightCue.cue_table) * structs.GQ_LEDCUE_SIZE
    cuedata_ptr_offset = 0
    for cue in LightCue.cue_table.values():
        cue.set_addr(cues_ptr_start + cues_ptr_offset)
        cues_ptr_offset += cue.size()

        for frame in cue.frames:
            frame.set_addr(cuedata_ptr_start + cuedata_ptr_offset)
            cuedata_ptr_offset += frame.size()

    # Now that the frame data table is complete, we can calculate the starting
    #  locations of the variable tables.
    # First, allocate memory on-cart for the persistent variables
    vars_ptr_start = cuedata_ptr_start + cuedata_ptr_offset
    vars_ptr_offset = 0
    for var in list(Variable.storageclass_table['persistent'].values()):
        var.set_addr(vars_ptr_start + vars_ptr_offset)
        vars_ptr_offset += var.size()

    menus_ptr_start = vars_ptr_start + vars_ptr_offset
    menus_ptr_offset = 0

    for menu in Menu.menu_table.values():
        menu.set_addr(menus_ptr_start + menus_ptr_offset)
        menus_ptr_offset += menu.size()

    # The event table's addresses are calculated as part of the placement of
    #  stages.
    events_ptr_start = menus_ptr_start + menus_ptr_offset
    events_ptr_offset = 0

    # The stage table is next, because it depends upon references to the animations and menus, even though
    #  it may before them in the final layout.
    stage_ptr_offset = 0
    for stage in Stage.stage_table.values():
        for event_type in structs.EventType:
            if event_type in stage.events:
                event = stage.events[event_type]
                event.set_addr(events_ptr_start + events_ptr_offset)
                events_ptr_offset += event.size()

        stage.set_addr(stage_ptr_start + stage_ptr_offset)
        stage_ptr_offset += structs.GQ_STAGE_SIZE

    init_ptr_start = events_ptr_start + events_ptr_offset
    init_ptr_offset = 0
    init_table = dict()
    Game.game.startup_code_ptr = init_ptr_start

    # Allocate our volatile variables on the heap, and their initialization code.
    for var in list(Variable.storageclass_table['volatile'].values()):
        # Heap memory allocation
        var.set_addr(heap_ptr_start + heap_ptr_offset, namespace=structs.GQ_PTR_NS_HEAP)
        heap_ptr_offset += var.size()

        # Initialization code allocation.
        init_cmd = var.get_init_command()
        init_cmd.set_addr(init_ptr_start + init_ptr_offset)
        init_table[init_cmd.addr] = init_cmd
        init_ptr_offset += init_cmd.size()
    
    # Terminate the init code with a DONE
    done_cmd = CommandDone()
    done_cmd.set_addr(init_ptr_start + init_ptr_offset)
    init_table[done_cmd.addr] = done_cmd
    init_ptr_offset += done_cmd.size()

    # Now, do one more pass to try to resolve any unresolved symbols in commands.
    for cmd in Command.command_list:
        if not cmd.resolve():
            raise ValueError(f"Unresolved symbol in command {cmd}")

    symbol_table = {
        '.game' : Game.link_table,
        '.anim' : Animation.link_table,
        '.stage' : Stage.link_table,
        '.frame' : Frame.link_table,
        '.framedata' : FrameData.link_table,
        '.cues' : LightCue.link_table,
        '.cuedata' : LightCueFrame.link_table,
        '.var' : Variable.link_table,
        '.menu' : Menu.link_table,
        '.event' : Event.link_table,
        '.init' : init_table,
        '.heap' : Variable.heap_table
    }

    # Emit a human readable summary of the symbol table.

    section_table = []
    section_table_headers = ['Section', 'Start', 'Size', 'Symbol']

    PAD=10

    file_preamble = f"Linker summary for {Game.game.title}"
    print(file_preamble, file=table_dest)
    print('=' * len(file_preamble), file=table_dest)
    print(file=table_dest)
    print(file=table_dest)

    for section, table in symbol_table.items():
        if len(table) == 0:
            continue
        section_size = 0
        for symbol in table.values():
            section_size += symbol.size()

        section_table.append((section, f"{next(iter(table.values())).addr:#0{PAD}x}", f"{section_size:#0{PAD}x}", ''))

        for symbol in table.values():
            section_table.append(('', f"{symbol.addr:#0{PAD}x}", f"{symbol.size():#0{PAD}x}", repr(symbol)))
    
    print(tabulate(section_table, headers=section_table_headers), file=table_dest)

    # Return the machine-readable symbol table for use in final code generation.
    return symbol_table

# TODO: Generate initialization commands and add the pointer to them to the game
#       metadata header.

def generate_code(parsed, symbol_table : dict):
    output = bytes()

    # Emit each section in order to the output bytes.

    # Count the total number of symbols to be processed
    symbol_count = sum([len(table) for table in symbol_table.values()])

    next_expected_addr = structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_CART, 0x000000)

    with Progress(TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn(), TimeElapsedColumn()) as progress:
        task = progress.add_task(f"Generating code", total=symbol_count)
        for table in symbol_table.values():
            for addr, symbol in table.items():
                if structs.gq_ptr_get_ns(addr) != structs.GQ_PTR_NS_CART:
                    # Only emit code for the cartridge.
                    continue
                if addr != next_expected_addr:
                    # TODO: emit a more friendly error than this, since it's a compiler/linker error
                    raise ValueError(f"Symbol at address {addr:#0{10}x} is not contiguous with the previous symbol.")
                next_expected_addr += symbol.size()
                output += symbol.to_bytes()
                progress.update(task, advance=1)
    
    return output
