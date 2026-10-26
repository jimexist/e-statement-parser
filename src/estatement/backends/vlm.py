"""Backend C: render each page and transcribe it with a local OCR VLM on MLX.

Ignores the text layer entirely, so it also works on scanned/image-only
statements. Runs fully on-device via mlx-vlm; weights come from the local
Hugging Face cache (download once, then works offline).
"""

from __future__ import annotations

import hashlib
import tempfile
from functools import lru_cache
from pathlib import Path

import pymupdf

from ..models import Line
from .markdown import to_lines

NAME = "vlm"
DEFAULT_MODEL = "mlx-community/GLM-OCR-bf16"
# The default model is pinned to one Hugging Face commit and each file it needs to a
# SHA-256 and size, so a re-uploaded or tampered file is refused instead of loaded.
PINNED: dict[str, tuple[str, dict[str, tuple[str, int]]]] = {
    DEFAULT_MODEL: (
        "24f15402e83baa0a80eeeaecf5480e172abc6f2e",
        {
            "chat_template.jinja": (
                "062e7ee4cc8defa88a5938b5d456dc60366ffd80647f918946ee747bf09ddc7c",
                4606,
            ),
            "config.json": (
                "7bf6a133be2edf17779af72f5fb7e9252199ef58fe6b29c26bf249c071087354",
                1875,
            ),
            "generation_config.json": (
                "4e2a3412f65b2a21d315d928986c55723d3e60dfb92c3982a5b9fd56835b0aa5",
                165,
            ),
            "model.safetensors": (
                "3e93839427cf081600cd96651ba4d9edf6d6120f042555eb9fcfa36153905f74",
                2214872319,
            ),
            "model.safetensors.index.json": (
                "b25dcc93cd6c638d344ee12f9a0da2352c7fe6673debc5c324d248637480549b",
                39232,
            ),
            "preprocessor_config.json": (
                "02cc50c36240882ae35e8cd4077a25a379664108185d728d261cb785aefeccff",
                367,
            ),
            "processor_config.json": (
                "19dafea5bd6415c50e2da43a31583dab39f9496673260ad33d9fa6c638a1d077",
                597,
            ),
            "tokenizer.json": (
                "aa0fd058c73a5718bb191f6672dc16d122ee0147b20c123d1726514298f9968a",
                6838609,
            ),
            "tokenizer_config.json": (
                "7a76fcb27abbc2cb0249d81884fef972b2c27194e3e13db54baae50f58f141fb",
                1066,
            ),
        },
    ),
}
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


class ModelIntegrityError(RuntimeError):
    pass


def _snapshot(model_id: str, local_files_only: bool) -> Path:
    from huggingface_hub import snapshot_download

    revision, files = PINNED.get(model_id, (None, {}))
    path = snapshot_download(
        model_id, revision=revision, allow_patterns=list(files) or None, local_files_only=local_files_only
    )
    return Path(path)


def _verify(model_id: str, path: Path) -> None:
    for name, (digest, _) in PINNED.get(model_id, (None, {}))[1].items():
        if not (path / name).is_file():
            raise ModelNotInstalled(f"OCR model {model_id} is incomplete ({name} is missing)")
        with (path / name).open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != digest:
                raise ModelIntegrityError(f"{path / name} does not match its pinned SHA-256; delete it")


def model_size(model_id: str = DEFAULT_MODEL) -> int:
    return sum(size for _, size in PINNED.get(model_id, (None, {}))[1].values())


def is_installed(model_id: str = DEFAULT_MODEL) -> bool:
    """Cheap check (no hashing) that every pinned file is in the local cache."""
    try:
        path = _snapshot(model_id, local_files_only=True)
    except Exception:  # noqa: BLE001 - any cache miss means "not installed"
        return False
    return all((path / name).is_file() for name in PINNED.get(model_id, (None, {}))[1])


def local_model_path(model_id: str = DEFAULT_MODEL) -> Path:
    """Resolve weights from the local cache only; never touches the network."""
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        path = _snapshot(model_id, local_files_only=True)
    except LocalEntryNotFoundError:
        raise ModelNotInstalled(
            f"OCR model {model_id} is not installed. Download it in the app or run estatement download-model"
        ) from None
    _verify(model_id, path)
    return path


def download_model(model_id: str = DEFAULT_MODEL) -> Path:
    path = _snapshot(model_id, local_files_only=False)
    _verify(model_id, path)
    return path


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
