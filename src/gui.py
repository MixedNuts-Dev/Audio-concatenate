from __future__ import annotations

import asyncio
import os
import queue
import subprocess
import sys
import tkinter as tk
from collections.abc import Iterable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Optional

from .async_bridge import AsyncBridge
from .config import (
    CPU_LOGICAL,
    ENCODER_MODES,
    FIT_MODES,
    RESOLUTION_PRESETS,
    SUPPORTED_AUDIO_EXTS,
    SUPPORTED_IMAGE_EXTS,
    AppConfig,
)
from .converter import FFmpegConverter, FFprobeClient
from .jobs import ConversionJob, JobStatus

POLL_INTERVAL_MS = 100
ENCODER_LABEL = {"gpu": "GPU (NVENC)", "cpu": "CPU (libx264)"}


def _format_duration(us: Optional[int]) -> str:
    if not us or us <= 0:
        return "?"
    sec = us // 1_000_000
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


class AudioFileTable(ttk.Frame):
    """入力フォルダの音声ファイルを一覧表示する Treeview（単一選択）。"""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.tree = ttk.Treeview(
            self, columns=("name", "duration"), show="headings",
            selectmode="browse", height=10,
        )
        self.tree.heading("name", text="ファイル名")
        self.tree.heading("duration", text="尺")
        self.tree.column("name", width=480, anchor="w")
        self.tree.column("duration", width=80, anchor="center")
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._paths: dict[str, Path] = {}

    def populate(self, entries: Iterable[tuple[Path, Optional[int]]]) -> None:
        self.tree.delete(*self.tree.get_children())
        self._paths.clear()
        for path, duration_us in entries:
            iid = self.tree.insert(
                "", "end", values=(path.name, _format_duration(duration_us))
            )
            self._paths[iid] = path

    def selected_path(self) -> Optional[Path]:
        sel = self.tree.selection()
        if not sel:
            return None
        return self._paths.get(sel[0])

    def update_duration(self, path: Path, duration_us: Optional[int]) -> None:
        for iid, p in self._paths.items():
            if p == path:
                self.tree.set(iid, "duration", _format_duration(duration_us))
                return


class ImageFileTable(ttk.Frame):
    """画像フォルダ内の画像ファイルを一覧表示する Treeview（単一選択）。"""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.tree = ttk.Treeview(
            self, columns=("name",), show="headings",
            selectmode="browse", height=10,
        )
        self.tree.heading("name", text="ファイル名")
        self.tree.column("name", width=320, anchor="w")
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._paths: dict[str, Path] = {}

    def populate(self, paths: Iterable[Path]) -> None:
        self.tree.delete(*self.tree.get_children())
        self._paths.clear()
        for path in paths:
            iid = self.tree.insert("", "end", values=(path.name,))
            self._paths[iid] = path

    def selected_path(self) -> Optional[Path]:
        sel = self.tree.selection()
        if not sel:
            return None
        return self._paths.get(sel[0])


class ProgressPanel(ttk.LabelFrame):
    """変換進捗表示パネル。"""

    def __init__(self, master: tk.Misc, on_cancel) -> None:
        super().__init__(master, text="変換")
        self._on_cancel = on_cancel
        self.var_status = tk.StringVar(value="待機中")
        self.var_progress = tk.DoubleVar(value=0.0)

        ttk.Label(self, textvariable=self.var_status).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 2)
        )
        self.bar = ttk.Progressbar(
            self, orient="horizontal", mode="determinate",
            maximum=1000, variable=self.var_progress,
        )
        self.bar.grid(row=1, column=0, sticky="we", padx=6, pady=2)
        self.btn_cancel = ttk.Button(self, text="キャンセル", command=self._cancel, state="disabled")
        self.btn_cancel.grid(row=1, column=1, padx=6, pady=2)
        self.columnconfigure(0, weight=1)

    def begin(self, name: str) -> None:
        self.var_status.set(f"変換中: {name}")
        self.var_progress.set(0.0)
        self.btn_cancel.configure(state="normal")

    def update_progress(self, progress: float) -> None:
        self.var_progress.set(max(0.0, min(1000.0, progress * 1000)))

    def finish(self, status: JobStatus, name: str, error: Optional[str]) -> None:
        self.btn_cancel.configure(state="disabled")
        if status == JobStatus.DONE:
            self.var_status.set(f"完了: {name}")
            self.var_progress.set(1000)
        elif status == JobStatus.CANCELLED:
            self.var_status.set(f"キャンセル: {name}")
            self.var_progress.set(0)
        elif status == JobStatus.FAILED:
            self.var_status.set(f"失敗: {name}  ({error or 'unknown error'})")
            self.var_progress.set(0)

    def _cancel(self) -> None:
        self._on_cancel()


class App:
    """メインウィンドウ。設定・1ジョブ実行・GUI を集約する。"""

    def __init__(self) -> None:
        self.cfg = AppConfig.load()
        self.root = tk.Tk()
        self.root.title("Audio → Video Converter")
        self.root.geometry("780x680")

        self.bridge = AsyncBridge()
        self.bridge.start()

        self.converter = FFmpegConverter(self.cfg)
        self.ffprobe = FFprobeClient(Path(self.cfg.ffprobe_path))

        self._current_future = None  # concurrent.futures.Future
        self._current_task = None    # asyncio.Task（cancel 用）

        self._build_widgets()
        self._restore_settings_to_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(POLL_INTERVAL_MS, self._poll_ui_queue)
        self.refresh_input_list()
        self.refresh_images_list()
        self._detect_encoder_async()

    # ----------------------- UI 構築 -----------------------
    def _build_widgets(self) -> None:
        pad = {"padx": 6, "pady": 4}

        top = ttk.LabelFrame(self.root, text="設定")
        top.pack(fill="x", **pad)

        self.var_images_dir = tk.StringVar()
        self.var_input_dir = tk.StringVar()
        self.var_output_dir = tk.StringVar()
        self.var_resolution = tk.StringVar()
        self.var_fit = tk.StringVar()
        self.var_bitrate = tk.IntVar()
        self.var_encoder_mode = tk.StringVar()
        self.var_cpu_threads = tk.IntVar()
        self.var_encoder_status = tk.StringVar(value="検出中...")

        self._row_path(top, 0, "画像フォルダ", self.var_images_dir, self._browse_images_dir, refresh=True)
        self._row_path(top, 1, "入力フォルダ", self.var_input_dir, self._browse_input_dir, refresh=True)
        self._row_path(top, 2, "出力フォルダ", self.var_output_dir, self._browse_output_dir)

        opts = ttk.Frame(top)
        opts.grid(row=3, column=0, columnspan=4, sticky="we", padx=6, pady=4)
        ttk.Label(opts, text="解像度:").pack(side="left")
        ttk.Combobox(
            opts, textvariable=self.var_resolution,
            values=list(RESOLUTION_PRESETS.keys()), width=8, state="readonly",
        ).pack(side="left", padx=(2, 12))
        ttk.Label(opts, text="フィット:").pack(side="left")
        ttk.Combobox(
            opts, textvariable=self.var_fit, values=list(FIT_MODES),
            width=8, state="readonly",
        ).pack(side="left", padx=(2, 12))
        ttk.Label(opts, text="音質(kbps):").pack(side="left")
        ttk.Spinbox(opts, from_=96, to=512, increment=32, textvariable=self.var_bitrate, width=6).pack(side="left", padx=(2, 12))

        opts2 = ttk.Frame(top)
        opts2.grid(row=4, column=0, columnspan=4, sticky="we", padx=6, pady=4)
        ttk.Label(opts2, text="エンコーダ:").pack(side="left")
        encoder_cmb = ttk.Combobox(
            opts2, textvariable=self.var_encoder_mode,
            values=list(ENCODER_MODES), width=6, state="readonly",
        )
        encoder_cmb.pack(side="left", padx=(2, 6))
        encoder_cmb.bind("<<ComboboxSelected>>", lambda _e: self._detect_encoder_async())
        ttk.Label(opts2, textvariable=self.var_encoder_status, foreground="#0a0").pack(side="left", padx=(0, 16))
        ttk.Label(opts2, text=f"CPUスレッド (論理{CPU_LOGICAL}):").pack(side="left")
        ttk.Spinbox(opts2, from_=1, to=CPU_LOGICAL, textvariable=self.var_cpu_threads, width=4).pack(side="left", padx=(2, 4))

        top.columnconfigure(1, weight=1)

        # 画像一覧 + 音声ファイル一覧（横並び）
        mid_container = ttk.Frame(self.root)
        mid_container.pack(fill="both", expand=True, **pad)

        img_frame = ttk.LabelFrame(mid_container, text="画像一覧")
        img_frame.pack(side="left", fill="both", expand=True, padx=(0, 3))
        self.image_table = ImageFileTable(img_frame)
        self.image_table.pack(fill="both", expand=True, padx=4, pady=4)
        ttk.Button(img_frame, text="再読込", command=self.refresh_images_list).pack(
            side="left", padx=4, pady=4
        )

        audio_frame = ttk.LabelFrame(mid_container, text="音声ファイル一覧")
        audio_frame.pack(side="right", fill="both", expand=True, padx=(3, 0))
        self.audio_table = AudioFileTable(audio_frame)
        self.audio_table.pack(fill="both", expand=True, padx=4, pady=4)
        btns = ttk.Frame(audio_frame)
        btns.pack(fill="x", padx=4, pady=4)
        self.btn_convert = ttk.Button(btns, text="変換 ▶", command=self._start_conversion)
        self.btn_convert.pack(side="left")
        ttk.Button(btns, text="出力フォルダを開く", command=self._open_output_dir).pack(side="left", padx=4)

        # 進捗
        self.progress = ProgressPanel(self.root, on_cancel=self._cancel_conversion)
        self.progress.pack(fill="x", **pad)

        # ログ
        log_frame = ttk.LabelFrame(self.root, text="ログ")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=8, wrap="none")
        self.log_text.pack(fill="both", expand=True, side="left")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scroll.set, state="disabled")

    def _row_path(
        self, parent: ttk.Widget, row: int, label: str, var: tk.StringVar,
        browse_cb, refresh: bool = False,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="we", padx=6, pady=2)
        ttk.Button(parent, text="参照", command=browse_cb).grid(row=row, column=2, padx=2, pady=2)
        if refresh:
            ttk.Button(parent, text="再読込", command=self.refresh_input_list).grid(row=row, column=3, padx=2, pady=2)

    def _restore_settings_to_widgets(self) -> None:
        self.var_images_dir.set(self.cfg.images_dir)
        self.var_input_dir.set(self.cfg.input_dir)
        self.var_output_dir.set(self.cfg.output_dir)
        self.var_resolution.set(self.cfg.resolution)
        self.var_fit.set(self.cfg.fit_mode)
        self.var_bitrate.set(self.cfg.audio_bitrate_kbps)
        self.var_encoder_mode.set(self.cfg.encoder_mode)
        self.var_cpu_threads.set(self.cfg.cpu_threads)

    def _capture_settings_from_widgets(self) -> None:
        self.cfg.images_dir = self.var_images_dir.get()
        self.cfg.input_dir = self.var_input_dir.get()
        self.cfg.output_dir = self.var_output_dir.get()
        self.cfg.resolution = self.var_resolution.get()
        self.cfg.fit_mode = self.var_fit.get()
        try:
            self.cfg.audio_bitrate_kbps = int(self.var_bitrate.get())
        except (tk.TclError, ValueError):
            pass
        self.cfg.encoder_mode = self.var_encoder_mode.get() or "auto"
        try:
            self.cfg.cpu_threads = max(1, int(self.var_cpu_threads.get()))
        except (tk.TclError, ValueError):
            pass

    # ----------------------- ファイル参照 -----------------------
    def _browse_images_dir(self) -> None:
        path = filedialog.askdirectory(
            title="画像フォルダを選択",
            initialdir=self.var_images_dir.get() or str(Path.home()),
        )
        if path:
            self.var_images_dir.set(path)
            self.refresh_images_list()

    def refresh_images_list(self) -> None:
        images_dir = Path(self.var_images_dir.get())
        if not images_dir.is_dir():
            self.image_table.populate([])
            if self.var_images_dir.get().strip():
                self._append_log(f"[警告] 画像フォルダが見つかりません: {images_dir}")
            return
        files = sorted(
            p for p in images_dir.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTS
        )
        self.image_table.populate(files)

    def _browse_input_dir(self) -> None:
        path = filedialog.askdirectory(title="入力フォルダを選択", initialdir=self.var_input_dir.get())
        if path:
            self.var_input_dir.set(path)
            self.refresh_input_list()

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="出力フォルダを選択", initialdir=self.var_output_dir.get())
        if path:
            self.var_output_dir.set(path)

    # ----------------------- 入力一覧 -----------------------
    def refresh_input_list(self) -> None:
        input_dir = Path(self.var_input_dir.get())
        if not input_dir.is_dir():
            self.audio_table.populate([])
            if self.var_input_dir.get().strip():
                self._append_log(f"[警告] 入力フォルダが見つかりません: {input_dir}")
            return
        files = sorted(
            p for p in input_dir.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_AUDIO_EXTS
        )
        self.audio_table.populate([(p, None) for p in files])
        for p in files:
            self.bridge.submit_coro(self._probe_and_post(p))

    async def _probe_and_post(self, path: Path) -> None:
        try:
            us = await self.ffprobe.duration_us(path)
        except Exception:
            us = None
        self.bridge.post_to_ui({"type": "duration", "path": str(path), "duration_us": us})

    # ----------------------- エンコーダ検出 -----------------------
    def _detect_encoder_async(self) -> None:
        self._capture_settings_from_widgets()
        self.converter = FFmpegConverter(self.cfg)
        self.var_encoder_status.set("検出中...")
        self.bridge.submit_coro(self._detect_encoder_coro())

    async def _detect_encoder_coro(self) -> None:
        try:
            enc = await self.converter.resolve_encoder()
            label = ENCODER_LABEL.get(enc, enc)
        except Exception as exc:
            label = f"検出失敗: {exc}"
        self.bridge.post_to_ui({"type": "encoder_detected", "label": label})

    # ----------------------- 変換実行 -----------------------
    def _start_conversion(self) -> None:
        if self._current_future is not None and not self._current_future.done():
            messagebox.showinfo("実行中", "別の変換が実行中です。")
            return

        image_path = self.image_table.selected_path()
        if image_path is None or not image_path.exists():
            messagebox.showwarning("画像未選択", "画像一覧からジャケット画像を選択してください。")
            return
        audio = self.audio_table.selected_path()
        if audio is None:
            messagebox.showinfo("未選択", "音声ファイルを1つ選択してください。")
            return
        output_dir = Path(self.var_output_dir.get())
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("出力フォルダ作成失敗", str(exc))
            return

        self._capture_settings_from_widgets()
        self.cfg.save()
        self.converter = FFmpegConverter(self.cfg)

        job = ConversionJob(
            image_path=image_path,
            audio_path=audio,
            output_path=output_dir / (audio.stem + ".mp4"),
            resolution=self.cfg.resolution,
            fit_mode=self.cfg.fit_mode,
            audio_bitrate_kbps=self.cfg.audio_bitrate_kbps,
            background_color=self.cfg.background_color,
            cpu_threads=self.cfg.cpu_threads,
        )
        self.btn_convert.configure(state="disabled")
        self.progress.begin(job.output_path.name)
        self._append_log(f"=== 変換開始: {job.output_path.name} ===")
        try:
            self._current_future = self.bridge.submit_coro(self._run_job(job))
        except Exception as exc:
            self._current_future = None
            self.btn_convert.configure(state="normal")
            messagebox.showerror("変換開始エラー", str(exc))
            return

    async def _run_job(self, job: ConversionJob) -> None:
        self._current_task = asyncio.current_task()
        try:
            def on_progress(p: float) -> None:
                self.bridge.post_to_ui({"type": "progress", "progress": p})

            def on_log(line: str) -> None:
                self.bridge.post_to_ui({"type": "log", "name": job.output_path.name, "line": line})

            try:
                await self.converter.run(job, on_progress, on_log)
                job.status = JobStatus.DONE
                job.progress = 1.0
            except asyncio.CancelledError:
                job.status = JobStatus.CANCELLED
                job.error = "cancelled"
                try:
                    if job.output_path.exists():
                        job.output_path.unlink()
                except OSError:
                    pass
                self.bridge.post_to_ui({"type": "finish", "job": job})
                raise
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = str(exc)
        finally:
            self._current_task = None
            self.bridge.post_to_ui({"type": "finish", "job": job})

    def _cancel_conversion(self) -> None:
        task = self._current_task
        if task is None:
            return
        self.bridge.loop.call_soon_threadsafe(task.cancel)

    def _open_output_dir(self) -> None:
        path = Path(self.var_output_dir.get())
        if not path.exists():
            return
        if sys.platform.startswith("win"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    # ----------------------- async → UI poll -----------------------
    def _poll_ui_queue(self) -> None:
        try:
            while True:
                msg = self.bridge.ui_queue.get_nowait()
                self._handle_ui_msg(msg)
        except queue.Empty:
            pass
        finally:
            self.root.after(POLL_INTERVAL_MS, self._poll_ui_queue)

    def _handle_ui_msg(self, msg: dict[str, Any]) -> None:
        t = msg.get("type")
        if t == "progress":
            self.progress.update_progress(msg["progress"])
        elif t == "log":
            self._append_log(f"[{msg['name']}] {msg['line']}")
        elif t == "duration":
            self.audio_table.update_duration(Path(msg["path"]), msg["duration_us"])
        elif t == "encoder_detected":
            self.var_encoder_status.set(f"→ {msg['label']}")
        elif t == "finish":
            job: ConversionJob = msg["job"]
            self.progress.finish(job.status, job.output_path.name, job.error)
            self._append_log(f"=== 終了: {job.status.value} ({job.output_path.name}) ===")
            self.btn_convert.configure(state="normal")
            self._current_future = None

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ----------------------- 終了処理 -----------------------
    def _on_close(self) -> None:
        self._capture_settings_from_widgets()
        self.cfg.save()
        if self._current_task is not None:
            self.bridge.loop.call_soon_threadsafe(self._current_task.cancel)
        self.bridge.shutdown()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
