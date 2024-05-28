from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

import ffmpeg
import pathlib

from PIL import Image

# TODO: Set up globals or a singleton or something containing the base path etc.

class FrameEncoding(IntEnum):
    UNCOMPRESSED = 0x01
    RLE4 = 0x41
    RLE7 = 0x71

class Animation:
    anim_table = {}
    link_table = None
    
    # TODO: move DITHER_CHOICES to an enum?
    def __init__(self, name : str, source : str, dithering : str = None, frame_rate : int = None):
        self.name = name
        self.source = source
        self.frame_rate = frame_rate
        self.dithering = dithering

        if name in Animation.anim_table:
            raise ValueError("Animation {} already defined".format(name))
        Animation.anim_table[name] = self

        self.frames = []
        
        make_animation_kwargs = dict()
        if dithering:
            make_animation_kwargs['dithering'] = dithering
        if frame_rate:
            make_animation_kwargs['frame_rate'] = frame_rate

        # Reformat the animation source file into the build directory.
        make_animation(
            Path() / 'assets' / 'animations' / source,
            Path() / 'build' / 'assets' / 'animations' / name,
            **make_animation_kwargs
        )

        # Load each frame into a GqImage object
        for frame_path in (Path() / 'build' / 'assets' / 'animations' / name).glob('frame*.bmp'):
            self.frames.append(GqImage(path=frame_path))
    
    def __repr__(self) -> str:
        return f"Animation('{self.name}', '{self.source}', {repr(self.frame_rate)}, {repr(self.dithering)})"

class GqImage(object):
    def __init__(self, img : Image = None, path : pathlib.Path = None):
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

def make_animation(anim_src_path : pathlib.Path, output_dir : pathlib.Path, dither : str = 'none', framerate : int = 24):
    # Set up the output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    # Delete the old output files: anim.gif and frame*.bmp
    for file in output_dir.glob('anim.gif'):
        file.unlink()
    for file in output_dir.glob('frame*.bmp'):
        file.unlink()

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
    dithered = ffmpeg.filter([cropped, palette], 'paletteuse', new='false', dither=dither)
    # Apply the desired framerate
    out = dithered.filter('fps', framerate)

    # Write the output - summary gif
    out_file = output_dir / 'anim.gif'
    out.output(str(out_file)).run(overwrite_output=True)

    # Write the output - frame files
    out_file = output_dir / 'frame%04d.bmp'
    out.output(str(out_file)).run(overwrite_output=True)

def convert_animations(assets_dir : pathlib.Path, build_dir : pathlib.Path):
    pass
