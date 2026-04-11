import json
import pathlib
import subprocess

from src import uploader


class _FakeInsertRequest:
    def __init__(self, response: dict[str, object]):
        self._response = response

    def execute(self) -> dict[str, object]:
        return self._response


class _FakeVideosResource:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def insert(
        self,
        *,
        part: str,
        body: dict[str, object],
        media_body: object,
    ) -> _FakeInsertRequest:
        self.calls.append(
            {
                "part": part,
                "body": body,
                "media_body": media_body,
            }
        )
        return _FakeInsertRequest({"status": {"uploadStatus": "uploaded"}})


class _FakeYouTube:
    def __init__(self):
        self.videos_resource = _FakeVideosResource()

    def videos(self) -> _FakeVideosResource:
        return self.videos_resource


def _make_short_video(
    title: str,
    description: str,
    tags: list[str],
    publish_at: str,
) -> dict[str, object]:
    return {
        "title": title,
        "description": description,
        "tags": tags,
        "publish_at": publish_at,
    }


def _make_short_videos_response(short_videos: list[dict[str, object]]) -> str:
    return json.dumps({"short_videos": short_videos})


def test_prepare_creates_jsonl_manifest(monkeypatch, tmp_path):
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    (videos_dir / "b.mp4").write_text("video-b", encoding="utf-8")
    (videos_dir / "a.mp4").write_text("video-a", encoding="utf-8")
    (videos_dir / "notes.txt").write_text("ignore-me", encoding="utf-8")

    title_path = tmp_path / "title.txt"
    description_path = tmp_path / "description.txt"
    title_path.write_text("Main title", encoding="utf-8")
    description_path.write_text("Main description", encoding="utf-8")

    monkeypatch.setattr(uploader, "VIDEO_TITLE_PATH", title_path)
    monkeypatch.setattr(uploader, "VIDEO_DESCRIPTION_PATH", description_path)
    monkeypatch.setattr(
        uploader.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=_make_short_videos_response(
                [
                    _make_short_video(
                        title="Alpha title",
                        description="Alpha description",
                        tags=["alpha", "viral"],
                        publish_at="2026-01-01T10:00:00-08:00",
                    ),
                    _make_short_video(
                        title="Bravo title",
                        description="Bravo description",
                        tags=["bravo", "viral"],
                        publish_at="2026-01-01T18:00:00-08:00",
                    ),
                    _make_short_video(
                        title="Spare",
                        description="Spare",
                        tags=["spare"],
                        publish_at="2026-01-01T22:00:00-08:00",
                    ),
                    _make_short_video(
                        title="Spare",
                        description="Spare",
                        tags=["spare"],
                        publish_at="2026-01-02T10:00:00-08:00",
                    ),
                    _make_short_video(
                        title="Spare",
                        description="Spare",
                        tags=["spare"],
                        publish_at="2026-01-02T18:00:00-08:00",
                    ),
                    _make_short_video(
                        title="Spare",
                        description="Spare",
                        tags=["spare"],
                        publish_at="2026-01-02T22:00:00-08:00",
                    ),
                    _make_short_video(
                        title="Spare",
                        description="Spare",
                        tags=["spare"],
                        publish_at="2026-01-03T10:00:00-08:00",
                    ),
                    _make_short_video(
                        title="Spare",
                        description="Spare",
                        tags=["spare"],
                        publish_at="2026-01-03T18:00:00-08:00",
                    ),
                    _make_short_video(
                        title="Spare",
                        description="Spare",
                        tags=["spare"],
                        publish_at="2026-01-03T22:00:00-08:00",
                    ),
                ]
            ),
            stderr="",
        ),
    )

    uploader.prepare(
        videos_dir_path=videos_dir,
        last_uploaded_video_dt="2026-01-01T09:00:00-08:00",
    )

    manifest_path = videos_dir / uploader.UPLOAD_MANIFEST_PATH
    manifest_items = uploader._read_manifest(manifest_path)

    assert [pathlib.Path(item.video_path).name for item in manifest_items] == [
        "a.mp4",
        "b.mp4",
    ]
    assert manifest_items[0].body == {
        "snippet": {
            "title": "Alpha title",
            "description": "Alpha description",
            "tags": ["alpha", "viral"],
            "categoryId": "10",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": "2026-01-01T10:00:00-08:00",
            "containsSyntheticMedia": False,
            "selfDeclaredMadeForKids": False,
        },
    }
    assert manifest_items[1].body == {
        "snippet": {
            "title": "Bravo title",
            "description": "Bravo description",
            "tags": ["bravo", "viral"],
            "categoryId": "10",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": "2026-01-01T18:00:00-08:00",
            "containsSyntheticMedia": False,
            "selfDeclaredMadeForKids": False,
        },
    }
    assert (videos_dir / "a.mp4").exists()
    assert (videos_dir / "b.mp4").exists()
    assert (videos_dir / "notes.txt").exists()


def test_prepare_creates_manifest_for_more_than_nine_videos(monkeypatch, tmp_path):
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    for index in range(11):
        (videos_dir / f"{index:02}.mp4").write_text(f"video-{index}", encoding="utf-8")

    title_path = tmp_path / "title.txt"
    description_path = tmp_path / "description.txt"
    title_path.write_text("Main title", encoding="utf-8")
    description_path.write_text("Main description", encoding="utf-8")

    prompts: list[str] = []
    response = _make_short_videos_response(
        [
            _make_short_video(
                title=f"Title {index}",
                description=f"Description {index}",
                tags=[f"tag-{index}"],
                publish_at=publish_at,
            )
            for index, publish_at in enumerate(
                [
                    "2026-01-01T10:00:00-08:00",
                    "2026-01-01T18:00:00-08:00",
                    "2026-01-01T22:00:00-08:00",
                    "2026-01-02T10:00:00-08:00",
                    "2026-01-02T18:00:00-08:00",
                    "2026-01-02T22:00:00-08:00",
                    "2026-01-03T10:00:00-08:00",
                    "2026-01-03T18:00:00-08:00",
                    "2026-01-03T22:00:00-08:00",
                    "2026-01-04T10:00:00-08:00",
                    "2026-01-04T18:00:00-08:00",
                ],
                start=1,
            )
        ]
    )

    monkeypatch.setattr(uploader, "VIDEO_TITLE_PATH", title_path)
    monkeypatch.setattr(uploader, "VIDEO_DESCRIPTION_PATH", description_path)

    def fake_generate_content(prompt: str) -> str:
        prompts.append(prompt)
        return response

    monkeypatch.setattr(
        uploader,
        "_generate_content_with_local_agent",
        fake_generate_content,
    )

    uploader.prepare(
        videos_dir_path=videos_dir,
        last_uploaded_video_dt="2026-01-01T09:00:00-08:00",
    )

    manifest_items = uploader._read_manifest(videos_dir / uploader.UPLOAD_MANIFEST_PATH)

    assert len(manifest_items) == 11
    assert pathlib.Path(manifest_items[-1].video_path).name == "10.mp4"
    assert manifest_items[-1].body == {
        "snippet": {
            "title": "Title 11",
            "description": "Description 11",
            "tags": ["tag-11"],
            "categoryId": "10",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": "2026-01-04T18:00:00-08:00",
            "containsSyntheticMedia": False,
            "selfDeclaredMadeForKids": False,
        },
    }
    assert len(prompts) == 1
    assert "Prepare 11 YouTube short video descriptions" in prompts[0]
    assert "last video was published at 2026-01-01 09:00:00-08:00" in prompts[0]


def test_upload_uses_manifest_and_moves_videos(monkeypatch, tmp_path):
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    (videos_dir / "a.mp4").write_text("video-a", encoding="utf-8")
    (videos_dir / "b.mp4").write_text("video-b", encoding="utf-8")

    manifest_items = [
        uploader.ManifestItem(
            video_path=str(videos_dir / "a.mp4"),
            body={
                "snippet": {"title": "Alpha"},
                "status": {"publishAt": "2026-01-01T10:00:00-08:00"},
            },
        ),
        uploader.ManifestItem(
            video_path=str(videos_dir / "b.mp4"),
            body={
                "snippet": {"title": "Bravo"},
                "status": {"publishAt": "2026-01-01T18:00:00-08:00"},
            },
        ),
    ]
    manifest_path = videos_dir / uploader.UPLOAD_MANIFEST_PATH
    uploader._write_manifest(manifest_path=manifest_path, manifest_items=manifest_items)

    fake_youtube = _FakeYouTube()
    monkeypatch.setattr(
        uploader.credentials.Credentials,
        "from_authorized_user_file",
        lambda filename: object(),
    )
    monkeypatch.setattr(
        uploader.discovery,
        "build",
        lambda service_name, version, credentials: fake_youtube,
    )
    monkeypatch.setattr(
        uploader.http,
        "MediaFileUpload",
        lambda path, resumable: pathlib.Path(path),
    )

    uploader.upload(videos_dir_path=videos_dir)

    uploaded_dir = videos_dir / "uploaded"
    assert (uploaded_dir / "a.mp4").exists()
    assert (uploaded_dir / "b.mp4").exists()

    upload_calls = fake_youtube.videos_resource.calls
    assert len(upload_calls) == 2
    assert upload_calls[0]["part"] == "snippet,status"
    assert upload_calls[0]["body"] == {
        "snippet": {"title": "Alpha"},
        "status": {"publishAt": "2026-01-01T10:00:00-08:00"},
    }
    assert upload_calls[0]["media_body"] == videos_dir / "a.mp4"


def test_extract_model_text_from_gemini_output_accepts_nested_json():
    text = uploader._extract_model_text_from_gemini_output(
        '{"response":{"content":"{\\"short_videos\\":[]}"}}'
    )

    assert text == '{"short_videos":[]}'


def test_read_manifest_skips_empty_lines(tmp_path):
    manifest_path = tmp_path / "upload_manifest.jsonl"
    manifest_path.write_text(
        '{"video_path":"clip.mp4","body":{"snippet":{},"status":{}}}\n\n',
        encoding="utf-8",
    )

    manifest_items = uploader._read_manifest(manifest_path)

    assert len(manifest_items) == 1
    assert manifest_items[0].video_path == "clip.mp4"
