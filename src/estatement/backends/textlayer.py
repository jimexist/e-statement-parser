"""Backend A: read the PDF's embedded text layer with PyMuPDF.

No models, no rendering. Words are grouped into visual lines by their
vertical position so that table rows come out as one line each.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from ..models import Line

NAME = "textlayer"


def has_text_layer(pdf: Path | bytes, min_chars: int = 200) -> bool:
    doc = _open(pdf)
    return sum(len(p.get_text()) for p in doc) >= min_chars


def extract_lines(pdf: Path | bytes, y_tolerance: float = 2.0) -> list[Line]:
    doc = _open(pdf)
    lines: list[Line] = []
    for pno, page in enumerate(doc.pages(), start=1):
        rotated = _rotated_boxes(page)
        words = sorted(
            (w for w in page.get_text("words") if not _inside(w, rotated)),
            key=lambda w: (round(w[1], 1), w[0]),
        )
        rows: list[list[tuple]] = []
        for w in words:
            # Same row if the top edge is within tolerance of the row's first word.
            if rows and abs(rows[-1][0][1] - w[1]) <= y_tolerance:
                rows[-1].append(w)
            else:
                rows.append([w])
        for row in rows:
            row.sort(key=lambda w: w[0])
            lines.append(
                Line(
                    text=" ".join(w[4] for w in row),
                    page=pno,
                    y=row[0][1],
                    words=[(w[0], w[2], w[4]) for w in row],
                )
            )
    return lines


def _rotated_boxes(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """Bounding boxes of non-horizontal text (e.g. vertical legal footers)."""
    boxes = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            dx, dy = line["dir"]
            if abs(dy) > 0.1 or dx < 0:
                boxes.append(pymupdf.Rect(line["bbox"]))
    return boxes


def _inside(word: tuple, boxes: list[pymupdf.Rect]) -> bool:
    cx, cy = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
    return any(b.contains(pymupdf.Point(cx, cy)) for b in boxes)


def _open(pdf: Path | bytes) -> pymupdf.Document:
    if isinstance(pdf, (bytes, bytearray)):
        return pymupdf.open(stream=pdf, filetype="pdf")
    return pymupdf.open(pdf)
