"""Local web UI (FastAPI). Listens on 127.0.0.1 only.

Every API call must carry the per-launch token (sent as a custom header, which
browsers won't attach cross-origin without a CORS preflight we never grant),
and the Host header must be localhost, which blocks DNS-rebinding attacks.
"""

from __future__ import annotations

import secrets
import tempfile
from importlib import resources
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse

from .pipeline import parse_pdf
from .store import DEFAULT_DB, Store, sha256

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def create_app(db_path: Path = DEFAULT_DB, token: str | None = None) -> FastAPI:
    token = token or secrets.token_urlsafe(24)
    store = Store(db_path)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token

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

    @app.post("/api/import", dependencies=[Depends(auth)])
    async def import_files(files: list[UploadFile] = File(...), backend: str = Form("auto"),
                           allow_unreconciled: bool = Form(False)):
        results = []
        for f in files:
            data = await f.read()
            digest = sha256(data)
            item = {"file": f.filename}
            if store.has(digest):
                results.append(item | {"status": "duplicate"})
                continue
            # Parsers read from a path; the temp copy is deleted immediately.
            with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
                tmp.write(data)
                tmp.flush()
                try:
                    stmt = parse_pdf(Path(tmp.name), backend=backend)
                except Exception as e:  # noqa: BLE001
                    results.append(item | {"status": "error", "error": f"{type(e).__name__}: {e}"})
                    continue
            item |= {
                "bank": stmt.bank, "statement_date": stmt.statement_date.isoformat(),
                "backend": stmt.meta.get("backend"), "reconciled": stmt.ok,
                "transactions": sum(1 for _ in stmt.transactions()),
                "failed_checks": [c.name for c in stmt.checks if not c.ok],
                "warnings": stmt.warnings,
            }
            if stmt.ok or allow_unreconciled:
                _, inserted = store.save(stmt, digest, f.filename)
                item |= {"status": "imported", "inserted": inserted}
            else:
                item |= {"status": "rejected"}
            results.append(item)
        return results

    @app.get("/api/statements", dependencies=[Depends(auth)])
    def statements():
        return store.statements()

    @app.delete("/api/statements/{sid}", dependencies=[Depends(auth)])
    def delete_statement(sid: int):
        store.delete_statement(sid)
        return {"ok": True}

    @app.get("/api/accounts", dependencies=[Depends(auth)])
    def accounts():
        return store.accounts()

    @app.get("/api/transactions", dependencies=[Depends(auth)])
    def transactions(account: str | None = None, start: str | None = None,
                     end: str | None = None, q: str | None = None):
        return store.transactions(account=account, start=start, end=end, q=q)

    @app.get("/api/export.csv", dependencies=[Depends(auth)])
    def export(account: str | None = None, start: str | None = None, end: str | None = None):
        return PlainTextResponse(store.to_csv(account=account, start=start, end=end),
                                 media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="transactions.csv"'})

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
