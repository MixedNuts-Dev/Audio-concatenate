from __future__ import annotations

import asyncio
import concurrent.futures
import queue
import threading
from collections.abc import Awaitable, Callable
from typing import Any, Optional


class AsyncBridge:
    """専用スレッドで asyncio イベントループを動かし、Tkinter スレッドとの
    やり取りをスレッドセーフに仲介するブリッジ。

    - GUI スレッド → async: ``submit_coro`` でコルーチンをループに投入
    - async → GUI スレッド: ``post_to_ui`` で UI キューに投函し、GUI 側は
      ``ui_queue.get_nowait()`` を ``after()`` で定期 poll
    """

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self.ui_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run_loop, name="AsyncBridgeLoop", daemon=True
        )
        self._thread.start()
        self._ready.wait()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.set_exception_handler(self._handle_loop_exception)
        self._ready.set()
        try:
            self.loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(self.loop)
                for t in pending:
                    t.cancel()
                if pending:
                    self.loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            finally:
                self.loop.close()

    @staticmethod
    def _handle_loop_exception(
        loop: asyncio.AbstractEventLoop, context: dict[str, Any]
    ) -> None:
        import sys as _sys
        import traceback as _tb
        msg = context.get("message", "Unhandled exception in async loop")
        exc = context.get("exception")
        if exc is not None:
            print(f"[AsyncBridge] {msg}", file=_sys.stderr)
            _tb.print_exception(type(exc), exc, exc.__traceback__, file=_sys.stderr)
        else:
            print(f"[AsyncBridge] {msg}: {context}", file=_sys.stderr)

    def submit_coro(self, coro: Awaitable[Any]) -> concurrent.futures.Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def post_to_ui(self, msg: dict[str, Any]) -> None:
        """async 側から呼んで GUI スレッドにメッセージを送る。"""
        self.ui_queue.put(msg)

    def shutdown(self, timeout: float = 10.0) -> None:
        if self._thread is None:
            return
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=timeout)
        self._thread = None
