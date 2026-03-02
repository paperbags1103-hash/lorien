"""Concurrency layer for lorien — safe multi-agent/multi-thread DB access.

KuzuDB supports concurrent reads but only one writer at a time.
WriteQueue serializes all write operations through a single thread,
while reads happen directly (no lock needed).
"""
from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable


class WriteQueue:
    """Thread-safe write serializer for KuzuDB.

    Spawns a single background worker thread. Write callables are
    submitted via submit() and executed in FIFO order. Results are
    delivered through Future objects so callers can await them.

    Usage:
        wq = WriteQueue()
        future = wq.submit(lambda: store.add_fact(fact))
        result = future.result(timeout=5.0)  # blocks until done
        wq.shutdown()
    """

    def __init__(self, maxsize: int = 500) -> None:
        self._q: queue.Queue[tuple[Callable, Future] | None] = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._closed = False
        self._worker = threading.Thread(target=self._run, daemon=True, name="lorien-write-worker")
        self._worker.start()

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:          # shutdown sentinel
                self._q.task_done()
                break
            fn, future = item
            try:
                result = fn()
                future.set_result(result)
            except Exception as exc:
                future.set_exception(exc)
            finally:
                self._q.task_done()

    def submit(self, fn: Callable[[], Any]) -> Future:
        """Enqueue a write operation. Returns a Future for the result.

        Raises:
            RuntimeError: if the queue has been shut down.
            queue.Full: if the queue is at capacity.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("WriteQueue is shut down")
            future: Future = Future()
            self._q.put((fn, future))
            return future

    def submit_sync(self, fn: Callable[[], Any], timeout: float = 30.0) -> Any:
        """Submit and block until the operation completes."""
        return self.submit(fn).result(timeout=timeout)

    def queue_size(self) -> int:
        return self._q.qsize()

    def shutdown(self, wait: bool = True) -> None:
        """Stop accepting new work and optionally drain the queue."""
        with self._lock:
            self._closed = True
            self._q.put(None)
        if wait:
            self._worker.join(timeout=10.0)

    def __enter__(self) -> "WriteQueue":
        return self

    def __exit__(self, *_: Any) -> None:
        self.shutdown()
