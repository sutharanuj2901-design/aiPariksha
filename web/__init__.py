"""Dependency-free local web UI."""

from __future__ import annotations

from .server import PaperStore, serve

__all__ = ["PaperStore", "serve"]
