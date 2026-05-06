[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ImagePath,

    [Parameter(Mandatory = $true, Position = 1)]
    [string]$AudioPath,

    [Parameter(Position = 2)]
    [string]$OutputPath,

    [ValidateSet('1080p', '1440p', '2160p')]
    [string]$Resolution = '1080p',

    [ValidateSet('pad', 'crop', 'stretch')]
    [string]$FitMode = 'pad',

    [string]$BackgroundColor = 'black',

    [int]$AudioBitrateKbps = 320,

    [string]$FfmpegPath = 'D:\develop\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $FfmpegPath)) {
    throw "ffmpeg.exe が見つかりません: $FfmpegPath"
}
if (-not (Test-Path -LiteralPath $ImagePath)) {
    throw "画像ファイルが見つかりません: $ImagePath"
}
if (-not (Test-Path -LiteralPath $AudioPath)) {
    throw "音声ファイルが見つかりません: $AudioPath"
}

$resolutionMap = @{
    '1080p' = @{ Width = 1920; Height = 1080 }
    '1440p' = @{ Width = 2560; Height = 1440 }
    '2160p' = @{ Width = 3840; Height = 2160 }
}
$W = $resolutionMap[$Resolution].Width
$H = $resolutionMap[$Resolution].Height

if (-not $OutputPath) {
    $audioItem = Get-Item -LiteralPath $AudioPath
    $OutputPath = Join-Path $audioItem.DirectoryName ($audioItem.BaseName + '.mp4')
}

$outputDir = Split-Path -Parent $OutputPath
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

switch ($FitMode) {
    'pad' {
        $vf = "scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2:color=${BackgroundColor},setsar=1"
    }
    'crop' {
        $vf = "scale=${W}:${H}:force_original_aspect_ratio=increase,crop=${W}:${H},setsar=1"
    }
    'stretch' {
        $vf = "scale=${W}:${H},setsar=1"
    }
}

$ffmpegArgs = @(
    '-y',
    '-loop', '1',
    '-framerate', '2',
    '-i', $ImagePath,
    '-i', $AudioPath,
    '-c:v', 'libx264',
    '-tune', 'stillimage',
    '-preset', 'medium',
    '-crf', '18',
    '-pix_fmt', 'yuv420p',
    '-vf', $vf,
    '-r', '30',
    '-c:a', 'aac',
    '-b:a', "${AudioBitrateKbps}k",
    '-ar', '48000',
    '-ac', '2',
    '-movflags', '+faststart',
    '-shortest',
    $OutputPath
)

Write-Host "入力画像 : $ImagePath"
Write-Host "入力音声 : $AudioPath"
Write-Host "出力先   : $OutputPath"
Write-Host "解像度   : ${W}x${H} ($FitMode)"
Write-Host ''
Write-Host '変換を開始します...'

& $FfmpegPath @ffmpegArgs
if ($LASTEXITCODE -ne 0) {
    throw "ffmpeg がエラーで終了しました (exit code: $LASTEXITCODE)"
}

Write-Host ''
Write-Host "完了: $OutputPath"
