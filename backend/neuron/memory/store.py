"""SQLite store for facts, history, tool runs. Imports legacy JSON once."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "neuron_memory.db"
JSON_MEMORY = Path(__file__).resolve().parent.parent.parent / "memory_store.json"

_initialized = False


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    global _initialized
    conn = _conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS facts (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated TEXT
        );
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            t TEXT,
            role TEXT,
            text TEXT
        );
        CREATE TABLE IF NOT EXISTS tool_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            t TEXT,
            action TEXT,
            args TEXT,
            ok INTEGER,
            detail TEXT
        );
        """
    )
    conn.commit()
    # Import JSON once if facts empty
    n = conn.execute("SELECT COUNT(*) AS c FROM facts").fetchone()["c"]
    if n == 0 and JSON_MEMORY.exists():
        try:
            data = json.loads(JSON_MEMORY.read_text(encoding="utf-8"))
            for k, v in (data.get("facts") or {}).items():
                conn.execute(
                    "INSERT OR REPLACE INTO facts(key,value,updated) VALUES(?,?,?)",
                    (str(k).lower(), str(v), time.strftime("%Y-%m-%dT%H:%M:%S")),
                )
            for h in (data.get("history") or [])[-40:]:
                conn.execute(
                    "INSERT INTO history(t,role,text) VALUES(?,?,?)",
                    (h.get("t") or "", h.get("role") or "", h.get("text") or ""),
                )
            conn.commit()
        except Exception:
            pass
    conn.close()
    _initialized = True


def ensure() -> None:
    if not _initialized:
        init_db()


def remember(key: str, value: str) -> None:
    ensure()
    conn = _conn()
    conn.execute(
        "INSERT OR REPLACE INTO facts(key,value,updated) VALUES(?,?,?)",
        (key.lower().strip(), value.strip(), time.strftime("%Y-%m-%dT%H:%M:%S")),
    )
    conn.commit()
    conn.close()


def recall(key: str) -> str | None:
    ensure()
    conn = _conn()
    row = conn.execute("SELECT value FROM facts WHERE key=?", (key.lower().strip(),)).fetchone()
    conn.close()
    if row:
        return row["value"]
    return None


def log_tool_run(action: str, args: dict, ok: bool, detail: str = "") -> None:
    ensure()
    conn = _conn()
    conn.execute(
        "INSERT INTO tool_runs(t,action,args,ok,detail) VALUES(?,?,?,?,?)",
        (
            time.strftime("%Y-%m-%dT%H:%M:%S"),
            action,
            json.dumps(args or {}, ensure_ascii=False)[:500],
            1 if ok else 0,
            (detail or "")[:500],
        ),
    )
    # Cap
    conn.execute(
        "DELETE FROM tool_runs WHERE id NOT IN (SELECT id FROM tool_runs ORDER BY id DESC LIMIT 200)"
    )
    conn.commit()
    conn.close()


def recent_tool_runs(limit: int = 8) -> list[str]:
    ensure()
    conn = _conn()
    rows = conn.execute(
        "SELECT action, ok, detail FROM tool_runs ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        flag = "ok" if r["ok"] else "FAIL"
        out.append(f"- {r['action']} [{flag}] {r['detail'][:80]}")
    return out
