"""Plugin Market paths + shared helpers."""

from __future__ import annotations

from pathlib import Path


def backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def market_data() -> Path:
    d = backend_root() / "data" / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    return d


def installed_root() -> Path:
    d = market_data() / "installed"
    d.mkdir(parents=True, exist_ok=True)
    return d


def catalog_path() -> Path:
    return market_data() / "catalog.json"


def trust_path() -> Path:
    return market_data() / "trust.json"


def scaffold_root() -> Path:
    d = market_data() / "dev"
    d.mkdir(parents=True, exist_ok=True)
    return d
