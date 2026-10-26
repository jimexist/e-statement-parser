# PyInstaller spec: builds dist/eStatement.app
#   cd packaging && uv run pyinstaller estatement.spec --noconfirm --distpath ../dist --workpath ../build
# APP_VERSION (e.g. from a git tag) sets the bundle version.
# ESTATEMENT_OCR=0 builds the lite app: text-layer PDFs only, no MLX OCR runtime.
import os

from PyInstaller.utils.hooks import collect_all, collect_data_files

VERSION = os.environ.get("APP_VERSION", "0.0.0-dev")
OCR = os.environ.get("ESTATEMENT_OCR", "1") != "0"

datas = collect_data_files("estatement")
binaries, hiddenimports = [], ["estatement.backends.textlayer", "estatement.backends.vlm"]
# On-device OCR runtime (weights are downloaded separately, never bundled).
for pkg in ("mlx", "mlx_vlm", "pymupdf") if OCR else ("pymupdf",):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

excludes = ["torch", "torchvision", "docling", "docling_core", "docling_ibm_models", "ocrmac",
            "tkinter", "matplotlib", "IPython", "pytest", "mlx_audio", "tensorflow", "jax",
            # Pulled in by mlx-vlm (video, training, evals) and pymupdf (layout); unused by OCR.
            "cv2", "datasets", "pyarrow", "pandas", "onnxruntime", "scipy"]
if not OCR:
    excludes += ["mlx", "mlx_vlm", "mlx_lm", "transformers", "huggingface_hub", "hf_xet",
                 "tokenizers", "safetensors", "sentencepiece", "llguidance"]

a = Analysis(
    ["app_main.py"],
    pathex=["../src"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="eStatement", console=False,
          target_arch="arm64", argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="eStatement")
app = BUNDLE(
    coll,
    name="eStatement.app",
    bundle_identifier="local.estatement",
    info_plist={
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "14.0",
    },
)
