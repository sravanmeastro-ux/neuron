"""Scoped preferences for personalization (not a second memory system).

Priority (highest first):
  explicit task instruction
  → explicit procedure preference
  → explicit domain preference
  → explicit global preference
  → inferred preference
  → system default

Uses PersistentMemory allowlist for durable keys.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from neuron.v4.learn.types import Preference, PreferenceScope

log = logging.getLogger("neuron.v4.learn")

_PREFS: "PreferenceStore | None" = None

# Inferred prefs need repeated evidence before ranking influence
MIN_INFERRED_EVIDENCE = 5


class PreferenceStore:
    def __init__(self) -> None:
        self._items: list[Preference] = []
        self._inferred_counts: dict[str, int] = {}

    def set_explicit(
        self,
        key: str,
        value: str,
        *,
        scope: PreferenceScope = PreferenceScope.GLOBAL,
        domain: str = "",
        procedure_id: str = "",
        durable: bool = True,
    ) -> tuple[bool, str]:
        pref = Preference(
            key=key,
            value=value,
            scope=scope,
            domain=domain,
            procedure_id=procedure_id,
            explicit=True,
            confidence=1.0,
        )
        self._upsert(pref)
        if durable:
            return self._persist(pref)
        return True, "session-only"

    def note_inferred(self, key: str, value: str, *, domain: str = "") -> Preference | None:
        ck = f"{domain}|{key}|{value}".lower()
        self._inferred_counts[ck] = self._inferred_counts.get(ck, 0) + 1
        count = self._inferred_counts[ck]
        if count < MIN_INFERRED_EVIDENCE:
            return None
        conf = min(0.7, 0.35 + 0.05 * count)
        pref = Preference(
            key=key,
            value=value,
            scope=PreferenceScope.DOMAIN if domain else PreferenceScope.GLOBAL,
            domain=domain,
            explicit=False,
            confidence=conf,
        )
        # Never overwrite explicit
        for existing in self._items:
            if (
                existing.key == key
                and existing.explicit
                and existing.domain == domain
            ):
                return None
        self._upsert(pref)
        log.info("[PREFERENCE] inferred %s=%s conf=%.2f", key, value, conf)
        return pref

    def resolve(
        self,
        key: str,
        *,
        task_value: str | None = None,
        procedure_id: str = "",
        domain: str = "",
        default: str | None = None,
    ) -> tuple[str | None, str]:
        """Return (value, source_label)."""
        if task_value is not None and str(task_value).strip() != "":
            return str(task_value), "task_instruction"

        # procedure-scoped explicit
        for p in self._items:
            if (
                p.key == key
                and p.explicit
                and p.scope is PreferenceScope.PROCEDURE
                and procedure_id
                and p.procedure_id == procedure_id
            ):
                return p.value, "procedure_explicit"

        # domain-scoped explicit
        for p in self._items:
            if (
                p.key == key
                and p.explicit
                and p.scope is PreferenceScope.DOMAIN
                and domain
                and p.domain.lower() == domain.lower()
            ):
                return p.value, "domain_explicit"

        # global explicit
        for p in self._items:
            if p.key == key and p.explicit and p.scope is PreferenceScope.GLOBAL:
                return p.value, "global_explicit"

        # inferred (weaker)
        best: Preference | None = None
        for p in self._items:
            if p.key != key or p.explicit:
                continue
            if domain and p.domain and p.domain.lower() != domain.lower():
                continue
            if best is None or p.confidence > best.confidence:
                best = p
        if best:
            return best.value, "inferred"

        return default, "system_default"

    def list_all(self) -> list[Preference]:
        return list(self._items)

    def _upsert(self, pref: Preference) -> None:
        self._items = [
            p for p in self._items
            if not (
                p.key == pref.key
                and p.scope is pref.scope
                and p.domain == pref.domain
                and p.procedure_id == pref.procedure_id
                and p.explicit == pref.explicit
            )
        ]
        self._items.append(pref)
        if len(self._items) > 80:
            self._items = self._items[-80:]

    def _persist(self, pref: Preference) -> tuple[bool, str]:
        try:
            from neuron.memory import persistent
            key = f"pref.{pref.scope.value.lower()}.{pref.key}"
            if pref.domain:
                key = f"pref.{pref.domain}.{pref.key}"
            if pref.procedure_id:
                key = f"pref.proc.{pref.procedure_id}.{pref.key}"
            ok, msg = persistent().remember(key, pref.value)
            if ok:
                log.info("[PREFERENCE] durable %s=%s", key, pref.value[:40])
            return ok, msg
        except Exception as exc:
            return False, str(exc)

    def load_durable(self) -> int:
        """Best-effort hydrate from PersistentMemory common keys."""
        n = 0
        try:
            from neuron.memory import persistent
            mem = persistent()
            for key in (
                "pref.global.browser",
                "preferred_browser",
                "pref.browser",
                "default_browser",
            ):
                val = mem.recall(key)
                if val:
                    self.set_explicit("browser", val, durable=False)
                    n += 1
        except Exception:
            pass
        return n


def get_preference_store() -> PreferenceStore:
    global _PREFS
    if _PREFS is None:
        _PREFS = PreferenceStore()
        try:
            _PREFS.load_durable()
        except Exception:
            pass
    return _PREFS


def reset_preference_store() -> PreferenceStore:
    global _PREFS
    _PREFS = PreferenceStore()
    return _PREFS


__all__ = [
    "PreferenceStore",
    "get_preference_store",
    "reset_preference_store",
    "MIN_INFERRED_EVIDENCE",
]
