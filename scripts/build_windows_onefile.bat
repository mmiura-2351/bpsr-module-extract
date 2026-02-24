@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "SPEC_PATH=%PROJECT_ROOT%\build\module_ocr_tool.onefile.spec"
set "TESS_EXE=%PROJECT_ROOT%\module_ocr_tool\vendor\tesseract\tesseract.exe"
set "JPN_DATA=%PROJECT_ROOT%\module_ocr_tool\vendor\tesseract\tessdata\jpn.traineddata"

if not exist "%TESS_EXE%" (
  echo Missing file: %TESS_EXE%
  exit /b 1
)

if not exist "%JPN_DATA%" (
  echo Missing file: %JPN_DATA%
  exit /b 1
)

pushd "%PROJECT_ROOT%"
uv run --with pyinstaller pyinstaller --noconfirm --clean "%SPEC_PATH%"
set "BUILD_EXIT=%ERRORLEVEL%"
popd

if not "%BUILD_EXIT%"=="0" (
  exit /b %BUILD_EXIT%
)

echo Build complete: dist\ModuleOcrTool.exe
exit /b 0

