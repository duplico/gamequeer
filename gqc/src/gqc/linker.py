import sys

from tabulate import tabulate
from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn

from .datamodel import Game, Stage, Variable, Animation, Frame, FrameData, Event, Menu
from .datamodel import LightCue, LightCueFrame
from .commands import Command, CommandDone

from . import structs

def create_reserved_variables():
    # Create the reserved special-purpose variables for the game:
    for gq_var in structs.GQ_RESERVED_INTS:
        var = Variable('int', gq_var.name, gq_var.description, 'builtin_int')
        var.set_addr(gq_var.addr, namespace=structs.GQ_PTR_BUILTIN_INT)
    
    for gq_var in structs.GQ_RESERVED_STRS:
        var = Variable('str', gq_var.name, gq_var.description, 'builtin_str')
        var.set_addr(gq_var.addr, namespace=structs.GQ_PTR_BUILTIN_STR)
    
    for gq_var in structs.GQ_RESERVED_PERSISTENT:
        var = Variable(gq_var.type, gq_var.name, gq_var.description, 'persistent')

    # Create the reserved integer registers for the game:
    for reg_name in structs.GQ_REGISTERS_INT:
        var = Variable('int', reg_name, 0, 'volatile')
    
    # Create the reserved string registers for the game:
    for reg_name in structs.GQ_REGISTERS_STR:
        var = Variable('str', reg_name, '', 'volatile')

def create_symbol_table(table_dest = sys.stdout, cmd_dest = sys.stdout):
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

    heap_ptr_start = 0
    heap_ptr_offset = 0

    cart_ptr_start = 0
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
        anim.set_frame_pointer(structs.gq_ptr_get_addr(anim.frames[0].addr, expected_namespace=structs.GQ_PTR_NS_CART))
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

    menus_ptr_start = cuedata_ptr_start + cuedata_ptr_offset
    menus_ptr_offset = 0

    for menu in Menu.menu_table.values():
        menu.set_addr(menus_ptr_start + menus_ptr_offset)
        menus_ptr_offset += menu.size()

    # Allocation of volatile variables to the heap is required for event code
    #  to resolve correctly, so do that now. We'll have another pass later to
    #  generate their initialization code.
    for var in list(Variable.storageclass_table['volatile'].values()):
        # Heap memory allocation
        var.set_addr(heap_ptr_start + heap_ptr_offset, namespace=structs.GQ_PTR_NS_HEAP)
        heap_ptr_offset += var.size()

    # The event table's addresses are calculated as part of the placement of
    #  stages.
    events_ptr_start = menus_ptr_start + menus_ptr_offset
    events_ptr_offset = 0

    # Stages require two passes: first to assign addresses to the stages themselves,
    #  then to handle all their component parts (especially the events).
    # First pass (addressing):
    stage_ptr_offset = 0
    for stage in Stage.stage_table.values():
        stage.set_addr(stage_ptr_start + stage_ptr_offset)
        stage_ptr_offset += structs.GQ_STAGE_SIZE

    # Second pass (events):
    for stage in Stage.stage_table.values():
        for event_type in structs.EventType:
            if event_type in stage.events:
                event = stage.events[event_type]
                event.set_addr(events_ptr_start + events_ptr_offset, namespace=structs.GQ_PTR_NS_CART)
                events_ptr_offset += event.size()

    init_ptr_start = events_ptr_start + events_ptr_offset
    init_ptr_offset = 0
    init_table = dict()
    Game.game.startup_code_ptr = structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_CART, init_ptr_start)

    # Generate the volatile variables' initialization code.
    for var in list(Variable.storageclass_table['volatile'].values()):
        # Initialization code allocation.
        init_cmd = var.get_init_command()
        init_cmd.set_addr(init_ptr_start + init_ptr_offset)
        init_table[init_cmd.addr] = init_cmd
        init_ptr_offset += init_cmd.size()
    
    # Terminate the init code with a DONE
    done_cmd = CommandDone()
    done_cmd.set_addr(init_ptr_start + init_ptr_offset, namespace=structs.GQ_PTR_NS_CART)
    init_table[done_cmd.addr] = done_cmd
    init_ptr_offset += done_cmd.size()

    # Now, because of hardware limitations of the flash chips we're using, we can only erase 4 KB sectors at
    #  a time. So we need to pad the initialization code with DONE commands until we reach a 4 KB boundary.
    while (init_ptr_start + init_ptr_offset) % 0x1000 != 0:
        done_cmd = CommandDone()
        done_cmd.set_addr(init_ptr_start + init_ptr_offset, namespace=structs.GQ_PTR_NS_CART)
        init_table[done_cmd.addr] = done_cmd
        init_ptr_offset += done_cmd.size()

    # Now that everything else has been addressed, we can calculate the starting
    #  locations of the variable tables.
    # First, allocate memory on-cart for the persistent variables
    vars_ptr_start = init_ptr_start + init_ptr_offset
    vars_ptr_offset = 0
    Game.game.persistent_var_ptr = vars_ptr_start
    
    # First, we do a pass to calculate the CRC16 checksum of the persistent variables.
    crc16_val = structs.GQ_CRC_SEED
    for var in Variable.storageclass_table['persistent'].values():
        crc16_val = structs.crc16_update(crc16_val, var.to_bytes())
    
    crc16_var = Variable('int', '__crc16.builtin', crc16_val, 'persistent')

    # Now we do a pass to place the persistent variables into the persistent section.    
    for var in Variable.storageclass_table['persistent'].values():
        var.set_addr(vars_ptr_start + vars_ptr_offset)
        vars_ptr_offset += var.size()
        
    Game.game.persistent_crc16_ptr = crc16_var.addr
    
    # Bounds checking.
    if vars_ptr_offset >= 0x1000:
        print("COMPILER ERROR: Persistent variable section exceeds 4 KB sector boundary.", file=sys.stderr)
        print("                This is a hardware limitation. Please reduce the use of persistent variables.", file=sys.stderr)
        exit(2)
    
    # Now we need to pad the persistent section to the end of the 4 KB sector.
    while vars_ptr_offset < 0x1000:
        dummy_int = Variable('int', f'__pad.{vars_ptr_offset}', 0xFFFFFFFF, 'persistent')
        dummy_int.set_addr(vars_ptr_start + vars_ptr_offset)
        vars_ptr_offset += dummy_int.size()

    # Finally, we need to add our write-through cache for the persistent variables.
    #  This needs to be the exact same size as the persistent section, and have the
    #  same values.
    cache_ptr_start = vars_ptr_start + vars_ptr_offset
    cache_ptr_offset = 0
    for var in list(Variable.storageclass_table['persistent'].values()):
        cache_var = Variable(var.datatype, f'__cache.{var.name}', var.value, 'persistent')
        cache_var.set_addr(cache_ptr_start + cache_ptr_offset)
        cache_ptr_offset += var.size()

    # Now, do one more pass to try to resolve any unresolved symbols in commands.
    for cmd in Command.command_list:
        if not cmd.resolve():
            print(f"FATAL: Unresolved symbols remain in command {cmd}{(': ' + str(cmd.unresolved_symbols)) if cmd.unresolved_symbols else ''}", file=sys.stderr)
            exit(1)
    
    # And in stages:
    for stage in Stage.stage_table.values():
        if not stage.resolve():
            print(f"FATAL: Unresolved symbols remain in Stage `{stage.name}`: {', '.join(stage.unresolved_symbols)}", file=sys.stderr)
            exit(1)

    symbol_table = {
        '.game' : Game.link_table,
        '.anim' : Animation.link_table,
        '.stage' : Stage.link_table,
        '.frame' : Frame.link_table,
        '.framedata' : FrameData.link_table,
        '.cues' : LightCue.link_table,
        '.cuedata' : LightCueFrame.link_table,
        '.menu' : Menu.link_table,
        '.event' : Event.link_table,
        '.init' : init_table,
        '.var' : Variable.link_table,
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

    # Check whether the heap size exceeds the maximum (512 bytes)
    if heap_ptr_offset > 0x200:
        print(f"CRITICAL: Volatile variable table size exceeds maximum size of 512 bytes; actual size is {heap_ptr_offset} bytes.", file=sys.stderr)
        exit(2)

    cmds_table = []
    cmds_table_headers = ['Address', 'Command', 'Op', 'Flags', 'arg1', 'arg2']
    next_expected_addr = list(Event.link_table.values())[0].event_statements[0].addr

    # Now let's print a human readable list of all our commands.
    for event in Event.link_table.values():
        if event.addr != next_expected_addr:
            print(f"WARNING: Event at address {event.addr:#0{10}x} is not contiguous with the previous event; expected {next_expected_addr:#0{10}x}.", file=sys.stderr)
        
        cmds_table.append((f"{event.addr:#0{PAD}x}", f'EVENT:{event.event_type.name}', '', '', '', ''))

        for cmd in event.event_statements:
            cmd_addr = cmd.addr
            for cmd_struct in cmd.cmd_list():
                cmds_table.append((f"{cmd_addr:#0{PAD}x}", cmd_struct.opcode.name, f'{cmd_struct.opcode.value:#0{4}x}', f'{cmd_struct.flags:#0{4}x}', f"{cmd_struct.arg1:#0{PAD}x}", f"{cmd_struct.arg2:#0{PAD}x}"))
                cmd_addr += structs.GQ_OP_SIZE
                next_expected_addr += structs.GQ_OP_SIZE

    print(tabulate(cmds_table, headers=cmds_table_headers), file=cmd_dest)

    # print(cmds_by_addr)

    # Return the machine-readable symbol table for use in final code generation.
    return symbol_table

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
                if next_expected_addr >= structs.gq_ptr_apply_ns(structs.GQ_PTR_NS_CART, 0xFFFFFF):
                    print(f"OVERSIZE GAME ERROR: Address space exhausted at {next_expected_addr:#0{10}x}.", file=sys.stderr)
                    exit(1)

                if structs.gq_ptr_get_ns(addr) != structs.GQ_PTR_NS_CART:
                    # Only emit code for the cartridge.
                    continue
                if addr != symbol.addr:
                    print(f"COMPILER ERROR: Symbol at address {addr:#0{10}x} has an address mismatch with its symbol table entry.", file=sys.stderr)
                    exit(1)
                if addr != next_expected_addr:
                    print(f"COMPILER ERROR: While working on symbol {symbol}, expected address {next_expected_addr:#0{10}x} but got {addr:#0{10}x}.", file=sys.stderr)
                    exit(1)
                next_expected_addr += symbol.size()
                output += symbol.to_bytes()
                progress.update(task, advance=1)

        progress.update(task, completed=symbol_count)
    
    return output
