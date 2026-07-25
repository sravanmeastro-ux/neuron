"""NLU tests — normal speech should stay simple and work."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nlu  # noqa: E402


CASES = [
    # Plain commands stay plain
    ("open chrome", "open chrome"),
    ("close chrome", "close chrome"),
    ("open youtube", "open youtube"),
    ("close notepad", "close notepad"),
    # Tiny normal variations
    ("please open chrome", "open chrome"),
    ("can you open chrome", "open chrome"),
    ("open the chrome", "open chrome"),
    ("close my chrome", "close chrome"),
    ("open google chrome", "open chrome"),
    ("hey neuron open chrome", "open chrome"),
    ("start chrome", "open chrome"),
    ("quit chrome", "close chrome"),
    ("exit chrome", "close chrome"),
    # STT
    ("open crome", "open chrome"),
    ("open you tube", "open youtube"),
    # Confusion traps only
    ("minimize the video", "minimize the video"),
    ("minimize the window", "minimize the window"),
    ("exit fullscreen", "exit fullscreen"),
    ("analyze how steam works", "learn how steam works"),
    ("analyse how chrome works", "learn how chrome works"),
]


def main():
    failed = 0
    for raw, expect in CASES:
        info = nlu.understand(raw)
        got = info["canonical"]
        if got == expect:
            print(f"OK  {raw!r} -> {got!r}")
        else:
            print(f"FAIL {raw!r}\n  expected {expect!r}\n  got      {got!r}")
            failed += 1
    print(f"\n=== NLU: {len(CASES) - failed}/{len(CASES)} passed ===")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
