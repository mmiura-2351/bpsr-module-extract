param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptDir "..")
$specPath = Join-Path $projectRoot "build/module_ocr_tool.onefile.spec"
$vendorDir = Join-Path $projectRoot "module_ocr_tool/vendor/tesseract"
$requiredExe = Join-Path $vendorDir "tesseract.exe"
$requiredJpn = Join-Path $vendorDir "tessdata/jpn.traineddata"

if (!(Test-Path $requiredExe)) {
  throw "Missing file: $requiredExe"
}
if (!(Test-Path $requiredJpn)) {
  throw "Missing file: $requiredJpn"
}

Push-Location $projectRoot
try {
  $args = @(
    "--with", "pyinstaller",
    "--with", "numpy",
    "--with", "mss",
    "--with", "opencv-python",
    "--with", "pytesseract",
    "--with", "rapidfuzz",
    "pyinstaller",
    "--noconfirm"
  )
  if ($Clean) {
    $args += "--clean"
  }
  $args += $specPath
  uv run @args
} finally {
  Pop-Location
}

Write-Host "Build complete: dist/ModuleOcrTool.exe"
