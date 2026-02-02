import datetime
import logging
import os
import pathlib
from typing import Generator

import pydantic
import typer
from google import genai
from google.oauth2 import credentials
from googleapiclient import discovery, http

from src import google_auth, utils

logger = logging.getLogger(__name__)
logger.setLevel(level=logging.INFO)

SHORT_VIDEOS_DIR = utils.DIST_DIR / "video" / "output_mp4"
VIDEO_TITLE_PATH = utils.DIST_DIR / "video" / "title.txt"
VIDEO_DESCRIPTION_PATH = utils.DIST_DIR / "video" / "description.txt"


class ShortVideo(pydantic.BaseModel):
    title: str
    description: str
    tags: list[str]
    publish_at: str


class Response(pydantic.BaseModel):
    short_videos: list[ShortVideo]


def run(
    videos_dir_path: pathlib.Path = SHORT_VIDEOS_DIR,
    last_uploaded_video_dt: str = "now",
) -> None:
    """Uploads short videos from a directory to YouTube.

    Args:
        videos_dir_path: Path to the directory containing .mp4 videos to upload.
        last_uploaded_video_dt: The date and time of the last uploaded video.
            Can be "now" or an ISO formatted date string.
    """
    if "GEMINI_API_KEY" not in os.environ:
        raise Exception("GEMINI_API_KEY is not set")

    creds = credentials.Credentials.from_authorized_user_file(
        filename=google_auth.CREDENTIALS_PATH
    )

    youtube = discovery.build("youtube", "v3", credentials=creds)

    video_data_gen = _get_short_videos_descriptions(
        main_video_title=_read_file_content(path=VIDEO_TITLE_PATH),
        main_video_description=_read_file_content(path=VIDEO_DESCRIPTION_PATH),
        last_uploaded_video_dt_str=last_uploaded_video_dt,
    )

    uploaded_videos_dir_path = videos_dir_path / "uploaded"
    uploaded_videos_dir_path.mkdir(exist_ok=True)

    for video_path in list(videos_dir_path.iterdir()):
        if video_path.suffix != ".mp4":
            continue

        media = http.MediaFileUpload(video_path, resumable=True)

        video_data = next(video_data_gen)

        body = {
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

        response = (
            youtube.videos()
            .insert(part="snippet,status", body=body, media_body=media)
            .execute()
        )

        if response["status"]["uploadStatus"] == "uploaded":
            logger.info(f"Uploaded {video_path.stem} {video_data}")

            video_path.rename(uploaded_videos_dir_path / video_path.name)
        else:
            raise Exception(f"Failed to upload: {response}")


def _get_short_videos_descriptions(
    main_video_title: str,
    main_video_description: str,
    last_uploaded_video_dt_str: str,
    num: int = 9,
) -> Generator[ShortVideo, None, None]:
    last_uploaded_video_dt = utils.parse_datetime(last_uploaded_video_dt_str)

    publish_schedule = "3 times a day (at 10am, 6pm, 10pm)"

    client = genai.Client()

    while True:
        prompt = f"""
            Prepare {num} YouTube short video descriptions for the provided main video title, description, tags and publish date (ISO format, PST timezone).
            Tags should be viral.
            Video should be published {publish_schedule}, last video was published at {last_uploaded_video_dt}.
            Don't use emoji in texts

            Main video title: {main_video_title}
            Main video description: {main_video_description}
        """

        raw_response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": Response.model_json_schema(),
            },
        )
        response = Response.model_validate_json(raw_response.text)

        assert len(response.short_videos) == num

        yield from response.short_videos

        last_uploaded_video_dt += datetime.timedelta(days=3)


def _read_file_content(path: pathlib.Path) -> str:
    with open(path, "r") as file:
        return file.read()


if __name__ == "__main__":
    typer.run(run)
