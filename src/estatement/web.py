"""Local web UI (FastAPI). Listens on 127.0.0.1 only.

Every API call must carry the per-launch token (sent as a custom header, which
browsers won't attach cross-origin without a CORS preflight we never grant),
and the Host header must be localhost, which blocks DNS-rebinding attacks.
"""

from __future__ import annotations

import secrets
import tempfile
import threading
from importlib import resources
from importlib.util import find_spec
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel

from .backends import vlm
from .pipeline import parse_pdf
from .store import DEFAULT_DB, AccountRow, StatementRow, Store, TransactionRow, sha256

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
SCRIPTS = {"app": "app.js", "alpine.min": "alpine-3.14.9.min.js"}


class ImportResult(BaseModel):
    file: str | None
    status: Literal["imported", "duplicate", "rejected", "error"]
    error: str | None = None
    bank: str | None = None
    statement_date: str | None = None
    backend: str | None = None
    reconciled: bool | None = None
    transactions: int | None = None
    inserted: int | None = None
    failed_checks: list[str] = []
    warnings: list[str] = []
    needs_ocr_model: bool = False


class Deleted(BaseModel):
    ok: bool = True


class OcrModel(BaseModel):
    available: bool  # the OCR runtime is part of this install
    installed: bool
    downloading: bool
    done_bytes: int
    total_bytes: int
    error: str | None = None


class OcrDownload:
    """Fetches the pinned OCR model in the background when the user asks for it.

    This is the only network access the app makes, and only on that click."""

    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.error: str | None = None

    def _run(self) -> None:
        try:
            vlm.download_model()
        except Exception as e:  # noqa: BLE001 - shown in the UI
            self.error = f"{type(e).__name__}: {e}"

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def status(self) -> OcrModel:
        if find_spec("mlx_vlm") is None:
            return OcrModel(available=False, installed=False, downloading=False, done_bytes=0, total_bytes=0)
        from huggingface_hub import constants

        total = vlm.model_size()
        downloading = bool(self.thread and self.thread.is_alive())
        installed = not downloading and vlm.is_installed()
        blobs = Path(constants.HF_HUB_CACHE) / f"models--{vlm.DEFAULT_MODEL.replace('/', '--')}" / "blobs"
        done = sum(f.stat().st_size for f in blobs.iterdir()) if downloading and blobs.is_dir() else 0
        return OcrModel(
            available=True,
            installed=installed,
            downloading=downloading,
            done_bytes=total if installed else min(done, total),
            total_bytes=total,
            error=self.error,
        )


class ImportStatus(BaseModel):
    running: bool
    file_count: int = 0
    file_index: int = 0  # 1-based index of the file being parsed
    file: str | None = None
    backend: str | None = None
    attempt: int | None = None  # OCR pass, when OCR is retried at another resolution
    page: int | None = None
    page_count: int | None = None
    results: list[ImportResult] = []


class ImportJob:
    """Parses uploaded statements on a background thread (OCR can take minutes)
    and keeps a status the UI polls. One import runs at a time."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.thread: threading.Thread | None = None
        self.state = ImportStatus(running=False)

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, uploads: list[tuple[str | None, bytes]], backend: str, allow_unreconciled: bool) -> None:
        self.state = ImportStatus(running=True, file_count=len(uploads))
        self.thread = threading.Thread(
            target=self._run, args=(uploads, backend, allow_unreconciled), daemon=True
        )
        self.thread.start()

    def status(self) -> ImportStatus:
        return self.state.model_copy(update={"running": self.running})

    def _progress(self, **fields) -> None:
        if "attempt" in fields:
            fields.update(page=None, page_count=None)
        self.state = self.state.model_copy(update=fields)

    def _run(self, uploads: list[tuple[str | None, bytes]], backend: str, allow_unreconciled: bool) -> None:
        results = []
        for i in range(len(uploads)):
            # Drop each PDF's bytes as soon as we take it so none outlive the import.
            name, data = uploads[i]
            uploads[i] = (name, b"")
            self.state = ImportStatus(
                running=True, file_count=len(uploads), file_index=i + 1, file=name, results=list(results)
            )
            try:
                item = self._import_one(name, data, backend, allow_unreconciled)
            except Exception as e:  # noqa: BLE001 - reported to the user per file
                item = ImportResult(file=name, status="error", error=f"{type(e).__name__}: {e}")
            results.append(item)
            self.state = self.state.model_copy(update={"results": list(results)})

    def _import_one(
        self, name: str | None, data: bytes, backend: str, allow_unreconciled: bool
    ) -> ImportResult:
        digest = sha256(data)
        if self.store.has(digest):
            return ImportResult(file=name, status="duplicate")
        # Parsers read from a path; the temp copy is deleted immediately.
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(data)
            tmp.flush()
            try:
                stmt = parse_pdf(Path(tmp.name), backend=backend, progress=self._progress)
            except vlm.ModelNotInstalled:
                return ImportResult(
                    file=name,
                    status="error",
                    error="This PDF has no text layer and needs the on-device OCR model.",
                    needs_ocr_model=True,
                )
        item = ImportResult(
            file=name,
            status="rejected",
            bank=stmt.bank,
            statement_date=stmt.statement_date.isoformat(),
            backend=stmt.meta.get("backend"),
            reconciled=stmt.ok,
            transactions=sum(1 for _ in stmt.transactions()),
            failed_checks=[c.name for c in stmt.checks if not c.ok],
            warnings=stmt.warnings,
        )
        if stmt.ok or allow_unreconciled:
            _, item.inserted = self.store.save(stmt, digest, name)
            item.status = "imported"
        return item


def create_app(db_path: Path = DEFAULT_DB, token: str | None = None) -> FastAPI:
    token = token or secrets.token_urlsafe(24)
    store = Store(db_path)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    ocr = OcrDownload()
    job = app.state.job = ImportJob(store)

    @app.middleware("http")
    async def host_guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0]
        if host not in ALLOWED_HOSTS:
            return PlainTextResponse("forbidden host", status_code=403)
        return await call_next(request)

    def auth(request: Request):
        if not secrets.compare_digest(request.headers.get("x-token", ""), token):
            raise HTTPException(403, "bad token")

    @app.get("/", response_class=HTMLResponse)
    def index():
        page = resources.files("estatement").joinpath("static/index.html").read_text()
        return page.replace("__TOKEN__", token)

    # Only the listed scripts are served. Alpine is vendored (pinned, integrity-checked
    # against npm) so the UI works offline.
    @app.get("/{name}.js")
    def script(name: str):
        if (file := SCRIPTS.get(name)) is None:
            raise HTTPException(404)
        js = resources.files("estatement").joinpath(f"static/{file}").read_text()
        return Response(js, media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.post("/api/import", dependencies=[Depends(auth)], response_model=ImportStatus)
    async def import_files(
        files: Annotated[list[UploadFile], File()],
        backend: Annotated[str, Form()] = "auto",
        allow_unreconciled: Annotated[bool, Form()] = False,
    ) -> ImportStatus:
        uploads = [(f.filename, await f.read()) for f in files]
        if job.running:  # checked after the awaits so two uploads can't both start
            raise HTTPException(409, "an import is already running")
        job.start(uploads, backend, allow_unreconciled)
        return job.status()

    # Plain def (runs in the threadpool) so polling works while a parse is running.
    @app.get("/api/import", dependencies=[Depends(auth)], response_model=ImportStatus)
    def import_status() -> ImportStatus:
        return job.status()

    @app.get("/api/ocr-model", dependencies=[Depends(auth)], response_model=OcrModel)
    def ocr_model() -> OcrModel:
        return ocr.status()

    @app.post("/api/ocr-model/download", dependencies=[Depends(auth)], response_model=OcrModel)
    def download_ocr_model() -> OcrModel:
        if not ocr.status().installed:
            ocr.start()
        return ocr.status()

    @app.get("/api/statements", dependencies=[Depends(auth)], response_model=list[StatementRow])
    def statements() -> list[StatementRow]:
        return store.statements()

    @app.delete("/api/statements/{sid}", dependencies=[Depends(auth)], response_model=Deleted)
    def delete_statement(sid: int) -> Deleted:
        store.delete_statement(sid)
        return Deleted()

    @app.get("/api/accounts", dependencies=[Depends(auth)], response_model=list[AccountRow])
    def accounts() -> list[AccountRow]:
        return store.accounts()

    @app.get("/api/transactions", dependencies=[Depends(auth)], response_model=list[TransactionRow])
    def transactions(
        account: str | None = None, start: str | None = None, end: str | None = None, q: str | None = None
    ) -> list[TransactionRow]:
        return store.transactions(account=account, start=start, end=end, q=q)

    @app.get("/api/export.csv", dependencies=[Depends(auth)])
    def export(account: str | None = None, start: str | None = None, end: str | None = None):
        return PlainTextResponse(
            store.to_csv(account=account, start=start, end=end),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="transactions.csv"'},
        )

    return app


def serve(db_path: Path = DEFAULT_DB, port: int = 8765, open_browser: bool = True) -> None:
    import threading
    import webbrowser

    import uvicorn

    app = create_app(db_path)
    url = f"http://127.0.0.1:{port}/"
    print(f"eStatement running at {url} (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
