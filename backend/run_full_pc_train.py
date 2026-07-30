"""Run a full PC inventory + deep learn (background-safe wait)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pc_trainer  # noqa: E402


def main():
    print(pc_trainer.start_training(deep_learn=True, deep_limit=40, force_refresh=True))
    # Keep process alive while daemon worker runs
    while True:
        s = pc_trainer.status()
        phase = s.get("phase")
        print(
            f"[status] phase={phase} apps={s.get('scanned_apps')} "
            f"folders={s.get('scanned_folders')} learned={s.get('learned')} "
            f"queued={s.get('queued')} err={s.get('last_error') or '-'}",
            flush=True,
        )
        if not s.get("running") and phase in ("done", "error", "idle"):
            print(pc_trainer.status_report(), flush=True)
            break
        time.sleep(8)


if __name__ == "__main__":
    main()
