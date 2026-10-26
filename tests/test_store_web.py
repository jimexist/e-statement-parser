import csv
import io
import os
import stat

from fastapi.testclient import TestClient

from estatement.store import Store
from estatement.web import create_app

from synthetic import demo_statements


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
    rows = {r["description"]: r for r in store.transactions()}
    assert rows["SUPERMARKET PARKWAY"]["amount"] == "-82.35"
    assert rows["Advice FAST Payment / Receipt | SALARY PAYMENT"]["balance"] == "6000.00"
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
    assert c.get("/api/transactions", headers={"X-Token": "t0k"}).status_code == 200
    assert c.get("/", headers={"Host": "attacker.example"}).status_code == 403
    assert "t0k" in c.get("/").text


def test_web_rejects_non_statement_upload(tmp_path):
    app = create_app(tmp_path / "w.sqlite", token="t")
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.post("/api/import", headers={"X-Token": "t"},
               files={"files": ("x.pdf", b"not a pdf", "application/pdf")}, data={"backend": "textlayer"})
    assert r.status_code == 200
    assert r.json()[0]["status"] == "error"
