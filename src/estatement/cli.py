"""Command line: ``estatement import|parse|export|serve|app``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import BACKENDS, parse_pdf
from .store import DEFAULT_DB, Store, sha256


def _summary(stmt) -> str:
    n = sum(1 for _ in stmt.transactions())
    status = "reconciled" if stmt.ok else "NOT reconciled"
    return f"{stmt.bank} {stmt.statement_date} via {stmt.meta.get('backend')}: {n} transactions, {status}"


def cmd_import(args) -> int:
    store = Store(args.db)
    bad = 0
    for p in map(Path, args.pdf):
        data = p.read_bytes()
        digest = sha256(data)
        if store.has(digest) and not args.replace:
            print(f"{p.name}: already imported")
            continue
        try:
            stmt = parse_pdf(p, backend=args.backend)
        except Exception as e:  # noqa: BLE001
            print(f"{p.name}: FAILED ({type(e).__name__}: {e})", file=sys.stderr)
            bad += 1
            continue
        if not stmt.ok:
            bad += 1
            for c in stmt.checks:
                if not c.ok:
                    print(f"  check failed: {c.name}", file=sys.stderr)
            if not args.allow_unreconciled:
                print(f"{p.name}: {_summary(stmt)} - not saved (use --allow-unreconciled)", file=sys.stderr)
                continue
        _, inserted = store.save(stmt, digest, p.name, replace=args.replace)
        print(f"{p.name}: {_summary(stmt)}, {inserted} new rows")
    return 1 if bad else 0


def cmd_parse(args) -> int:
    stmt = parse_pdf(Path(args.pdf), backend=args.backend)
    print(_summary(stmt), file=sys.stderr)
    for c in stmt.checks:
        print(f"  [{'ok' if c.ok else 'FAIL'}] {c.name}", file=sys.stderr)
    for w in stmt.warnings:
        print(f"  warning: {w}", file=sys.stderr)
    import csv
    out = open(args.csv, "w", newline="") if args.csv else sys.stdout
    w = csv.writer(out)
    w.writerow(["txn_date", "post_date", "account", "description", "reference", "amount", "balance"])
    for a, t in stmt.transactions():
        w.writerow([t.txn_date, t.post_date or "", a.key, t.description, t.reference or "", t.amount,
                    "" if t.balance is None else t.balance])
    return 0 if stmt.ok else 1


def cmd_export(args) -> int:
    data = Store(args.db).to_csv(start=args.start, end=args.end, account=args.account)
    if args.out:
        Path(args.out).write_text(data)
    else:
        sys.stdout.write(data)
    return 0


def cmd_serve(args) -> int:
    from .web import serve
    serve(Path(args.db), port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_app(args) -> int:
    from .desktop import main
    main(Path(args.db))
    return 0


def cmd_download_model(args) -> int:
    from .backends.vlm import download_model

    print(f"Downloading {args.model} from Hugging Face (one time; parsing itself stays offline)...")
    print(download_model(args.model))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="estatement", description="Parse bank e-statements locally.")
    ap.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite file (default {DEFAULT_DB})")
    sub = ap.add_subparsers(dest="cmd", required=True)
    backends = ["auto", *BACKENDS]

    p = sub.add_parser("import", help="parse PDFs and store them")
    p.add_argument("pdf", nargs="+")
    p.add_argument("--backend", default="auto", choices=backends)
    p.add_argument("--replace", action="store_true", help="re-import files already stored")
    p.add_argument("--allow-unreconciled", action="store_true",
                   help="store statements whose totals don't reconcile")
    p.set_defaults(fn=cmd_import)

    p = sub.add_parser("parse", help="parse one PDF to CSV without storing")
    p.add_argument("pdf")
    p.add_argument("--backend", default="auto", choices=backends)
    p.add_argument("--csv")
    p.set_defaults(fn=cmd_parse)

    p = sub.add_parser("export", help="export stored transactions as CSV")
    p.add_argument("--out")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--account")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("serve", help="local web UI on 127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("download-model", help="fetch the on-device OCR model (for image-only PDFs)")
    p.add_argument("--model", default="mlx-community/GLM-OCR-bf16")
    p.set_defaults(fn=cmd_download_model)

    p = sub.add_parser("app", help="desktop window")
    p.set_defaults(fn=cmd_app)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
