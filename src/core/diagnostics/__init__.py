"""The diagnostics bundle behind the tray's Copy Diagnostics (issue #1897).

One builder, :func:`build_bundle`, feeds both ``GET /api/v1/diagnostics`` (server up) and
``python3 -m src.core.diagnostics`` (server down, same JSON on stdout).
"""

from src.core.diagnostics.builder import build_bundle

__all__ = ["build_bundle"]
