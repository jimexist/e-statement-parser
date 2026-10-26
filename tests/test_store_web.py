import base64
import csv
import hashlib
import io
import os
import stat
from importlib import resources

from fastapi.testclient import TestClient
from synthetic import demo_statements

from estatement.store import Store
from estatement.web import create_app


def test_store_is_idempotent_and_private(tmp_path):
    db = tmp_path / "x.sqlite"
    store = Store(db)
    a, b = demo_statements()
    _, n1 = store.save(a, "sha-a", "a.pdf")
    _, n2 = store.save(a, "sha-a", "a.pdf")
    store.save(b, "sha-b", "b.pdf")
    assert (n1, n2) == (5, 0)
    assert len(store.transactions()) == 7
    assert stat.S_IMODE(os.stat(db).st_mode) == 0o600


def test_amounts_round_trip_exactly(tmp_path):
    store = Store(tmp_path / "x.sqlite")
    for i, s in enumerate(demo_statements()):
        store.save(s, f"sha{i}")
    rows = {r.description: r for r in store.transactions()}
    assert str(rows["SUPERMARKET DEMO"].amount) == "-82.35"
    assert str(rows["Advice FAST Payment / Receipt | SALARY PAYMENT"].balance) == "6000.00"
    out = list(csv.DictReader(io.StringIO(store.to_csv(account="DBS:deposit:****0001"))))
    assert [r["amount"] for r in out] == ["5000.00", "-2300.00"]


def test_delete_statement_cascades(tmp_path):
    store = Store(tmp_path / "x.sqlite")
    a, _ = demo_statements()
    sid, _ = store.save(a, "sha-a")
    store.delete_statement(sid)
    assert store.transactions() == []


def test_web_requires_token_and_local_host(tmp_path):
    app = create_app(tmp_path / "w.sqlite", token="t0k")
    c = TestClient(app, base_url="http://127.0.0.1")
    assert c.get("/api/transactions").status_code == 403
    assert c.get("/api/transactions", headers={"X-Token": "t0k"}).json() == []
    assert c.get("/", headers={"Host": "attacker.example"}).status_code == 403
    assert "t0k" in c.get("/").text


def test_web_serves_scripts(tmp_path):
    c = TestClient(create_app(tmp_path / "w.sqlite", token="t"), base_url="http://127.0.0.1")
    page = c.get("/").text
    assert 'src="/app.js"' in page and 'src="/alpine.min.js"' in page
    for path, marker in [("/alpine.min.js", "Alpine"), ("/app.js", "estatement-token")]:
        r = c.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
        assert marker in r.text
    assert c.get("/web.js").status_code == 404


def test_web_rejects_non_statement_upload(tmp_path):
    app = create_app(tmp_path / "w.sqlite", token="t")
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.post(
        "/api/import",
        headers={"X-Token": "t"},
        files={"files": ("x.pdf", b"not a pdf", "application/pdf")},
        data={"backend": "textlayer"},
    )
    assert r.status_code == 200
    assert r.json()[0]["status"] == "error"


def test_api_serves_exact_decimal_amounts(tmp_path):
    db = tmp_path / "w.sqlite"
    store = Store(db)
    for i, s in enumerate(demo_statements()):
        store.save(s, f"sha{i}")
    c = TestClient(create_app(db, token="t"), base_url="http://127.0.0.1")
    rows = c.get("/api/transactions", params={"q": "SUPERMARKET"}, headers={"X-Token": "t"}).json()
    assert [r["amount"] for r in rows] == ["-82.35"]
    stmts = c.get("/api/statements", headers={"X-Token": "t"}).json()
    assert {s["bank"]: s["reconciled"] for s in stmts} == {"UOB": True, "DBS": True}


# sha384 of dist/cdn.min.js from the alpinejs@3.14.9 npm tarball (npm integrity
# sha512-gqSOhTEy...), matching jsDelivr's published hash for that file.
ALPINE_SRI = "sha384-9Ax3MmS9AClxJyd5/zafcXXjxmwFhZCdsT6HJoJjarvCaAkJlk5QDzjLJm+Wdx5F"


def test_vendored_alpine_is_unmodified():
    static = resources.files("estatement").joinpath("static")
    digest = hashlib.sha384(static.joinpath("alpine-3.14.9.min.js").read_bytes()).digest()
    assert "sha384-" + base64.b64encode(digest).decode() == ALPINE_SRI
    assert f'integrity="{ALPINE_SRI}"' in static.joinpath("index.html").read_text()
