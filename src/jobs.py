from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ConversionJob:
    image_path: Path
    audio_path: Path
    output_path: Path
    resolution: str = "1080p"
    fit_mode: str = "pad"
    audio_bitrate_kbps: int = 320
    background_color: str = "black"
    encoder: str = "cpu"                    # 実際に使用したエンコーダ ('gpu' / 'cpu')
    cpu_threads: int = 1
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    error: Optional[str] = None
    duration_us: Optional[int] = None
