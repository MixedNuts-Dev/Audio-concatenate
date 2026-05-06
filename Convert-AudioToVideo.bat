@echo off
REM Usage: drag image and audio onto this .bat (image first, audio second)
REM   or:  Convert-AudioToVideo.bat "image.png" "audio.wav" ["output.mp4"]

if "%~2"=="" (
    echo Usage: %~nx0 ^<image^> ^<audio^> [output.mp4]
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Convert-AudioToVideo.ps1" -ImagePath "%~1" -AudioPath "%~2" %~3
pause
