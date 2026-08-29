"""Chess Log narrative summary service.

Assembles a prompt from:
  - Per-preset category counts across all selected games
  - Why-notes (non-empty entry["why"] values), capped to avoid token bloat
  - Whole-game notes (CARANotes header) for games that have them

Calls AIService.send_message and parses the LLM response into a structured
result with a narrative paragraph and a list of shallow-note flags.

The LLM is asked to flag why-notes that are "shallow" — e.g. ones that merely
restate the category label without adding insight (§5.2).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.models.database_model import GameData
from app.services.ai_service import AIService
from app.services.chess_log_storage_service import ChessLogStorageService
from app.services.notes_storage_service import NotesStorageService

# Maximum why-notes and game-notes included in the prompt to stay within
# reasonable token budgets.  If the library is larger the extras are silently
# omitted — the summary is still representative.
_MAX_WHY_NOTES = 40
_MAX_GAME_NOTES = 10

_SYSTEM_PROMPT = (
    "You are a chess coach helping a player reflect on their self-annotated game moments. "
    "Be specific, encouraging, and concrete. Avoid generic advice. "
    "Write in second person ('you', 'your')."
)

_USER_TEMPLATE = """\
Below is a summary of the moments I have tagged across my recent games in CARA's Chess Log.

## Category counts by preset

{category_counts_block}

## My own notes on individual moments (why-notes)

{why_notes_block}

## Whole-game notes

{game_notes_block}

---

Please write two things:

1. **Narrative summary** (2–4 paragraphs): a reflective synthesis of the patterns you \
see — what recurring themes emerge, where I seem to be making progress, and what \
areas still need attention.  Reference specific categories and quote a few of my \
own words where they are illuminating.

2. **Shallow notes** (optional): list any why-notes that merely restate the category \
label without adding insight (e.g. "I made a mistake" under a Mistake category, \
or "I calculated badly" under Calculation).  If none are shallow, omit this section. \
Format as a bullet list under the heading "## Also flagged".

Keep the narrative concise and actionable.
"""


def build_prompt(
    games: List[GameData],
    player: str = "",
    color_filter: str = "both",
) -> str:
    """Assemble the LLM prompt from the given games.

    Args:
        games:        Games to draw data from (already filtered to the desired scope).
        player:       Player name for scoping (empty = all players).
        color_filter: "white" / "black" / "both".

    Returns:
        Formatted prompt string ready to send as the user message.
    """
    player_cf = (player or "").casefold().strip()

    category_counts: Dict[str, Dict[str, int]] = {}  # preset → cat → count
    why_notes: List[Tuple[str, str]] = []             # (preset_cat_label, note)
    game_notes: List[str] = []

    for game in games:
        if not _game_matches_player_color(game, player_cf, color_filter):
            continue

        if getattr(game, "has_chess_log_tags", False):
            paths_data = ChessLogStorageService.load_tags(game)
            for entries in paths_data.values():
                for entry in entries:
                    preset = entry.get("preset", "")
                    cat = entry.get("cat", "") or ""
                    why = (entry.get("why") or "").strip()
                    if preset:
                        counts = category_counts.setdefault(preset, {})
                        counts[cat] = counts.get(cat, 0) + 1
                    if why and len(why_notes) < _MAX_WHY_NOTES:
                        label = f"{preset}/{cat}" if cat else f"{preset}/uncategorized"
                        why_notes.append((label, why))

        if len(game_notes) < _MAX_GAME_NOTES and getattr(game, "has_notes", False):
            note_text = NotesStorageService.load_notes(game)
            if note_text and note_text.strip():
                game_notes.append(note_text.strip())

    category_counts_block = _format_category_counts(category_counts)
    why_notes_block = _format_why_notes(why_notes)
    game_notes_block = _format_game_notes(game_notes)

    return _USER_TEMPLATE.format(
        category_counts_block=category_counts_block,
        why_notes_block=why_notes_block,
        game_notes_block=game_notes_block,
    )


def generate_narrative(
    games: List[GameData],
    provider: str,
    model: str,
    api_key: str,
    base_url_override: Optional[str],
    player: str = "",
    color_filter: str = "both",
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, List[str]]:
    """Generate a narrative summary from the given games.

    Args:
        games:             Games in scope (already filtered to the desired Data Source).
        provider:          AIProvider string ("openai", "anthropic", "custom").
        model:             Model ID.
        api_key:           API key.
        base_url_override: Custom endpoint base URL (None for OpenAI/Anthropic).
        player:            Player filter (empty = all players).
        color_filter:      "white" / "black" / "both".
        config:            Optional config dict forwarded to AIService.

    Returns:
        (success, narrative_text, shallow_flags)
        On failure: (False, error_message, [])
    """
    player_cf = (player or "").casefold().strip()
    has_data = any(
        getattr(g, "has_chess_log_tags", False)
        for g in games
        if _game_matches_player_color(g, player_cf, color_filter)
    )
    if not has_data:
        return False, "No Chess Log data found to summarise.", []

    prompt = build_prompt(games, player=player, color_filter=color_filter)

    service = AIService(config=config)
    messages = [{"role": "user", "content": prompt}]
    success, response = service.send_message(
        provider=provider,
        model=model,
        api_key=api_key,
        messages=messages,
        system_prompt=_SYSTEM_PROMPT,
        base_url_override=base_url_override,
    )
    if not success:
        return False, response, []

    narrative, shallow_flags = _parse_response(response)
    return True, narrative, shallow_flags


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _game_matches_player_color(
    game: GameData, player_cf: str, color_filter: str
) -> bool:
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


def _format_category_counts(
    category_counts: Dict[str, Dict[str, int]],
) -> str:
    if not category_counts:
        return "(no moments tagged)"
    lines = []
    for preset in sorted(category_counts):
        lines.append(f"**{preset}**")
        counts = category_counts[preset]
        named = sorted((k, v) for k, v in counts.items() if k)
        for cat, count in named:
            lines.append(f"  - {cat}: {count}")
        if "" in counts:
            lines.append(f"  - (uncategorized): {counts['']}")
    return "\n".join(lines)


def _format_why_notes(why_notes: List[Tuple[str, str]]) -> str:
    if not why_notes:
        return "(no notes written)"
    lines = []
    for label, note in why_notes:
        lines.append(f"- [{label}] {note}")
    return "\n".join(lines)


def _format_game_notes(game_notes: List[str]) -> str:
    if not game_notes:
        return "(no whole-game notes)"
    return "\n\n---\n\n".join(game_notes)


def _parse_response(response: str) -> Tuple[str, List[str]]:
    """Split the LLM response into (narrative, shallow_flags).

    Looks for the sentinel heading "## Also flagged" (case-insensitive) to
    separate the narrative from the optional shallow-note list.  The shallow
    flags are extracted as bullet items.  If the sentinel is absent the entire
    response is treated as the narrative with no flags.
    """
    lower = response.lower()
    sentinel_idx = lower.find("## also flagged")
    if sentinel_idx == -1:
        return response.strip(), []

    narrative = response[:sentinel_idx].strip()
    flagged_block = response[sentinel_idx:].strip()

    flags: List[str] = []
    for line in flagged_block.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ", "• ")):
            item = stripped[2:].strip()
            if item:
                flags.append(item)

    return narrative, flags
