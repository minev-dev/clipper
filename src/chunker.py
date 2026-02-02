import json
import pathlib
import subprocess
from typing import NamedTuple

import tqdm
import typer

from src import utils

logger = utils.get_logger(__name__)


class VideoMetadata(NamedTuple):
    duration: float
    width: int
    height: int


class CropParams(NamedTuple):
    width: int
    height: int
    x: int
    y: int


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

    metadata = _get_video_metadata(full_video_path)
    video_duration = int(metadata.duration)
    current_duration = video_duration - start_from_s

    crop_params = _calculate_crop_params(metadata, offset)

    logger.info(
        f"Video size: {metadata.width}x{metadata.height}. Crop: {crop_params.width}x{crop_params.height} at ({crop_params.x},{crop_params.y})"
    )

    for start_time in tqdm.tqdm(range(start_from_s, video_duration, duration)):
        if current_duration < duration:
            break

        current_video = output_path / f"{start_time}.mp4"
        _process_chunk(
            full_video_path, current_video, start_time, duration, crop_params
        )

        current_duration -= duration
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


def _get_video_metadata(path: pathlib.Path) -> VideoMetadata:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    duration = float(data["format"]["duration"])

    # Find video stream
    video_stream = next(s for s in data["streams"] if s["codec_type"] == "video")
    width = int(video_stream["width"])
    height = int(video_stream["height"])

    # Handle rotation
    tags = video_stream.get("tags", {})
    rotate = tags.get("rotate")
    if rotate:
        rotation = int(rotate)
        if abs(rotation) in (90, 270):
            width, height = height, width

    return VideoMetadata(duration, width, height)


def _calculate_crop_params(metadata: VideoMetadata, offset: int) -> CropParams:
    """Calculates crop parameters for 9:16 aspect ratio.

    Target is vertical 9:16. We want to crop a 9:16 area from the source.
    The crop height will be the full height of the video.
    The crop width will be calculated based on that height.
    """
    crop_height = metadata.height
    crop_width = int(crop_height * 9 / 16)

    # Center crop + offset
    x = (metadata.width - crop_width) // 2 + offset
    y = 0

    # Ensure x is valid (within bounds)
    if x < 0:
        logger.warning(f"Calculated x offset {x} is < 0, clamping to 0")
        x = 0
    if x + crop_width > metadata.width:
        logger.warning(
            f"Calculated x offset {x} + width {crop_width} > video width {metadata.width}, clamping"
        )
        x = metadata.width - crop_width

    return CropParams(crop_width, crop_height, x, y)


def _process_chunk(
    full_video_path: pathlib.Path,
    current_video: pathlib.Path,
    start_time: int,
    duration: int,
    crop_params: CropParams,
) -> None:
    """Processes a single video chunk using ffmpeg.

    FFmpeg filter:
    1. crop to 9:16 aspect ratio
    2. scale to 1080x1920
    """
    if current_video.exists():
        logger.info(f"{current_video!r} already exists")
        return

    filter_complex = f"crop={crop_params.width}:{crop_params.height}:{crop_params.x}:{crop_params.y},scale=1080:1920"

    cmd = [
        "ffmpeg",
        "-y",  # Overwrite
        "-ss",
        str(start_time),
        "-t",
        str(duration),
        "-i",
        str(full_video_path),
        "-filter:v",
        filter_complex,
        "-r",
        "30",  # fps
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-loglevel",
        "error",
        str(current_video),
    ]

    try:
        subprocess.run(cmd, check=True)
        logger.info(f"Created {current_video.name}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to process chunk starting at {start_time}: {e}")


if __name__ == "__main__":
    typer.run(run)
