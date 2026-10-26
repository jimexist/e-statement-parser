"""SQLite storage and CSV export.

Amounts are stored as integer cents. The source PDF is never stored, only its
SHA-256, so re-importing the same file is a no-op. The database file is
created with owner-only permissions.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from .models import AccountKind, Statement

DEFAULT_DB = Path.home() / "Library" / "Application Support" / "estatement" / "estatement.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    source_name TEXT,
    bank TEXT NOT NULL,
    statement_date TEXT NOT NULL,
    backend TEXT,
    reconciled INTEGER NOT NULL,
    checks TEXT NOT NULL,
    meta TEXT NOT NULL,
    warnings TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    key TEXT PRIMARY KEY,
    bank TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    number_masked TEXT NOT NULL,
    currency TEXT NOT NULL,
    holder TEXT
);
CREATE TABLE IF NOT EXISTS account_balances (
    statement_id INTEGER NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
    account_key TEXT NOT NULL REFERENCES accounts(key),
    opening_cents INTEGER,
    closing_cents INTEGER,
    PRIMARY KEY (statement_id, account_key)
);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
    account_key TEXT NOT NULL REFERENCES accounts(key),
    txn_date TEXT NOT NULL,
    post_date TEXT,
    description TEXT NOT NULL,
    reference TEXT,
    amount_cents INTEGER NOT NULL,
    balance_cents INTEGER,
    category TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS ix_txn_date ON transactions(txn_date);
CREATE INDEX IF NOT EXISTS ix_txn_account ON transactions(account_key, txn_date);
"""

CSV_COLUMNS = [
    "txn_date",
    "post_date",
    "bank",
    "account_kind",
    "account_name",
    "account",
    "description",
    "reference",
    "amount",
    "balance",
    "currency",
    "category",
    "statement_date",
]


CENT = Decimal("0.01")


def cents(d: Decimal | None) -> int | None:
    return None if d is None else int((d * 100).to_integral_value())


def from_cents(c: int) -> Decimal:
    return (Decimal(c) / 100).quantize(CENT)


class TransactionRow(BaseModel):
    id: str
    statement_id: int
    account_key: str
    txn_date: str
    post_date: str | None
    description: str
    reference: str | None
    amount: Decimal
    balance: Decimal | None
    category: str | None
    note: str | None
    bank: str
    account_kind: AccountKind
    account_name: str
    account: str
    currency: str
    statement_date: str


class CheckRow(BaseModel):
    name: str
    expected: str
    actual: str
    ok: bool


class StatementRow(BaseModel):
    id: int
    source_name: str | None
    bank: str
    statement_date: str
    backend: str | None
    reconciled: bool
    checks: list[CheckRow]
    warnings: list[str]
    imported_at: str
    n_transactions: int


class AccountRow(BaseModel):
    key: str
    bank: str
    kind: AccountKind
    name: str
    number_masked: str
    currency: str
    holder: str | None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Store:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        if new:
            self.path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def has(self, digest: str) -> bool:
        return self.db.execute("SELECT 1 FROM statements WHERE sha256 = ?", (digest,)).fetchone() is not None

    def save(
        self, stmt: Statement, digest: str, source_name: str | None = None, replace: bool = False
    ) -> tuple[int, int]:
        """Store a parsed statement. Returns (statement_id, transactions inserted)."""
        with self.db:
            if replace:
                self.db.execute("DELETE FROM statements WHERE sha256 = ?", (digest,))
            elif row := self.db.execute("SELECT id FROM statements WHERE sha256 = ?", (digest,)).fetchone():
                return row["id"], 0
            cur = self.db.execute(
                "INSERT INTO statements (sha256, source_name, bank, statement_date, backend, reconciled,"
                " checks, meta, warnings, imported_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    digest,
                    source_name,
                    stmt.bank,
                    stmt.statement_date.isoformat(),
                    stmt.meta.get("backend"),
                    int(stmt.ok),
                    json.dumps(
                        [
                            CheckRow(
                                name=c.name, expected=str(c.expected), actual=str(c.actual), ok=c.ok
                            ).model_dump()
                            for c in stmt.checks
                        ]
                    ),
                    json.dumps(stmt.meta),
                    json.dumps(stmt.warnings),
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )
            sid = cur.lastrowid
            assert sid is not None
            inserted = 0
            for a in stmt.accounts:
                self.db.execute(
                    "INSERT INTO accounts (key, bank, kind, name, number_masked, currency, holder)"
                    " VALUES (?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET name=excluded.name,"
                    " holder=COALESCE(excluded.holder, accounts.holder)",
                    (a.key, a.bank, a.kind, a.name, a.number_masked, a.currency, a.holder),
                )
                self.db.execute(
                    "INSERT INTO account_balances VALUES (?,?,?,?)",
                    (sid, a.key, cents(a.opening_balance), cents(a.closing_balance)),
                )
                for t in a.transactions:
                    cur = self.db.execute(
                        "INSERT OR IGNORE INTO transactions (id, statement_id, account_key, txn_date,"
                        " post_date, description, reference, amount_cents, balance_cents)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            t.natural_key(a.key),
                            sid,
                            a.key,
                            t.txn_date.isoformat(),
                            t.post_date.isoformat() if t.post_date else None,
                            t.description,
                            t.reference,
                            cents(t.amount),
                            cents(t.balance),
                        ),
                    )
                    inserted += cur.rowcount
            return sid, inserted

    def transactions(
        self,
        account: str | None = None,
        start: str | None = None,
        end: str | None = None,
        q: str | None = None,
    ) -> list[TransactionRow]:
        sql = [
            "SELECT t.*, a.bank, a.kind AS account_kind, a.name AS account_name,"
            " a.number_masked AS account, a.currency, s.statement_date"
            " FROM transactions t JOIN accounts a ON a.key = t.account_key"
            " JOIN statements s ON s.id = t.statement_id WHERE 1=1"
        ]
        args: list = []
        if account:
            sql.append("AND t.account_key = ?")
            args.append(account)
        if start:
            sql.append("AND t.txn_date >= ?")
            args.append(start)
        if end:
            sql.append("AND t.txn_date <= ?")
            args.append(end)
        if q:
            sql.append("AND t.description LIKE ?")
            args.append(f"%{q}%")
        sql.append("ORDER BY t.txn_date, t.account_key, t.rowid")
        return [
            TransactionRow(
                **dict(r),
                amount=from_cents(r["amount_cents"]),
                balance=None if r["balance_cents"] is None else from_cents(r["balance_cents"]),
            )
            for r in self.db.execute(" ".join(sql), args)
        ]

    def statements(self) -> list[StatementRow]:
        rows = self.db.execute(
            "SELECT s.id, s.source_name, s.bank, s.statement_date, s.backend, s.reconciled, s.checks,"
            " s.warnings, s.imported_at, COUNT(t.id) AS n_transactions FROM statements s"
            " LEFT JOIN transactions t ON t.statement_id = s.id GROUP BY s.id"
            " ORDER BY s.statement_date DESC, s.bank"
        ).fetchall()
        return [
            StatementRow(
                **dict(r) | {"checks": json.loads(r["checks"]), "warnings": json.loads(r["warnings"])}
            )
            for r in rows
        ]

    def accounts(self) -> list[AccountRow]:
        return [
            AccountRow(**dict(r))
            for r in self.db.execute("SELECT * FROM accounts ORDER BY bank, kind, number_masked")
        ]

    def delete_statement(self, statement_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM statements WHERE id = ?", (statement_id,))

    def to_csv(self, **filters) -> str:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in self.transactions(**filters):
            w.writerow(r.model_dump())
        return buf.getvalue()
