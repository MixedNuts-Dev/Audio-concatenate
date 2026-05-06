from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from .config import RESOLUTION_PRESETS, AppConfig
from .jobs import ConversionJob

# Windows でサブプロセスのコンソール窓を出さないためのフラグ
_NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


class FFmpegError(RuntimeError):
    """ffmpeg / ffprobe の実行失敗を表す例外。"""


class VideoFilterBuilder:
    """フィットモードに応じた -vf フィルタ式を組み立てる。"""

    def __init__(self, width: int, height: int, fit_mode: str, bg_color: str = "black") -> None:
        self.width = width
        self.height = height
        self.fit_mode = fit_mode
        self.bg_color = bg_color

    def build(self) -> str:
        w, h = self.width, self.height
        if self.fit_mode == "pad":
            base = (
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={self.bg_color}"
            )
        elif self.fit_mode == "crop":
            base = (
                f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h}"
            )
        elif self.fit_mode == "stretch":
            base = f"scale={w}:{h}"
        else:
            raise ValueError(f"unknown fit_mode: {self.fit_mode}")
        # NVENC / libx264 共通で yuv420p に揃え、SAR を 1:1 にしておく
        return f"{base},format=yuv420p,setsar=1"


class EncoderProbe:
    """ffmpeg のハードウェアエンコーダ可否を実機テストで判定する。"""

    def __init__(self, ffmpeg_path: Path) -> None:
        self.ffmpeg_path = ffmpeg_path
        self._has_nvenc: bool | None = None

    async def has_nvenc(self) -> bool:
        if self._has_nvenc is not None:
            return self._has_nvenc
        if not self.ffmpeg_path.exists():
            self._has_nvenc = False
            return False
        proc = await asyncio.create_subprocess_exec(
            str(self.ffmpeg_path),
            "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.1",
            "-c:v", "h264_nvenc", "-f", "null", "-",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=_NO_WINDOW_FLAGS,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            self._has_nvenc = False
            return False
        self._has_nvenc = proc.returncode == 0
        return self._has_nvenc


class FFprobeClient:
    """ffprobe のラッパ。"""

    def __init__(self, ffprobe_path: Path) -> None:
        self.ffprobe_path = ffprobe_path

    async def duration_us(self, audio_path: Path) -> int:
        if not self.ffprobe_path.exists():
            raise FFmpegError(f"ffprobe not found: {self.ffprobe_path}")
        proc = await asyncio.create_subprocess_exec(
            str(self.ffprobe_path),
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            str(audio_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=_NO_WINDOW_FLAGS,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise FFmpegError(f"ffprobe failed: {stderr.decode('utf-8', errors='replace')}")
        try:
            data = json.loads(stdout.decode("utf-8", errors="replace"))
            seconds = float(data["format"]["duration"])
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise FFmpegError(f"failed to parse ffprobe output: {exc}") from exc
        return int(seconds * 1_000_000)


class FFmpegConverter:
    """ffmpeg を起動して 1 ジョブを実行する変換器。

    - GPU: NVENC (h264_nvenc) で映像を高速エンコード
    - CPU: libx264 (still image チューン) でフォールバック
    - 共通: 音声は AAC、 -threads でCPUスレッド数を制限
    """

    LOG_TAIL_KEEP = 30

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.ffmpeg_path = Path(cfg.ffmpeg_path)
        self.ffprobe = FFprobeClient(Path(cfg.ffprobe_path))
        self.probe = EncoderProbe(self.ffmpeg_path)

    async def resolve_encoder(self) -> str:
        """encoder_mode 設定と実機検出から、実際に使うエンコーダ ('gpu'/'cpu') を決める。"""
        mode = self.cfg.encoder_mode
        if mode == "cpu":
            return "cpu"
        if mode == "gpu":
            return "gpu"
        # auto
        return "gpu" if await self.probe.has_nvenc() else "cpu"

    async def run(
        self,
        job: ConversionJob,
        on_progress: Callable[[float], None],
        on_log: Callable[[str], None],
    ) -> None:
        self._validate(job)
        if job.duration_us is None:
            job.duration_us = await self.ffprobe.duration_us(job.audio_path)
        duration_us = max(1, job.duration_us)

        encoder = await self.resolve_encoder()
        job.encoder = encoder

        width, height = RESOLUTION_PRESETS[job.resolution]
        vf = VideoFilterBuilder(width, height, job.fit_mode, job.background_color).build()

        job.output_path.parent.mkdir(parents=True, exist_ok=True)
        args = self._build_args(job, vf, encoder)

        on_log(f"[encoder] {encoder} (threads={job.cpu_threads or self.cfg.cpu_threads})")

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=_NO_WINDOW_FLAGS,
        )
        log_tail: list[str] = []
        try:
            await asyncio.gather(
                self._read_progress(proc.stdout, duration_us, on_progress),
                self._read_log(proc.stderr, on_log, log_tail),
                proc.wait(),
            )
        except asyncio.CancelledError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            raise

        if proc.returncode != 0:
            tail = "\n".join(log_tail[-10:])
            raise FFmpegError(f"ffmpeg exit code {proc.returncode}\n{tail}")

    def _validate(self, job: ConversionJob) -> None:
        if not self.ffmpeg_path.exists():
            raise FFmpegError(f"ffmpeg not found: {self.ffmpeg_path}")
        if not job.image_path.exists():
            raise FFmpegError(f"image not found: {job.image_path}")
        if not job.audio_path.exists():
            raise FFmpegError(f"audio not found: {job.audio_path}")

    def _build_args(self, job: ConversionJob, vf: str, encoder: str) -> list[str]:
        threads = job.cpu_threads if job.cpu_threads > 0 else self.cfg.cpu_threads
        common_pre = [
            str(self.ffmpeg_path),
            "-y",
            "-hide_banner",
            "-loglevel", "info",
            "-threads", str(threads),
            "-loop", "1",
            "-framerate", "2",
            "-i", str(job.image_path),
            "-i", str(job.audio_path),
            "-vf", vf,
            "-r", "30",
        ]
        if encoder == "gpu":
            video_args = [
                "-c:v", "h264_nvenc",
                "-preset", "p6",
                "-tune", "hq",
                "-rc", "vbr",
                "-cq", "19",
                "-b:v", "8M",
                "-maxrate", "12M",
                "-bufsize", "16M",
                "-spatial-aq", "1",
                "-temporal-aq", "1",
                "-rc-lookahead", "20",
                "-pix_fmt", "yuv420p",
            ]
        else:
            video_args = [
                "-c:v", "libx264",
                "-tune", "stillimage",
                "-preset", "medium",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
            ]
        common_post = [
            "-c:a", "aac",
            "-b:a", f"{job.audio_bitrate_kbps}k",
            "-ar", "48000",
            "-ac", "2",
            "-movflags", "+faststart",
            "-shortest",
            "-progress", "pipe:1",
            "-nostats",
            str(job.output_path),
        ]
        return common_pre + video_args + common_post

    async def _read_progress(
        self,
        stream: asyncio.StreamReader,
        duration_us: int,
        on_progress: Callable[[float], None],
    ) -> None:
        while True:
            raw = await stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key in ("out_time_us", "out_time_ms"):
                try:
                    cur = int(value)
                except ValueError:
                    continue
                on_progress(cur / duration_us)
            elif key == "progress" and value == "end":
                on_progress(1.0)

    async def _read_log(
        self,
        stream: asyncio.StreamReader,
        on_log: Callable[[str], None],
        tail: list[str],
    ) -> None:
        while True:
            raw = await stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                on_log(line)
                tail.append(line)
                if len(tail) > self.LOG_TAIL_KEEP:
                    del tail[0]
