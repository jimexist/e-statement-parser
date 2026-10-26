"""Bootstrap ground truth for statements that have a text layer.

The text layer is the bank's own characters, and a statement is only accepted
as ground truth when every printed total reconciles (card sub-totals, total
withdrawals/deposits, row-by-row running balance). Image-only statements are
transcribed by hand instead. Output goes to data/ground_truth/ (gitignored).

    uv run python eval/make_ground_truth.py data/statements/*.pdf
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from estatement.backends.textlayer import has_text_layer
from estatement.pipeline import parse_pdf

OUT = Path("data/ground_truth")


def to_json(stmt) -> dict:
    return {
        "source": "text layer, all statement totals reconciled",
        "bank": stmt.bank,
        "statement_date": stmt.statement_date.isoformat(),
        "transactions": [
            {
                "account": a.key,
                "post_date": t.post_date.isoformat() if t.post_date else None,
                "txn_date": t.txn_date.isoformat(),
                "description": t.description,
                "reference": t.reference,
                "amount": str(t.amount),
                "balance": str(t.balance) if t.balance is not None else None,
            }
            for a, t in stmt.transactions()
        ],
    }


def main(paths: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for p in map(Path, paths):
        dest = OUT / f"{p.stem}.json"
        if not has_text_layer(p):
            print(f"skip {p.name}: no text layer (transcribe by hand)")
            continue
        stmt = parse_pdf(p, backend="textlayer")
        if not stmt.ok:
            print(f"skip {p.name}: totals do not reconcile")
            continue
        dest.write_text(json.dumps(to_json(stmt), indent=1))
        print(f"wrote {dest} ({sum(1 for _ in stmt.transactions())} transactions, {len(stmt.checks)} checks)")


if __name__ == "__main__":
    main(sys.argv[1:])
