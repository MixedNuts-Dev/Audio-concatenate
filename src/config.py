from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def _project_root() -> Path:
    # PyInstaller で frozen された場合、sys.executable が .exe のパスを指す
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT: Path = _project_root()
CONFIG_FILE: Path = PROJECT_ROOT / "config.json"

def _default_ffmpeg() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "ffmpeg.exe"
    return Path(r"D:\develop\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe")


def _default_ffprobe() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "ffprobe.exe"
    return Path(r"D:\develop\ffmpeg-master-latest-win64-gpl-shared\bin\ffprobe.exe")


DEFAULT_FFMPEG: Path = _default_ffmpeg()
DEFAULT_FFPROBE: Path = _default_ffprobe()
DEFAULT_INPUT_DIR: Path = PROJECT_ROOT / "input"
DEFAULT_OUTPUT_DIR: Path = PROJECT_ROOT / "output"
DEFAULT_IMAGES_DIR: Path = PROJECT_ROOT / "images"

SUPPORTED_AUDIO_EXTS: tuple[str, ...] = (
    ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma",
)
SUPPORTED_IMAGE_EXTS: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".bmp", ".webp",
)

RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "2160p": (3840, 2160),
}
FIT_MODES: tuple[str, ...] = ("pad", "crop", "stretch")
ENCODER_MODES: tuple[str, ...] = ("auto", "gpu", "cpu")

CPU_LOGICAL = os.cpu_count() or 1
DEFAULT_CPU_THREADS = max(1, int(CPU_LOGICAL * 0.7))


@dataclass
class AppConfig:
    ffmpeg_path: str = str(DEFAULT_FFMPEG)
    ffprobe_path: str = str(DEFAULT_FFPROBE)
    image_path: str = ""
    input_dir: str = str(DEFAULT_INPUT_DIR)
    output_dir: str = str(DEFAULT_OUTPUT_DIR)
    resolution: str = "1080p"
    fit_mode: str = "pad"
    audio_bitrate_kbps: int = 320
    background_color: str = "black"
    encoder_mode: str = "auto"           # auto / gpu / cpu
    cpu_threads: int = DEFAULT_CPU_THREADS

    @classmethod
    def load(cls) -> "AppConfig":
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                known = {f for f in cls.__dataclass_fields__}
                return cls(**{k: v for k, v in data.items() if k in known})
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        return cls()

    def save(self) -> None:
        CONFIG_FILE.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
