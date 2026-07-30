"""Install + live-train priority apps for NEURON.

Run:  python run_priority_train.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import priority_apps  # noqa: E402


def main():
    print(priority_apps.install_builtins(force=True), flush=True)
    n = priority_apps.seed_voice_recipes()
    print(f"Seeded {n} voice recipes.", flush=True)
    print("Starting live UI train (may open apps briefly)…", flush=True)
    print(priority_apps.train_live(), flush=True)


if __name__ == "__main__":
    main()
