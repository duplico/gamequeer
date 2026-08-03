import sys
import struct
import itertools
from enum import IntEnum
from typing import Iterable
import pathlib
from collections import namedtuple
import pickle

import webcolors
from PIL import Image
from rich import print
from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn

from . import structs
from .structs import EventType
from .anim import make_animation

import hashlib

FrameOnDisk = namedtuple('FrameOnDisk', ['compression_type_name', 'width', 'height', 'bytes'])
CueColor = namedtuple('CueColor', ['name', 'r', 'g', 'b'])
GqcIntOperand = namedtuple('GqcIntOperand', 'is_literal value')

# A `str(<int_expression>)` cast appearing as one operand of a `+`
# string-concatenation chain (gamequeer#386), as opposed to the whole RHS of
# a `:=` (which stays on the `CommandCastStr`-direct-to-dst path it always
# used -- see `parser.parse_assignment`). `int_expr` is whatever
# `int_expression`'s own parse action already produced: a `GqcIntOperand` or
# an `IntExpression`. `StrExpression.get_result_symbol` lowers this to a
# `CommandCastStr` writing into a freshly-allocated string register, reusing
# the same register pool (and the same free-after-use bookkeeping) as any
# other operand that needs to be loaded into a register.
GqcStrCastOperand = namedtuple('GqcStrCastOperand', 'int_expr')

# `badge_count()` -- a nullary popcount intrinsic over the 320-bit
# badges-seen bitfield (gamequeer#387). It carries no data of its own (no
# argument, no variable/literal backing it), so -- unlike `GqcIntOperand` --
# it can never be returned as-is as a subexpression's result; it always has
# to be lowered into a runtime loop first (see
# `IntExpression._emit_badge_count`). This is just the marker
# `parser.parse_badge_count_operand`/`parse_int_operand`/
# `IntExpression.get_result_symbol` recognize to trigger that lowering, the
# same role `GqcStrCastOperand` plays for an inline `str(x)` cast.
GqcBadgeCountOperand = namedtuple('GqcBadgeCountOperand', [])

class Game:
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7
    game_name : str = None
    # The directory containing the game's entry `.gq` file (gamequeer#420's
    # game-as-directory convention). Set by gqc.py's `compile` command (and
    # by tests that drive the parser directly) before parsing, so
    # animations{}/lightcues{} sources -- and Game.__init__ below, via the
    # game{}-anywhere relaxation -- never have to assume anything about
    # *when* the game{} block itself is parsed relative to those sections.
    # Defaults to the CWD, matching gqc's historical CWD-relative asset
    # resolution for the common case where the entry file lives at the top
    # of the invocation directory.
    game_dir : pathlib.Path = pathlib.Path()
    game = None

    # Set (regardless of whether a Game instance exists yet) the first time
    # any stage's event code calls fw_version() (gamequeer#411), so the
    # game{}-anywhere relaxation (gamequeer#420) can't lose the signal to a
    # fw_version() call that's parsed *before* the game{} block itself --
    # see parse_fw_version_operand and Game.__init__ below.
    needs_fw_probe_seen = False

    def __init__(self, id : int, title : str, author : str, starting_stage : str = 'start'):
        self.addr = 0x00000000 # Set at link time
        self.stages = []

        self.starting_stage = None
        self.starting_stage_name = starting_stage

        self.startup_code_ptr = None
        self.persistent_var_ptr = None

        self.persistent_crc16_ptr = None

        # Set by parser.parse_fw_version_operand the first time a game
        # calls fw_version() (gamequeer#411). linker.inject_fw_version_probe
        # only synthesizes the probe stage -- and its firmware pays for the
        # probe's BGDONE/TIMER race -- when this is True, so a game that
        # never calls fw_version() has zero footprint from this feature.
        # Seeded from needs_fw_probe_seen rather than starting False: since
        # gamequeer#420, a fw_version() call may already have been parsed
        # (and recorded there) before this game{} block itself is reached.
        self.needs_fw_probe = Game.needs_fw_probe_seen

        if Game.game is not None:
            raise ValueError("Game already defined")
        Game.game = self

        self.id = id
        self.title = title
        self.author = author

        # gamequeer#420: game{} may now be parsed after some/all of a
        # game's stages (it no longer has to be the first top-level
        # section), so a stage matching starting_stage may already be
        # sitting in Stage.stage_table by the time we get here -- add_stage()
        # only runs this same check for a stage parsed *after* this point.
        for stage in Stage.stage_table.values():
            if stage.name == self.starting_stage_name:
                self.starting_stage = stage
                break

    def add_stage(self, stage):
        self.stages.append(stage)
        if stage.name == self.starting_stage_name:
            self.starting_stage = stage

    def __repr__(self) -> str:
        return f"Game({self.id}, {repr(self.title)}, {repr(self.author)}, crc_ptr={self.persistent_crc16_ptr:#0{10}x})"
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Game.link_table[self.addr] = self
    
    def size(self):
        return structs.GQ_HEADER_SIZE

    def to_bytes(self):
        if self.starting_stage is None:
            raise ValueError("COMPILER ERROR: Starting stage not defined")
        if self.persistent_crc16_ptr is None:
            raise ValueError("COMPILER ERROR: No pointer to the persistent section CRC16 is defined.")
        
        header = structs.GqHeader(
            magic=structs.GQ_MAGIC,
            id=self.id,
            title=self.title.encode('ascii')[:structs.GQ_STR_SIZE-1],
            starting_stage_ptr=self.starting_stage.addr,
            startup_code_ptr=self.startup_code_ptr,
            persistent_var_ptr=self.persistent_var_ptr,
            persistent_crc16_ptr=self.persistent_crc16_ptr,
            color=0x00, # Unassigned.
            flags=0,
            crc16=0
        )
        return struct.pack(structs.GQ_HEADER_FORMAT, *header)

class Event:
    event_table = []
    link_table = dict()

    def __init__(self, event_type : EventType, event_statements : Iterable):
        self.event_type = event_type
        self.addr = 0x00000000 # Set at link time

        self.event_statements = event_statements
        
        from .commands import CommandDone
        self.event_statements.append(CommandDone())

    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Event.link_table[self.addr] = self

        statement_addr = addr

        for statement in self.event_statements:
            statement.set_addr(statement_addr, namespace)
            statement_addr += statement.size()

    def to_bytes(self):
        event_bytes = []
        for statement in self.event_statements:
            event_bytes.append(statement.to_bytes())
        return b''.join(event_bytes)

    def size(self):
        return sum(statement.size() for statement in self.event_statements)

    def __repr__(self) -> str:
        return f"Event({self.event_type.name}, {self.event_statements})"

class Stage:
    stage_table = {}
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7
    BoundMenu = namedtuple('BoundMenu', ['menu_name', 'menu_prompt'])

    def __init__(self, name : str, bganim : str = None, bgcue : str = None, menu : 'Stage.BoundMenu' = None, events : Iterable = [], textentry : bool = False, textentry_prompt : str = None):
        self.addr = 0x00000000 # Set at link time
        self.id = len(Stage.stage_table)
        self.resolved = False
        self.name = name
        self.bganim_name = bganim
        self.bgcue_name = bgcue
        self.menu_def = menu
        self.textentry = textentry
        self.textentry_prompt = textentry_prompt
        self.prompt_addr = 0x00000000
        self.unresolved_symbols = []

        if menu and textentry:
            raise ValueError("Stage cannot have both a menu and text entry prompt")

        if name in Stage.stage_table:
            raise ValueError(f"Stage {name} already defined")
        Stage.stage_table[name] = self

        self.events = dict()

        for event in events:
            if event.event_type not in self.events:
                self.events[event.event_type] = event
            else:
                raise ValueError(f"Event {event.event_type} already defined in stage {name}")

        self.resolve()

        # gamequeer#420: game{} may not have been parsed yet (it's no
        # longer required to be the first top-level section) -- in that
        # case Game.__init__ itself scans Stage.stage_table for a
        # starting_stage match once it *is* parsed, so there's nothing to
        # register here yet.
        if Game.game is not None:
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

        # Attempt to resolve menu
        if not self.menu_def:
            self.menu = None
        else:
            if self.menu_def.menu_name in Menu.menu_table:
                self.menu = Menu.menu_table[self.menu_def.menu_name]
            else:
                self.unresolved_symbols.append(self.menu_def.menu_name)
                resolved = False
        
        # Attempt to resolve menu/text prompt
        if self.menu_def and self.menu_def.menu_prompt:
            prompt_name = self.menu_def.menu_prompt
        elif self.textentry_prompt:
            prompt_name = self.textentry_prompt
        else:
            prompt_name = None
        
        if prompt_name:
            if prompt_name in Variable.var_table:
                if Variable.var_table[prompt_name].datatype != 'str':
                    raise ValueError(f"Prompt {prompt_name} is not a string")
                if Variable.var_table[prompt_name].addr:
                    self.prompt_addr = Variable.var_table[prompt_name].addr
                else:
                    self.unresolved_symbols.append(prompt_name)
                    resolved = False
            else:
                self.unresolved_symbols.append(prompt_name)
                resolved = False

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
        return f"Stage({self.name}, menu={self.menu_def} bganim={self.bganim_name}, bgcue={self.bgcue_name}, events={self.events})"
    
    def to_bytes(self):
        if not self.resolve():
            raise ValueError(f"Stage {self.name} has unresolved symbols: {self.unresolved_symbols}")
        
        event_pointers = []
        for event_type in EventType:
            if event_type in self.events:
                event_pointers.append(self.events[event_type].addr)
            else:
                event_pointers.append(0x00)

        if self.menu:
            menu_pointer = self.menu.addr
        elif self.textentry:
            menu_pointer = structs.gq_ptr_apply_ns(structs.GQ_PTR_BUILTIN_MENU_FLAGS, 0)
        else:
            menu_pointer = 0x00000000

        stage = structs.GqStage(
            id=self.id,
            anim_bg_pointer=self.bganim.addr if self.bganim else 0,
            cue_bg_pointer=self.bgcue.addr if self.bgcue else 0,
            menu_pointer=menu_pointer,
            prompt_pointer = self.prompt_addr,
            event_commands=event_pointers
        )

        return struct.pack(structs.GQ_STAGE_FORMAT, stage.id, stage.anim_bg_pointer, stage.cue_bg_pointer, stage.menu_pointer, stage.prompt_pointer, *stage.event_commands)

class Variable:
    var_table = {}
    storageclass_table = dict(persistent={}, volatile={}, builtin_int={}, builtin_str = {})
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7
    heap_table = dict()
    
    str_literals = dict()

    @classmethod
    def get_str_literal(cls, value : str) -> str:
        if value in cls.str_literals:
            return cls.str_literals[value]
        else:
            name = f'S{len(cls.str_literals)}.strlit'
            cls.str_literals[value] = name

            # Create a persistent variable to hold the string literal
            Variable('str', name, value, storageclass='persistent')
            return name

    def __init__(self, datatype : str, name : str, value, storageclass : str = None):
        self.addr = 0x00000000 # Set at link time
        self.init_from = None
        self.datatype = datatype
        self.name = name
        self.value = value
        self.storageclass = None
        # Read-only by cart convention (gamequeer#411, e.g. GQI_FW_VERSION):
        # writing an as-yet-undefined reserved int corrupts adjacent RAM on
        # firmware that predates it. Only linker.create_reserved_variables()
        # ever sets this False; every other Variable stays writable. See
        # commands.CommandSetInt/CommandArithmetic.resolve() for enforcement.
        self.writable = True

        if name in Variable.var_table:
            existing_storageclass = Variable.var_table[name].storageclass
            # existing_storageclass is None for a same-section duplicate
            # (gamequeer#338): both definitions are constructed before
            # either one has a storage class assigned, which happens once
            # for the whole section afterwards via set_storageclass(). Treat
            # that the same as any other non-builtin duplicate rather than
            # crashing on None.startswith(...).
            if existing_storageclass and existing_storageclass.startswith('builtin'):
                raise ValueError(f"Cannot redefine builtin variable {name}")
            else:
                raise ValueError(f"Duplicate definition of {name}")
        Variable.var_table[name] = self
        
        if storageclass:
            self.set_storageclass(storageclass)

        # Skip type validation for builtins
        if storageclass and storageclass.startswith("builtin"):
            return

        # If this variable is not a builtin (reserved keyword), validate the value.
        #  Builtin variables are reserved for internal use, and their values are
        #  irrelevant except at runtime.
        if datatype == "int":
            if not isinstance(value, int):
                raise ValueError(f"Invalid value {value} for int variable {name}")
        elif datatype == "str":
            if not isinstance(value, str):
                raise ValueError(f"Invalid value {value} for str variable {name}")
            if len(value) > structs.GQ_STR_SIZE-1:
                raise ValueError(f"String {name} length {len(value)} exceeds maximum of {structs.GQ_STR_SIZE-1}")

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
        assert storageclass in ["volatile", "persistent", "builtin_int", "builtin_str"]
        self.storageclass = storageclass
        Variable.storageclass_table[storageclass][self.name] = self

        # If this variable is a volatile string, create a persistent variable to use for
        #  initialization purposes.
        # Volatile ints don't need this because they can be initialized with a literal-flagged 
        #  operation.
        if storageclass == "volatile" and self.datatype == "str":
            init_var = Variable(self.datatype, f'{self.name}.init', self.value, storageclass="persistent")
            self.init_from = init_var
    
    def to_bytes(self):
        if self.datatype == "int":
            # t_gq_int is a signed 32-bit int on-cart (see gamequeer.h), so a
            # negative value must be encoded as signed two's complement --
            # plain int.to_bytes(..., 'little') defaults to unsigned and
            # raises OverflowError on a negative value (gamequeer#359).
            # Non-negative values (including the linker's 0xFFFFFFFF padding
            # sentinel, see linker.py) keep the unsigned encoding they
            # already had, so this only changes behavior for negatives.
            return self.value.to_bytes(
                structs.GQ_INT_SIZE, 'little', signed=self.value < 0
            )
        elif self.datatype == "str":
            strlen = len(self.value)
            if strlen > structs.GQ_STR_SIZE-1: # -1 for null terminator
                raise ValueError(f"String {self.name} length {strlen} exceeds maximum of {structs.GQ_STR_SIZE-1}")
            # Convert self.value from str to null-padded bytes of length structs.GQ_STR_SIZE:
            return self.value.encode('ascii').ljust(structs.GQ_STR_SIZE, b'\x00')
        else:
            raise ValueError(f"Invalid datatype {self.datatype}")
    
    def get_init_command(self):
        if self.storageclass != 'volatile':
            raise ValueError(f"Persistent variable {self.name} cannot be added to init table.")
        
        from .commands import CommandSetInt, CommandSetStr
        if self.datatype == "str":
            return CommandSetStr(None, None, self.name, self.init_from.name)
        elif self.datatype == "int":
            return CommandSetInt(None, None, self.name, GqcIntOperand(is_literal=True, value=self.value))
        else:
            raise ValueError(f"Invalid datatype {self.datatype}")

    def size(self):
        if self.datatype == "int":
            return structs.GQ_INT_SIZE
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
        elif namespace in [structs.GQ_PTR_BUILTIN_INT, structs.GQ_PTR_BUILTIN_STR]:
            # Builtin variables are not linked into the symbol table
            pass
        else:
            raise ValueError("Invalid or unsupported namespace")

class FrameEncoding(IntEnum):
    UNCOMPRESSED = 0x01
    RLE4 = 0x41
    RLE7 = 0x71

class Animation:
    anim_table = {}
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7
    next_id : str = 0
    
    def __init__(self, name : str, source : str, dithering : str = 'none', frame_rate : int = 5, duration: int = 100, w : int = 128, h : int = 128):
        self.frame_pointer = 0x00000000
        self.addr = 0x00000000
        self.name = name
        self.source = source
        self.dithering = dithering
        self.ticks_per_frame = 100 // frame_rate
        self.width = w
        self.height = h

        # Animation widths and heights must fit in a uint8_t
        if self.width > 128:
            raise ValueError(f"Animation {name} width {self.width} exceeds maximum of 128")
        if self.height > 128:
            raise ValueError(f"Animation {name} height {self.height} exceeds maximum of 128")

        if name in Animation.anim_table:
            raise ValueError("Animation {} already defined".format(name))

        # Only claim an id once the duplicate-name check has passed, so a
        # rejected redefinition doesn't leak an id that no Animation ends up
        # using (gamequeer#338).
        self.id = Animation.next_id
        Animation.next_id += 1

        Animation.anim_table[name] = self

        self.frames = []

        with Progress(TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn(), TimeElapsedColumn()) as animation_progress:
            anim_task = animation_progress.add_task(f"[blue]Animation [italic]{name}[/italic]", total=None)
            hash_task = animation_progress.add_task(f" [dim]-- digest", total=1, start=False)
            
            if 100 % frame_rate != 0:
                print(f"[red][bold]WARNING[/bold][/red]: [blue][italic]{self.name}[/italic][/blue] frame rate {frame_rate} not a factor of 100; setting to {100 / self.ticks_per_frame}")
                frame_rate = 100 / self.ticks_per_frame

            if frame_rate > 20:
                print(f"[red][bold]WARNING[/bold][/red]: [blue][italic]{self.name}[/italic][/blue] frame rate {frame_rate} exceeds 20 FPS; every frame will be clamped to a minimum on-screen duration of 5 ticks (20 FPS) on the badge.")

            make_animation_kwargs = dict()
            if dithering:
                make_animation_kwargs['dithering'] = dithering
            if frame_rate:
                make_animation_kwargs['frame_rate'] = frame_rate
            if self.width:
                make_animation_kwargs['width'] = self.width
            if self.height:
                make_animation_kwargs['height'] = self.height

            # gamequeer#420: resolved relative to the game's own directory
            # (Game.game_dir), not the process CWD -- an absolute `source`
            # still bypasses this entirely (pathlib truncates a `/`-joined
            # absolute right-hand side), which linker.py's fw_version()
            # probe-frame synthesis relies on.
            self.src_path = Game.game_dir / 'assets' / 'animations' / source
            self.dst_path = pathlib.Path() / 'build' / 'assets' / 'animations' / Game.game_name / name
            digest_path = self.dst_path / '.digest'

            # Check if the dst_path has a file in it called .digest and compare it to self.digest()
            # If they match, skip the ffmpeg conversion step
            ffmpeged = False
            if digest_path.exists():
                # If a previous run already left build output in dst_path,
                # use it to tentatively determine whether this is a
                # single-still-image animation before comparing digests, so
                # self.ticks_per_frame - and therefore self.digest() -
                # matches what was in effect when the stored digest was
                # written. Without this, the single-still override further
                # down (`if len(frame_paths) == 1: self.ticks_per_frame =
                # duration`) only ever happens *after* the cache check, so
                # the digest checked against the cache could never match the
                # one that was stored, and the cache never hit for stills
                # (gamequeer#376). The real frame count - and the
                # corresponding permanent override - is (re)determined below
                # once dst_path is known to be current. Only the first two
                # matches are needed (and the directory isn't otherwise
                # touched), so this doesn't pay for a full sorted listing.
                original_ticks_per_frame = self.ticks_per_frame
                try:
                    existing_frames = list(itertools.islice(self.dst_path.glob('frame*.bmp'), 2))
                    if len(existing_frames) == 1:
                        self.ticks_per_frame = duration

                    animation_progress.update(hash_task, total=1)
                    animation_progress.start_task(hash_task)
                    with open(digest_path, 'r') as digest_file:
                        if digest_file.read() == self.digest():
                            animation_progress.update(hash_task, completed=1, total=1)
                            animation_progress.update(anim_task, completed=1, total=1)
                            ffmpeged = True
                            animation_progress.update(hash_task, advance=1)
                finally:
                    self.ticks_per_frame = original_ticks_per_frame

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

            if len(frame_paths) == 1:
                self.ticks_per_frame = duration
            
            # Animation durations must fit in a uint16_t
            if self.ticks_per_frame > 0xffff:
                raise ValueError(f"Animation {name} duration {self.ticks_per_frame} exceeds maximum of 65535")

            for frame_path in frame_paths:
                serialized_path = frame_path.with_suffix('.gqframe')
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
        
        # Frame counts must fit in a uint16_t
        if len(self.frames) > 0xffff:
            raise ValueError(f"Animation {name} has too many frames ({len(self.frames)}); maximum is 65535")
        
        if len(self.frames) == 0:
            raise ValueError(f"Animation {name} has no frames - possible image content or compiler error")
            
    def digest(self) -> int:
        # An Animation object is uniquely identified by a hash of the source file,
        #  its frame rate, size, and its dithering configuration.

        # Get a SHA-256 hash of self.source's contents
        with open(self.src_path, 'rb') as file:
            contents = file.read()
            sha256_hash = hashlib.sha256(contents)
        sha256_hash.update(str(self.ticks_per_frame).encode('ascii'))
        sha256_hash.update(self.dithering.encode('ascii'))
        sha256_hash.update(str(self.width).encode('ascii'))
        sha256_hash.update(str(self.height).encode('ascii'))
        from . import __version__
        sha256_hash.update(__version__.encode('ascii'))
        return sha256_hash.hexdigest()
    
    def set_frame_pointer(self, frame_pointer : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.frame_pointer = structs.gq_ptr_apply_ns(namespace, frame_pointer)
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Animation.link_table[self.addr] = self
    
    def size(self):
        return structs.GQ_ANIM_SIZE

    def __repr__(self) -> str:
        return f"Animation('{self.name}', '{self.source}', {100/self.ticks_per_frame}, {repr(self.dithering)}, {self.frame_pointer:#0{10}x})"
    
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

    image_formats = dict(
        IMAGE_FMT_1BPP_COMP_RLE7=0x71,
        # IMAGE_FMT_1BPP_COMP_RLE4=0x41,
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
            IMAGE_FMT_1BPP_COMP_RLE7=self.image_rle7_bytes(),
            # IMAGE_FMT_1BPP_COMP_RLE4=self.image_rle4_bytes(),
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
            # pickle.load() trusts in_path's contents; this is a local
            # build-cache file gqc itself wrote (see serialize(), above), not
            # untrusted input. A poisoned build directory could still use
            # this for arbitrary code execution -- not changing the format
            # here (aligns #46, a separate decision).
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

class Menu:
    menu_table = dict()
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7

    def __init__(self, name : str, options : dict):
        self.name = name
        self.options = options
        self.addr = 0x00000000 # Set at link time

        if len(options) == 0:
            raise ValueError("At least one menu option is required.")

        if len(options) > structs.GQ_MENU_MAX_OPTIONS:
            raise ValueError(f"Menu {name} has too many options ({len(options)}); maximum is {structs.GQ_MENU_MAX_OPTIONS}")

        if name in Menu.menu_table:
            raise ValueError(f"Menu {name} already defined")
        
        for label in options:
            if len(label) > structs.GQ_STR_SIZE-1: # null term
                raise ValueError("Menu label too long.")

        Menu.menu_table[name] = self

    def __repr__(self) -> str:
        return f"Menu({self.name}, {self.options})"

    def size(self):
        size_per_option = structs.GQ_STR_SIZE + structs.GQ_INT_SIZE
        return structs.GQ_INT_SIZE + len(self.options) * size_per_option
    
    def to_bytes(self):
        bytes_out = len(self.options).to_bytes(structs.GQ_INT_SIZE, 'little')

        for label, value in self.options.items():
            bytes_out += label.encode('ascii').ljust(structs.GQ_STR_SIZE, b'\x00')
            # t_gq_int (GQI_MENU_VALUE) is a signed 32-bit int on-cart (see
            # gamequeer.h), so a negative option value must be encoded as
            # signed two's complement -- plain int.to_bytes(..., 'little')
            # defaults to unsigned and raises OverflowError on a negative
            # value (gamequeer#362). Non-negative values keep the unsigned
            # encoding they already had; unlike the persistent-variable
            # section (gamequeer#359 / linker.py's 0xFFFFFFFF padding
            # sentinel), the menu section has no analogous non-negative
            # sentinel that would need to stay unsigned, but the conditional
            # form is kept anyway to match that fix's pattern.
            bytes_out += value.to_bytes(structs.GQ_INT_SIZE, 'little', signed=value < 0)

        return bytes_out
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        Menu.link_table[self.addr] = self

class LightCue:
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7
    cue_table = dict()

    def __init__(self, colors : list[CueColor]):
        self.frames = []
        self.colors = dict()
        self.name = None
        self.addr = 0x00000000 # Set at link time

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
            # Same local-build-cache trust assumption as Frame.deserialize,
            # above (not changing the pickle format here, aligns #46).
            c = pickle.load(file)
        self.frames = c.frames
        self.colors = c.colors

    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        LightCue.link_table[self.addr] = self
    
    def to_bytes(self):
        # Frame count must fit in a uint16_t
        if len(self.frames) > 0xffff:
            print(f"LightCue {self.name} has too many frames ({len(self.frames)}); maximum is 65535", file=sys.stderr)
            exit(1)

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
    ALLOWED_TRANSITIONS = ['none', 'smooth']
    link_table = dict() # OrderedDict not needed to remember order since Python 3.7

    def __init__(self, colors : list[str], duration : int, transition : str = 'none'):
        self.colors = colors
        self.duration = duration
        self.transition = transition
        self.lightcue = None
        self.resolved = False

        if self.transition not in LightCueFrame.ALLOWED_TRANSITIONS:
            raise ValueError(f"Invalid transition {self.transition}; options are {LightCueFrame.ALLOWED_TRANSITIONS}")
        
        # Cue frame durations must fit in a uint16_t
        if self.duration > 0xffff:
            print(f"LightCueFrame has duration {self.duration} which exceeds maximum of 65535", file=sys.stderr)
            exit(1)
    
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
        flags = 0x00
        
        if self.transition == "smooth":
            flags |= structs.LedCueFrameFlags.TRANSITION_SMOOTH

        frame_colors = []
        for color in self.colors:
            frame_colors.append(color.r)
            frame_colors.append(color.g)
            frame_colors.append(color.b)
        frame_struct = structs.GqLedCueFrame(
            self.duration,
            flags,
            *frame_colors
        )
        return struct.pack(structs.GQ_LEDCUE_FRAME_FORMAT, *frame_struct)
    
    def size(self):
        return structs.GQ_LEDCUE_FRAME_SIZE

    def __repr__(self):
        return f"LightCueFrame({self.colors}, {self.duration}, {self.transition})"

# --- compile-time constant folding for int expressions (gamequeer#385) ------
# t_gq_int is a signed 32-bit int on-cart (see gamequeer.h), and
# run_arithmetic() (gamequeer/src/bytecode.c) evaluates every arithmetic op
# using plain C semantics on that type -- folding must match that exactly,
# not Python's own operator semantics, which diverge from C for `//`/`%`
# whenever the operands' signs differ.

_T_GQ_INT_MIN = -(2 ** 31)
_T_GQ_INT_MAX = 2 ** 31 - 1


def _fits_t_gq_int(value: int) -> bool:
    return _T_GQ_INT_MIN <= value <= _T_GQ_INT_MAX


def _c_truncating_divmod(a: int, b: int) -> tuple[int, int]:
    """C's truncating `/` and `%` (quotient rounds toward zero, remainder
    takes the sign of the dividend) -- NOT Python's own `//`/`%`, which
    round toward negative infinity instead and disagree with C whenever
    exactly one operand is negative."""
    quotient = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        quotient = -quotient
    remainder = a - quotient * b
    return quotient, remainder


def fold_constant_int_expression(node):
    """Attempt to evaluate an int-expression parse-tree node (a
    `GqcIntOperand`, an already-lowered `IntExpression`, or a raw
    `[operand, op, operand]` / `[op, operand]` token list as produced by
    pyparsing's `infix_notation` -- see `parser.parse_int_expression`) as a
    compile-time constant.

    Returns the folded `t_gq_int` value, or `None` if `node` isn't a pure
    compile-time constant. This is the single entry point both
    `parser.parse_int_expression` (for a whole, e.g. fully-parenthesized,
    expression) and `IntExpression.get_result_symbol` (for a literal-only
    subtree nested inside an otherwise non-constant expression) fold
    through, so future sugar built on top of it (gamequeer#386, #387) has
    one place to hook rather than two.

    Folding declines (returns `None`, falling back to ordinary runtime
    codegen) in every case where computing an answer here could diverge
    from the VM's actual runtime behavior:
      - any operand references a variable or a register, rather than being
        a literal;
      - the operator is `badge_get`, or the node is a `badge_count()` call
        -- both read live badge state, not a constant, regardless of
        whether `badge_get`'s own operand is a literal (`badge_count()`
        never has one);
      - a `/` or `%` whose literal divisor is 0 -- the VM leaves this
        unguarded at runtime (see `run_arithmetic`), so folding it would
        turn a runtime behavior into either a compile-time crash or a
        silently wrong constant;
      - a `<<`/`>>` shift amount outside `[0, 31]`, or a `<<` of a negative
        left-hand value -- both undefined behavior in C, so not something
        gqc should compute a specific answer for at compile time (this
        matches the existing `1<<50` shapes in test_expressions.py, which
        already only assert that compilation succeeds, never a specific
        value);
      - any result that wouldn't fit in `t_gq_int` (signed 32-bit) -- gqc
        does not replicate the target compiler's signed-overflow behavior,
        so an expression that would overflow at runtime is simply left
        unfolded (and still overflows the same way it always did).
    """
    from .commands import CommandArithmetic

    if isinstance(node, IntExpression):
        # Already resolved by an earlier fold attempt (e.g. a parenthesized
        # sub-expression, folded when parser.parse_int_expression built it).
        # If that left it with no emitted commands and a literal result,
        # reuse that result; otherwise it's a real (non-foldable) expression
        # and re-deriving from its raw tokens here would just repeat the
        # same "not foldable" conclusion.
        if not node.commands and node.result_symbol.is_literal:
            return node.result_symbol.value
        return None

    if isinstance(node, GqcIntOperand):
        return node.value if node.is_literal else None

    if isinstance(node, GqcBadgeCountOperand):
        # badge_count() reads live badge state, not a constant -- same
        # reasoning as badge_get below, just with no operand of its own to
        # even consider (gamequeer#387). `node_len not in (2, 3)` a few
        # lines down would decline this anyway (a 0-field namedtuple has
        # `len() == 0`), but that's incidental; this is the intentional,
        # explicit no-fold.
        return None

    # The remaining shape is a raw `[operand, op, operand]` / `[op, operand]`
    # token group -- a plain `list` when built by this module's own
    # left-fold recursion (parser.parse_int_expression), or a pyparsing
    # `ParseResults` when it's a nested (non-outermost) precedence group
    # straight from `infix_notation`. Duck-type on length rather than
    # isinstance-checking both, since ParseResults isn't a `list` subclass.
    if isinstance(node, str):
        return None
    try:
        node_len = len(node)
    except TypeError:
        return None
    if node_len not in (2, 3):
        # Covers bare single-token groups (len 1, handled by the recursive
        # unwrap above one level up) and >3-token same-precedence chains
        # nested inside a non-outermost operator level, which
        # IntExpression.get_result_symbol doesn't support lowering either
        # (a pre-existing limitation, not something gamequeer#385 is
        # responsible for fixing) -- decline to fold rather than guess.
        return None

    if len(node) == 2:
        operator, operand = node
        if operator not in CommandArithmetic.UNARY_OPERATORS or operator == 'badge_get':
            return None
        value = fold_constant_int_expression(operand)
        if value is None:
            return None
        if operator == '!':
            result = int(value == 0)
        elif operator == '-':
            result = -value
        elif operator == '~':
            result = ~value
        else:
            return None
        return result if _fits_t_gq_int(result) else None

    operand0, operator, operand1 = node
    if operator not in CommandArithmetic.OPERATORS:
        return None
    left = fold_constant_int_expression(operand0)
    right = fold_constant_int_expression(operand1)
    if left is None or right is None:
        return None

    if operator in ('/', '%'):
        if right == 0:
            return None
        quotient, remainder = _c_truncating_divmod(left, right)
        result = quotient if operator == '/' else remainder
    elif operator == '+':
        result = left + right
    elif operator == '-':
        result = left - right
    elif operator == '*':
        result = left * right
    elif operator == '==':
        result = int(left == right)
    elif operator == '!=':
        result = int(left != right)
    elif operator == '>':
        result = int(left > right)
    elif operator == '<':
        result = int(left < right)
    elif operator == '>=':
        result = int(left >= right)
    elif operator == '<=':
        result = int(left <= right)
    elif operator == '&&':
        result = int(left != 0 and right != 0)
    elif operator == '||':
        result = int(left != 0 or right != 0)
    elif operator == '&':
        result = left & right
    elif operator == '|':
        result = left | right
    elif operator == '^':
        result = left ^ right
    elif operator == '<<':
        if not (0 <= right <= 31) or left < 0:
            return None
        result = left << right
    elif operator == '>>':
        if not (0 <= right <= 31):
            return None
        result = left >> right
    else:
        return None

    return result if _fits_t_gq_int(result) else None

class IntExpression:
    def __init__(self, expression_toks : list[GqcIntOperand], instring, loc):
        self.expression_toks = expression_toks
        self.instring = instring
        self.loc = loc
        self.resolved = False
        self.result_symbol = None
        self.commands = []
        self.unresolved_symbols = []

        self.used_registers = set()

        if len(self.expression_toks) == 0:
            raise ValueError("Empty expression")
        
        self.result_symbol = self.get_result_symbol(self.expression_toks)

        # If the result is in a register, we need to free it.
        if self.result_symbol.value in structs.GQ_REGISTERS_INT:
            self.free_register(self.result_symbol.value)

    def alloc_register(self):
        for register_name in structs.GQ_REGISTERS_INT:
            if register_name not in self.used_registers:
                self.used_registers.add(register_name)
                return register_name
        raise ValueError("No free registers available")

    def free_register(self, reg : str):
        self.used_registers.remove(reg)

    def get_result_symbol(self, subexpr : list) -> GqcIntOperand:
        from .commands import CommandSetInt, CommandArithmetic, unregister_orphaned_commands

        if isinstance(subexpr, IntExpression):
            # About to discard subexpr's own pre-built commands and
            # re-derive its subtree from raw tokens under *this*
            # expression's own register pool instead (see
            # unregister_orphaned_commands's docstring for why that's the
            # only safe way to combine two independently-allocated
            # register pools, and why the discard needs this cleanup step
            # -- gamequeer#387).
            unregister_orphaned_commands(subexpr.commands)
            subexpr = subexpr.expression_toks

        if isinstance(subexpr, GqcBadgeCountOperand):
            # A badge_count() leaf reached directly, e.g. as one operand of
            # a binary op ("badge_count() + 1" hands this get_result_symbol
            # call subexpr[0] bare, not wrapped in a list) -- gamequeer#387.
            return self._emit_badge_count()

        if isinstance(subexpr, GqcIntOperand):
            return subexpr
        elif len(subexpr) == 1:
            # subexpr[0] may itself be a bare GqcBadgeCountOperand -- e.g.
            # the sole atom of "x = badge_count();", which
            # parser.parse_int_expression wraps as
            # IntExpression([GqcBadgeCountOperand()], ...). Recurse instead
            # of handing it back unresolved; every other len-1 shape here is
            # already a GqcIntOperand (or an IntExpression to unwrap), so
            # this recursion is a no-op passthrough for them.
            return self.get_result_symbol(subexpr[0])
        elif len(subexpr) > 3:
            raise ValueError(f"Invalid subexpression length {len(subexpr)}: should be [operand, operator, operand] or [operator operand]")

        # A literal-only subtree (e.g. the "2*3" in "2*3+x") -- fold it to a
        # single literal instead of allocating a register and emitting real
        # arithmetic ops for it. Nested precedence groups like this one
        # never pass back through parser.parse_int_expression's own fold
        # attempt (only a fully-parenthesized -- or the outermost -- group
        # does), so this is the only place that sees them.
        folded = fold_constant_int_expression(subexpr)
        if folded is not None:
            return GqcIntOperand(is_literal=True, value=folded)

        if len(subexpr) == 2:
            # Unary operation.
            operand0 = GqcIntOperand(is_literal=False, value=self.alloc_register())
            operand1 = self.get_result_symbol(subexpr[1])
            operator = subexpr[0]
        else: # len(subexpr) == 3
            operand0 = self.get_result_symbol(subexpr[0])
            operand1 = self.get_result_symbol(subexpr[2])
            operator = subexpr[1]
        
        # If the left operand is not a register, we need to load it into one.
        if operand0.is_literal or operand0.value not in structs.GQ_REGISTERS_INT:
            reg0 = self.alloc_register()
            self.commands.append(CommandSetInt(None, None, reg0, operand0))
            operand0 = GqcIntOperand(is_literal=False, value=reg0)

        # The right operand does not need to be loaded into a register, because our commands
        #  don't require it, it's not in danger of being overwritten (like the left operand),
        #  and there's no performance benefit to "registers" in the Gamequeer badge.
        # However, if the right operand is a register (meaning it was likely the result of an
        #  operation previously generated by this function), we need to free it for later use.
        if not operand1.is_literal and operand1.value in structs.GQ_REGISTERS_INT:
            self.free_register(operand1.value)

        # Now, we can generate the operation command.
        
        # Select the opcode based on the operator token
        operator_lookup_by_cardinality = {
            2: CommandArithmetic.UNARY_OPERATORS,
            3: CommandArithmetic.OPERATORS
        }[len(subexpr)]
        if operator in operator_lookup_by_cardinality:
            opcode = operator_lookup_by_cardinality[operator]
        else:
            raise ValueError(f"Invalid operator {operator}")
        
        # Generate the command itself
        self.commands.append(CommandArithmetic(opcode, self.instring, self.loc, operand0, operand1))

        # All GQ arithmetic commands are actually accumulators, so the result is always stored in the left operand.
        #  So, we can return the left operand as the result of this subexpression.
        return operand0

    def _emit_badge_count(self) -> GqcIntOperand:
        """Lower a `badge_count()` leaf (gamequeer#387) to a runtime
        popcount loop over the *existing* `badge_get` opcode (`QCGET`) --
        the FROZEN VM CONTRACT rules out both a new dedicated opcode and a
        new register. The alternative would be to unroll `BADGES_ALLOWED`
        (320) `QCGET`+`ADDBY` pairs inline; that's ~3x fewer *runtime* ops
        per call (no per-iteration `GOTOIFN`/`GOTO` overhead: ~642 for an
        unrolled sequence vs. ~1924 for this loop -- 2 init ops, then 320
        iterations of a 6-op `GOTOIFN`+3-op-body+`GOTO`x2 truthy pass, plus
        one final falsy pass) but ~70x more *bytecode* (320 * 2 = 640 ops
        vs. this loop's fixed 9, regardless of `BADGES_ALLOWED`) for every
        call site -- a bad trade for something meant to be sugar. The issue
        (gamequeer#387) also specifies the loop form directly ("the
        hand-rolled loop-over-badge_get(i) bytecode").

        Counts the loop variable *down* from `BADGES_ALLOWED` to 0, so the
        continue-test is a bare truthiness check on the counter register
        itself (`CommandIf` with that register as its own condition) --
        not a `>=`/`>` comparison, which would need yet another register:
        every `CommandArithmetic` op (comparisons included) overwrites its
        own destination, so comparing the counter directly against a bound
        would clobber it.

        Register cost: allocates 3 of gqc's 4 `GQ_REGISTERS_INT` for the
        duration of the loop (accumulator, counter, per-iteration
        `badge_get` result); only the accumulator survives past this method
        as the returned result. An enclosing expression that evaluates a
        second `badge_count()` -- or otherwise needs 2+ registers -- while
        the first's accumulator is still live can exhaust the register file
        (`No free registers available`, the same pre-existing diagnostic
        `test_register_allocation_depth_5_exhausts_registers` covers for
        deeply nested arithmetic). See docs/authoring-and-perf-carts.md.
        """
        from .commands import CommandSetInt, CommandArithmetic, CommandIf, CommandGoto, CommandLoop

        acc_reg = self.alloc_register()
        idx_reg = self.alloc_register()
        acc_operand = GqcIntOperand(is_literal=False, value=acc_reg)
        idx_operand = GqcIntOperand(is_literal=False, value=idx_reg)

        self.commands.append(CommandSetInt(self.instring, self.loc, acc_reg, GqcIntOperand(is_literal=True, value=0)))
        self.commands.append(CommandSetInt(self.instring, self.loc, idx_reg, GqcIntOperand(is_literal=True, value=structs.BADGES_ALLOWED)))

        bit_reg = self.alloc_register()
        bit_operand = GqcIntOperand(is_literal=False, value=bit_reg)

        # while (idx) { idx -= 1; bit = badge_get(idx); acc += bit; }
        # -- idx is decremented *before* use, so it visits BADGES_ALLOWED-1
        # down to 0 inclusive (BADGES_ALLOWED distinct badge indices), never
        # BADGES_ALLOWED itself (which get_badge_bit() would reject as
        # out-of-range and return 0 for anyway -- see gamequeer.c -- but
        # this keeps the index space exactly [0, BADGES_ALLOWED) with no
        # reliance on that guard).
        decrement_and_accumulate = [
            CommandArithmetic(structs.OpCode.SUBBY, self.instring, self.loc, idx_operand, GqcIntOperand(is_literal=True, value=1)),
            CommandArithmetic(structs.OpCode.QCGET, self.instring, self.loc, bit_operand, idx_operand),
            CommandArithmetic(structs.OpCode.ADDBY, self.instring, self.loc, acc_operand, bit_operand),
        ]
        guarded_body = [
            CommandIf(
                self.instring, self.loc, idx_operand,
                decrement_and_accumulate,
                [CommandGoto(self.instring, self.loc, form='break')],
            )
        ]
        self.commands.append(CommandLoop(self.instring, self.loc, guarded_body))

        # idx/bit are pure loop scratch, done for good once the loop is
        # built; acc is this method's result and stays allocated, exactly
        # like a unary op's freshly-allocated destination register does at
        # this same point in the len(subexpr) == 2 branch above.
        self.free_register(bit_reg)
        self.free_register(idx_reg)

        return acc_operand

    def resolve(self):
        if self.resolved:
            return True
        
        resolved = True

        for command in self.commands:
            if not command.resolve():
                resolved = False
                self.unresolved_symbols += command.unresolved_symbols
                break

        self.resolved = resolved
        return resolved
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        addr_offset = 0
        for cmd in self.commands:
            cmd.set_addr(addr + addr_offset, namespace)
            addr_offset += cmd.size()

    def size(self):
        return sum(command.size() for command in self.commands)

    def __repr__(self) -> str:
        if not self.resolved:
            return f"IntExpression({self.expression_toks})"
        else:
            return ' '.join(map(repr, self.commands))

class StrExpression:
    def __init__(self, expression_toks : list[str], instring, loc):
        self.expression_toks = expression_toks
        self.instring = instring
        self.loc = loc
        self.resolved = False
        self.result_symbol = None
        self.commands = []
        self.unresolved_symbols = []
        
        self.used_registers = set()

        if len(self.expression_toks) == 0:
            raise ValueError("Empty expression")
        
        self.result_symbol = self.get_result_symbol(self.expression_toks)

        if self.result_symbol in structs.GQ_REGISTERS_STR:
            self.free_register(self.result_symbol)
        
    def alloc_register(self) -> str:
        for register_name in structs.GQ_REGISTERS_STR:
            if register_name not in self.used_registers:
                self.used_registers.add(register_name)
                return register_name
        raise ValueError("No free registers available")

    def free_register(self, reg : str):
        self.used_registers.remove(reg)

    def get_result_symbol(self, subexpr : list) -> str:
        from .commands import CommandSetStr, CommandStrModify, CommandCastStr

        if isinstance(subexpr, StrExpression):
            subexpr = subexpr.expression_toks

        if isinstance(subexpr, GqcStrCastOperand):
            # An inline `str(x)` operand (gamequeer#386): there's no existing
            # variable to just reference, so cast into a fresh string
            # register -- same register pool, same free-after-use lifecycle
            # as loading any other operand into a register below.
            reg = self.alloc_register()
            self.commands.append(CommandCastStr(self.instring, self.loc, reg, subexpr.int_expr))
            return reg

        if isinstance(subexpr, str):
            return subexpr
        elif len(subexpr) != 3:
            raise ValueError(f"Invalid subexpression length {len(subexpr)}: should be [operand, operator, operand]")
        
        # len(subexpr) == 3 past here.
        operand0 = self.get_result_symbol(subexpr[0])
        operand1 = self.get_result_symbol(subexpr[2])
        operator = subexpr[1]

        # If the left operand is not a register, we need to load it into one.
        if operand0 not in structs.GQ_REGISTERS_STR:
            reg0 = self.alloc_register()
            self.commands.append(CommandSetStr(None, None, reg0, operand0))
            operand0 = reg0
        
        # The right operand does not need to be loaded into a register, because our commands
        #  don't require it, it's not in danger of being overwritten (like the left operand),
        #  and there's no performance benefit to "registers" in Gamequeer.
        # However, if the right operand is a register (meaning it was likely the result of an
        #  operation previously generated by this function), we need to free it for later use.
        if operand1 in structs.GQ_REGISTERS_STR:
            self.free_register(operand1)

        # Now, we can generate the operation command.
        # Cardinality here is always binary
        if operator in CommandStrModify.OPERATORS:
            opcode = CommandStrModify.OPERATORS[operator]
        else:
            raise ValueError(f"Invalid operator {operator}")
        
        # Generate the command itself
        self.commands.append(CommandStrModify(opcode, self.instring, self.loc, operand0, operand1))

        # All GQ string commands are actually accumulators, so the result is always stored in the left operand.
        #  So, we can return the left operand as the result of this subexpression.
        return operand0
    
    def resolve(self):
        if self.resolved:
            return True
        
        resolved = True

        for command in self.commands:
            if not command.resolve():
                resolved = False
                self.unresolved_symbols += command.unresolved_symbols
                break

        self.resolved = resolved
        return resolved

    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        addr_offset = 0
        for cmd in self.commands:
            cmd.set_addr(addr + addr_offset, namespace)
            addr_offset += cmd.size()

    def size(self):
        return sum(command.size() for command in self.commands)
    
    def __repr__(self) -> str:
        if not self.resolved:
            return f"StrExpression({self.expression_toks})"
        else:
            return ' '.join(map(repr, self.commands))
