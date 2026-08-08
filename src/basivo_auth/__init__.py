"""basivo-auth: scaffold production-hardened FastAPI authentication services."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("basivo-auth")
except PackageNotFoundError:  # pragma: no cover - only when running from a raw checkout
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
