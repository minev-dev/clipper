import pathlib

import moviepy
import typer
from moviepy.video.fx import Crop


def run(full_video_path: pathlib.Path, duration: int = 30) -> None:
    """Splits video into chunks

    Example:

        python src/main.py /path/to/file.mov
    """
    output_path = full_video_path.parent / "output_mp4"
    output_path.mkdir(exist_ok=True)

    with moviepy.VideoFileClip(full_video_path) as video:
        current_duration = int(video.duration)

        for start_time in range(0, current_duration, duration):
            clip = video.subclipped(
                start_time=start_time, end_time=start_time + duration
            )

            current_duration -= duration
            current_video = output_path / f"{start_time}.mp4"

            (w, h) = clip.size
            crop_width = h * 9 / 16

            x1, x2 = (w - crop_width) // 2, (w + crop_width) // 2
            y1, y2 = 0, h
            cropper = Crop(x1=x1, y1=y1, x2=x2, y2=y2)

            clip = cropper.apply(clip=clip)
            clip = clip.resized((1080, 1920))
            clip = clip.with_fps(30)

            clip.write_videofile(current_video, remove_temp=True)

            print("-----------------###-----------------")


if __name__ == "__main__":
    typer.run(run)
