"""Backend D: Apple Vision framework OCR (VNRecognizeTextRequest), on-device.

Built into macOS, so no model download. Returns word boxes, which we group
into lines. Unlike the PDF text layer, OCR gives no reading order, so
side-by-side panels (e.g. HSBC's transaction list next to its account
summary) are separated by finding empty vertical gutters first.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pymupdf

from ..models import Line

NAME = "applevision"

# A box is (top, x0, x1, bottom, text), all normalised to 0..1, origin top-left.
Box = tuple[float, float, float, float, str]


def extract_lines(pdf: Path, dpi: int = 300) -> list[Line]:
    from ocrmac import ocrmac

    doc = pymupdf.open(pdf)
    lines: list[Line] = []
    with tempfile.TemporaryDirectory() as tmp:
        for pno, page in enumerate(doc, start=1):
            img = Path(tmp) / f"p{pno}.png"
            page.get_pixmap(dpi=dpi).save(img)
            # Each result: (text, confidence, (x, y, w, h)), normalised, origin bottom-left.
            results = ocrmac.OCR(str(img), recognition_level="accurate",
                                 language_preference=["en-US"]).recognize()
            boxes = [(1 - (y + h), x, x + w, 1 - y, text) for text, _c, (x, y, w, h) in results]
            for column in _split_columns(boxes):
                lines += _rows_to_lines(column, pno, page.rect)
    return lines


def _split_columns(boxes: list[Box], bins: int = 200, min_gap: int = 2) -> list[list[Box]]:
    """Split side-by-side panels at an empty vertical gutter.

    Table columns also leave empty gutters, so a candidate only counts as a
    panel break when the rows on either side do *not* line up. Boxes that span
    the gutter (full-width paragraphs) stay with the left column.
    """
    if not boxes:
        return []
    cover = [0] * bins
    for _t, x0, x1, _b, _s in boxes:
        for i in range(max(0, int(x0 * bins)), min(bins, int(x1 * bins) + 1)):
            cover[i] += 1
    lo = min(int(b[1] * bins) for b in boxes)
    hi = max(int(b[2] * bins) for b in boxes)
    threshold = max(3, len(boxes) // 15)  # tolerate a few full-width lines
    candidates, run = [], 0
    for i in range(lo, hi):
        run = run + 1 if cover[i] <= threshold else 0
        if run == min_gap:
            candidates.append((i - min_gap + 1) / bins)
    for g in candidates:
        left = [b for b in boxes if b[2] <= g + 0.005]
        right = [b for b in boxes if b[1] >= g]
        if len(right) < 5 or len(left) < 5:
            continue
        aligned = sum(
            any(l[0] <= (r[0] + r[3]) / 2 <= l[3] for l in left) for r in right) / len(right)
        if aligned < 0.75:
            left = [b for b in boxes if b[1] < g]
            return [left, *_split_columns(right, bins, min_gap)]
    return [boxes]


def _rows_to_lines(boxes: list[Box], pno: int, rect: pymupdf.Rect) -> list[Line]:
    boxes = sorted(boxes, key=lambda b: (b[0], b[1]))
    rows: list[list[Box]] = []
    for b in boxes:
        # Same row when vertical extents overlap by more than half the shorter box.
        if rows:
            r = rows[-1][0]
            overlap = min(r[3], b[3]) - max(r[0], b[0])
            if overlap > 0.5 * min(r[3] - r[0], b[3] - b[0]):
                rows[-1].append(b)
                continue
        rows.append([b])
    out = []
    for row in rows:
        row.sort(key=lambda b: b[1])
        out.append(Line(
            text=" ".join(b[4] for b in row),
            page=pno,
            y=row[0][0] * rect.height,
            words=[(b[1] * rect.width, b[2] * rect.width, b[4]) for b in row],
        ))
    return out
