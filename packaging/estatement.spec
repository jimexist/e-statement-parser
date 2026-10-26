# PyInstaller spec: builds dist/eStatement.app
# uv run pyinstaller packaging/estatement.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = collect_data_files("estatement")
binaries, hiddenimports = [], ["estatement.backends.textlayer", "estatement.backends.vlm"]
# On-device OCR runtime (weights are downloaded separately, never bundled).
for pkg in ("mlx", "mlx_vlm", "pymupdf"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis(
    ["app_main.py"],
    pathex=["../src"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["torch", "torchvision", "docling", "docling_core", "docling_ibm_models", "ocrmac",
              "tkinter", "matplotlib", "IPython", "pytest", "mlx_audio", "tensorflow", "jax"],
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
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "14.0",
    },
)
