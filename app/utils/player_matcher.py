"""Player-to-game matching helpers for Chess Log filtering."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.game_data import GameData


def game_matches_player_color(
    game: "GameData", player_cf: str, color_filter: str
) -> bool:
    """Return True iff game should be included for the given player + color filter.

    Args:
        game:         Game whose White/Black headers are checked.
        player_cf:    Casefolded, stripped player name. Empty string matches all games.
        color_filter: One of "white", "black", or "both" / any other value.
    """
    if not player_cf:
        return True
    white_cf = (game.white or "").casefold().strip()
    black_cf = (game.black or "").casefold().strip()
    is_white = player_cf == white_cf
    is_black = player_cf == black_cf
    if not (is_white or is_black):
        return False
    if color_filter == "white" and not is_white:
        return False
    if color_filter == "black" and not is_black:
        return False
    return True


def game_player_is_black(game: "GameData", player_name: str) -> bool:
    """Return True iff `player_name` played Black in `game`.

    Case-insensitive, whitespace-stripped comparison against `game.black`.
    Returns False when `player_name` is empty, when the player didn't play
    at all, or when the player played White. Used to decide mini-board
    orientation in Chess Log dialogs: True → flip so Black is at bottom.
    """
    player_cf = (player_name or "").casefold().strip()
    if not player_cf:
        return False
    black_cf = (game.black or "").casefold().strip()
    return player_cf == black_cf
