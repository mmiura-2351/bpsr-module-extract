# Windows: Tesseract同梱ビルド

## 1. 前提

- Windows 環境
- Python / `uv`
- 本リポジトリ

## 2. GitHub Actionsでビルド（ローカル環境構築不要）

このリポジトリには以下の GitHub Actions workflow を追加済み:

- `.github/workflows/build-windows-exe.yml`
- `.github/workflows/build-windows-onedir.yml`

### 2.1 単一exe（onefile）

実行方法:

1. GitHub の `Actions` タブを開く
2. `Build Windows EXE` を選択
3. `Run workflow` を実行
4. 完了後、Artifacts から `ModuleOcrTool-windows` を取得

Artifacts の zip には以下が含まれる:

- `ModuleOcrTool.exe`
- `README.txt`（同梱向けの簡易使用手順）
- `ocr_range_guide.png`（OCR範囲設定の使用例画像）

補足:

- workflow 内で `choco install tesseract` を実行
- `module_ocr_tool/vendor/tesseract` へ自動コピー
- `jpn.traineddata` が無ければ自動取得
- onefile は `UPX無効` でビルドされる

### 2.2 Defender警告を下げたい場合（onedir）

実行方法:

1. GitHub の `Actions` タブを開く
2. `Build Windows Onedir` を選択
3. `Run workflow` を実行
4. 完了後、Artifacts から `ModuleOcrTool-windows-onedir` を取得

Artifacts の zip には以下が含まれる:

- `ModuleOcrTool/`（exe + 依存DLL一式）
- `README.txt`
- `ocr_range_guide.png`

## 3. ローカルWindowsでビルド

## 3.1 Tesseractを同梱配置

以下に Tesseract 一式を配置する:

```text
module_ocr_tool/vendor/tesseract/
  tesseract.exe
  tessdata/jpn.traineddata
  (必要DLL)
```

配置の詳細は [module_ocr_tool/vendor/tesseract/README.md](/home/develop/develop/bpsr-module-ocr/module_ocr_tool/vendor/tesseract/README.md) を参照。

## 3.2 ビルド

PowerShell:

```powershell
./scripts/build_windows_onefile.ps1 -Clean
```

または cmd:

```bat
scripts\build_windows_onefile.bat
```

内部的には以下を実行:

```bash
uv run \
  --with pyinstaller \
  --with numpy \
  --with mss \
  --with opencv-python \
  --with pytesseract \
  --with rapidfuzz \
  pyinstaller --noconfirm --clean build/module_ocr_tool.onefile.spec
```

## 3.3 ローカルで onedir ビルド

PowerShell:

```powershell
./scripts/build_windows_onedir.ps1 -Clean
```

または cmd:

```bat
scripts\build_windows_onedir.bat
```

## 4. 生成物

ローカルビルド時:

- `dist/ModuleOcrTool.exe`

GitHub Actions artifacts:

- `ModuleOcrTool.exe`
- `README.txt`
- `ocr_range_guide.png`

`onefile` のため、実行時に展開される一時ディレクトリから同梱 Tesseract を参照する。

ローカル onedir ビルド時:

- `dist/ModuleOcrTool/`

GitHub Actions onedir artifacts:

- `ModuleOcrTool/`
- `README.txt`
- `ocr_range_guide.png`

## 5. 実行時挙動

- アプリ起動時、`module_ocr_tool/app/tesseract_runtime.py` が Tesseract を自動検出
- 同梱優先で `pytesseract.pytesseract.tesseract_cmd` を設定
- `tessdata` が見つかれば `TESSDATA_PREFIX` も自動設定

## 6. デバッグログ

- ログファイルは自動で出力される
- Windows実行時の既定出力先:
  - `%LOCALAPPDATA%/ModuleOcrTool/logs/module_ocr_tool.log`
- 環境変数 `MODULE_OCR_LOG_DIR` を設定すると出力先を上書き可能

## 7. トラブルシュート

- `No module named 'mss'` や `No module named 'rapidfuzz'` が出る場合:
  - ビルド時に依存同梱付きコマンドを使っていない可能性がある
  - `scripts/build_windows_onefile.ps1` / `scripts/build_windows_onefile.bat` を使って再ビルドする
- Windows Defender / SmartScreen の警告が強い場合:
  - まず `Build Windows Onedir` を使用する
  - 可能ならコード署名を行う
