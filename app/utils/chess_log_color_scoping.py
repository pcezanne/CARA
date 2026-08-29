"""Derive the color that just moved from a Chess Log path key.

Path keys are dotted child-index sequences (e.g. "0", "0.0", "0.1.0").
Their length equals the ply count from the root — odd means White just moved,
even (and > 0) means Black just moved.
"""

from __future__ import annotations

from typing import Optional

from app.utils.pgn_variation_path import decode_path


def color_from_path_key(path_key: str) -> Optional[str]:
    """Return ``"white"``, ``"black"``, or ``None`` (root / invalid path).

    Used by ChessLogStatsService to scope tagged moments to the color that
    made the move, without requiring the color to be stored in the entry.
    """
    path = decode_path(path_key)
    if path is None or len(path) == 0:
        return None
    return "white" if len(path) % 2 == 1 else "black"
