import datetime
import os
import pathlib
import string
import subprocess
from typing import Iterable

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

MANIFEST_PROMPT_TEMPLATE = string.Template(
    """
Create the file upload_manifest.jsonl in the current working directory.

Write exactly $num JSON lines, one per provided video path, using each path exactly once and preserving the provided order.

Each line must use this schema:
{"video_path":"<provided video path>","body":{"snippet":{"title":"...","description":"...","tags":["..."],"categoryId":"10","defaultLanguage":"en"},"status":{"privacyStatus":"private","publishAt":"<ISO datetime in PST/PDT>","containsSyntheticMedia":false,"selfDeclaredMadeForKids":false}}}

Requirements:
- Tags should be viral.
- Video should be published $publish_schedule.
- Last video was published at $last_uploaded_video_dt.
- Don't use emoji in texts.
- Do not modify any file other than upload_manifest.jsonl.

Main video title: $main_video_title
Main video description: $main_video_description
Video paths:
$video_paths
"""
)


class ManifestItem(pydantic.BaseModel):
    video_path: str
    body: dict[str, object]


class ManifestSnippet(pydantic.BaseModel):
    title: str
    description: str
    tags: list[str]
    categoryId: str
    defaultLanguage: str


class ManifestStatus(pydantic.BaseModel):
    privacyStatus: str
    publishAt: str
    containsSyntheticMedia: bool
    selfDeclaredMadeForKids: bool


class ManifestBody(pydantic.BaseModel):
    snippet: ManifestSnippet
    status: ManifestStatus


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

    resolved_last_uploaded_video_dt = utils.parse_datetime(last_uploaded_video_dt)
    manifest_path = videos_dir_path / UPLOAD_MANIFEST_PATH
    _create_manifest_with_local_agent(
        videos_dir_path=videos_dir_path,
        manifest_path=manifest_path,
        main_video_title=_read_file_content(path=VIDEO_TITLE_PATH),
        main_video_description=_read_file_content(path=VIDEO_DESCRIPTION_PATH),
        last_uploaded_video_dt=resolved_last_uploaded_video_dt,
        video_paths=video_paths,
    )
    manifest_items = _read_manifest(manifest_path=manifest_path)
    _validate_manifest(manifest_items=manifest_items, video_paths=video_paths)
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


def _create_manifest_with_local_agent(
    videos_dir_path: pathlib.Path,
    manifest_path: pathlib.Path,
    main_video_title: str,
    main_video_description: str,
    last_uploaded_video_dt: datetime.datetime,
    video_paths: list[pathlib.Path],
) -> None:
    prompt = _build_manifest_prompt(
        main_video_title=main_video_title,
        main_video_description=main_video_description,
        last_uploaded_video_dt=last_uploaded_video_dt,
        video_paths=video_paths,
    )
    if manifest_path.exists():
        manifest_path.unlink()

    result = subprocess.run(
        [
            "gemini",
            "--model",
            MODEL_NAME,
            "--approval-mode",
            "auto_edit",
            "-p",
            prompt,
        ],
        capture_output=True,
        check=True,
        cwd=videos_dir_path,
        env=os.environ.copy(),
        text=True,
    )

    if manifest_path.exists():
        return

    raise RuntimeError(
        "Gemini local agent did not create the manifest file. "
        f"stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}"
    )


def _read_manifest(manifest_path: pathlib.Path) -> list[ManifestItem]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as file:
        return [
            ManifestItem.model_validate_json(line)
            for line in file.read().splitlines()
            if line.strip()
        ]


def _validate_manifest(
    manifest_items: list[ManifestItem],
    video_paths: list[pathlib.Path],
) -> None:
    expected_video_paths = [str(video_path) for video_path in video_paths]
    actual_video_paths = [manifest_item.video_path for manifest_item in manifest_items]

    if len(manifest_items) != len(video_paths):
        raise ValueError(
            "Manifest contains an unexpected number of items: "
            f"expected {len(video_paths)}, got {len(manifest_items)}"
        )

    if actual_video_paths != expected_video_paths:
        raise ValueError(
            "Manifest video paths do not match the requested upload order: "
            f"expected {expected_video_paths}, got {actual_video_paths}"
        )

    for manifest_item in manifest_items:
        ManifestBody.model_validate(manifest_item.body)


def _build_manifest_prompt(
    main_video_title: str,
    main_video_description: str,
    last_uploaded_video_dt: datetime.datetime,
    video_paths: Iterable[pathlib.Path],
) -> str:
    normalized_video_paths = [str(video_path) for video_path in video_paths]
    return MANIFEST_PROMPT_TEMPLATE.substitute(
        num=len(normalized_video_paths),
        publish_schedule=PUBLISH_SCHEDULE,
        last_uploaded_video_dt=last_uploaded_video_dt,
        main_video_title=main_video_title,
        main_video_description=main_video_description,
        video_paths="\n".join(normalized_video_paths),
    )


def _read_file_content(path: pathlib.Path) -> str:
    with open(path, "r", encoding="utf-8") as file:
        return file.read()


if __name__ == "__main__":
    app()
