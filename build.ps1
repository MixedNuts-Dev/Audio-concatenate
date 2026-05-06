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

# PyInstaller の確認
python -c "import PyInstaller" 2>$null
if (-not $?) {
    Write-Host "PyInstaller をインストール中..."
    pip install pyinstaller
}

# 前回のビルドをクリーン
foreach ($d in "dist", "build") {
    if (Test-Path $d) { Remove-Item $d -Recurse -Force }
}

# ビルド実行 (--onedir)
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
    Write-Error "ビルド失敗 (exit code $LASTEXITCODE)"
    exit $LASTEXITCODE
}

# FFmpeg バイナリを dist\AudioToVideo\ にコピー
Write-Host ""
Write-Host "FFmpeg バイナリをコピー中..."
foreach ($bin in $FFMPEG_BINS) {
    $src = Join-Path $FFMPEG_SRC $bin
    $dst = Join-Path $DIST_DIR $bin
    if (-not (Test-Path $src)) {
        Write-Error "FFmpeg ファイルが見つかりません: $src"
        exit 1
    }
    Copy-Item $src $dst -Force
    Write-Host "  コピー: $bin"
}

Write-Host ""
Write-Host "ビルド成功: $DIST_DIR\AudioToVideo.exe"
Write-Host "配布時は $DIST_DIR\ フォルダごと配布してください。"
