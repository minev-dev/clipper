import json
import pathlib
import subprocess
from typing import Any

from src import uploader


class _FakeInsertRequest:
    def __init__(self, response: dict[str, object], chunk_progress: list[int] | None = None):
        self._response = response
        self._chunk_progress = chunk_progress or []
        self.next_chunk_calls = 0

    def execute(self) -> dict[str, object]:
        return self._response

    def next_chunk(self) -> tuple[object | None, dict[str, object] | None]:
        self.next_chunk_calls += 1
        if self._chunk_progress:
            uploaded_bytes = self._chunk_progress.pop(0)
            if self._chunk_progress:
                return _FakeUploadStatus(uploaded_bytes), None
            return _FakeUploadStatus(uploaded_bytes), self._response

        return None, self._response


class _FakeUploadStatus:
    def __init__(self, uploaded_bytes: int):
        self.resumable_progress = uploaded_bytes


class _FakeVideosResource:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def insert(
        self,
        *,
        part: str,
        body: dict[str, object],
        media_body: object,
    ) -> _FakeInsertRequest:
        request = _FakeInsertRequest(
            {"status": {"uploadStatus": "uploaded"}},
            chunk_progress=[3, 7],
        )
        self.calls.append(
            {
                "part": part,
                "body": body,
                "media_body": media_body,
                "request": request,
            }
        )
        return request


class _FakeYouTube:
    def __init__(self):
        self.videos_resource = _FakeVideosResource()

    def videos(self) -> _FakeVideosResource:
        return self.videos_resource


class _FakeProgressBar:
    def __init__(self, total: int):
        self.total = total
        self.n = 0
        self.postfixes: list[str] = []
        self.closed = False

    def __enter__(self) -> "_FakeProgressBar":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def set_postfix_str(self, value: str, refresh: bool = False) -> None:
        del refresh
        self.postfixes.append(value)

    def update(self, value: int) -> None:
        self.n += value


def _make_manifest_item(
    video_path: pathlib.Path,
    title: str,
    description: str,
    tags: list[str],
    publish_at: str,
) -> dict[str, object]:
    return {
        "video_path": str(video_path),
        "body": {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "10",
                "defaultLanguage": "en",
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_at,
                "containsSyntheticMedia": False,
                "selfDeclaredMadeForKids": False,
            },
        },
    }


def _write_manifest(path: pathlib.Path, manifest_items: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(manifest_item) for manifest_item in manifest_items) + "\n",
        encoding="utf-8",
    )


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

    def fake_run(*args, **kwargs):
        assert kwargs["cwd"] == videos_dir
        assert args[0][0] == "codex"
        assert args[0][1] == "exec"
        assert "--model" in args[0]
        assert "gpt-5.4" in args[0]
        assert "--skip-git-repo-check" in args[0]
        _write_manifest(
            videos_dir / uploader.UPLOAD_MANIFEST_PATH,
            [
                _make_manifest_item(
                    video_path=videos_dir / "a.mp4",
                    title="Alpha title",
                    description="Alpha description",
                    tags=["alpha", "viral"],
                    publish_at="2026-01-01T10:00:00-08:00",
                ),
                _make_manifest_item(
                    video_path=videos_dir / "b.mp4",
                    title="Bravo title",
                    description="Bravo description",
                    tags=["bravo", "viral"],
                    publish_at="2026-01-01T18:00:00-08:00",
                ),
            ],
        )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(uploader.subprocess, "run", fake_run)

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
    generated_record_count = [0]
    monkeypatch.setattr(uploader, "VIDEO_TITLE_PATH", title_path)
    monkeypatch.setattr(uploader, "VIDEO_DESCRIPTION_PATH", description_path)

    def _extract_video_paths_from_prompt(prompt: str) -> list[str]:
        marker = "Video paths:\n"
        assert marker in prompt
        return [line.strip() for line in prompt.split(marker, 1)[1].splitlines() if line.strip()]

    publish_times = [
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
    ]

    def fake_run(*args, **kwargs):
        assert kwargs["cwd"] == videos_dir
        prompt = args[0][-1]
        prompts.append(prompt)
        chunk_video_paths = _extract_video_paths_from_prompt(prompt)

        chunk_records = [
            _make_manifest_item(
                video_path=pathlib.Path(video_path),
                title=f"Title {generated_record_count[0] + index}",
                description=f"Description {generated_record_count[0] + index}",
                tags=[f"tag-{generated_record_count[0] + index}"],
                publish_at=publish_times[generated_record_count[0] + index - 1],
            )
            for index, video_path in enumerate(chunk_video_paths, start=1)
        ]
        generated_record_count[0] += len(chunk_video_paths)
        _write_manifest(
            videos_dir / uploader.UPLOAD_MANIFEST_PATH,
            chunk_records,
        )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(uploader.subprocess, "run", fake_run)

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
    assert len(prompts) == 3
    assert all("Create the file upload_manifest.jsonl" in prompt for prompt in prompts)
    assert len(_extract_video_paths_from_prompt(prompts[0])) == 5
    assert len(_extract_video_paths_from_prompt(prompts[1])) == 5
    assert len(_extract_video_paths_from_prompt(prompts[2])) == 1
    assert "Write exactly 5 JSON lines" in prompts[0]
    assert "Write exactly 5 JSON lines" in prompts[1]
    assert "Write exactly 1 JSON lines" in prompts[2]
    assert len(prompts) == 3
    assert all(len(_extract_video_paths_from_prompt(prompt)) <= 5 for prompt in prompts)
    assert "Last video was published at 2026-01-01 09:00:00-08:00" in prompts[0]
    assert "Last video was published at 2026-01-02 18:00:00-08:00" in prompts[1]
    assert "Last video was published at 2026-01-04 10:00:00-08:00" in prompts[2]
    assert str(videos_dir / "10.mp4") in prompts[2]


def test_prepare_tracks_each_manifest_chunk_in_progress(monkeypatch, tmp_path):
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    for index in range(11):
        (videos_dir / f"{index:02}.mp4").write_text(f"video-{index}", encoding="utf-8")

    title_path = tmp_path / "title.txt"
    description_path = tmp_path / "description.txt"
    title_path.write_text("Main title", encoding="utf-8")
    description_path.write_text("Main description", encoding="utf-8")

    monkeypatch.setattr(uploader, "VIDEO_TITLE_PATH", title_path)
    monkeypatch.setattr(uploader, "VIDEO_DESCRIPTION_PATH", description_path)

    fake_progress_bars: list[_FakeProgressBar] = []

    def fake_create_step_progress(description: str, total: int) -> _FakeProgressBar:
        assert description == "prepare"
        progress_bar = _FakeProgressBar(total=total)
        fake_progress_bars.append(progress_bar)
        return progress_bar

    publish_times = [
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
    ]
    generated_record_count = [0]

    def fake_run(*args, **kwargs):
        del args, kwargs
        chunk_size = min(
            uploader.MANIFEST_CHUNK_SIZE,
            11 - generated_record_count[0],
        )
        chunk_records = [
            _make_manifest_item(
                video_path=videos_dir / f"{generated_record_count[0] + index:02}.mp4",
                title=f"Title {generated_record_count[0] + index + 1}",
                description=f"Description {generated_record_count[0] + index + 1}",
                tags=[f"tag-{generated_record_count[0] + index + 1}"],
                publish_at=publish_times[generated_record_count[0] + index],
            )
            for index in range(chunk_size)
        ]
        generated_record_count[0] += chunk_size
        _write_manifest(videos_dir / uploader.UPLOAD_MANIFEST_PATH, chunk_records)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(uploader, "_create_step_progress", fake_create_step_progress)
    monkeypatch.setattr(uploader.subprocess, "run", fake_run)

    uploader.prepare(
        videos_dir_path=videos_dir,
        last_uploaded_video_dt="2026-01-01T09:00:00-08:00",
    )

    assert len(fake_progress_bars) == 1
    progress_bar = fake_progress_bars[0]
    assert progress_bar.total == 6
    assert progress_bar.n == 6
    assert progress_bar.postfixes == [
        "scan videos",
        "load context (11 videos)",
        "generate manifest (1/3)",
        "generate manifest (2/3)",
        "generate manifest (3/3)",
        "validate manifest",
        "done",
    ]


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
    _write_manifest(
        manifest_path,
        [manifest_item.model_dump(mode="json") for manifest_item in manifest_items],
    )

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
    request = upload_calls[0]["request"]
    assert isinstance(request, _FakeInsertRequest)
    assert request.next_chunk_calls == 2


def test_get_uploaded_bytes_falls_back_to_progress_fraction():
    class _ProgressStatus:
        def progress(self) -> float:
            return 0.5

    assert uploader._get_uploaded_bytes(_ProgressStatus(), total_bytes=10) == 5


def test_progress_bar_formats_render_postfix():
    assert "{postfix}" in uploader.STEP_BAR_FORMAT
    assert "{postfix}" in uploader.UPLOAD_BAR_FORMAT


def test_prepare_raises_when_agent_does_not_create_manifest(monkeypatch, tmp_path):
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    (videos_dir / "a.mp4").write_text("video-a", encoding="utf-8")

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
            stdout="done",
            stderr="",
        ),
    )

    try:
        uploader.prepare(videos_dir_path=videos_dir)
    except RuntimeError as error:
        assert "did not create the manifest file" in str(error)
        assert "Codex CLI" in str(error)
    else:
        raise AssertionError("Expected prepare() to fail when the manifest is missing")


def test_read_manifest_skips_empty_lines(tmp_path):
    manifest_path = tmp_path / "upload_manifest.jsonl"
    manifest_path.write_text(
        '{"video_path":"clip.mp4","body":{"snippet":{},"status":{}}}\n\n',
        encoding="utf-8",
    )

    manifest_items = uploader._read_manifest(manifest_path)

    assert len(manifest_items) == 1
    assert manifest_items[0].video_path == "clip.mp4"
