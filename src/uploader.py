import datetime
import os
import pathlib
import string
import subprocess
from typing import Any, Iterable, cast

import pydantic
import tqdm
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
STEP_BAR_FORMAT = (
    "{desc:<10} {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} steps [{elapsed}<{remaining}]"
)
UPLOAD_BAR_FORMAT = (
    "{desc:<18} {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]"
)
MANIFEST_CHUNK_SIZE = 5

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
    body: dict[str, Any]


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
    with _create_step_progress(description="prepare", total=4) as progress:
        progress.set_postfix_str("scan videos", refresh=True)
        video_paths = sorted(
            video_path for video_path in videos_dir_path.iterdir() if video_path.suffix == ".mp4"
        )
        if not video_paths:
            progress.close()
            logger.info(f"No .mp4 files found in {videos_dir_path}")
            return

        progress.update(1)

        progress.set_postfix_str(f"load context ({len(video_paths)} videos)", refresh=True)
        resolved_last_uploaded_video_dt = utils.parse_datetime(last_uploaded_video_dt)
        manifest_path = videos_dir_path / UPLOAD_MANIFEST_PATH
        main_video_title = _read_file_content(path=VIDEO_TITLE_PATH)
        main_video_description = _read_file_content(path=VIDEO_DESCRIPTION_PATH)
        progress.update(1)

        progress.set_postfix_str("generate manifest", refresh=True)
        current_last_uploaded_video_dt = resolved_last_uploaded_video_dt
        for chunk_start in range(0, len(video_paths), MANIFEST_CHUNK_SIZE):
            chunk_manifest_items = _create_manifest_with_local_agent(
                videos_dir_path=videos_dir_path,
                manifest_path=manifest_path,
                main_video_title=main_video_title,
                main_video_description=main_video_description,
                last_uploaded_video_dt=current_last_uploaded_video_dt,
                video_paths=video_paths[
                    chunk_start : chunk_start + MANIFEST_CHUNK_SIZE
                ],
                append=chunk_start > 0,
            )
            current_last_uploaded_video_dt = _get_last_publish_at(
                manifest_items=chunk_manifest_items
            )
        progress.update(1)

        progress.set_postfix_str("validate manifest", refresh=True)
        manifest_items = _read_manifest(manifest_path=manifest_path)
        _validate_manifest(manifest_items=manifest_items, video_paths=video_paths)
        progress.update(1)
        progress.set_postfix_str("done", refresh=True)

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
    youtube = cast(Any, discovery.build("youtube", "v3", credentials=creds))

    uploaded_videos_dir_path = videos_dir_path / "uploaded"
    uploaded_videos_dir_path.mkdir(exist_ok=True)

    overall_progress = _create_step_progress(description="upload", total=len(manifest_items))
    try:
        for manifest_item in manifest_items:
            video_path = pathlib.Path(manifest_item.video_path)
            if not video_path.exists():
                raise FileNotFoundError(f"Manifest references a missing video file: {video_path}")

            overall_progress.set_postfix_str(video_path.name, refresh=True)
            response = _upload_video(
                youtube=youtube,
                video_path=video_path,
                body=manifest_item.body,
            )

            if response["status"]["uploadStatus"] == "uploaded":
                logger.info(f"Uploaded {video_path.stem}")
                video_path.rename(uploaded_videos_dir_path / video_path.name)
                overall_progress.update(1)
            else:
                raise Exception(f"Failed to upload: {response}")

        overall_progress.set_postfix_str("done", refresh=True)
    finally:
        overall_progress.close()


def _upload_video(
    youtube: Any,
    video_path: pathlib.Path,
    body: dict[str, Any],
) -> dict[str, Any]:
    media = http.MediaFileUpload(str(video_path), resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    total_bytes = video_path.stat().st_size
    progress_description = f"{video_path.stem[:18]}"
    with tqdm.tqdm(
        total=total_bytes,
        desc=progress_description,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        dynamic_ncols=True,
        leave=False,
        colour="blue",
        bar_format=UPLOAD_BAR_FORMAT,
    ) as progress:
        if hasattr(request, "next_chunk"):
            response = None
            while response is None:
                status, response = request.next_chunk()
                uploaded_bytes = _get_uploaded_bytes(status=status, total_bytes=total_bytes)
                progress.update(max(0, uploaded_bytes - progress.n))

            progress.update(max(0, total_bytes - progress.n))
            return response

        response = request.execute()
        progress.update(total_bytes)
        return response


def _get_uploaded_bytes(status: object, total_bytes: int) -> int:
    if status is None:
        return 0

    resumable_progress = getattr(status, "resumable_progress", None)
    if resumable_progress is not None:
        return int(resumable_progress)

    progress = getattr(status, "progress", None)
    if callable(progress):
        return int(progress() * total_bytes)

    return 0


def _create_manifest_with_local_agent(
    videos_dir_path: pathlib.Path,
    manifest_path: pathlib.Path,
    main_video_title: str,
    main_video_description: str,
    last_uploaded_video_dt: datetime.datetime,
    video_paths: list[pathlib.Path],
    *,
    append: bool = False,
) -> list[ManifestItem]:
    prompt = _build_manifest_prompt(
        main_video_title=main_video_title,
        main_video_description=main_video_description,
        last_uploaded_video_dt=last_uploaded_video_dt,
        video_paths=video_paths,
    )
    previous_manifest_lines: list[str] = []
    if append and manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as file:
            previous_manifest_lines = [line for line in file.read().splitlines() if line]
        manifest_path.unlink()

    elif manifest_path.exists():
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

    if not manifest_path.exists():
        raise RuntimeError(
            "Gemini local agent did not create the manifest file. "
            f"stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}"
        )

    generated_manifest_items = _read_manifest(manifest_path=manifest_path)
    _validate_manifest(manifest_items=generated_manifest_items, video_paths=video_paths)

    if append and previous_manifest_lines:
        chunk_manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
        merged_manifest_lines = previous_manifest_lines + [
            line for line in chunk_manifest_lines if line
        ]
        manifest_path.write_text(
            "\n".join(merged_manifest_lines) + "\n",
            encoding="utf-8",
        )

    return generated_manifest_items


def _get_last_publish_at(manifest_items: list[ManifestItem]) -> datetime.datetime:
    if not manifest_items:
        raise ValueError("Manifest is empty")

    last_publish_at = manifest_items[-1].body["status"]["publishAt"]
    if not isinstance(last_publish_at, str):
        raise ValueError(f"Manifest publishAt is not a string: {last_publish_at!r}")

    return datetime.datetime.fromisoformat(last_publish_at)



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


def _create_step_progress(description: str, total: int) -> tqdm.tqdm:
    return tqdm.tqdm(
        total=total,
        desc=description,
        unit="step",
        dynamic_ncols=True,
        colour="green",
        bar_format=STEP_BAR_FORMAT,
    )


if __name__ == "__main__":
    app()
