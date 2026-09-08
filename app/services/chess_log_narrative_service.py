"""Chess Log narrative summary service.

Assembles a prompt from:
  - Per-preset CLAMP glossary (verbatim definitions; prevents LLM letter-expansion errors)
  - Per-preset category counts binned over time (4 trend bins via chess_log_stats_service)
  - Why-notes (non-empty entry["why"] values), capped to avoid token bloat
  - Whole-game notes (CARANotes header) for games that have them

Calls AIService.send_message and parses the LLM response into a narrative string.
The shallow-note flagging step has been removed from the prompt; _parse_response
always returns an empty flags list for backward compatibility with callers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from app.models.database_model import GameData
from app.services.ai_service import AIService
from app.services.chess_log_stats_service import ChessLogPresetSeries, aggregate
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
    "Write in second person ('you', 'your'). "
    "If a category's counts across bins don't show a consistent direction, say so plainly rather than forcing a trend narrative — but still report any genuine qualitative insight from that category's why-notes even when the numeric trend is inconclusive. A small or irregular count doesn't mean there's nothing worth learning from what you actually wrote. "
    "Write in plain, direct sentences. Avoid decorative devices like em-dashes for dramatic pause and tidy aphoristic closers ('X is the mechanism, Y is the consequence') — but don't lose the underlying connections between categories when the data supports them (e.g. if a hung piece and a dangerous alignment happen on the same tagged moment, say so directly, just without the flourish). "
)

# Registry of per-preset glossary text.
# Contract: preset name → verbatim glossary text. Only presets with non-empty
# text get a glossary block emitted. Only presets present in the filtered data
# get their glossary block included at all.
#
# Rule for additions (CCT / 3x3 / Custom): when Paul supplies verbatim glossary
# text for a preset, drop it in here as-is. Do NOT paraphrase, do NOT invent
# definitions. If a definition has not been supplied, the entry stays as "" so
# no glossary block is emitted — an absent glossary is better than a wrong one.
_PRESET_GLOSSARIES: Dict[str, str] = {
    "CLAMP": (
        "- C — Checks: A checking move — either one the opponent's last move enabled that "
        "wasn't accounted for, or one the player's own candidate move allows in return.\n"
        "- L — Loose Pieces and Squares: A piece or square left undefended or under-defended "
        "— the opponent's loose piece going unclaimed, or one of the player's own left hanging "
        "by their candidate move.\n"
        "- A — Alignments: A dangerous lineup along a file, rank, diagonal, or knight's reach "
        "— enabling pins, skewers, forks, or discovered attacks — whether the opponent's last "
        "move created it unnoticed, or the player's own candidate move creates it against "
        "themselves.\n"
        "- M — Mobility Restrictions: A piece left with restricted movement and at risk of "
        "being trapped — an opponent's piece that could have been cornered, or one of the "
        "player's own boxed in by their candidate move.\n"
        "- P — Passed Pawns: A pawn positioned to become unstoppable — the opponent's passed "
        "pawn not dealt with in time, or the player's own candidate move handing them one."
    ),
    # TODO: Add CCT glossary text when Paul provides it.
    "CCT": "",
    # TODO: Add 3x3 glossary text when Paul provides it.
    "3x3": "",
    # TODO: Add Custom glossary text when Paul provides it.
    "Custom": "",
}

_USER_PREAMBLE = """\
Below is a summary of the moments I have tagged across my recent games in CARA's Chess Log.
{glossary_section}## Category counts by preset (over time)

{category_counts_block}

## My own notes on individual moments (why-notes)

{why_notes_block}

Treat whole-game notes as illustrative color only — use them to flavor observations \
grounded in the category-count and why-note evidence above, never as the primary basis \
for a conclusion.

## Whole-game notes

{game_notes_block}

---

"""

_NARRATIVE_STEP = (
    "1. **Narrative summary** (3–5 paragraphs): a reflective synthesis of the patterns you "
    "see — what recurring themes emerge, where I seem to be making progress, and what "
    "areas still need attention.  Reference specific categories and quote a few of my "
    "own words where they are illuminating."
)

_CLOSING = "\n\nKeep the narrative concise and actionable.\n"


def build_prompt(
    games: List[GameData],
    player: str = "",
    color_filter: str = "both",
    include_also_flagged: bool = True,  # accepted but unused; kept for backward compat
) -> str:
    """Assemble the LLM prompt from the given games.

    Args:
        games:                Games to draw data from (already filtered to the desired scope).
        player:               Player name for scoping (empty = all players).
        color_filter:         "white" / "black" / "both".
        include_also_flagged: Ignored — shallow-note flagging has been removed from the prompt.
                              Parameter kept so existing call sites do not need updating.

    Returns:
        Formatted prompt string ready to send as the user message.
    """
    player_cf = (player or "").casefold().strip()

    preset_names: Set[str] = set()
    flat_counts: Dict[str, Dict[str, int]] = {}   # fallback when aggregate returns empty
    why_notes: List[Tuple[str, str]] = []
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
                        preset_names.add(preset)
                        counts = flat_counts.setdefault(preset, {})
                        counts[cat] = counts.get(cat, 0) + 1
                    if why and len(why_notes) < _MAX_WHY_NOTES:
                        label = f"{preset}/{cat}" if cat else f"{preset}/uncategorized"
                        why_notes.append((label, why))

        if len(game_notes) < _MAX_GAME_NOTES and getattr(game, "has_notes", False):
            note_text = NotesStorageService.load_notes(game)
            if note_text and note_text.strip():
                game_notes.append(note_text.strip())

    # Trend-binned counts — 4 bins so the model can discuss early vs recent patterns.
    series_map = aggregate(
        games,
        player=player or "",
        color_filter=color_filter,
        chart_cfg={"target_progression_bins": 4, "min_games_per_ordinal_bin": 1},
    )

    glossary_block = _format_glossary(preset_names)
    glossary_section = f"\n{glossary_block}\n\n" if glossary_block else "\n"

    if series_map:
        category_counts_block = _format_trend_counts(series_map)
    elif flat_counts:
        category_counts_block = (
            "(trend data unavailable — insufficient dated games)\n\n"
            + _format_category_counts(flat_counts)
        )
    else:
        category_counts_block = "(no moments tagged)"

    why_notes_block = _format_why_notes(why_notes)
    game_notes_block = _format_game_notes(game_notes)

    preamble = _USER_PREAMBLE.format(
        glossary_section=glossary_section,
        category_counts_block=category_counts_block,
        why_notes_block=why_notes_block,
        game_notes_block=game_notes_block,
    )
    instruction = "Please write:\n\n" + _NARRATIVE_STEP + _CLOSING
    return preamble + instruction


def generate_narrative(
    games: List[GameData],
    provider: str,
    model: str,
    api_key: str,
    base_url_override: Optional[str],
    player: str = "",
    color_filter: str = "both",
    config: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 60,
    token_limit: Optional[int] = None,
    include_also_flagged: bool = True,
) -> Tuple[bool, str, List[str]]:
    """Generate a narrative summary from the given games.

    Args:
        games:                Games in scope (already filtered to the desired Data Source).
        provider:             AIProvider string ("openai", "anthropic", "custom").
        model:                Model ID.
        api_key:              API key.
        base_url_override:    Custom endpoint base URL (None for OpenAI/Anthropic).
        player:               Player filter (empty = all players).
        color_filter:         "white" / "black" / "both".
        config:               Optional config dict forwarded to AIService.
        timeout_seconds:      Request timeout passed to AIService.send_message.
        token_limit:          Max tokens passed to AIService.send_message (None = AIService default).
        include_also_flagged: Ignored — kept for call-site backward compat.

    Returns:
        (success, narrative_text, shallow_flags)
        shallow_flags is always [] — the shallow-note step has been removed from the prompt.
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

    prompt = build_prompt(
        games,
        player=player,
        color_filter=color_filter,
        include_also_flagged=include_also_flagged,
    )

    service = AIService(config=config)
    messages = [{"role": "user", "content": prompt}]
    success, response = service.send_message(
        provider=provider,
        model=model,
        api_key=api_key,
        messages=messages,
        system_prompt=_SYSTEM_PROMPT,
        base_url_override=base_url_override,
        token_limit=token_limit,
        timeout_seconds=timeout_seconds,
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


def _format_glossary(preset_names: Set[str]) -> str:
    """Emit glossary blocks for presets that appear in the data and have a glossary entry."""
    blocks = []
    for preset in sorted(preset_names):
        text = _PRESET_GLOSSARIES.get(preset, "")
        if text:
            blocks.append(f"## Glossary — {preset}\n\n{text}")
    return "\n\n".join(blocks)


def _format_trend_counts(series_map: Dict[str, ChessLogPresetSeries]) -> str:
    """Format trend-binned category counts as a prompt block."""
    lines = []
    for preset in sorted(series_map):
        series = series_map[preset]
        lines.append(f"### {preset}")
        for i, bin_ in enumerate(series.bins, 1):
            parts = []
            for cat in series.categories:
                count = bin_.counts.get(cat, 0)
                if count > 0:
                    label = cat if cat else "uncategorized"
                    parts.append(f"{label}:{count}")
            if not parts:
                parts.append("(no moments)")
            header = f"Bin {i} ({bin_.lab0} → {bin_.lab1}, {bin_.total} moments)"
            lines.append(f"{header}: {' '.join(parts)}")
    return "\n".join(lines)


def _format_category_counts(
    category_counts: Dict[str, Dict[str, int]],
) -> str:
    """Flat (non-trend) category counts — used as fallback when aggregate returns empty."""
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
    """Return (narrative, []).

    Shallow-note flagging has been removed from the prompt; flags are always
    empty. The sentinel split is intentionally gone — if an old-model response
    happens to include "## Also flagged", it becomes part of the narrative text
    rather than being silently discarded.
    """
    return response.strip(), []
