"""Streaming LLM responses — token/chunk iterator over local Ollama."""

from __future__ import annotations

import json
from typing import Iterator


def stream_llm(prompt: str, *, system: str = "") -> Iterator[dict]:
    """
    Yield {type: llm_token|llm_done|llm_error, text/delta}.
    Uses existing llm config; no rewrite of planners.
    """
    text = (prompt or "").strip()
    if not text:
        yield {"type": "llm_done", "text": ""}
        return
    try:
        import json as _json
        from pathlib import Path
        import urllib.request

        cfg = _json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
        )
        llm = cfg.get("llm") or {}
        if not llm.get("enabled", True):
            yield {"type": "llm_done", "text": "", "skipped": True}
            return
        base = str(llm.get("base_url") or "http://localhost:11434/v1").rstrip("/")
        # Prefer native Ollama stream for lower latency
        ollama = base.replace("/v1", "")
        model = llm.get("model") or "qwen3:14b"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": text})
        body = _json.dumps({
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": float(llm.get("temperature", 0.1) or 0.1),
                "num_predict": int(llm.get("num_predict", 140) or 140),
            },
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{ollama}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        full = []
        with urllib.request.urlopen(req, timeout=float(llm.get("timeout_seconds", 18) or 18)) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    obj = _json.loads(line)
                except Exception:
                    continue
                delta = ((obj.get("message") or {}).get("content")) or ""
                if delta:
                    full.append(delta)
                    yield {"type": "llm_token", "delta": delta, "text": "".join(full)}
                if obj.get("done"):
                    break
        yield {"type": "llm_done", "text": "".join(full)}
    except Exception as exc:
        yield {"type": "llm_error", "error": str(exc), "text": ""}
