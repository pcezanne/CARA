"""Data containers for Chess Log PDF export snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import chess


@dataclass
class TagRowSnapshot:
    """Immutable snapshot of one _TagRowWidget's current state for PDF export."""

    move_label: str
    preset: str
    entries: List[Dict[str, Any]]
    fen: Optional[str]
    played_move: Optional[chess.Move]
    show_ignore: bool
    best_move: Optional[chess.Move] = field(default=None)
