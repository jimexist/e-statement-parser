"""Backend C: render each page and transcribe it with a local OCR VLM on MLX.

Ignores the text layer entirely, so it also works on scanned/image-only
statements. Runs fully on-device via mlx-vlm; weights come from the local
Hugging Face cache (download once, then works offline).
"""

from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

import pymupdf

from ..models import Line
from .markdown import to_lines

NAME = "vlm"
DEFAULT_MODEL = "mlx-community/GLM-OCR-bf16"
PROMPTS = {
    "glm_ocr": "Text Recognition:",
    "paddleocr_vl": "OCR:",
}
# General-purpose VLMs (e.g. Gemma) need an explicit transcription instruction.
GENERIC_PROMPT = (
    "Transcribe all text on this page exactly as printed, top to bottom. "
    "Put each table row on one line with its cells separated by single spaces, "
    "keep every number and code exactly, and do not summarise or add anything."
)


class ModelNotInstalled(RuntimeError):
    pass


def local_model_path(model_id: str = DEFAULT_MODEL) -> Path:
    """Resolve weights from the local cache only; never touches the network."""
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        return Path(snapshot_download(model_id, local_files_only=True))
    except LocalEntryNotFoundError:
        raise ModelNotInstalled(
            f"OCR model {model_id} is not installed. Run once: estatement download-model"
        ) from None


def download_model(model_id: str = DEFAULT_MODEL) -> Path:
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(model_id))


@lru_cache(maxsize=2)
def _load(model_id: str):
    import os

    path = local_model_path(model_id)
    os.environ["HF_HUB_OFFLINE"] = "1"  # keep transformers/mlx-vlm from phoning home
    from mlx_vlm import load

    return load(str(path))


def extract_lines(
    pdf: Path, model_id: str = DEFAULT_MODEL, dpi: int = 200, pages: list[int] | None = None
) -> list[Line]:
    from mlx_vlm import generate
    from mlx_vlm.prompt_utils import apply_chat_template

    model, processor = _load(model_id)
    prompt = PROMPTS.get(model.config.model_type, GENERIC_PROMPT)
    chat = apply_chat_template(processor, model.config, prompt, num_images=1)
    assert isinstance(chat, str)
    doc = pymupdf.open(pdf)
    lines: list[Line] = []
    with tempfile.TemporaryDirectory() as tmp:
        for pno, page in enumerate(doc.pages(), start=1):
            if pages and pno not in pages:
                continue
            img = Path(tmp) / f"p{pno}.png"
            page.get_pixmap(dpi=dpi).save(img)
            out = generate(
                model, processor, chat, [str(img)], max_tokens=4096, temperature=0.0, verbose=False
            )
            lines += to_lines(out if isinstance(out, str) else out.text, page=pno)
    return lines
