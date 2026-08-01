"""Lightweight local embeddings — hashed token/char n-grams (numpy only).

No model download. Typical latency < 2ms per utterance.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

import numpy as np

_DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)


def _hash_idx(token: str, salt: str = "") -> int:
    h = hashlib.blake2b(f"{salt}{token}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h, "little") % _DIM


def embed_text(text: str) -> np.ndarray:
    """Unit-normalized bag-of-features vector."""
    t = (text or "").lower().strip()
    vec = np.zeros(_DIM, dtype=np.float32)
    if not t:
        return vec
    tokens = _TOKEN_RE.findall(t)
    for tok in tokens:
        vec[_hash_idx(tok, "t")] += 1.0
        if len(tok) >= 3:
            for i in range(len(tok) - 2):
                vec[_hash_idx(tok[i : i + 3], "c3")] += 0.35
    # bigrams
    for a, b in zip(tokens, tokens[1:]):
        vec[_hash_idx(f"{a}_{b}", "b")] += 0.8
    n = float(np.linalg.norm(vec))
    if n > 1e-8:
        vec /= n
    return vec


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None:
        return 0.0
    return float(np.dot(a, b))


@lru_cache(maxsize=128)
def embed_cached(text: str) -> tuple[float, ...]:
    return tuple(float(x) for x in embed_text(text))


def embed_from_cache(text: str) -> np.ndarray:
    return np.asarray(embed_cached(text), dtype=np.float32)
