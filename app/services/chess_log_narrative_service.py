"""Chess Log narrative summary service.

Assembles a prompt from:
  - Per-preset CLAMP glossary (verbatim definitions; prevents LLM letter-expansion errors)
  - Per-preset category counts binned over time (4 trend bins via chess_log_stats_service)
  - Why-notes (all non-empty entry["why"] values, no cap)
  - Whole-game notes (CARANotes header) for all games that have them, no cap

No input truncation is applied. At typical tagging rates the full prompt stays well
within 5–10% of the context window; the API's own error handling is the real
constraint if a library ever grows large enough to matter.

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
from app.utils.player_matcher import game_matches_player_color as _game_matches_player_color

_SYSTEM_PROMPT = (
    "You are a chess coach helping a player reflect on their self-annotated game moments. "
    "Be specific, encouraging, and concrete. Avoid generic advice. "
    "Write in second person ('you', 'your'). "
    "If a category's counts across bins don't show a consistent direction, say so plainly rather than forcing a trend narrative — but still report any genuine qualitative insight from that category's why-notes even when the numeric trend is inconclusive. A small or irregular count doesn't mean there's nothing worth learning from what you actually wrote. "
    "Write in plain, direct sentences. Never use em-dashes anywhere in your response, for any purpose - including setting off lists of numbers or parenthetical asides. Use commas, periods, or separate sentences instead. Don't lose the underlying connections between categories when the data supports them (e.g. if a hung piece and a dangerous alignment happen on the same tagged moment, say so directly, just without the flourish). "
    "Refer to time periods using their actual calendar labels (e.g. specific months or date ranges) provided in the data. Never use generic placeholder language like 'periods' or 'bins' when a real time label is available. "
    "Structure your response as three markdown sections, in this exact order, using exactly these headers:\n\n"
    "## Patterns & Recurrent Themes\n"
    "## Tactical Breakdown\n"
    "## Key Takeaways\n\n"
    "The Patterns & Recurrent Themes section is a markdown bullet list — emit it as 2 to 4 bullet items (one per theme) using `-` as the bullet marker, with a blank line separating each bullet's body from the next bullet. Each bullet must begin with a bold sentence-fragment lead-in that names the theme in 3 to 8 words, followed by a period, then 2 to 5 sentences of body text (e.g. `- **Rushing calculation in sharp positions.** You repeatedly ...`). The lead-in must stand on its own as a scannable summary of the theme. Do NOT nest bullets; do NOT emit sub-bullets. Focus on the underlying behavioral tendencies (rushing calculation, drifting attention in slow positions, missing prophylaxis, etc.), keep the tone player-focused, and do NOT frame around CLAMP letters or percentages — category-level detail belongs in the Tactical Breakdown section that follows. "
    "The Tactical Breakdown section MUST be a markdown pipe table with exactly three "
    "columns and a header row, in this exact format:\n\n"
    "| Skill | Observed Issue | Strategic Impact |\n"
    "| --- | --- | --- |\n"
    "| ... | ... | ... |\n\n"
    "One row per chess-concept theme that the data supports. In the Skill column, use "
    "generic chess-concept labels that you synthesize from the underlying moves and "
    "why-notes — for example: King Safety, Piece Coordination, Pawn Structure, "
    "Calculation Depth, Time Management, Move Order, Tactical Awareness, Prophylaxis. "
    "Do NOT use CLAMP letters, CLAMP category names (Checks, Loose Pieces and Squares, "
    "Alignments, Mobility Restrictions, Passed Pawns), CCT category names (Checks, "
    "Captures, Threats), or 3x3 Why-question labels in the Skill column — treat those "
    "as grouping hints only and name the underlying chess concept instead. This is where "
    "per-concept percentages and pattern-level observations belong — not in Patterns & "
    "Recurrent Themes. Do not repeat the same content across multiple rows. Do not add "
    "extra columns. Every row MUST populate all three columns with substantive content "
    "— never emit a row where Strategic Impact is empty, whitespace, a placeholder like "
    "— or N/A, or a restatement of the Observed Issue. Strategic Impact must name the "
    "concrete downstream consequence for the game (material loss, king exposure, "
    "initiative surrendered, tempo wasted, etc.). If you cannot articulate a distinct "
    "Strategic Impact for a row, drop the row entirely rather than emit a blank cell. "
    "Do not emit any prose outside the table in this section. "
    "The Key Takeaways section is the single most important part of your response and must never be dropped or reduced to a throwaway line. Write it as 1 to 3 short paragraphs of continuous prose, not a numbered or bulleted list. Each paragraph must begin with a bold sentence-fragment lead-in that names the actionable takeaway in 3 to 8 words, followed by a period, then the paragraph body (e.g. `**Slow down in king-attack positions.** When the tagged notes mention...`). Each paragraph must be anchored to a specific quote or short phrase drawn verbatim from the player's own why-notes or whole-game notes, and use that anchor to name a concrete, actionable next step. Do not restate the earlier sections in miniature and do not offer generic coaching advice that isn't tied to the player's own words. If you are running short on space, compress or omit low-signal rows in the Tactical Breakdown table (few tagged moments, no clear trend, such as Mobility or Passed Pawns when sparse) rather than sacrifice anything in Key Takeaways. "
    "When discussing a category's trend across periods, do not mechanically list every period's name and number in a row more than once. Refer to the overall pattern in plain language (e.g. 'consistently across all four logged periods,' 'in every period without exception') and name specific periods only when calling out a genuine standout (the highest or lowest, or a real change point), not as a rote enumeration. "
    "When a preset's category letters are not all distinct (as with CCT, where both Checks and Captures start with C), never use a bare letter as shorthand for either one. Always use the full category name (Checks, Captures, Threats) to keep them unambiguous. This does not apply to CLAMP, where each letter maps to exactly one category and bare-letter shorthand (C, L, A, M, P) remains fine. "
    "For CCT-tagged moments, a tag can describe either side of the board. A Checks, Captures, or Threats tag may mean the player's own candidate move created that problem, or it may mean the opponent's prior move created it and the player failed to respond to it. Read the why-note itself to tell which; do not assume a tag always means 'the player's move was the problem.' "
    "When you cite a specific move from a game, always give the full move+color pairing: 'move number. move, White vs Black' (for example, '16. b4, NotThePainter vs mattsartin'). Never abbreviate to just 'vs Black' or 'the b4 move' — the reader needs the move number, the SAN, and the player-color pairing every time. "
    "Cap verbatim quotes from the player's why-notes at 1 to 2 per theme, per table row, and per Key Takeaway paragraph. Do not sprinkle a quote into every sentence — pick the one or two that best carry the point and let them do the work. "
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
    "CCT": (
        "- C — Checks: A checking move — either one the opponent's last move enabled that "
        "wasn't accounted for, or one the player's own candidate move allows in return.\n"
        "- C — Captures: A piece or square left undefended or under-defended, the "
        "opponent's loose piece going unclaimed, or one of the player's own left hanging "
        "by their candidate move.\n"
        "- T — Threats: An aggressive move, such as attacking a higher-value piece, "
        "creating a mating sequence, or setting up a tactical fork, that forces the "
        "opponent to respond defensively on their very next turn to avoid immediate "
        "material or positional loss."
    ),
    # 3x3 uses a structural Why-questions block rather than a letter glossary — see
    # _3X3_STRUCTURE_BLOCK and _format_3x3_structure() below.
    "3x3": "",
}

_USER_PREAMBLE = """\
Below is a summary of the moments I have tagged across my recent games in CARA's Chess Log.
{glossary_section}## Category counts by preset (over time)

(Use the calendar label shown for each time period, e.g. "June-July 2025" — never "Bin N" or "period 3".)

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
    "Please write:\n\n"
    "1. **Patterns & Recurrent Themes** (a bullet list of 2 to 4 bullets, one per "
    "cross-cutting behavioral theme): emit each theme as a `-` bullet with a blank "
    "line between bullets. Begin each bullet with a bold sentence-fragment lead-in "
    "naming the theme in 3 to 8 words, followed by a period, then 2 to 5 sentences "
    "of body text (e.g. `- **Rushing calculation in sharp positions.** I repeatedly "
    "...`). Focus on the player-level behavior (how I seem to think, when I rush, "
    "what I overlook), not on CLAMP letters or category percentages — that granular "
    "data goes in the Tactical Breakdown table below. Reference at most 1 to 2 "
    "verbatim quotes from my own why-notes per theme. Do NOT nest bullets.\n\n"
    "2. **Tactical Breakdown** (a markdown pipe table, not prose): exactly the header "
    "row `| Skill | Observed Issue | Strategic Impact |` followed by an alignment "
    "separator row `| --- | --- | --- |` and one row per chess-concept theme supported "
    "by the data. In the Skill column, use generic chess-concept labels (King Safety, "
    "Piece Coordination, Pawn Structure, Calculation Depth, Time Management, Move Order, "
    "etc.) — do NOT use CLAMP letters, CLAMP category names, CCT category names, or 3x3 "
    "Why-question labels. At most 1 to 2 verbatim quotes per row. No prose outside the "
    "table in this section. Every row must fill all three columns — if you cannot "
    "write a substantive Strategic Impact, drop the row rather than leave it blank.\n\n"
    "3. **Key Takeaways** (1 to 3 short paragraphs of continuous prose, not a "
    "numbered or bulleted list): begin each paragraph with a bold sentence-fragment "
    "lead-in naming the actionable takeaway in 3 to 8 words, followed by a period, "
    "then the paragraph body (e.g. `**Slow down in king-attack positions.** When "
    "my tagged notes mention...`). Each paragraph anchored to a specific quote or "
    "short phrase from my own why-notes or whole-game notes, naming a concrete, "
    "actionable next step. Do not restate the earlier sections in miniature. At "
    "most 1 to 2 verbatim quotes per paragraph.\n\n"
    "Format all three as markdown sections with the exact headers "
    "`## Patterns & Recurrent Themes`, `## Tactical Breakdown`, and "
    "`## Key Takeaways`, in that order. When citing a specific move from a game, "
    "use the full move+color pairing (e.g. `16. b4, NotThePainter vs mattsartin`).\n"
)

_CLOSING = ""


def sanitize_narrative_markdown(text: str) -> str:
    """Drop presentational noise from LLM narrative markdown before rendering.

    Two classes of garbage are removed so that both the on-screen QTextEdit
    (setMarkdown path) and the PDF renderer receive identical clean input:

    1. Bare thematic-break lines (---/***/___ alone on a line): presentational
       noise that Qt renders as a subtle HR anyway; ## headings already give
       visual separation so the loss is imperceptible in the PDF.
    2. Pipe-table rows where any cell is empty after stripping: defense in
       depth for blank Strategic Impact cells the model occasionally emits
       despite explicit prompt instructions to the contrary.

    Table separator rows (| --- | --- | --- |) have 2+ pipe-delimited cells
    and are not matched by the thematic-break rule, so they are preserved.
    """
    def _is_separator(line: str) -> bool:
        stripped = line.strip().strip("|")
        if not stripped:
            return False
        cells = [c.strip() for c in stripped.split("|")]
        if len(cells) < 2:
            return False
        return all(c and all(ch in "-: " for ch in c) for c in cells)

    out = []
    for line in text.split("\n"):
        stripped = line.strip()
        # 1. Thematic break: 3+ identical chars from -/*/_, no pipe character.
        if (
            len(stripped) >= 3
            and stripped[0] in "-*_"
            and all(ch == stripped[0] for ch in stripped)
            and "|" not in stripped
        ):
            continue
        # 2. Pipe-table row with any empty cell (separators are preserved above).
        if stripped.startswith("|") and not _is_separator(stripped):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if any(not c for c in cells):
                continue
        out.append(line)
    return "\n".join(out)


def build_prompt(
    games: List[GameData],
    player: str = "",
    color_filter: str = "both",
) -> str:
    """Assemble the LLM prompt from the given games.

    Args:
        games:         Games to draw data from (already filtered to the desired scope).
        player:        Player name for scoping (empty = all players).
        color_filter:  "white" / "black" / "both".

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
                    if why:
                        label = f"{preset}/{cat}" if cat else f"{preset}/uncategorized"
                        why_notes.append((label, why))

        if getattr(game, "has_notes", False):
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
    threexthree_block = _format_3x3_structure(preset_names)
    combined = "\n\n".join(b for b in (glossary_block, threexthree_block) if b)
    glossary_section = f"\n{combined}\n\n" if combined else "\n"

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
    return preamble + _NARRATIVE_STEP


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
) -> Tuple[bool, str, List[str]]:
    """Generate a narrative summary from the given games.

    Args:
        games:              Games in scope (already filtered to the desired Data Source).
        provider:           AIProvider string ("openai", "anthropic", "custom").
        model:              Model ID.
        api_key:            API key.
        base_url_override:  Custom endpoint base URL (None for OpenAI/Anthropic).
        player:             Player filter (empty = all players).
        color_filter:       "white" / "black" / "both".
        config:             Optional config dict forwarded to AIService.
        timeout_seconds:    Request timeout passed to AIService.send_message.
        token_limit:        Max tokens passed to AIService.send_message (None = AIService default).

    Returns:
        (success, narrative_text, shallow_flags)
        shallow_flags is always [] — shallow-note flagging is handled separately via flag_shallow_notes().
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
    )

    thinking = (
        {"type": "disabled"}
        if any(name in (model or "").lower() for name in ("sonnet-5", "opus-5"))
        else None
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
        thinking=thinking,
    )
    if not success:
        return False, response, []

    narrative, shallow_flags = _parse_response(response)
    return True, narrative, shallow_flags


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _format_glossary(preset_names: Set[str]) -> str:
    """Emit glossary blocks for presets that appear in the data and have a glossary entry."""
    blocks = []
    for preset in sorted(preset_names):
        text = _PRESET_GLOSSARIES.get(preset, "")
        if text:
            blocks.append(f"## Glossary — {preset}\n\n{text}")
    return "\n\n".join(blocks)


_3X3_STRUCTURE_BLOCK = (
    "## Why-note structure — 3x3\n\n"
    "Each 3x3-tagged moment may include answers to up to four questions, always "
    "asked in this order, though the player may skip any of them:\n\n"
    "1. Why did I choose that move?\n"
    "2. Why is my move not ideal?\n"
    "3. Why is the better move better than my chosen move?\n"
    "4. What do I do in the future so this doesn't happen again?\n\n"
    "These are the four questions from GM Noel Studer's 3x3 method. Treat a "
    "missing answer to any of the four as simply unanswered, not as evidence of "
    "anything. All four always describe the player's own chosen move and their "
    "own reasoning about it, never the opponent's move."
)


def _format_3x3_structure(preset_names: Set[str]) -> str:
    """Emit the 3x3 Why-questions block iff 3x3 data is present in the filtered data."""
    return _3X3_STRUCTURE_BLOCK if "3x3" in preset_names else ""


def _bin_month_label(lab0: str, lab1: str) -> str:
    """Convert an ISO date pair to a natural calendar label.

    Same-month: "June 2025".  Same-year span: "June-July 2025".
    Cross-year: "Dec 2025-Jan 2026".  Falls back to raw strings on parse failure.
    """
    from datetime import date as _date

    _FULL = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    _SHORT = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]

    def _parse(s: str) -> Optional[_date]:
        try:
            return _date.fromisoformat(s)
        except (ValueError, TypeError):
            return None

    d0, d1 = _parse(lab0), _parse(lab1)
    if d0 is None or d1 is None:
        return f"{lab0} to {lab1}"

    m0, y0, m1, y1 = d0.month, d0.year, d1.month, d1.year
    if y0 == y1:
        if m0 == m1:
            return f"{_FULL[m0 - 1]} {y0}"
        return f"{_FULL[m0 - 1]}-{_FULL[m1 - 1]} {y0}"
    return f"{_SHORT[m0 - 1]} {y0}-{_SHORT[m1 - 1]} {y1}"


def _format_trend_counts(series_map: Dict[str, ChessLogPresetSeries]) -> str:
    """Format trend-binned category percentages as a prompt block.

    Each bin shows category % of that bin's total (same denominator as the chart
    Y-axis).  A lifetime average (total-weighted, not average-of-percentages) is
    prepended per preset so the model has a single anchor value per category.
    """
    lines = []
    for preset in sorted(series_map):
        series = series_map[preset]
        lines.append(f"### {preset}")

        # Lifetime totals for total-weighted average
        lifetime_total = sum(b.total for b in series.bins)
        lifetime_counts: Dict[str, int] = {}
        for bin_ in series.bins:
            for cat, count in bin_.counts.items():
                lifetime_counts[cat] = lifetime_counts.get(cat, 0) + count

        if lifetime_total > 0:
            avg_parts = []
            for cat in series.categories:
                count = lifetime_counts.get(cat, 0)
                if count > 0:
                    pct = round(count * 100 / lifetime_total)
                    label = cat if cat else "uncategorized"
                    avg_parts.append(f"{label} {pct}%")
            if avg_parts:
                lines.append(f"Overall average: {', '.join(avg_parts)}")

        for bin_ in series.bins:
            month_label = _bin_month_label(bin_.lab0, bin_.lab1)
            if bin_.total == 0:
                lines.append(f"{month_label}: (no moments)")
                continue
            parts = []
            for cat in series.categories:
                count = bin_.counts.get(cat, 0)
                if count > 0:
                    pct = round(count * 100 / bin_.total)
                    label = cat if cat else "uncategorized"
                    parts.append(f"{label} {pct}%")
            if not parts:
                parts.append("(no moments)")
            lines.append(f"{month_label} ({bin_.total} moments): {', '.join(parts)}")
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
