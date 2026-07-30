"""Optional native microphone background listener (local, free).

Uses sounddevice if installed; otherwise no-op (browser mic remains primary).
"""

from __future__ import annotations

import threading
from typing import Callable

import numpy as np


_listener_thread: threading.Thread | None = None
_stop = threading.Event()


def available() -> bool:
    try:
        import sounddevice  # noqa: F401
        return True
    except Exception:
        return False


def start_background(on_pcm: Callable[[np.ndarray], None], *, sample_rate: int = 16000) -> str:
    """Start capturing mic PCM in a daemon thread. on_pcm receives float32 mono chunks."""
    global _listener_thread
    if not available():
        return "Native mic unavailable (install sounddevice). Use the browser/Electron mic."
    if _listener_thread and _listener_thread.is_alive():
        return "Native mic already listening."

    _stop.clear()

    def _run():
        import sounddevice as sd
        block = int(sample_rate * 0.064)  # ~64ms

        def callback(indata, frames, time_info, status):
            if _stop.is_set():
                raise sd.CallbackStop()
            mono = indata[:, 0].astype(np.float32).copy() if indata.ndim > 1 else indata.astype(np.float32).copy()
            try:
                on_pcm(mono)
            except Exception as exc:
                print(f"[mic] callback error: {exc}", flush=True)

        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=block,
            callback=callback,
        ):
            print("[mic] native background listening started", flush=True)
            while not _stop.wait(0.2):
                pass
        print("[mic] native listening stopped", flush=True)

    _listener_thread = threading.Thread(target=_run, daemon=True, name="neuron-mic")
    _listener_thread.start()
    return "Native mic listening."


def stop_background() -> str:
    _stop.set()
    return "Native mic stopped."
