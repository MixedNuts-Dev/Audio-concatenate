Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$FFMPEG_SRC = "D:\develop\ffmpeg-master-latest-win64-gpl-shared\bin"
$FFMPEG_BINS = @(
    "ffmpeg.exe",
    "ffprobe.exe",
    "avcodec-61.dll",
    "avdevice-61.dll",
    "avfilter-10.dll",
    "avformat-61.dll",
    "avutil-59.dll",
    "postproc-58.dll",
    "swresample-5.dll",
    "swscale-8.dll"
)
$DIST_DIR = "dist\AudioToVideo"
$FFMPEG_DEST = "$DIST_DIR\bin"

# Check PyInstaller
python -c "import PyInstaller" 2>$null
if (-not $?) {
    Write-Host "Installing PyInstaller..."
    pip install pyinstaller
}

# Clean previous build
foreach ($d in "dist", "build") {
    if (Test-Path $d) { Remove-Item $d -Recurse -Force }
}

# Build (--onedir)
python -m PyInstaller `
    --noconsole `
    --onedir `
    --name "AudioToVideo" `
    --hidden-import "tkinter" `
    --hidden-import "_tkinter" `
    --hidden-import "tkinter.ttk" `
    --hidden-import "tkinter.filedialog" `
    --hidden-import "tkinter.messagebox" `
    app.py

if ($LASTEXITCODE -ne 0) {
    Write-Error "Build failed (exit code $LASTEXITCODE)"
    exit $LASTEXITCODE
}

# Copy FFmpeg binaries to dist\AudioToVideo\bin\
Write-Host ""
Write-Host "Copying FFmpeg binaries..."
New-Item -ItemType Directory -Force -Path $FFMPEG_DEST | Out-Null
foreach ($bin in $FFMPEG_BINS) {
    $src = Join-Path $FFMPEG_SRC $bin
    $dst = Join-Path $FFMPEG_DEST $bin
    if (-not (Test-Path $src)) {
        Write-Error "FFmpeg file not found: $src"
        exit 1
    }
    Copy-Item $src $dst -Force
    Write-Host "  Copied: bin\$bin"
}

Write-Host ""
Write-Host "Build successful: $DIST_DIR\AudioToVideo.exe"
Write-Host "Distribute the entire $DIST_DIR\ folder."
