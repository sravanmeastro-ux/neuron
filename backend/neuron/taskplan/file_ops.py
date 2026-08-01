"""File helpers used by desktop folder workflows (registered as tools)."""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

from neuron.windows.result import fail, ok


def _desktop() -> Path:
    return Path.home() / "Desktop"


def _base(location: str) -> Path:
    loc = (location or "desktop").strip().lower()
    if loc in ("desktop", "desk"):
        return _desktop()
    if loc in ("documents", "docs"):
        return Path.home() / "Documents"
    if loc in ("downloads",):
        return Path.home() / "Downloads"
    p = Path(os.path.expandvars(os.path.expanduser(location)))
    return p if p.is_dir() else _desktop()


def task_move_files(args: dict | None = None):
    """Move files matching pattern into dest folder under location."""
    args = args or {}
    pattern = (args.get("pattern") or "*.pdf").strip()
    dest_name = (args.get("dest") or args.get("folder") or "Projects").strip()
    location = (args.get("location") or "desktop").strip()
    base = _base(location)
    dest = base / dest_name
    try:
        dest.mkdir(parents=True, exist_ok=True)
        moved = []
        for src in base.glob(pattern):
            if not src.is_file():
                continue
            if src.parent.resolve() == dest.resolve():
                continue
            target = dest / src.name
            shutil.move(str(src), str(target))
            moved.append(src.name)
        if not moved:
            return ok(f"No files matching {pattern} on {base.name}.", state={"moved": []})
        return ok(
            f"Moved {len(moved)} file(s) into {dest_name}.",
            state={"moved": moved, "dest": str(dest)},
            method="filesystem",
        )
    except Exception as exc:
        return fail(str(exc))


def task_zip_folder(args: dict | None = None):
    """Zip a folder under Desktop/Documents into sibling .zip."""
    args = args or {}
    name = (args.get("name") or args.get("folder") or "Projects").strip()
    location = (args.get("location") or "desktop").strip()
    base = _base(location)
    folder = base / name
    if not folder.is_dir():
        return fail(f"Folder not found: {folder}")
    zip_path = base / f"{name}.zip"
    try:
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(folder):
                for fn in files:
                    full = Path(root) / fn
                    zf.write(full, arcname=str(full.relative_to(folder.parent)))
        return ok(f"Created {zip_path.name}.", state={"path": str(zip_path)}, method="filesystem")
    except Exception as exc:
        return fail(str(exc))
