"""Shared helpers for computing move info from a chess.pgn.Game.

Used by ShowTagsDialog and the Tags Report panel so neither pulls in the other.
"""

from __future__ import annotations

from typing import Optional, Tuple

import chess
import chess.pgn

from app.utils.pgn_variation_path import decode_path, node_at_path


def ply_for_path(pgn_game: Optional[chess.pgn.Game], path) -> int:
    """Return the ply index for *path* within *pgn_game* (0-based from root)."""
    if pgn_game is None:
        return len(path)
    node = node_at_path(pgn_game, path)
    if node is None:
        return len(path)
    try:
        return node.ply()
    except AttributeError:
        pass
    parent = getattr(node, "parent", None)
    if parent is None:
        return len(path)
    pre = parent.board()
    return (pre.fullmove_number - 1) * 2 + (0 if pre.turn == chess.WHITE else 1)


def node_info(
    pgn_game: Optional[chess.pgn.Game],
    path_key: str,
) -> Tuple[str, Optional[chess.Move], str]:
    """Return (fen_after_move, played_move, move_label) for display.

    Returns ("", None, path_key) when the node cannot be located.
    """
    if pgn_game is None:
        return ("", None, path_key)
    path = decode_path(path_key)
    if not path:
        return ("", None, path_key)
    node = node_at_path(pgn_game, path)
    if node is None or node.move is None:
        return ("", None, path_key)
    try:
        pre_board = node.parent.board()
        san = pre_board.san(node.move)
        fullmove = pre_board.fullmove_number
        if pre_board.turn == chess.WHITE:
            move_label = f"{fullmove}. {san}"
        else:
            move_label = f"{fullmove}… {san}"
        fen = node.board().fen()
        return (fen, node.move, move_label)
    except Exception:
        return ("", None, path_key)
