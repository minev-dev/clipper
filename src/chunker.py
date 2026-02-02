import logging
import pathlib
from typing import cast

import moviepy
import tqdm
import typer
from moviepy import VideoClip
from moviepy.video import fx

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

    start_from_s = _get_start_time(output_path, duration)
    logger.info(f"Starting from {start_from_s}s")

    with moviepy.VideoFileClip(full_video_path) as video:
        video_duration = int(video.duration)
        current_duration = video_duration - start_from_s

        for start_time in tqdm.tqdm(range(start_from_s, video_duration, duration)):
            if current_duration < duration:
                break

            current_video = output_path / f"{start_time}.mp4"

            if current_video.exists():
                logger.info(f"{current_video!r} already exists")
                continue

            clip = video.subclipped(
                start_time=start_time, end_time=start_time + duration
            )

            current_duration -= duration

            (w, h) = clip.size
            crop_width = h * 9 / 16

            x1, x2 = (w - crop_width) // 2 + offset, (w + crop_width) // 2 + offset
            y1, y2 = 0, h
            cropper = fx.Crop(x1=x1, y1=y1, x2=x2, y2=y2)

            clip = cast(VideoClip, cropper.apply(clip=clip))
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


def _get_start_time(output_path: pathlib.Path, duration: int) -> int:
    start_from_s = 0
    existing_files = list(output_path.glob("*.mp4"))
    if existing_files:
        existing_starts = []
        for f in existing_files:
            try:
                val = int(f.stem)
                existing_starts.append(val)
            except ValueError:
                pass

        if existing_starts:
            last_start = max(existing_starts)
            start_from_s = last_start + duration
            logger.info(f"Resuming from {start_from_s}s detected from existing output.")
    return start_from_s


if __name__ == "__main__":
    typer.run(run)
