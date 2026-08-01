"""Production readiness version + paths."""

from __future__ import annotations

from pathlib import Path

PRODUCT_NAME = "N.E.U.R.O.N"
PRODUCT_VERSION = "1.0.0"
API_COMPAT = "4.10"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    d = backend_root() / "data" / "production"
    d.mkdir(parents=True, exist_ok=True)
    return d


def wizard_state_path() -> Path:
    return data_dir() / "wizard_state.json"


def diagnostics_report_path() -> Path:
    return data_dir() / "last_diagnostics.json"


def install_marker_path() -> Path:
    return data_dir() / "install_marker.json"


def release_notes_path() -> Path:
    return data_dir() / "RELEASE_NOTES.md"
