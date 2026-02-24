# Tesseract Bundle Directory

`単一exe` ビルド時に同梱する Tesseract 一式をこのディレクトリに配置します。

必須:

- `tesseract.exe`
- `tessdata/jpn.traineddata`

推奨:

- 同梱配布元の DLL 群（`lib*.dll` など）
- `tessdata/eng.traineddata`（デバッグ用）

例:

```text
module_ocr_tool/vendor/tesseract/
  tesseract.exe
  libtesseract-5.dll
  leptonica-1.83.1.dll
  tessdata/
    jpn.traineddata
```

