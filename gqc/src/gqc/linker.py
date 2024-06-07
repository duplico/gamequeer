import sys
import typing
from collections import namedtuple

from tabulate import tabulate
from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn

from .datamodel import Game, Stage, Variable, Animation, Frame, FrameData, Event

from . import structs

def create_symbol_table(table_dest = sys.stdout):
    # Output order:
    # header (fixed size)
    # animations (fixed size by count)
    # stages (fixed size by count) (TODO)
    # frames (fixed size by count)
    # frame data (variable size)
    # variable area (variable size)
    # events code (variable size)

    frame_count = sum([len(anim.frames) for anim in Animation.anim_table.values()])

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
    
    # Now that the frame data table is complete, we can calculate the starting
    #  locations of the variable tables.
    vars_ptr_start = frame_data_ptr_start + frame_data_ptr_offset
    vars_ptr_offset = 0
    for var in list(Variable.storageclass_table['persistent'].values()) + list(Variable.storageclass_table['volatile'].values()):
        var.set_addr(vars_ptr_start + vars_ptr_offset)
        vars_ptr_offset += var.size()

    # TODO: Menus

    # The event table's addresses are calculated as part of the placement of
    #  stages.
    events_ptr_start = vars_ptr_start + vars_ptr_offset
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

    symbol_table = {
        '.game' : Game.link_table,
        '.anim' : Animation.link_table,
        '.stage' : Stage.link_table,
        '.frame' : Frame.link_table,
        '.framedata' : FrameData.link_table,
        '.var' : Variable.link_table,
        '.event' : Event.link_table,
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

def generate_code(parsed, symbol_table : dict):
    output = bytes()

    # Emit each section in order to the output bytes.
    # TODO: error if their addresses are non-contiguous.
    #       or, switch to using Intel Hex format or TI-TXT format.

    # Count the total number of symbols to be processed
    symbol_count = sum([len(table) for table in symbol_table.values()])

    with Progress(TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn(), TimeElapsedColumn()) as progress:
        task = progress.add_task(f"Generating code", total=symbol_count)
        for table in symbol_table.values():
            for symbol in table.values():
                output += symbol.to_bytes()
                progress.update(task, advance=1)
    
    return output
