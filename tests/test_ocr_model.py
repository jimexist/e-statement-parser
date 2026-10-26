import hashlib
import time

import pytest
from fastapi.testclient import TestClient

from estatement import web
from estatement.backends import vlm
from estatement.web import create_app


@pytest.fixture
def pinned(monkeypatch):
    files = {"config.json": (hashlib.sha256(b"{}").hexdigest(), 2)}
    monkeypatch.setitem(vlm.PINNED, "test/model", ("0" * 40, files))
    return "test/model"


def test_verify_accepts_pinned_files(tmp_path, pinned):
    (tmp_path / "config.json").write_bytes(b"{}")
    vlm._verify(pinned, tmp_path)


def test_verify_rejects_changed_file(tmp_path, pinned):
    (tmp_path / "config.json").write_bytes(b"{ }")
    with pytest.raises(vlm.ModelIntegrityError):
        vlm._verify(pinned, tmp_path)


def test_verify_reports_missing_file(tmp_path, pinned):
    with pytest.raises(vlm.ModelNotInstalled):
        vlm._verify(pinned, tmp_path)


def test_default_model_is_pinned_to_a_commit():
    revision, files = vlm.PINNED[vlm.DEFAULT_MODEL]
    assert len(revision) == 40 and "model.safetensors" in files
    assert all(len(digest) == 64 for digest, _ in files.values())


def test_download_starts_only_when_asked(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(web, "find_spec", lambda name: object())
    monkeypatch.setattr(vlm, "is_installed", lambda model_id=vlm.DEFAULT_MODEL: bool(calls))
    monkeypatch.setattr(vlm, "download_model", lambda model_id=vlm.DEFAULT_MODEL: calls.append(model_id))
    c = TestClient(create_app(tmp_path / "w.sqlite", token="t"), base_url="http://127.0.0.1")
    status = c.get("/api/ocr-model", headers={"X-Token": "t"}).json()
    assert status["available"] and not status["installed"] and not calls
    assert c.post("/api/ocr-model/download").status_code == 403
    c.post("/api/ocr-model/download", headers={"X-Token": "t"})
    for _ in range(100):
        status = c.get("/api/ocr-model", headers={"X-Token": "t"}).json()
        if status["installed"]:
            break
    assert status["installed"] and calls == [vlm.DEFAULT_MODEL]


def test_ocr_import_waits_for_confirmation(tmp_path, monkeypatch):
    parsed = []
    monkeypatch.setattr(web, "resolve_backend", lambda pdf, backend: "vlm")
    monkeypatch.setattr(vlm, "is_installed", lambda model_id=vlm.DEFAULT_MODEL: True)
    monkeypatch.setattr(web, "parse_pdf", lambda pdf, backend, progress: parsed.append(backend) or 1 / 0)
    c = TestClient(create_app(tmp_path / "w.sqlite", token="t"), base_url="http://127.0.0.1")

    def post(**data):
        files = {"files": ("scan.pdf", b"%PDF-", "application/pdf")}
        c.post("/api/import", headers={"X-Token": "t"}, files=files, data=data)
        for _ in range(600):
            status = c.get("/api/import", headers={"X-Token": "t"}).json()
            if not status["running"]:
                return status["results"][0]
            time.sleep(0.05)
        raise AssertionError("import did not finish")

    first = post()
    assert first["status"] == "needs_confirm" and first["needs_ocr_confirm"] and not parsed
    assert post(confirm_ocr="true")["status"] == "error" and parsed == ["vlm"]
