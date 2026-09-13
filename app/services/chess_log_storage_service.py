"""Service for storing and loading Chess Log moments in PGN tags."""

import json
import uuid
from typing import Dict, List, Optional, Any
from io import StringIO
from datetime import datetime, timezone

import chess.pgn

from app.models.database_model import GameData
from app.services.pgn_service import PgnService
from app.services.logging_service import LoggingService
from app.utils.pgn_tag_compression import (
    decode_and_decompress_to_str,
    compress_and_encode_from_str,
    compute_checksum,
)


class ChessLogStorageService:
    """Service for storing and loading Chess Log moments in PGN tags.

    Uses [CARAChessLog "..."] with gzip+base64 encoding,
    [CARAChessLogInfo "..."] for metadata, and [CARAChessLogChecksum "..."]
    for integrity verification — same pattern as CARAAnnotations / CARANotes.

    Storage schema (before compression):
        {"_v": 1, "paths": {path_key: [entry, ...]}}

    One path key = one moment. A path's list may hold multiple entries so that
    a CCT tag with two letters (both apply to the same moment) costs one moment
    against the 3-moment cap, not two.  count_tags() counts paths, not entries.

    For 3x3 moments, cat is one of "Why1", "Why2", "Why3" and why holds the
    answer text.  A single 3x3 moment stores up to three entries (one per Why
    answered), all sharing the same path key.  Insertion order is preserved by
    json.dumps/loads and Python dicts (3.7+), so Why1 always precedes Why2
    and Why3 when loaded back.  preset="3x3" on all three entries.
    """

    TAG_NAME = "CARAChessLog"
    TAG_INFO = "CARAChessLogInfo"
    TAG_CHECKSUM = "CARAChessLogChecksum"
    CHIP_TEXT = "🏷"

    @staticmethod
    def has_chess_log_tags(game: GameData) -> bool:
        """Return True if game has a CARAChessLog tag."""
        if game is None or not hasattr(game, "pgn") or game.pgn is None:
            return False
        try:
            chess_game = chess.pgn.read_game(StringIO(game.pgn))
            return chess_game is not None and ChessLogStorageService.TAG_NAME in chess_game.headers
        except Exception:
            return False

    @staticmethod
    def load_tags(game: GameData) -> Dict[str, List[Dict[str, Any]]]:
        """Load Chess Log moments from game PGN.

        Returns {path_key: [entry, ...]}. Returns {} on missing tag, checksum
        mismatch (also strips the corrupt tags), or any error.
        Sets game.has_chess_log_tags as a side effect.
        """
        if game is None:
            return {}
        if not hasattr(game, "pgn") or game.pgn is None:
            game.has_chess_log_tags = False
            return {}
        try:
            chess_game = chess.pgn.read_game(StringIO(game.pgn))
            if not chess_game or ChessLogStorageService.TAG_NAME not in chess_game.headers:
                game.has_chess_log_tags = False
                return {}
            encoded = chess_game.headers[ChessLogStorageService.TAG_NAME]
            json_text = decode_and_decompress_to_str(encoded)
            if ChessLogStorageService.TAG_CHECKSUM in chess_game.headers:
                stored = chess_game.headers[ChessLogStorageService.TAG_CHECKSUM]
                if compute_checksum(json_text.encode("utf-8")) != stored:
                    LoggingService.get_instance().warning(
                        "Chess Log checksum mismatch — removing corrupt tags."
                    )
                    ChessLogStorageService._remove_chess_log_tags(game)
                    game.has_chess_log_tags = False
                    return {}
            payload = json.loads(json_text)
            paths_data: Dict[str, List[Dict[str, Any]]] = payload.get("paths", {})
            game.has_chess_log_tags = ChessLogStorageService.count_tags(paths_data) > 0
            return paths_data
        except ValueError:
            ChessLogStorageService._remove_chess_log_tags(game)
            game.has_chess_log_tags = False
            return {}
        except Exception:
            game.has_chess_log_tags = False
            return {}

    @staticmethod
    def store_tags(
        game: GameData,
        paths_data: Dict[str, List[Dict[str, Any]]],
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Store Chess Log moments into game PGN (in-memory). Returns True on success."""
        if game is None or not hasattr(game, "pgn") or game.pgn is None:
            return False
        try:
            payload = {"_v": 1, "paths": paths_data}
            json_text = json.dumps(payload, ensure_ascii=False)
            data_bytes = json_text.encode("utf-8")
            checksum = compute_checksum(data_bytes)
            encoded = compress_and_encode_from_str(json_text, compresslevel=9)
            app_version = (config or {}).get("version", "1.0")
            info_str = (
                f"App Version: {app_version}, "
                f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            chess_game = chess.pgn.read_game(StringIO(game.pgn))
            if not chess_game:
                return False
            chess_game.headers[ChessLogStorageService.TAG_NAME] = encoded
            chess_game.headers[ChessLogStorageService.TAG_INFO] = info_str
            chess_game.headers[ChessLogStorageService.TAG_CHECKSUM] = checksum
            has_tags = ChessLogStorageService.count_tags(paths_data) > 0
            # Sync chip into the real header BEFORE export so it is durably persisted.
            ChessLogStorageService._sync_chess_log_chip_in_headers(chess_game, inject=has_tags)
            game.pgn = PgnService.export_game_to_pgn(chess_game)
            game.has_chess_log_tags = has_tags
            # Sync Python-side attributes for immediate in-session UI consistency.
            from app.utils.game_tags_utils import parse_game_tags, tags_display_text
            new_raw = chess_game.headers.get("CARAGameTags", "")
            game.game_tags_raw = new_raw
            game.game_tags = tags_display_text(parse_game_tags(new_raw))
            return True
        except Exception as e:
            LoggingService.get_instance().error(
                f"Error storing Chess Log tags: {e}", exc_info=e
            )
            return False

    @staticmethod
    def clear_tags(game: GameData) -> bool:
        """Remove CARAChessLog* tags from game PGN (in-memory)."""
        if game is None or not hasattr(game, "pgn") or game.pgn is None:
            return False
        ChessLogStorageService._remove_chess_log_tags(game)  # also removes chip from header
        game.has_chess_log_tags = False
        return True

    @staticmethod
    def count_tags(paths_data: Dict[str, List[Dict[str, Any]]]) -> int:
        """Count distinct moments (non-empty path keys) — NOT total entries.

        One path = one moment, even if it carries multiple entries
        (e.g. CCT with two letters selected on the same moment).
        """
        return sum(1 for entries in paths_data.values() if entries)

    @staticmethod
    def make_entry(
        preset: str,
        cat: str,
        why: str = "",
        ignore_shallow: bool = False,
        is_shallow: bool = False,
    ) -> Dict[str, Any]:
        """Build a single moment entry dict with a new UUID and UTC timestamp."""
        entry: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "preset": preset,
            "cat": cat,
            "why": why,
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if ignore_shallow:
            entry["ignore_shallow"] = True
        if is_shallow:
            entry["is_shallow"] = True
        return entry

    @staticmethod
    def _sync_chess_log_chip_in_headers(chess_game, *, inject: bool) -> None:
        """Add or remove the Chess Log chip in chess_game.headers["CARAGameTags"] in-place.

        Must be called BEFORE PgnService.export_game_to_pgn() so the change is
        durably written into game.pgn. Mutating game.game_tags_raw alone is not
        enough — that attribute is not the serialization source.
        """
        from app.utils.game_tags_utils import parse_game_tags, format_game_tags
        raw = chess_game.headers.get("CARAGameTags", "")
        tags = parse_game_tags(raw)
        chip = ChessLogStorageService.CHIP_TEXT
        chip_lower = chip.casefold()
        if inject:
            if chip_lower not in {t.casefold() for t in tags}:
                tags = [chip] + tags
        else:
            tags = [t for t in tags if t.casefold() != chip_lower]
        new_raw = format_game_tags(tags)
        if new_raw:
            chess_game.headers["CARAGameTags"] = new_raw
        elif "CARAGameTags" in chess_game.headers:
            del chess_game.headers["CARAGameTags"]

    @staticmethod
    def _remove_chess_log_tags(game: GameData) -> None:
        """Remove CARAChessLog* tags and Chess Log chip from game PGN (in-memory, best-effort)."""
        try:
            chess_game = chess.pgn.read_game(StringIO(game.pgn))
            if not chess_game:
                return
            for key in (
                ChessLogStorageService.TAG_NAME,
                ChessLogStorageService.TAG_INFO,
                ChessLogStorageService.TAG_CHECKSUM,
            ):
                if key in chess_game.headers:
                    del chess_game.headers[key]
            ChessLogStorageService._sync_chess_log_chip_in_headers(chess_game, inject=False)
            game.pgn = PgnService.export_game_to_pgn(chess_game)
            # Sync Python-side attributes for immediate in-session UI consistency.
            from app.utils.game_tags_utils import parse_game_tags, tags_display_text
            new_raw = chess_game.headers.get("CARAGameTags", "")
            game.game_tags_raw = new_raw
            game.game_tags = tags_display_text(parse_game_tags(new_raw))
        except Exception:
            pass
