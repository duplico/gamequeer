import ffmpeg
import pathlib

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
