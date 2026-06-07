# fetch_bins.ps1 — скачивает ffmpeg.exe и yt-dlp.exe в папку python/bin/
# Запускать один раз перед сборкой PyInstaller-бандла.
# Идемпотентно: пропускает скачивание если файл уже есть.
#
# Использование:
#   cd Транскрибатор\python
#   .\fetch_bins.ps1

$ErrorActionPreference = "Stop"
$BinDir = Join-Path $PSScriptRoot "bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

# ── yt-dlp.exe ────────────────────────────────────────────────────────────────
$YtDlpDst = Join-Path $BinDir "yt-dlp.exe"
if (Test-Path $YtDlpDst) {
    Write-Host "yt-dlp.exe уже есть, пропускаем" -ForegroundColor Cyan
} else {
    Write-Host "Скачиваем yt-dlp.exe ..." -ForegroundColor Yellow
    $YtDlpUrl = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    Invoke-WebRequest -Uri $YtDlpUrl -OutFile $YtDlpDst -UseBasicParsing
    $SizeMB = [math]::Round((Get-Item $YtDlpDst).Length / 1MB, 1)
    Write-Host "yt-dlp.exe скачан ($SizeMB МБ)" -ForegroundColor Green
}

# ── ffmpeg.exe ────────────────────────────────────────────────────────────────
$FfmpegDst = Join-Path $BinDir "ffmpeg.exe"
if (Test-Path $FfmpegDst) {
    Write-Host "ffmpeg.exe уже есть, пропускаем" -ForegroundColor Cyan
} else {
    Write-Host "Скачиваем ffmpeg (essentials build от BtbN) ..." -ForegroundColor Yellow

    # BtbN/FFmpeg-Builds — последний релиз, essentials (только ffmpeg/ffprobe/ffplay), gpl, Windows 64-bit
    $FfmpegZipUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    $TmpZip = Join-Path $env:TEMP "ffmpeg-latest.zip"
    $TmpDir = Join-Path $env:TEMP "ffmpeg-extract"

    Invoke-WebRequest -Uri $FfmpegZipUrl -OutFile $TmpZip -UseBasicParsing
    Write-Host "Распаковываем ..." -ForegroundColor Yellow

    if (Test-Path $TmpDir) { Remove-Item $TmpDir -Recurse -Force }
    Expand-Archive -Path $TmpZip -DestinationPath $TmpDir

    # Структура архива: ffmpeg-master-latest-win64-gpl/bin/ffmpeg.exe
    $FfmpegSrc = Get-ChildItem -Path $TmpDir -Recurse -Filter "ffmpeg.exe" |
                 Where-Object { $_.DirectoryName -match "\\bin$" } |
                 Select-Object -First 1

    if (-not $FfmpegSrc) {
        throw "ffmpeg.exe не найден в архиве. Проверьте структуру: $TmpDir"
    }

    Copy-Item $FfmpegSrc.FullName -Destination $FfmpegDst
    Remove-Item $TmpZip -Force
    Remove-Item $TmpDir -Recurse -Force

    $SizeMB = [math]::Round((Get-Item $FfmpegDst).Length / 1MB, 1)
    Write-Host "ffmpeg.exe скачан ($SizeMB МБ)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Готово! Содержимое python/bin/:" -ForegroundColor Green
Get-ChildItem $BinDir | Format-Table Name, @{N="МБ";E={[math]::Round($_.Length/1MB,1)}}
