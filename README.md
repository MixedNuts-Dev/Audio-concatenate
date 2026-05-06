# Audio → YouTube動画 変換ツール

ジャケット画像と音声ファイル（FLAC / MP3 / WAV / M4A / AAC / OGG / Opus / WMA）を
組み合わせ、YouTube アップロードに適した MP4（H.264 + AAC, yuv420p, faststart）に
変換する Tkinter 製 GUI アプリケーションです。

## 特長
- **GPU 対応**: NVIDIA GPU が利用可能なら NVENC (`h264_nvenc`) で高速エンコード。
  使えない場合は自動的に CPU (`libx264`) にフォールバック
- **CPU スレッド制御**: 論理コア数の70%を既定値とし、GUI から調整可能
- **非同期処理**: `asyncio` + 専用ワーカスレッドでGUIをブロックせずに変換
- **コンソール非表示**: 起動時もサブプロセス起動時もコンソールウィンドウを表示しない
- **キャンセル対応**: 実行中の変換を途中で安全に中止
- **進捗表示**: ffmpeg の `-progress pipe:1` を読み取って百分率で表示

## 必要環境
- Windows 10 / 11
- Python 3.10 以降（標準ライブラリ `tkinter` が必要）
- FFmpeg (`ffmpeg.exe` / `ffprobe.exe`)
  既定パス: `D:\develop\ffmpeg-master-latest-win64-gpl-shared\bin\`
  別の場所にある場合は `config.json` を編集して再起動
- GPU 利用時: NVIDIA ドライバ + NVENC 対応 GPU

外部 PyPI パッケージは不要です。

## ディレクトリ構成
```
Audio-concatenate\
├── input\            # 音声ファイル投入先（変更可）
├── output\           # MP4 出力先（変更可）
├── images\           # ジャケット画像置き場
├── src\
│   ├── main.py       # エントリポイント
│   ├── gui.py        # Tkinter GUI（App / AudioFileTable / ProgressPanel）
│   ├── async_bridge.py # AsyncBridge: GUI ⇄ asyncio ループ
│   ├── jobs.py       # ConversionJob / JobStatus
│   ├── converter.py  # FFmpegConverter / FFprobeClient / EncoderProbe / VideoFilterBuilder
│   └── config.py     # AppConfig（dataclass + 永続化）
├── config.json       # 起動時に復元される設定（自動生成）
├── run.bat           # 起動用バッチ（pythonw 経由）
└── run.vbs           # 完全コンソールレス起動用（推奨）
```

## 起動方法
1. `input\` フォルダに音声ファイルを置く
2. `images\` フォルダにジャケット画像を置く
3. **`run.vbs`** をダブルクリック（コンソール一切なし）
   - もしくは `run.bat`（一瞬コマンドプロンプトが見える）
   - ターミナルから手動起動するなら `pythonw -m src.main`

## 使い方
1. **ジャケット画像** を「参照」ボタンから選択
2. **入力フォルダ** に音声を置いて「再読込」を押すと一覧が更新される
3. 一覧から音声を **1つ** 選択
4. **解像度 / フィット / 音質 / エンコーダ / CPUスレッド** を設定
5. **「変換 ▶」** を押すと変換開始、進捗バーが伸びていく
6. 必要なら「キャンセル」で中止
7. 完了したら「出力フォルダを開く」で結果を確認

### 設定項目
| 項目 | 値 | 説明 |
|------|----|------|
| 解像度 | `1080p` / `1440p` / `2160p` | 出力解像度 |
| フィット | `pad` / `crop` / `stretch` | 画像が解像度と合わない時の処理 |
| 音質 (kbps) | 96 〜 512 | AAC ビットレート |
| エンコーダ | `auto` / `gpu` / `cpu` | `auto` は NVENC 検出して使い、不可なら CPU |
| CPUスレッド | 1 〜 論理コア数 | ffmpeg の `-threads` 指定 |

設定は終了時に `config.json` に保存され、次回起動時に復元されます。
エンコーダ欄の右側に実際に使われるエンコーダ（GPU / CPU）が表示されます。

## 出力仕様（YouTube向け）
- 動画 (GPU): `h264_nvenc`, preset `p6`, tune `hq`, VBR, cq=19, 8M/12M/16M
- 動画 (CPU): `libx264`, preset `medium`, tune `stillimage`, CRF 18
- 共通: 1920×1080 / 2560×1440 / 3840×2160, yuv420p, 30fps, faststart
- 音声: AAC-LC, 48 kHz, 2ch, 既定 320 kbps
- コンテナ: MP4

## トラブルシューティング
- **「ffmpeg not found」**: `config.json` の `ffmpeg_path` / `ffprobe_path` を実際のパスに修正
- **エンコーダ欄が「検出失敗」**: ffmpeg.exe にアクセスできていない可能性あり
- **GPU 選択時にエラー**: NVENC 対応していない GPU またはドライバ未更新。`auto` か `cpu` に変更
- **音声尺が `?` のまま**: ffprobe が起動できていない可能性あり
- **GUI が固まる**: 変換は別スレッドで動くため通常起きません。ログ欄を確認

## ライセンス
プロジェクト個別利用想定。FFmpeg 自体のライセンス（GPL）には別途従ってください。
