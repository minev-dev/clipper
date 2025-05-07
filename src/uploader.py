import datetime
import os
import pathlib
from typing import Generator

import openai
import pydantic
import typer
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = typer.Typer()


CLIENT_SECRET_PATH = "client_secret.json"
CREDENTIALS_PATH = "token.json"


class ShortVideo(pydantic.BaseModel):
    title: str
    description: str
    tags: list[str]
    publish_at: str


class Response(pydantic.BaseModel):
    short_videos: list[ShortVideo]


@app.command()
def upload_videos(
    videos_dir_path: pathlib.Path, main_video_title: str, main_video_description: str
) -> None:
    if "OPENAI_API_KEY" not in os.environ:
        raise KeyError("Please set 'OPENAI_API_KEY' env variable")

    creds = Credentials.from_authorized_user_file(CREDENTIALS_PATH)

    youtube = build("youtube", "v3", credentials=creds)

    video_data_gen = _get_short_videos_descriptions(
        main_video_title=main_video_title,
        main_video_description=main_video_description,
    )

    uploaded_videos_dir_path = videos_dir_path / "uploaded"
    uploaded_videos_dir_path.mkdir(exist_ok=True)

    for video_path in list(videos_dir_path.iterdir()):
        if video_path.suffix != ".mp4":
            continue

        media = MediaFileUpload(video_path, resumable=True)

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

        request = (
            youtube.videos()
            .insert(part="snippet,status", body=body, media_body=media)
            .execute()
        )

        if request["status"]["uploadStatus"] == "uploaded":
            print(f"Uploaded {video_data.publish_at} {video_path.stem}")
            video_path.rename(uploaded_videos_dir_path / video_path.name)
        else:
            print(request)
            raise Exception("FAILED")


@app.command()
def generate_credentials() -> None:
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRET_PATH,
        scopes=[
            "https://www.googleapis.com/auth/youtube",
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtubepartner",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        ],
    )
    creds = flow.run_local_server(port=0)
    # Save the credentials for the next run
    with open(CREDENTIALS_PATH, "w") as token:
        token.write(creds.to_json())


def _get_short_videos_descriptions(
    main_video_title: str, main_video_description: str, num: int = 9
) -> Generator[ShortVideo, None, None]:
    client = openai.OpenAI()

    # last_uploaded_video_dt = datetime.datetime(
    #     2025, 2, 9, 23, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-8))
    # )
    last_uploaded_video_dt = datetime.datetime.now()
    publish_schedule = "3 times a day (at 10am, 6pm, 10pm)"

    while True:
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-2024-11-20",
            messages=[
                {
                    "role": "system",
                    "content": f"Prepare {num} YouTube short video descriptions for the provided main video title, description, tags and publish date (ISO format, PST timezone). Tags should be viral. Video should be published {publish_schedule}, last video was published at {last_uploaded_video_dt}. Don't use emoji in texts",
                },
                {
                    "role": "user",
                    "content": f"Main video title: {main_video_title}\nMain video description: {main_video_description}",
                },
            ],
            response_format=Response,
        )
        short_videos = completion.choices[0].message.parsed.short_videos

        assert len(short_videos) == num

        yield from short_videos

        last_uploaded_video_dt += datetime.timedelta(days=3)


if __name__ == "__main__":
    app()
