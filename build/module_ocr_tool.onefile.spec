# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

spec_path_value = globals().get("SPEC")
if spec_path_value:
    project_root = Path(spec_path_value).resolve().parent.parent
else:
    project_root = Path.cwd().resolve()

entrypoint = project_root / "module_ocr_tool" / "main.py"
vendor_tesseract_dir = project_root / "module_ocr_tool" / "vendor" / "tesseract"

if not vendor_tesseract_dir.exists():
    raise SystemExit(
        "Tesseract 同梱フォルダがありません: "
        f"{vendor_tesseract_dir}\n"
        "module_ocr_tool/vendor/tesseract/ に tesseract.exe と tessdata を配置してください。"
    )

tesseract_exe = vendor_tesseract_dir / "tesseract.exe"
jpn_traineddata = vendor_tesseract_dir / "tessdata" / "jpn.traineddata"
if not tesseract_exe.exists() or not jpn_traineddata.exists():
    raise SystemExit(
        "Tesseract 同梱ファイルが不足しています。\n"
        f"- required: {tesseract_exe}\n"
        f"- required: {jpn_traineddata}"
    )

datas = []
datas += collect_data_files("pytesseract")
datas += collect_data_files("mss")

# Bundle whole Tesseract folder so runtime can locate exe + tessdata + dependent DLLs.
for src in vendor_tesseract_dir.rglob("*"):
    if not src.is_file():
        continue
    relative_parent = src.relative_to(vendor_tesseract_dir).parent
    target_dir = Path("tesseract") / relative_parent
    datas.append((str(src), str(target_dir)))

binaries = []
binaries += collect_dynamic_libs("cv2")

a = Analysis(
    [str(entrypoint)],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "cv2",
        "numpy",
        "pytesseract",
        "mss",
        "rapidfuzz",
        "rapidfuzz.fuzz",
        "rapidfuzz.process",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ModuleOcrTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
