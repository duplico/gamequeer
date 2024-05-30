import sys
import struct
from enum import IntEnum
from typing import Iterable
import pathlib
from PIL import Image

import pyparsing as pp

from . import structs
from .anim import make_animation

class Game:
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7
    game = None

    def __init__(self, id : int, title : str, author : str, starting_stage : str = 'start'):
        self.addr = 0x00000000 # Set at link time
        self.stages = []
        self.animations = []
        self.variables = []

        self.starting_stage = None
        self.starting_stage_name = starting_stage

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
            flags=0,
            crc16=0
        )
        return struct.pack(structs.GQ_HEADER_FORMAT, *header)

class Stage:
    stage_table = {}
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7

    def __init__(self, name : str, bganim : str = None, menu : str = None, event_statements : Iterable = []):
        self.addr = 0x00000000 # Set at link time
        self.id = len(Stage.stage_table)
        self.resolved = False
        self.name = name
        self.bganim_name = bganim
        self.menu_name = menu
        self.event_statements = event_statements
        self.unresolved_symbols = []

        if name in Stage.stage_table:
            raise ValueError(f"Stage {name} already defined")
        Stage.stage_table[name] = self

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

        # TODO: Attempt to resolve menu

        # TODO: Anything to do with event statements here?

        # Return whether the resolution of all symbols is complete.
        self.resolved = resolved
        return resolved

    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Stage.link_table[self.addr] = self
    
    def size(self):
        return structs.GQ_STAGE_SIZE

    def __repr__(self) -> str:
        return f"Stage({self.name})"
    
    def to_bytes(self):
        stage = structs.GqStage(
            id=self.id,
            anim_bg_pointer=self.bganim.addr if self.bganim else 0,
            menu_pointer=0,
            events_code_pointer=0,
            events_code_size=0
        )
        return struct.pack(structs.GQ_STAGE_FORMAT, *stage)
        

class Variable:
    var_table = {}
    storageclass_table = dict(persistent={}, volatile={})
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7

    def __init__(self, datatype : str, name : str, value, storageclass : str =None):
        self.addr = 0x00000000 # Set at link time
        self.datatype = datatype
        self.name = name
        self.value = value

        # TODO: set when the section is finished parsing
        self.storageclass = None

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
    
    def size(self):
        if self.datatype == "int":
            return 4
        elif self.datatype == "str":
            return structs.GQ_STR_SIZE
        else:
            raise ValueError(f"Invalid datatype {self.datatype}")
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Variable.link_table[self.addr] = self

# TODO: Set up globals or a singleton or something containing the base path etc.

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
    def __init__(self, name : str, source : str, dithering : str = 'none', frame_rate : int = 25):
        self.frame_pointer = 0x00000000
        self.addr = 0x00000000
        self.name = name
        self.source = source
        self.frame_rate = frame_rate
        self.dithering = dithering

        self.id = Animation.next_id
        Animation.next_id += 1

        if name in Animation.anim_table:
            raise ValueError("Animation {} already defined".format(name))
        Animation.anim_table[name] = self

        print(f"Begin work on animation `{name}`")

        self.frames = []
        
        make_animation_kwargs = dict()
        if dithering:
            make_animation_kwargs['dithering'] = dithering
        if frame_rate:
            make_animation_kwargs['frame_rate'] = frame_rate

        # TODO: Namespace built animations by game name
        # Reformat the animation source file into the build directory.
        make_animation(
            pathlib.Path() / 'assets' / 'animations' / source,
            pathlib.Path() / 'build' / 'assets' / 'animations' / name,
            **make_animation_kwargs
        )

        print(f"  Converting frames to target binary format...", end='', flush=True)
        dot_timer_start = (self.frame_rate if self.frame_rate else 25) * 2
        dot_timer = dot_timer_start
        # Load each frame into a Frame object
        for frame_path in (pathlib.Path() / 'build' / 'assets' / 'animations' / name).glob('frame*.bmp'):
            self.frames.append(Frame(path=frame_path))
            if dot_timer == 0:
                print(".", end='', flush=True)
                dot_timer = dot_timer_start
            else:
                dot_timer -= 1
        print("done.")
        print(f"Complete work on animation `{name}`")
    
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
        return f"Animation('{self.name}', '{self.source}', {repr(self.frame_rate)}, {repr(self.dithering)})"
    
    def to_bytes(self):
        anim_struct = structs.GqAnim(
            id=self.id,
            frame_count=len(self.frames),
            frame_rate=self.frame_rate,
            flags=0,
            width=self.frames[0].width,
            height=self.frames[0].height,
            frame_pointer=self.frame_pointer
        )
        return struct.pack(structs.GQ_ANIM_FORMAT, *anim_struct)

class Frame:
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7

    def __init__(self, img : Image = None, path : pathlib.Path = None):
        self.data_pointer = 0x00000000
        self.addr = 0x00000000
        self.frame_data = FrameData(self)

        assert img or path
        
        if img:
            self.image = img
        elif path:
            self.image = Image.open(path)
        
        self.image = self.image.convert('1')

        # Now, determine which of these image types is the smallest:
        image_types = dict(
            IMAGE_FMT_1BPP_COMP_RLE4=self.image_rle4_bytes(),
            IMAGE_FMT_1BPP_COMP_RLE7=self.image_rle7_bytes(),
            IMAGE_FMT_1BPP_UNCOMP=self.uncompressed_bytes()
        )

        # TODO: replace with the enum
        image_formats = dict(
            IMAGE_FMT_1BPP_COMP_RLE7=0x71,
            IMAGE_FMT_1BPP_COMP_RLE4=0x41,
            IMAGE_FMT_1BPP_UNCOMP=0x01
        )

        self.compression_type_name = sorted(list(image_types.keys()), key=lambda a: len(image_types[a]))[0]
        self.compression_type_number = image_formats[self.compression_type_name]
        self.bytes = image_types[self.compression_type_name]

        self.width = self.image.width
        self.height = self.image.height
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Frame.link_table[self.addr] = self
    
    def to_bytes(self):
        frame_struct = structs.GqAnimFrame(
            bPP=self.compression_type_number,
            data_pointer=self.data_pointer,
            data_size=len(self.bytes)
        )
        return struct.pack(structs.GQ_ANIM_FRAME_FORMAT, *frame_struct)
    
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
