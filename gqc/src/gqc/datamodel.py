import sys
import struct
from enum import IntEnum
from typing import Iterable
import pathlib
from collections import namedtuple
import pickle

import webcolors
from PIL import Image
import pyparsing as pp
from rich import print
from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn

from . import structs
from .structs import EventType
from .structs import OpCode as CommandType
from .anim import make_animation
import hashlib

# TODO: Turn the datamodel module into a directory

FrameOnDisk = namedtuple('FrameOnDisk', ['compression_type_name', 'width', 'height', 'bytes'])
CueColor = namedtuple('CueColor', ['name', 'r', 'g', 'b'])

class Game:
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7
    game_name : str = None
    game = None

    def __init__(self, id : int, title : str, author : str, starting_stage : str = 'start'):
        self.addr = 0x00000000 # Set at link time
        self.stages = []
        self.animations = []
        self.variables = []

        self.starting_stage = None
        self.starting_stage_name = starting_stage

        self.startup_code_ptr = None

        if Game.game is not None:
            raise ValueError("Game already defined")
        Game.game = self

        self.id = id
        self.title = title
        self.author = author

    def add_stage(self, stage):
        self.stages.append(stage)
        if stage.name == self.starting_stage_name:
            self.starting_stage = stage

    def add_animation(self, animation):
        self.animations.append(animation)

    def add_variable(self, variable):
        self.variables.append(variable)

    # TODO: Replace
    def pprint(self):
        print("Stages:")
        for stage in self.stages:
            print(stage)
        print("Animations:")
        for anim in self.animations:
            print(anim)
        print("Variables:")
        for var in self.variables:
            print(var)
    
    def __repr__(self) -> str:
        return f"Game({self.id}, {repr(self.title)}, {repr(self.author)})"
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Game.link_table[self.addr] = self
    
    def size(self):
        return structs.GQ_HEADER_SIZE

    def to_bytes(self):
        if self.starting_stage is None:
            raise ValueError("Starting stage not defined")
        header = structs.GqHeader(
            magic=structs.GQ_MAGIC,
            id=self.id,
            title=self.title.encode('ascii')[:structs.GQ_STR_SIZE-1],
            anim_count=len(Animation.anim_table),
            stage_count=len(Stage.stage_table),
            starting_stage_ptr=self.starting_stage.addr,
            startup_code_ptr=self.startup_code_ptr,
            flags=0,
            crc16=0
        )
        return struct.pack(structs.GQ_HEADER_FORMAT, *header)

# TODO: Module for Commands?

class Command:
    command_list = []

    def __init__(self, command_type : CommandType, instring = None, loc = None,  flags : int = 0, arg1 : int = 0, arg2 : int = 0):
        self.instring = instring
        self.loc = loc
        self.addr = 0x00000000 # TODO
        
        self.command_type = command_type
        self.command_flags = flags
        self.arg1 = arg1
        self.arg2 = arg2
        self.resolved = False

        Command.command_list.append(self)
    
    def resolve(self):
        # TODO: Probably not this:
        self.resolved = True
        return True
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        # TODO: Add a check to ensure that the namespace byte isn't already
        #       set in the address.
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)

    def to_bytes(self):
        if not self.resolve():
            # TODO: Raise a GqError here, or otherwise show the location of the error in source
            raise ValueError("Unresolved command symbols remain")

        op = structs.GqOp(
            opcode=self.command_type,
            flags=self.command_flags,
            arg1=self.arg1,
            arg2=self.arg2
        )
        return struct.pack(structs.GQ_OP_FORMAT, *op)
    
    def size(self):
        return structs.GQ_OP_SIZE

    def __repr__(self) -> str:
        return f"Command({self.command_type.name}:{self.command_flags} {self.arg1} {self.arg2});"

class CommandDone(Command):
    def __init__(self):
        super().__init__(CommandType.DONE)
        self.resolved = True

    def __repr__(self) -> str:
        return "DONE"

class CommandGoStage(Command):
    def __init__(self, instring, loc, stage : str):
        super().__init__(CommandType.GOSTAGE, instring, loc)
        self.stage_name = stage
    
    def resolve(self):
        if self.resolved:
            return True

        # TODO: Extract constant for NULL:
        if self.stage_name in Stage.stage_table and Stage.stage_table[self.stage_name].addr != 0x00000000:
            self.arg1 = Stage.stage_table[self.stage_name].addr
            self.resolved = True
        
        return self.resolved

    def __repr__(self) -> str:
        return f"GOSTAGE {self.arg1}"

class CommandPlayBg(Command):
    def __init__(self, instring, loc, bganim : str):
        super().__init__(CommandType.PLAYBG, instring, loc)
        self.anim_name = bganim
    
    def resolve(self):
        if self.resolved:
            return True

        if self.anim_name in Animation.anim_table and Animation.anim_table[self.anim_name].addr != 0x00000000:
            self.arg1 = Animation.anim_table[self.anim_name].addr
            self.resolved = True
        
        return self.resolved
    
    def __repr__(self) -> str:
        return f"PLAYBG {self.arg1}"

class CommandCue(Command):
    def __init__(self, instring, loc, cue : str):
        super().__init__(CommandType.CUE, instring, loc)
        self.cue_name = cue
    
    def resolve(self):
        if self.resolved:
            return True

        if self.cue_name in LightCue.cue_table and LightCue.cue_table[self.cue_name].addr != 0x00000000:
            self.arg1 = LightCue.cue_table[self.cue_name].addr
            self.resolved = True
        
        return self.resolved
    
    def __repr__(self) -> str:
        return f"CUE {self.arg1}"

class CommandSetVar(Command):
    def __init__(self, instring, loc, dst : str, src : str, datatype : str):
        super().__init__(CommandType.SETVAR, instring, loc, arg1=None, arg2=None)
        self.src_name = src
        self.dst_name = dst
        self.datatype = datatype

        if self.datatype == "str":
            self.command_flags = structs.OpFlags.TYPE_STR
        elif self.datatype == "int":
            self.command_flags = structs.OpFlags.TYPE_INT
        else:
            raise ValueError(f"Invalid datatype {self.datatype}")

        self.resolve()
    
    def resolve(self):
        if self.resolved:
            return True

        resolved = True

        # TODO: Test for null differently:
        # TODO: Test for valid memory namespaces:
        if self.dst_name in Variable.var_table and Variable.var_table[self.dst_name].addr != 0x00000000:
            self.arg1 = Variable.var_table[self.dst_name].addr
        else:
            resolved = False
        
        if self.src_name in Variable.var_table and Variable.var_table[self.src_name].addr != 0x00000000:
            self.arg2 = Variable.var_table[self.src_name].addr
        else:
            resolved = False
        
        # Rudimentary type checking:
        if self.src_name in Variable.var_table and self.dst_name in Variable.var_table:
            if Variable.var_table[self.src_name].datatype != self.datatype:
                raise ValueError(f"Variable {self.src_name} is of type {Variable.var_table[self.src_name].datatype}, not {self.datatype}")
            if Variable.var_table[self.dst_name].datatype != self.datatype:
                raise ValueError(f"Variable {self.dst_name} is of type {Variable.var_table[self.dst_name].datatype}, not {self.datatype}")

        self.resolved = resolved
        
        return self.resolved
    
    def __repr__(self) -> str:
        return f"SETVAR {self.dst_name} {self.src_name}"

class Event:
    event_table = []
    link_table = dict()

    def __init__(self, event_type : EventType, event_statements : Iterable):
        self.event_type = event_type
        self.addr = 0x00000000 # Set at link time

        self.event_statements = event_statements
        # TODO: Don't emit an event object if the statements are empty?
        self.event_statements.append(CommandDone())
        # TODO: don't generate anything for an empty event

    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Event.link_table[self.addr] = self

    def to_bytes(self):
        event_bytes = []
        for statement in self.event_statements:
            event_bytes.append(statement.to_bytes())
        return b''.join(event_bytes)

    def size(self):
        # TODO: List needed??
        return sum(statement.size() for statement in self.event_statements)

    def __repr__(self) -> str:
        return f"Event({self.event_type.name}, {self.event_statements})"

class Stage:
    stage_table = {}
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7

    def __init__(self, name : str, bganim : str = None, bgcue : str = None, menu : str = None, events : Iterable = []):
        self.addr = 0x00000000 # Set at link time
        self.id = len(Stage.stage_table)
        self.resolved = False
        self.name = name
        self.bganim_name = bganim
        self.bgcue_name = bgcue
        self.menu_name = menu
        self.unresolved_symbols = []

        if name in Stage.stage_table:
            raise ValueError(f"Stage {name} already defined")
        Stage.stage_table[name] = self

        self.events = dict()

        # TODO: Validate it's a valid event type
        for event in events:
            if event.event_type not in self.events:
                self.events[event.event_type] = event
            else:
                raise ValueError(f"Event {event.event_type} already defined in stage {name}")

        self.resolve()

        # TODO: what?
        Game.game.add_stage(self)

    def resolve(self) -> bool:
        # Don't bother trying to resolve symbols if we've already done so.
        if self.resolved:
            return True
        
        self.unresolved_symbols = []
        resolved = True

        # Attempt to resolve background animation
        if self.bganim_name is None:
            self.bganim = None
        elif self.bganim_name in Animation.anim_table:
            self.bganim = Animation.anim_table[self.bganim_name]
        else:
            self.unresolved_symbols.append(self.bganim_name)
            resolved = False

        # Attempt to resolve background cue
        if self.bgcue_name is None:
            self.bgcue = None
        elif self.bgcue_name in LightCue.cue_table:
            self.bgcue = LightCue.cue_table[self.bgcue_name]
        else:
            self.unresolved_symbols.append(self.bgcue_name)
            resolved = False

        # TODO: Attempt to resolve menu

        # Event statements resolve themselves at code generation time

        # Return whether the resolution of all symbols is complete.
        self.resolved = resolved
        return resolved

    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Stage.link_table[self.addr] = self
    
    def size(self):
        return structs.GQ_STAGE_SIZE

    def __repr__(self) -> str:
        return f"Stage({self.name}, events={self.events})"
    
    def to_bytes(self):
        # TODO: Maybe only calculate the events once?
        event_pointers = []
        for event_type in EventType:
            # TODO: These seem to happen in order in CPython 3.10, but need to confirm
            # TODO: Need to resolve the addr of all the events rather than just setting
            #       them all to null
            if event_type in self.events:
                # TODO: Not this - resolve the address of the event code first
                event_pointers.append(self.events[event_type].addr)
            else:
                event_pointers.append(0x00)

        # TODO: Figure out a better way to pack the following:
        stage = structs.GqStage(
            id=self.id,
            anim_bg_pointer=self.bganim.addr if self.bganim else 0,
            cue_bg_pointer=self.bgcue.addr if self.bgcue else 0,
            menu_pointer=0,
            event_commands=event_pointers
        )
        return struct.pack(structs.GQ_STAGE_FORMAT, stage.id, stage.anim_bg_pointer, stage.cue_bg_pointer, stage.menu_pointer, *stage.event_commands)

class Variable:
    var_table = {}
    storageclass_table = dict(persistent={}, volatile={})
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7
    heap_table = dict()

    def __init__(self, datatype : str, name : str, value, storageclass : str = None):
        self.addr = 0x00000000 # Set at link time
        self.init_from = None
        self.datatype = datatype
        self.name = name
        self.value = value

        if name in Variable.var_table:
            raise ValueError(f"Duplicate definition of {name}")
        Variable.var_table[name] = self

        if datatype == "int":
            if not isinstance(value, int):
                raise ValueError(f"Invalid value {value} for int variable {name}")
        elif datatype == "str":
            if not isinstance(value, str):
                raise ValueError(f"Invalid value {value} for str variable {name}")
            if len(value) > structs.GQ_STR_SIZE-1:
                raise ValueError(f"String {name} length {len(value)} exceeds maximum of {structs.GQ_STR_SIZE-1}")

        # TODO: needed?
        Game.game.add_variable(self)
        
        if storageclass:
            self.set_storageclass(storageclass)

    def __str__(self) -> str:
        return "<{} {} {} = {}>@{}".format(
            self.storageclass if self.storageclass else 'unlinked', 
            self.datatype, 
            self.name, 
            self.value, 
            self.addr
        )
    
    def __repr__(self) -> str:
        return f"Variable({repr(self.datatype)}, {repr(self.name)}, {self.value}, storageclass={repr(self.storageclass)})"

    def set_storageclass(self, storageclass):
        assert storageclass in ["volatile", "persistent"]
        self.storageclass = storageclass
        Variable.storageclass_table[storageclass][self.name] = self

        # If this variable is volatile, create a persistent variable to use
        #  for initialization purposes.
        # TODO: De-duplicate init vars
        if storageclass == "volatile":
            init_var = Variable(self.datatype, f'{self.name}.init', self.value, storageclass="persistent")
            self.init_from = init_var
    
    def to_bytes(self):
        if self.datatype == "int":
            # TODO: Extract constant int size and put it in structs.py
            return self.value.to_bytes(4, 'little')
        elif self.datatype == "str":
            strlen = len(self.value)
            if strlen > structs.GQ_STR_SIZE-1: # -1 for null terminator
                raise ValueError(f"String {self.name} length {strlen} exceeds maximum of {structs.GQ_STR_SIZE-1}")
        else:
            raise ValueError(f"Invalid datatype {self.datatype}")
    
    def get_init_command(self):
        if self.storageclass != 'volatile':
            raise ValueError(f"Persistent variable {self.name} cannot be added to init table.")
        
        return CommandSetVar(None, None, self.name, self.init_from.name, self.datatype)

    def size(self):
        if self.datatype == "int":
            return 4
        elif self.datatype == "str":
            return structs.GQ_STR_SIZE
        else:
            raise ValueError(f"Invalid datatype {self.datatype}")
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        if namespace == structs.GQ_PTR_NS_CART:
            Variable.link_table[self.addr] = self
        elif namespace == structs.GQ_PTR_NS_HEAP:
            Variable.heap_table[self.addr] = self
        else:
            raise ValueError("Invalid or unsupported namespace")

# TODO: Use this:
class FrameEncoding(IntEnum):
    UNCOMPRESSED = 0x01
    RLE4 = 0x41
    RLE7 = 0x71

class Animation:
    anim_table = {}
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7
    next_id : str = 0
    
    # TODO: move DITHER_CHOICES to an enum?
    # TODO: deduplicate the resolution of defaults here:
    # TODO: change source from a str to a pathlib.Path
    # TODO: accept a size parameter
    # TODO: Make sure the frame count fits in a 16-bit integer
    def __init__(self, name : str, source : str, dithering : str = 'none', frame_rate : int = 25):
        self.frame_pointer = 0x00000000
        self.addr = 0x00000000
        self.name = name
        self.source = source
        self.dithering = dithering
        self.ticks_per_frame = 100 // frame_rate

        self.id = Animation.next_id
        Animation.next_id += 1

        if name in Animation.anim_table:
            raise ValueError("Animation {} already defined".format(name))
        Animation.anim_table[name] = self

        with Progress(TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn(), TimeElapsedColumn()) as animation_progress:
            anim_task = animation_progress.add_task(f"[blue]Animation [italic]{name}[/italic]", total=None)
            hash_task = animation_progress.add_task(f" [dim]-- digest", total=1, start=False)
            
            self.frames = []
            
            # TODO: Additional frame rate validation
            if 100 % frame_rate != 0:
                print(f"[red][bold]WARNING[/bold][/red]: [blue][italic]{self.name}[/italic][/blue] frame rate {frame_rate} not a factor of 100; setting to {100 / self.ticks_per_frame}")
                frame_rate = 100 / self.ticks_per_frame

            make_animation_kwargs = dict()
            if dithering:
                make_animation_kwargs['dithering'] = dithering
            if frame_rate:
                make_animation_kwargs['frame_rate'] = frame_rate

            self.src_path = pathlib.Path() / 'assets' / 'animations' / source
            self.dst_path = pathlib.Path() / 'build' / 'assets' / 'animations' / Game.game_name / name
            digest_path = self.dst_path / '.digest'
            
            # Check if the dst_path has a file in it called .digest and compare it to self.digest()
            # If they match, skip the ffmpeg conversion step
            ffmpeged = False
            if digest_path.exists():
                animation_progress.update(hash_task, total=1)
                animation_progress.start_task(hash_task)
                with open(digest_path, 'r') as digest_file:
                    if digest_file.read() == self.digest():
                        animation_progress.update(hash_task, completed=1, total=1)
                        animation_progress.update(anim_task, completed=1, total=1)
                        ffmpeged = True
                        animation_progress.update(hash_task, advance=1)

            # Reformat the animation source file into the build directory.
            if not ffmpeged:
                make_animation(
                    animation_progress,
                    self.src_path,
                    self.dst_path,
                    **make_animation_kwargs
                )
            binary_task = animation_progress.add_task(f" [dim]-> gqimage", total=1, start=False)
            
            # Load each frame into a Frame object
            frame_paths = sorted(self.dst_path.glob('frame*.bmp'))
            animation_progress.update(binary_task, total=len(frame_paths))
            animation_progress.start_task(binary_task)
            for frame_path in frame_paths:
                serialized_path = frame_path.with_suffix('.gqframe')
                # TODO: Do some kind of error handling here for whatever can be
                #       raised while trying to deserialize the frame.
                if ffmpeged and serialized_path.exists():
                    self.frames.append(Frame(path=serialized_path))
                else:
                    self.frames.append(Frame(path=frame_path))
                    self.frames[-1].serialize(serialized_path)
                animation_progress.update(binary_task, advance=1)
            animation_progress.start_task(anim_task)
            animation_progress.update(anim_task, completed=1, total=1)

            # Write the digest of the source file to the .digest file
            if not ffmpeged:
                animation_progress.update(hash_task, total=1)
                animation_progress.start_task(hash_task)
                with open(self.dst_path / '.digest', 'w') as digest_file:
                    digest_file.write(self.digest())
                animation_progress.update(hash_task, advance=1)
            
    def digest(self) -> int:
        # An Animation object is uniquely identified by a hash of the source file,
        #  its frame rate, size, and its dithering configuration.
        # TODO: The following should be added, but currently it breaks when
        #       trying to load from file (because the frames list is empty)
        #size = f"{self.frames[0].width}x{self.frames[0].height}"

        # Get a SHA-256 hash of self.source's contents
        with open(self.src_path, 'rb') as file:
            contents = file.read()
            sha256_hash = hashlib.sha256(contents)
        sha256_hash.update(str(self.ticks_per_frame).encode('ascii'))
        sha256_hash.update(self.dithering.encode('ascii'))
        # sha256_hash.update(size.encode('ascii')) TODO: Re-add
        from . import __version__
        sha256_hash.update(__version__.encode('ascii'))
        return sha256_hash.hexdigest()
    
    def set_frame_pointer(self, frame_pointer : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.frame_pointer = structs.gq_ptr_apply_ns(namespace, frame_pointer)
    
    # TODO: break this out into an abstract class or something.
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        # TODO: Add a check to ensure that the namespace byte isn't already
        #       set in the address.
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Animation.link_table[self.addr] = self
    
    def size(self):
        return structs.GQ_ANIM_SIZE

    def __repr__(self) -> str:
        return f"Animation('{self.name}', '{self.source}', {100/self.ticks_per_frame}, {repr(self.dithering)})"
    
    def to_bytes(self):
        anim_struct = structs.GqAnim(
            id=self.id,
            frame_count=len(self.frames),
            ticks_per_frame=self.ticks_per_frame,
            flags=0,
            width=self.frames[0].width,
            height=self.frames[0].height,
            frame_pointer=self.frame_pointer
        )
        return struct.pack(structs.GQ_ANIM_FORMAT, *anim_struct)

class Frame:
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7

    # TODO: replace with the enum
    image_formats = dict(
        # IMAGE_FMT_1BPP_COMP_RLE7=0x71,
        IMAGE_FMT_1BPP_COMP_RLE4=0x41,
        IMAGE_FMT_1BPP_UNCOMP=0x01
    )

    def __init__(self, img : Image = None, path : pathlib.Path = None):
        self.addr = 0x00000000
        self.frame_data = FrameData(self)

        assert img or path
        
        reading_bytes = False

        if img:
            self.image = img
        elif path:
            if path.suffix == '.gqframe':
                self.deserialize(path)
                return
            else:
                self.image = Image.open(path)
        
        self.image = self.image.convert('1')

        # Now, determine which of these image types is the smallest:
        image_types = dict(
            # IMAGE_FMT_1BPP_COMP_RLE7=self.image_rle7_bytes(), # TODO: Re-add once the C side supports it
            IMAGE_FMT_1BPP_COMP_RLE4=self.image_rle4_bytes(),
            IMAGE_FMT_1BPP_UNCOMP=self.uncompressed_bytes()
        )

        self.compression_type_name = sorted(list(image_types.keys()), key=lambda a: len(image_types[a]))[0]
        self.compression_type_number = Frame.image_formats[self.compression_type_name]
        self.bytes = image_types[self.compression_type_name]

        self.width = self.image.width
        self.height = self.image.height
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Frame.link_table[self.addr] = self
    
    def to_bytes(self):
        frame_struct = structs.GqAnimFrame(
            bPP=self.compression_type_number,
            data_pointer=self.frame_data.addr,
            data_size=len(self.bytes)
        )
        return struct.pack(structs.GQ_ANIM_FRAME_FORMAT, *frame_struct)
    
    def serialize(self, out_path : pathlib.Path):
        d = FrameOnDisk(
            compression_type_name=self.compression_type_name,
            width=self.width,
            height=self.height,
            bytes=self.bytes
        )
        with open(out_path, 'wb') as file:
            pickle.dump(d, file)

    def deserialize(self, in_path : pathlib.Path):
        with open(in_path, 'rb') as file:
            d = pickle.load(file)
            self.compression_type_name = d.compression_type_name
            self.compression_type_number = Frame.image_formats[self.compression_type_name]
            self.width = d.width
            self.height = d.height
            self.bytes = d.bytes

    def size(self):
        return structs.GQ_ANIM_FRAME_SIZE

    def uncompressed_bytes(self):
        run = 0
        val = 0
        out_bytes = []
        row_run = 0

        for pixel_raw in self.image.getdata():
            pixel = 1 if pixel_raw else 0

            if run == 8 or row_run == self.image.width:
                out_bytes.append(val)
                run = 0
                val = 0
                if row_run == self.image.width:
                    row_run = 0
            
            if pixel:
                val |= (0b10000000 >> run)
            
            run += 1
            row_run += 1

        # We definitely didn't finish the above with a write-out, so do one:
        out_bytes.append(val)
        
        return bytes(out_bytes)

    def rle_bytes(self, bits):
        val = 1 if self.image.getdata()[0] else 0
        run = 0
        out_bytes = []
        if bits == 4:
            run_max = 0x0f
            val_mask = 0xf0
        elif bits == 7:
            run_max = 0x7f # 127
            val_mask = 0xfe
        else:
            assert False # ERROR.

        for pixel_raw in list(self.image.getdata())[1:]:
            pixel = 1 if pixel_raw else 0
            if pixel == val:
                # same as previous pixel value; add to the run value
                if run == run_max:
                    run = 0
                    out_bytes.append(val_mask + val)
                else:
                    run += 1
            else:
                # different from previous pixel value; write out current run,
                # and then change run and val.
                out_bytes.append((run << (8-bits)) + val)
                run = 0
                val = pixel
        # We always have at least one more value to write-out:
        out_bytes.append((run << (8-bits)) + val)
        
        return bytes(out_bytes)

    def image_rle4_bytes(self):
        return self.rle_bytes(4)
    
    def image_rle7_bytes(self):
        return self.rle_bytes(7)

    def __repr__(self) -> str:
        return f"Frame({self.width}x{self.height}:{self.compression_type_name})"

class FrameData:
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7

    def __init__(self, frame : Frame):
        self.frame = frame
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        FrameData.link_table[self.addr] = self
    
    def to_bytes(self):
        return self.frame.bytes

    def size(self):
        return len(self.frame.bytes)
    
    def __repr__(self) -> str:
        return f"FrameData({self.frame.width}x{self.frame.height}:{self.frame.compression_type_name})"

class LightCue:
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7
    cue_table = dict()

    def __init__(self, colors : list[CueColor]):
        self.frames = []
        self.colors = dict()
        self.name = None

        for color in colors:
            if color.name in self.colors:
                raise ValueError(f"Duplicate color {color.name}")
            self.colors[color.name] = color
    
    def set_name(self, name : str):
        if self.name != None:
            raise ValueError("Cue already named")
        self.name = name
        
        if self.name in LightCue.cue_table:
            raise ValueError(f"Duplicate cue {name}")
        LightCue.cue_table[self.name] = self

    def serialize(self, out_path : pathlib.Path):
        with open(out_path, 'wb') as file:
            pickle.dump(self, file)
    
    def deserialize(self, in_path : pathlib.Path):
        with open(in_path, 'rb') as file:
            c = pickle.load(file)
        self.frames = c.frames
        self.colors = c.colors

    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        LightCue.link_table[self.addr] = self
    
    def to_bytes(self):
        cue_struct = structs.GqLedCue(
            frame_count=len(self.frames),
            flags=0,
            frames=self.frames[0].addr
        )
        return struct.pack(structs.GQ_LEDCUE_FORMAT, *cue_struct)
    
    def size(self):
        return structs.GQ_LEDCUE_SIZE
    
    def __repr__(self):
        return f"LightCue(name={self.name})"

class LightCueFrame:
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7

    def __init__(self, colors : list[str], duration : int, transition : str = 'smooth'):
        self.colors = colors
        self.duration = duration
        self.transition = transition
        # TODO: Handle packing transition into flags
        self.lightcue = None
        self.resolved = False
    
    def add_to_cue(self, cue : LightCue):
        self.lightcue = cue
        self.lightcue.frames.append(self)
        self.resolve()
    
    def resolve(self):
        if not self.lightcue:
            return False
        if self.resolved:
            return True
        
        resolved_colors = []
        for color_name in self.colors:
            if color_name in self.lightcue.colors:
                resolved_colors.append(self.lightcue.colors[color_name])
            else:
                try:
                    color = webcolors.name_to_rgb(color_name)
                    resolved_colors.append(CueColor(color_name, color.red, color.green, color.blue))
                except ValueError:
                    raise ValueError(f"Unresolvable color name {color_name} somewhere in this file.")
        
        self.colors = resolved_colors
        self.resolved = True
        return True
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        LightCueFrame.link_table[self.addr] = self
    
    def to_bytes(self):
        frame_colors = []
        for color in self.colors:
            frame_colors.append(color.r)
            frame_colors.append(color.g)
            frame_colors.append(color.b)
        frame_struct = structs.GqLedCueFrame(
            self.duration,
            0, # TODO
            *frame_colors
        )
        return struct.pack(structs.GQ_LEDCUE_FRAME_FORMAT, *frame_struct)
    
    def size(self):
        return structs.GQ_LEDCUE_FRAME_SIZE

    def __repr__(self):
        return f"LightCueFrame({self.colors}, {self.duration}, {self.transition})"
