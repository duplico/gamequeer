import ffmpeg
import pathlib

from PIL import Image
from PIL.Image import Dither

from rich.progress import Progress

def make_animation_from_video(progress: Progress, anim_src_path : pathlib.Path, output_dir : pathlib.Path, dithering : str = 'none', frame_rate : int = 25, height : int = 128, width : int = 128):
    # Load the source file
    in_file = ffmpeg.input(anim_src_path)

    # Scale the video to make its height or width the specified size
    # TODO: Decide if we want to scale the video to the specified size or crop it
    scaled = in_file.filter('scale', h=height, w=width)
    cropped = scaled
    # Create the palette
    black = ffmpeg.input('color=c=0x000000:r=1:d=1:s=8x16', f='lavfi')
    white = ffmpeg.input('color=c=0xffffff:r=1:d=1:s=8x16', f='lavfi')
    palette = ffmpeg.filter([black, white], 'hstack', 2)
    # Apply dithering
    dithered = ffmpeg.filter([cropped, palette], 'paletteuse', new='false', dither=dithering)
    # Apply the desired framerate
    out = dithered.filter('fps', frame_rate)

    # Write the output - summary gif and frame files
    out_files = [
        (output_dir / 'anim.gif', progress.add_task(f" [dim]-> gif summary", total=1, start=False)),
        (output_dir / 'frame%04d.bmp', progress.add_task(f" [dim]-> bmp frames", total=1, start=False))
    ]

    for out_file, task in out_files:
        try:
            progress.start_task(task)
            out.output(str(out_file)).run(overwrite_output=True, quiet=True)
            progress.update(task, completed=1, total=1)
        except ffmpeg._run.Error as e:
            raise ValueError(f"ffmpeg error; Raw output of ffmpeg follows: \n\n{e.stderr.decode()}")
        progress.update(task, advance=1)

def make_animation_from_image(progress: Progress, anim_src_path : pathlib.Path, output_dir : pathlib.Path, dithering : str = 'none', height : int = 128, width : int = 128):
    # Load the source file
    in_img = Image.open(anim_src_path)

    if dithering == 'none':
        dither_method = Dither.NONE
    elif dithering == 'floyd_steinberg':
        dither_method = Dither.FLOYDSTEINBERG
    else:
        raise ValueError(f"Dithering algorithm {dithering} is not supported for single images.")

    # Scale the image to make its height or width the specified size
    scaled = in_img.resize((width, height))
    # Quantize the image to black and white, using the specified dithering algorithm
    quantized = scaled.convert('1', dither=dither_method)

    # Write the output - summary gif and frame files
    out_files = [
        (output_dir / 'anim.gif', progress.add_task(f" [dim]-> gif summary", total=1, start=False)),
        (output_dir / 'frame0000.bmp', progress.add_task(f" [dim]-> bmp frames", total=1, start=False))
    ]

    for out_file, task in out_files:
        try:
            progress.start_task(task)
            quantized.save(out_file)
            progress.update(task, completed=1, total=1)
        except OSError as e:
            raise ValueError(f"Error writing image; {e}")

def make_animation(progress: Progress, anim_src_path : pathlib.Path, output_dir : pathlib.Path, dithering : str = 'none', frame_rate : int = 25, duration : int = 100, height : int = 128, width : int = 128):
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
    
    # Check whether the source file is a video or an image
    if anim_src_path.suffix in ['.bmp', '.png', '.jpg', '.jpeg']:
        make_animation_from_image(progress, anim_src_path, output_dir, dithering, height, width)
    else:
        make_animation_from_video(progress, anim_src_path, output_dir, dithering, frame_rate, height, width)

    

def convert_animations(assets_dir : pathlib.Path, build_dir : pathlib.Path):
    pass
