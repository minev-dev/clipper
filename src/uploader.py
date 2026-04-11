import datetime
import json
import os
import pathlib
import string
import subprocess
from typing import Generator, cast

import pydantic
import typer
from google.oauth2 import credentials
from googleapiclient import discovery, http

from src import google_auth, utils

logger = utils.get_logger(__name__)

SHORT_VIDEOS_DIR = utils.DIST_DIR / "video" / "output_mp4"
VIDEO_TITLE_PATH = utils.DIST_DIR / "video" / "title.txt"
VIDEO_DESCRIPTION_PATH = utils.DIST_DIR / "video" / "description.txt"
UPLOAD_MANIFEST_PATH = "upload_manifest.jsonl"

PUBLISH_SCHEDULE = "3 times a day (at 10am, 6pm, 10pm)"
MODEL_NAME = "gemini-3.1-pro-preview"

PROMPT_TEMPLATE = string.Template(
    """
Prepare $num YouTube short video descriptions for the provided main video title, description, tags and publish date (ISO format, PST timezone).
Tags should be viral.
Video should be published $publish_schedule, last video was published at $last_uploaded_video_dt.
Don't use emoji in texts

Main video title: $main_video_title
Main video description: $main_video_description
"""
)


class ShortVideo(pydantic.BaseModel):
    title: str
    description: str
    tags: list[str]
    publish_at: str


class Response(pydantic.BaseModel):
    short_videos: list[ShortVideo]


class ManifestItem(pydantic.BaseModel):
    video_path: str
    body: dict[str, object]


app = typer.Typer()


@app.command()
def prepare(
    videos_dir_path: pathlib.Path = SHORT_VIDEOS_DIR,
    last_uploaded_video_dt: str = "now",
) -> None:
    """Creates a JSONL upload manifest for short videos in a directory.

    Args:
        videos_dir_path: Path to the directory containing .mp4 videos to upload.
        last_uploaded_video_dt: The date and time of the last uploaded video.
            Can be "now" or an ISO formatted date string.
    """
    video_paths = sorted(
        video_path for video_path in videos_dir_path.iterdir() if video_path.suffix == ".mp4"
    )
    if not video_paths:
        logger.info(f"No .mp4 files found in {videos_dir_path}")
        return

    manifest_items = _build_manifest(
        main_video_title=_read_file_content(path=VIDEO_TITLE_PATH),
        main_video_description=_read_file_content(path=VIDEO_DESCRIPTION_PATH),
        last_uploaded_video_dt_str=last_uploaded_video_dt,
        video_paths=video_paths,
    )
    manifest_path = videos_dir_path / UPLOAD_MANIFEST_PATH
    _write_manifest(manifest_path=manifest_path, manifest_items=manifest_items)
    logger.info(f"Created manifest: {manifest_path}")


@app.command()
def upload(
    videos_dir_path: pathlib.Path = SHORT_VIDEOS_DIR,
    manifest_path: pathlib.Path | None = None,
) -> None:
    """Uploads short videos to YouTube using a prebuilt manifest.

    Args:
        videos_dir_path: Path to the directory containing the source videos.
        manifest_path: Path to the JSONL manifest file. Defaults to the manifest
            inside ``videos_dir_path``.
    """
    resolved_manifest_path = manifest_path or (videos_dir_path / UPLOAD_MANIFEST_PATH)
    manifest_items = _read_manifest(manifest_path=resolved_manifest_path)
    if not manifest_items:
        logger.info(f"No manifest items found in {resolved_manifest_path}")
        return

    creds = credentials.Credentials.from_authorized_user_file(
        filename=google_auth.CREDENTIALS_PATH
    )
    youtube = discovery.build("youtube", "v3", credentials=creds)

    uploaded_videos_dir_path = videos_dir_path / "uploaded"
    uploaded_videos_dir_path.mkdir(exist_ok=True)

    for manifest_item in manifest_items:
        video_path = pathlib.Path(manifest_item.video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Manifest references a missing video file: {video_path}")

        media = http.MediaFileUpload(video_path, resumable=True)

        response = (
            youtube.videos()
            .insert(part="snippet,status", body=manifest_item.body, media_body=media)
            .execute()
        )

        if response["status"]["uploadStatus"] == "uploaded":
            logger.info(f"Uploaded {video_path.stem}")
            video_path.rename(uploaded_videos_dir_path / video_path.name)
        else:
            raise Exception(f"Failed to upload: {response}")


def _build_manifest(
    main_video_title: str,
    main_video_description: str,
    last_uploaded_video_dt_str: str,
    video_paths: list[pathlib.Path],
) -> list[ManifestItem]:
    video_count = len(video_paths)
    manifest_items: list[ManifestItem] = []
    video_data_gen = _get_short_videos_descriptions(
        main_video_title=main_video_title,
        main_video_description=main_video_description,
        last_uploaded_video_dt_str=last_uploaded_video_dt_str,
        num=video_count,
    )

    for video_path in video_paths:
        short_video = next(video_data_gen)
        manifest_items.append(
            ManifestItem(
                video_path=str(video_path),
                body=_create_video_body(short_video),
            )
        )
    return manifest_items


def _create_video_body(video_data: ShortVideo) -> dict[str, object]:
    return {
        "snippet": {
            "title": video_data.title,
            "description": video_data.description,
            "tags": video_data.tags,
            "categoryId": "10",  # Music (https://gist.github.com/dgp/1b24bf2961521bd75d6c)
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": video_data.publish_at,
            "containsSyntheticMedia": False,
            "selfDeclaredMadeForKids": False,
        },
    }


def _write_manifest(
    manifest_path: pathlib.Path,
    manifest_items: list[ManifestItem],
) -> None:
    with open(manifest_path, "w", encoding="utf-8") as file:
        for manifest_item in manifest_items:
            file.write(manifest_item.model_dump_json())
            file.write("\n")


def _read_manifest(manifest_path: pathlib.Path) -> list[ManifestItem]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as file:
        return [
            ManifestItem.model_validate_json(line)
            for line in file.read().splitlines()
            if line.strip()
        ]


def _get_short_videos_descriptions(
    main_video_title: str,
    main_video_description: str,
    last_uploaded_video_dt_str: str,
    num: int,
) -> Generator[ShortVideo, None, None]:
    last_uploaded_video_dt = utils.parse_datetime(last_uploaded_video_dt_str)
    if num <= 0:
        return

    yield from _generate_short_videos(
        main_video_title=main_video_title,
        main_video_description=main_video_description,
        last_uploaded_video_dt=last_uploaded_video_dt,
        num=num,
    )


def _generate_short_videos(
    main_video_title: str,
    main_video_description: str,
    last_uploaded_video_dt: datetime.datetime,
    num: int,
) -> list[ShortVideo]:
    prompt = PROMPT_TEMPLATE.substitute(
        num=num,
        publish_schedule=PUBLISH_SCHEDULE,
        last_uploaded_video_dt=last_uploaded_video_dt,
        main_video_title=main_video_title,
        main_video_description=main_video_description,
    )

    raw_response = _generate_content_with_local_agent(prompt)
    response = Response.model_validate_json(raw_response)

    if len(response.short_videos) < num:
        raise ValueError(
            "Gemini local agent returned fewer short video descriptions than requested"
        )

    return response.short_videos[:num]


def _generate_content_with_local_agent(prompt: str) -> str:
    result = subprocess.run(
        [
            "gemini",
            "--model",
            MODEL_NAME,
            "--output-format",
            "json",
            "-p",
            prompt,
        ],
        capture_output=True,
        check=True,
        env=os.environ.copy(),
        text=True,
    )

    if not result.stdout.strip():
        raise ValueError("Gemini local agent returned no output")

    return _extract_model_text_from_gemini_output(result.stdout)


def _extract_model_text_from_gemini_output(raw_output: str) -> str:
    parsed_output = json.loads(raw_output)
    if isinstance(parsed_output, dict) and "short_videos" in parsed_output:
        return raw_output

    output_text = _find_text_in_response(parsed_output)
    if output_text is None:
        if isinstance(parsed_output, dict) and "error" in parsed_output:
            raise RuntimeError(f"Gemini local agent error: {parsed_output['error']}")
        raise ValueError("Unable to parse text response from local gemini agent")

    if not _is_json(output_text):
        raise ValueError(
            "Gemini local agent output is not valid JSON for the expected schema"
        )
    return output_text


def _find_text_in_response(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None

    if isinstance(value, list):
        for item in reversed(value):
            text = _find_text_in_response(item)
            if text is not None:
                return text
        return None

    if isinstance(value, dict):
        response = cast(dict[str, object], value)

        if "text" in response:
            output_text = _find_text_in_response(response["text"])
            if output_text is not None:
                return output_text

        if "content" in response:
            output_text = _find_text_in_response(response["content"])
            if output_text is not None:
                return output_text

        if "output" in response:
            return _find_text_in_response(response["output"])

        for nested_value in response.values():
            output_text = _find_text_in_response(nested_value)
            if output_text is not None:
                return output_text

        return None

    return None


def _is_json(value: str) -> bool:
    try:
        json.loads(value)
        return True
    except json.JSONDecodeError:
        return False


def _read_file_content(path: pathlib.Path) -> str:
    with open(path, "r", encoding="utf-8") as file:
        return file.read()


if __name__ == "__main__":
    app()
