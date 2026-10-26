"""Score every extraction backend against the ground truth.

Prints metrics only (no transaction content), so the report is safe to share.

    uv run python eval/compare.py            # all backends, cached extraction
    uv run python eval/compare.py --fresh    # re-run extraction
"""

from __future__ import annotations

import argparse
import difflib
import json
import pickle
import re
import time
from collections import defaultdict
from pathlib import Path

from estatement.banks import parse_lines
from estatement.models import Statement
from estatement.pipeline import extract_lines, parse_pdf

STATEMENTS = Path("data/statements")
TRUTH = Path("data/ground_truth")
CACHE = Path("data/cache")

BACKENDS = {
    "A textlayer (PyMuPDF)": ("textlayer", {}),
    "B docling (layout+table models)": ("docling", {}),
    "C1 GLM-OCR 0.9B (MLX) @200dpi": ("vlm", {"model_id": "mlx-community/GLM-OCR-bf16", "dpi": 200}),
    "C1 GLM-OCR 0.9B (MLX) @150dpi": ("vlm", {"model_id": "mlx-community/GLM-OCR-bf16", "dpi": 150}),
    "C1 GLM-OCR + retry until reconciled": ("vlm-retry", {}),
    "C2 PaddleOCR-VL-1.6 (MLX)": ("vlm", {"model_id": "mlx-community/PaddleOCR-VL-1.6-5bit", "dpi": 200}),
    "C3 Gemma-4 E2B 4bit (MLX)": ("vlm", {"model_id": "mlx-community/gemma-4-e2b-it-4bit", "dpi": 200}),
    "C4 Gemma-4 E4B 4bit (MLX)": ("vlm", {"model_id": "mlx-community/gemma-4-e4b-it-4bit", "dpi": 200}),
    "auto (textlayer, else GLM-OCR + retry)": ("auto", {}),
    "D Apple Vision OCR": ("applevision", {}),
}


def norm(s: str | None) -> str:
    return re.sub(r"[\s|]+", "", s or "").upper()


def extract_cached(pdf: Path, label: str, fresh: bool):
    backend, kw = BACKENDS[label]
    key = CACHE / f"{pdf.stem}.{re.sub(r'[^a-z0-9]+', '_', label.lower())}.pkl"
    if key.exists() and not fresh:
        return pickle.loads(key.read_bytes())
    t0 = time.perf_counter()
    try:
        if backend in ("vlm-retry", "auto"):
            lines, err = parse_pdf(pdf, "vlm" if backend == "vlm-retry" else "auto"), None
        else:
            lines, err = extract_lines(pdf, backend, **kw), None
    except Exception as e:  # noqa: BLE001 - report, don't crash the comparison
        lines, err = [], f"{type(e).__name__}"
    result = (lines, time.perf_counter() - t0, err)
    CACHE.mkdir(parents=True, exist_ok=True)
    key.write_bytes(pickle.dumps(result))
    return result


def score(pred, truth) -> dict:
    """Pair rows by (account, txn_date, amount), then compare the other fields."""
    pool = defaultdict(list)
    for p in pred:
        pool[(p["account"], p["txn_date"], p["amount"])].append(p)
    matched = desc_exact = ref_ok = ref_n = perfect = 0
    sim = 0.0
    for t in truth:
        cands = pool.get((t["account"], t["txn_date"], t["amount"]))
        if not cands:
            continue
        # Best description match among same-key candidates.
        p = max(
            cands,
            key=lambda c: difflib.SequenceMatcher(
                None, norm(c["description"]), norm(t["description"])
            ).ratio(),
        )
        cands.remove(p)
        matched += 1
        r = difflib.SequenceMatcher(None, norm(p["description"]), norm(t["description"])).ratio()
        sim += r
        d_ok = norm(p["description"]) == norm(t["description"])
        desc_exact += d_ok
        r_ok = (p["reference"] or None) == (t["reference"] or None)
        if t["reference"]:
            ref_n += 1
            ref_ok += r_ok
        perfect += d_ok and r_ok and p["post_date"] == t["post_date"] and p["balance"] == t["balance"]
    n_t, n_p = len(truth), len(pred)
    return {
        "recall": matched / n_t if n_t else 1.0,
        "precision": matched / n_p if n_p else (1.0 if not n_t else 0.0),
        "desc_exact": desc_exact / matched if matched else 0.0,
        "desc_sim": sim / matched if matched else 0.0,
        "ref_exact": ref_ok / ref_n if ref_n else None,
        "row_perfect": perfect / n_t if n_t else 1.0,
        "n_truth": n_t,
        "n_pred": n_p,
    }


def rows_of(stmt) -> list[dict]:
    return [
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
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--backend", action="append", help="substring of a backend label")
    args = ap.parse_args()
    labels = [l for l in BACKENDS if not args.backend or any(b.lower() in l.lower() for b in args.backend)]

    out = [
        "| Backend | Statement | Rows found / truth | Recall | Precision | Desc exact | Desc sim"
        " | Ref exact | Row perfect | Totals reconcile | Seconds |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    agg = {}
    for label in labels:
        tot = defaultdict(float)
        for gt_path in sorted(TRUTH.glob("*.json")):
            pdf = STATEMENTS / f"{gt_path.stem}.pdf"
            truth = json.loads(gt_path.read_text())["transactions"]
            lines, secs, err = extract_cached(pdf, label, args.fresh)
            stmt = None
            if not err:
                try:
                    stmt = lines if isinstance(lines, Statement) else parse_lines(lines)
                except Exception as e:  # noqa: BLE001
                    err = type(e).__name__
            s = score(rows_of(stmt) if stmt else [], truth)
            ok = "yes" if stmt and stmt.ok else ("ERR " + err if err else "no")
            ref = "-" if s["ref_exact"] is None else f"{s['ref_exact']:.0%}"
            out.append(
                f"| {label} | {gt_path.stem} | {s['n_pred']} / {s['n_truth']} | {s['recall']:.0%} | "
                f"{s['precision']:.0%} | {s['desc_exact']:.0%} | {s['desc_sim']:.3f} | {ref} | "
                f"{s['row_perfect']:.0%} | {ok} | {secs:.1f} |"
            )
            tot["truth"] += s["n_truth"]
            tot["perfect"] += s["row_perfect"] * s["n_truth"]
            tot["recall"] += s["recall"] * s["n_truth"]
            tot["ok"] += bool(stmt and stmt.ok)
            tot["n"] += 1
            tot["secs"] += secs
        agg[label] = tot
    print("\n".join(out))
    print("\n| Backend | Statements reconciled | Row recall | Row perfect | Total seconds |")
    print("|---|---|---|---|---|")
    for label, t in agg.items():
        print(
            f"| {label} | {int(t['ok'])}/{int(t['n'])} | {t['recall'] / t['truth']:.1%} | "
            f"{t['perfect'] / t['truth']:.1%} | {t['secs']:.1f} |"
        )


if __name__ == "__main__":
    main()
