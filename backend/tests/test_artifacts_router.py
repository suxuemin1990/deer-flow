import asyncio
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import FileResponse

import app.gateway.routers.artifacts as artifacts_router

ACTIVE_ARTIFACT_CASES = [
    ("poc.html", "<html><body><script>alert('xss')</script></body></html>"),
    ("page.xhtml", '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>hello</body></html>'),
    ("image.svg", '<svg xmlns="http://www.w3.org/2000/svg"><script>alert("xss")</script></svg>'),
]


def _make_request(query_string: bytes = b"") -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": query_string})


def test_get_artifact_reads_utf8_text_file_on_windows_locale(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    text = "Curly quotes: \u201cutf8\u201d"
    artifact_path.write_text(text, encoding="utf-8")

    original_read_text = Path.read_text

    def read_text_with_gbk_default(self, *args, **kwargs):
        kwargs.setdefault("encoding", "gbk")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text_with_gbk_default)
    monkeypatch.setattr(artifacts_router, "resolve_thread_artifact_path", lambda _thread_id, _path: artifact_path)

    request = _make_request()
    response = asyncio.run(artifacts_router.get_artifact("thread-1", "mnt/user-data/outputs/note.txt", request))

    assert bytes(response.body).decode("utf-8") == text
    assert response.media_type == "text/plain"


@pytest.mark.parametrize(("filename", "content"), ACTIVE_ARTIFACT_CASES)
def test_get_artifact_forces_download_for_active_content(tmp_path, monkeypatch, filename: str, content: str) -> None:
    artifact_path = tmp_path / filename
    artifact_path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "resolve_thread_artifact_path", lambda _thread_id, _path: artifact_path)

    response = asyncio.run(artifacts_router.get_artifact("thread-1", f"mnt/user-data/outputs/{filename}", _make_request()))

    assert isinstance(response, FileResponse)
    assert response.headers.get("content-disposition", "").startswith("attachment;")


@pytest.mark.parametrize(("filename", "content"), ACTIVE_ARTIFACT_CASES)
def test_get_artifact_forces_download_for_active_content_in_skill_archive(tmp_path, monkeypatch, filename: str, content: str) -> None:
    skill_path = tmp_path / "sample.skill"
    with zipfile.ZipFile(skill_path, "w") as zip_ref:
        zip_ref.writestr(filename, content)

    monkeypatch.setattr(artifacts_router, "resolve_thread_artifact_path", lambda _thread_id, _path: skill_path)

    response = asyncio.run(artifacts_router.get_artifact("thread-1", f"mnt/user-data/outputs/sample.skill/{filename}", _make_request()))

    assert response.headers.get("content-disposition", "").startswith("attachment;")
    assert bytes(response.body) == content.encode("utf-8")


def test_get_artifact_download_false_does_not_force_attachment(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "resolve_thread_artifact_path", lambda _thread_id, _path: artifact_path)

    app = FastAPI()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/note.txt?download=false")

    assert response.status_code == 200
    assert response.text == "hello"
    assert "content-disposition" not in response.headers


def test_get_artifact_download_true_forces_attachment_for_skill_archive(tmp_path, monkeypatch) -> None:
    skill_path = tmp_path / "sample.skill"
    with zipfile.ZipFile(skill_path, "w") as zip_ref:
        zip_ref.writestr("notes.txt", "hello")

    monkeypatch.setattr(artifacts_router, "resolve_thread_artifact_path", lambda _thread_id, _path: skill_path)

    app = FastAPI()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/sample.skill/notes.txt?download=true")

    assert response.status_code == 200
    assert response.text == "hello"
    assert response.headers.get("content-disposition", "").startswith("attachment;")


def test_get_artifact_short_url_resolves_under_user_data(tmp_path, monkeypatch) -> None:
    """The new short URL ``.../artifacts/uploads/<file>`` resolves to user-data/uploads/."""
    from app.gateway import path_utils

    user_data = tmp_path / "threads" / "thread-1" / "user-data"
    (user_data / "uploads").mkdir(parents=True)
    artifact_path = user_data / "uploads" / "doc.txt"
    artifact_path.write_text("hello", encoding="utf-8")

    paths_stub = type(
        "P",
        (),
        {"sandbox_user_data_dir": staticmethod(lambda _tid: user_data)},
    )()
    monkeypatch.setattr(path_utils, "get_paths", lambda: paths_stub)

    app = FastAPI()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/uploads/doc.txt")

    assert response.status_code == 200
    assert response.text == "hello"


def test_get_artifact_legacy_mnt_url_still_resolves(tmp_path, monkeypatch) -> None:
    """The legacy URL with ``mnt/user-data/`` prefix keeps working via stripping."""
    from app.gateway import path_utils

    user_data = tmp_path / "threads" / "thread-1" / "user-data"
    (user_data / "outputs").mkdir(parents=True)
    artifact_path = user_data / "outputs" / "report.txt"
    artifact_path.write_text("legacy", encoding="utf-8")

    paths_stub = type(
        "P",
        (),
        {"sandbox_user_data_dir": staticmethod(lambda _tid: user_data)},
    )()
    monkeypatch.setattr(path_utils, "get_paths", lambda: paths_stub)

    app = FastAPI()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get(
            "/api/threads/thread-1/artifacts/mnt/user-data/outputs/report.txt"
        )

    assert response.status_code == 200
    assert response.text == "legacy"


def test_get_artifact_absolute_host_path_url_resolves(tmp_path, monkeypatch) -> None:
    """An absolute host path under user-data (as stored by present_files) must resolve.

    ``present_files`` stores absolute host paths in ``thread.values.artifacts``;
    the frontend concatenates that path onto ``/api/threads/{tid}/artifacts``,
    producing URLs like ``.../artifacts/<host_user_data_dir>/outputs/foo``.
    The router must recognize and serve those.
    """
    from app.gateway import path_utils

    user_data = tmp_path / "threads" / "thread-1" / "user-data"
    (user_data / "outputs").mkdir(parents=True)
    artifact_path = user_data / "outputs" / "hello.txt"
    artifact_path.write_text("hello world", encoding="utf-8")

    paths_stub = type(
        "P",
        (),
        {"sandbox_user_data_dir": staticmethod(lambda _tid: user_data)},
    )()
    monkeypatch.setattr(path_utils, "get_paths", lambda: paths_stub)

    app = FastAPI()
    app.include_router(artifacts_router.router)

    # Frontend URL: base + "/api/threads/{tid}/artifacts" + abs_path (which starts with "/")
    # → "/api/threads/{tid}/artifacts" + "/...host.../outputs/hello.txt"
    abs_url = f"/api/threads/thread-1/artifacts{artifact_path}"
    with TestClient(app) as client:
        response = client.get(abs_url)

    assert response.status_code == 200
    assert response.text == "hello world"


def test_get_artifact_short_url_rejects_traversal(tmp_path, monkeypatch) -> None:
    from app.gateway import path_utils

    user_data = tmp_path / "threads" / "thread-1" / "user-data"
    user_data.mkdir(parents=True)

    paths_stub = type(
        "P",
        (),
        {"sandbox_user_data_dir": staticmethod(lambda _tid: user_data)},
    )()
    monkeypatch.setattr(path_utils, "get_paths", lambda: paths_stub)

    app = FastAPI()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/../../../etc/passwd")

    assert response.status_code in (400, 403, 404)


def test_upload_artifact_url_returns_short_form() -> None:
    from deerflow.uploads.manager import upload_artifact_url

    url = upload_artifact_url("thread-1", "report.pdf")
    assert url == "/api/threads/thread-1/artifacts/uploads/report.pdf"
    assert "/mnt/user-data" not in url


def test_upload_artifact_url_percent_encodes_filename() -> None:
    from deerflow.uploads.manager import upload_artifact_url

    url = upload_artifact_url("thread-1", "my file?name.pdf")
    assert "/api/threads/thread-1/artifacts/uploads/" in url
    assert " " not in url
    assert "?" not in url
