# CLAUDE.md

このファイルは Claude Code がこのリポジトリで作業する際のガイドです。

## プロジェクト概要
ジャケット画像 + 音声 → YouTube 向け MP4 変換ツール。Python 3.10+ / Tkinter / asyncio
で実装された GUI アプリケーション。1 ジョブずつ順次変換するシンプル構成。
外部 PyPI 依存なし、標準ライブラリと FFmpeg
（`D:\develop\ffmpeg-master-latest-win64-gpl-shared\bin\`）のみで動作。

## アーキテクチャ

### スレッドモデル
2 スレッドモデル。両者は thread-safe な `queue.Queue` と
`asyncio.run_coroutine_threadsafe` で疎結合。

```
┌─ Main Thread (Tkinter) ─┐         ┌─ AsyncBridgeLoop Thread ─┐
│  App.root.mainloop()    │         │  asyncio.run_forever()   │
│  100ms 毎 ui_queue poll │ ←msg─── │  FFmpegConverter.run()   │
│  ボタン → submit_coro   │ ──coro→ │  EncoderProbe / FFprobe  │
└─────────────────────────┘         └──────────────────────────┘
```

GUI 側は常にメインスレッドからのみ Tkinter API を呼ぶ。async 側は ffmpeg を
`create_subprocess_exec` で起動し、進捗とログを `bridge.post_to_ui()` 経由で送る。

### モジュール責務（OOP）
| ファイル | クラス | 責務 |
|----------|--------|------|
| `config.py` | `AppConfig` (dataclass) | 設定値と JSON 永続化。`load()` / `save()` |
| `jobs.py` | `ConversionJob`, `JobStatus` | ジョブ表現（dataclass + enum） |
| `converter.py` | `FFmpegConverter`, `FFprobeClient`, `EncoderProbe`, `VideoFilterBuilder`, `FFmpegError` | FFmpeg 呼び出しの抽象化 |
| `async_bridge.py` | `AsyncBridge` | asyncio ループを別スレッドで動かす橋渡し |
| `gui.py` | `App`, `AudioFileTable`, `ProgressPanel` | Tkinter GUI |
| `main.py` | – | `App().run()` を呼ぶだけのエントリ |

キュー機能は廃止済み。1 度に走るジョブは常に 1 件のみ。

### エンコーダ選択ロジック
`FFmpegConverter.resolve_encoder()` が最終的に使うエンコーダを決定する。

```
encoder_mode = "auto" → EncoderProbe.has_nvenc() を実機テスト
                       (color=lavfi → h264_nvenc → null) で成功なら "gpu", 失敗なら "cpu"
encoder_mode = "gpu"  → 強制 "gpu"
encoder_mode = "cpu"  → 強制 "cpu"
```

`EncoderProbe` は結果をインスタンス内にキャッシュするので 1 起動あたり 1 回しか実行しない。
GUI でエンコーダモードを変えると `App._detect_encoder_async()` が新しい `Probe` で再検出する。

### ffmpeg 引数
- 共通: `-threads N -loop 1 -framerate 2 -i image -i audio -vf <filter> -r 30 -c:a aac -b:a Xk -ar 48000 -ac 2 -movflags +faststart -shortest -progress pipe:1 -nostats`
- GPU: `-c:v h264_nvenc -preset p6 -tune hq -rc vbr -cq 19 -b:v 8M -maxrate 12M -bufsize 16M -spatial-aq 1 -temporal-aq 1 -rc-lookahead 20 -pix_fmt yuv420p`
- CPU: `-c:v libx264 -tune stillimage -preset medium -crf 18 -pix_fmt yuv420p`

`-progress pipe:1 -nostats` は進捗パースに必須なので残すこと。

### コンソール非表示
- ffmpeg / ffprobe を起動する全ての `create_subprocess_exec` で
  `creationflags=subprocess.CREATE_NO_WINDOW` を渡す（Windows のみ）。
  定数は `converter.py` の `_NO_WINDOW_FLAGS` に集約。
- アプリ自体は `pythonw.exe` で起動する（`run.bat` / `run.vbs`）。
  `run.vbs` は WScript 経由で完全コンソールレス起動。

### キャンセル処理
- `App._cancel_conversion()` → `loop.call_soon_threadsafe(task.cancel)` で
  実行中の `_run_job` タスクをキャンセル
- `FFmpegConverter.run()` 内で `except CancelledError` → `proc.terminate()`
  → 5 秒待って `proc.kill()`
- `App._run_job` の except で出力済み MP4 を `unlink()`

## 開発コマンド

```powershell
# 起動（コンソール非表示）
.\run.vbs
# または
.\run.bat
# またはターミナルから
pythonw -m src.main

# モジュール import チェック
python -c "from src import config, jobs, converter, async_bridge, gui, main; print('OK')"

# E2E テスト用ダミー素材生成（FFmpeg 経由）
$F = "D:\develop\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
& $F -y -f lavfi -i "color=c=blue:s=640x360:d=1" -frames:v 1 ".\images\test.png"
& $F -y -f lavfi -i "sine=frequency=440:duration=3" ".\input\_test.mp3"

# NVENC 動作確認
& $F -hide_banner -loglevel error -f lavfi -i "color=c=black:s=320x240:d=0.1" -c:v h264_nvenc -f null -
# 戻り値 0 なら NVENC 利用可
```

## 拡張時の注意

### 新機能を追加するとき
- **GUI から非同期処理を呼ぶ**: 必ず `self.bridge.submit_coro(coro)` を経由する
- **async から GUI を更新する**: 必ず `self.bridge.post_to_ui({...})` 経由
- **新しいサブプロセス起動**: `_NO_WINDOW_FLAGS` を `creationflags` に渡すこと

### ffmpeg 引数を変更するとき
`FFmpegConverter._build_args()` を編集。GPU/CPU で分岐している部分に注意。
共通部分（前後）と video_args（中央）が分離されているので個別に変更可能。

### フィルタを増やすとき
`VideoFilterBuilder.build()` に分岐を追加し、`config.py` の `FIT_MODES` にも追加。
GPU 経路でも CPU 側で組まれた `-vf` がそのまま使われる（NVENC は CPU フレームを受け入れる）。

### キュー機能を再導入したい場合
削除済みなので git history から `AsyncJobQueue` の旧実装を復元できる。再導入する場合は
`gui.py` の `_run_job` 周辺と AudioFileTable の `selectmode="extended"` 化、
`JobQueueTable` の追加が必要。

## 既知の設計判断
- **外部依存なし**: `pip install` 不要にするため Pillow / psutil 等は使わず
  `os.cpu_count()` で論理コア数を取得
- **画像 1 枚共通**: 1 ジョブ = 1 画像 + 1 音声。複数画像対応は未実装
- **dataclass + JSON**: 設定永続化は `dataclasses.asdict` + `json` のみで済むよう
  プリミティブ型に限定
- **エンコーダ検出は実機テスト**: `ffmpeg -encoders` の文字列マッチでなく
  実際に `h264_nvenc` で 1 フレームエンコードして判定（ドライバ未対応や
  GPU 不在も含めて確実に判定できる）
- **同期 I/O は最小限**: `Path.exists()` / `mkdir` のような瞬間で終わるものだけ
  同期、ffmpeg / ffprobe は必ず `create_subprocess_exec` で非同期化

## ファイル変更時のチェック
1. `python -c "from src import ..."` でインポートエラーなし
2. `App().run()` で GUI が立ち上がること（`after()` で自動 close するスモークテスト）
3. ダミー素材で 1 件変換して MP4 生成 + 進捗が 1.0 に到達することを確認
4. `encoder_mode = "gpu"` と `"cpu"` 両方で変換成功することを確認
