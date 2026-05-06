from __future__ import annotations

import sys
import traceback

from .gui import App


def main() -> None:
    try:
        App().run()
    except Exception:
        _fatal(traceback.format_exc())


def _fatal(detail: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "起動エラー",
            f"アプリケーションの起動に失敗しました。\n\n{detail}",
        )
        root.destroy()
    except Exception:
        print(detail, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
