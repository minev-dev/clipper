import pathlib
import logging

import moviepy
import typer
from moviepy.video.fx import Crop

logger = logging.getLogger(__name__)


def run(full_video_path: pathlib.Path, duration: int = 20, offset: int = 0) -> None:
    """Splits video into chunks

    Args:
        full_video_path: Path to full video to split
        duration: Duration of each chunk
        offset: Offset on `x` axis from the center
    """
    output_path = full_video_path.parent / "output_mp4"
    output_path.mkdir(exist_ok=True)

    with moviepy.VideoFileClip(full_video_path) as video:
        current_duration = int(video.duration)

        for start_time in range(0, current_duration, duration):
            if current_duration < duration:
                break

            clip = video.subclipped(
                start_time=start_time, end_time=start_time + duration
            )

            current_duration -= duration
            current_video = output_path / f"{start_time}.mp4"

            if current_video.exists():
                logger.info(f"{current_video!r} already exists")
                continue

            (w, h) = clip.size
            crop_width = h * 9 / 16

            x1, x2 = (w - crop_width) // 2 + offset, (w + crop_width) // 2 + offset
            y1, y2 = 0, h
            cropper = Crop(x1=x1, y1=y1, x2=x2, y2=y2)

            clip = cropper.apply(clip=clip)
            clip = clip.resized((1080, 1920))
            clip = clip.with_fps(30)

            clip.write_videofile(
                current_video,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile="temp-audio.m4a",
                remove_temp=True,
            )

            logger.info("-----------------###-----------------")

    logger.info("Finished")


if __name__ == "__main__":
    typer.run(run)
