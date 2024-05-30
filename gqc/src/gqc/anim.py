import ffmpeg
import pathlib

from rich.progress import Progress

def make_animation(progress: Progress, progress_tasks : list, anim_src_path : pathlib.Path, output_dir : pathlib.Path, dithering : str = 'none', frame_rate : int = 24):
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
    out_files = [
        (output_dir / 'anim.gif', progress_tasks[0]),
        (output_dir / 'frame%04d.bmp', progress_tasks[1])
    ]

    for out_file, task in out_files:
        try:
            progress.start_task(task)
            out.output(str(out_file)).run(overwrite_output=True, quiet=True)
            progress.update(task, completed=1, total=1)
        except ffmpeg._run.Error as e:
            raise ValueError(f"ffmpeg error; Raw output of ffmpeg follows: \n\n{e.stderr.decode()}")
        progress.update(task, advance=1)

def convert_animations(assets_dir : pathlib.Path, build_dir : pathlib.Path):
    pass
