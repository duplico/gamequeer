import struct
from enum import IntEnum
from pathlib import Path

import ffmpeg
import pathlib

from PIL import Image

from . import structs

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

        print(f"Begin work on animation {name}")

        self.frames = []
        
        make_animation_kwargs = dict()
        if dithering:
            make_animation_kwargs['dithering'] = dithering
        if frame_rate:
            make_animation_kwargs['frame_rate'] = frame_rate

        # TODO: Namespace built animations by game name
        # Reformat the animation source file into the build directory.
        make_animation(
            Path() / 'assets' / 'animations' / source,
            Path() / 'build' / 'assets' / 'animations' / name,
            **make_animation_kwargs
        )

        print(f"Generating binary data", end='', flush=True)
        dot_timer_start = self.frame_rate if self.frame_rate else 25
        dot_timer = dot_timer_start
        # Load each frame into a Frame object
        for frame_path in (Path() / 'build' / 'assets' / 'animations' / name).glob('frame*.bmp'):
            self.frames.append(Frame(path=frame_path))
            if dot_timer == 0:
                print(".", end='', flush=True)
                dot_timer = dot_timer_start
            else:
                dot_timer -= 1
        print("done.")
        print(f"Complete work on animation {name}")
    
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

def make_animation(anim_src_path : pathlib.Path, output_dir : pathlib.Path, dithering : str = 'none', frame_rate : int = 24):
    # Set up the output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    # Delete the old output files: anim.gif and frame*.bmp
    for file in output_dir.glob('anim.gif'):
        file.unlink()
    for file in output_dir.glob('frame*.bmp'):
        file.unlink()

    # Check whether the source file exists and raise a value error if it doesn't
    if not anim_src_path.exists():
        raise ValueError(f"Animation source file {anim_src_path} does not exist")

    # Load the source file
    in_file = ffmpeg.input(anim_src_path)

    # Scale the video to 128x128
    scaled = in_file.filter('scale', h=128, w=-1)
    # Crop the video to 128x128
    cropped = scaled.filter('crop', w=128, h=128)
    # Create the palette
    black = ffmpeg.input('color=c=0x000000:r=1:d=1:s=8x16', f='lavfi')
    white = ffmpeg.input('color=c=0xffffff:r=1:d=1:s=8x16', f='lavfi')
    palette = ffmpeg.filter([black, white], 'hstack', 2)
    # Apply dithering
    dithered = ffmpeg.filter([cropped, palette], 'paletteuse', new='false', dither=dithering)
    # Apply the desired framerate
    out = dithered.filter('fps', frame_rate)

    # Write the output - summary gif and frame files
    out_file_summary = output_dir / 'anim.gif'
    out_file_frames = output_dir / 'frame%04d.bmp'
    
    for out_file in [out_file_summary, out_file_frames]:
        try:
            print(f"Invoking ffmpeg {anim_src_path} -> {out_file}...", end='', flush=True)
            out.output(str(out_file)).run(overwrite_output=True, quiet=True)
            print("done.")
        except ffmpeg._run.Error as e:
            print()
            raise ValueError(f"ffmpeg error; Raw output of ffmpeg follows: \n\n{e.stderr.decode()}")

def convert_animations(assets_dir : pathlib.Path, build_dir : pathlib.Path):
    pass
