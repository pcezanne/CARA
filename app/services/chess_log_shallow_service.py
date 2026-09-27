"""Shallow-note classifier service for Chess Log Charts.

Wraps the AIService call and reply-parse logic that was previously inlined in
ChessLogShallowThread.run().  Pure function — no Qt dependencies.

Behavior change vs. the old inline code
----------------------------------------
Previously, any line the parser couldn't understand was silently dropped —
the corresponding note stayed DEEP but there was no record that the model
failed to classify it.  Now every input index is accounted for:

- An index is "parsed" when the reply contains a ``<idx>: SHALLOW`` or
  ``<idx>: DEEP`` line for it.
- Unparsed indices are returned in ``ShallowResult.unparsed_indices``.
- An unparsed index is NEVER marked SHALLOW — it stays DEEP unchanged.
- The caller (ChessLogShallowThread) surfaces a notice to the user when
  ``unparsed_indices`` is non-empty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Tuple

from app.services.ai_service import AIService, TokenUsage


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_CLASSIFIER_PROMPT = (
    "Classify each of these player self-notes as SHALLOW or DEEP.\n\n"
    "SHALLOW = only reports the outcome, the move played, or what's objectively\n"
    "wrong with the position — a label or a fact about the board, not an\n"
    "explanation of the player's own thinking\n"
    "(e.g. \"I blundered\", \"missed it\", \"this hangs my Rook for a Bishop\",\n"
    "\"there was a discovered attack on my Queen that I missed\").\n\n"
    "DEEP = explains why the PLAYER made the move or missed the better one —\n"
    "what they were thinking, focused on, or misjudging. Naming what's wrong\n"
    "with the position or the resulting tactic (a fork, a discovered attack, a\n"
    "weak rank) is NOT enough on its own — the note has to say something about\n"
    "the player's own reasoning or mental error, even if brief or tentative.\n\n"
    "A DEEP note doesn't need an explicit causal word like \"because\" — connecting\n"
    "two facts is enough. \"I saw the free rook\" next to \"missed the mate\" already\n"
    "explains the distraction that caused the miss.\n\n"
    "Examples of DEEP:\n"
    "- \"I went to kick their Knight not seeing my Bishop was hanging.\" (explains\n"
    "  what distracted them)\n"
    "- \"This is a calculation error, 2 attackers, one defender.\" (attributes\n"
    "  the mistake to a specific miscount, not just stating the position)\n"
    "- \"I think I played a3 to protect it from capture.\" (states own intent,\n"
    "  even tentatively)\n"
    "- \"I needed to get on the same file as the Queen to force it away.\"\n"
    "  (explains the missed plan)\n\n"
    "Examples of SHALLOW:\n"
    "- \"This hangs my Rook for a Bishop.\"\n"
    "- \"There was a discovered attack on my Queen that I missed.\"\n"
    "- \"I moved my queen into a forking square with my King.\"\n"
    "- \"This is a passive move, permitting my opponent to play Rc2, putting\n"
    "  their rook on a very powerful rank.\"\n"
    "- \"It appears that the engine wants to make sure they don't have a bishop\n"
    "  pair, but that's a guess.\" (explains the engine's logic, not the\n"
    "  player's own reasoning)\n\n"
    "For entries beginning with [3x3], the parts form one connected\n"
    "self-analysis of a single decision (Why I played it = player's\n"
    "intent, What was wrong = what was wrong with their move, Why the\n"
    "better move is better = often the same underlying point restated,\n"
    "Lesson = the takeaway). 'What was wrong' and 'Why the better move\n"
    "is better' are board-fact questions by design — a factual answer to\n"
    "either is NOT shallow. Classify the whole [3x3] entry as DEEP if\n"
    "'Why I played it' or 'Lesson' contains genuine player-perspective\n"
    "reasoning: what they were thinking, what they misread, or a specific\n"
    "lesson that names the pattern (not just 'be more careful'). Classify\n"
    "as SHALLOW only if all parts are bare board facts or generic filler\n"
    "with no player angle.\n\n"
    "Return one line per note: <index>: SHALLOW or <index>: DEEP.\n\n"
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShallowResult:
    """Result of classify_notes()."""

    success: bool
    # (game_number, path_key, preset) tuples judged SHALLOW
    shallow_keys: FrozenSet[Tuple[int, str, str]]
    error: Optional[str]
    usage: Optional[TokenUsage]
    model: str
    # Input indices for which the model returned neither SHALLOW nor DEEP.
    # These notes are left unchanged (not marked shallow).
    unparsed_indices: Tuple[int, ...]


# ---------------------------------------------------------------------------
# Verdict normalisation
# ---------------------------------------------------------------------------

# Regex that extracts (index, raw_verdict) from a classifier reply line.
# Tolerates decoration around the index and multiple separator styles:
#   0: SHALLOW          — standard colon
#   0. SHALLOW          — period (numbered-list style)
#   0) SHALLOW          — paren
#   - 0: SHALLOW        — leading bullet dash
#   [0] SHALLOW         — bracket-wrapped index (] is the separator)
#   Note 0: SHALLOW     — leading word
# The SHALLOW/DEEP equality check after normalisation is the true gate —
# prose lines that happen to contain a digit (e.g. "Here are 3 notes:") do
# not produce a valid verdict and stay unparsed.
_LINE_RE = re.compile(r'^\s*[^\d]*?(\d+)\s*[-\]:.)]\s*(.+?)\s*$')

# Characters stripped from both ends of the raw verdict token before the
# SHALLOW/DEEP equality check.  Covers trailing punctuation that prose-heavy
# local models append (e.g. "Shallow.") and markdown decoration that some
# models wrap around their answer (e.g. "**SHALLOW**", "`DEEP`", "_SHALLOW_").
# The final .strip() handles space-padded decoration: "** SHALLOW **" →
# strip(*) → " SHALLOW " → strip() → "SHALLOW".
# Trailing prose ("SHALLOW (because…)") is NOT stripped — it stays unparsed.
_VERDICT_STRIP_CHARS = '.,!;*_`'


def _normalize_verdict(raw: str) -> str:
    return raw.strip().strip(_VERDICT_STRIP_CHARS).strip().upper()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_notes(
    notes: List[Tuple[int, int, str, str, str]],
    provider: str,
    model: str,
    api_key: str,
    base_url_override: Optional[str],
    config: Optional[dict],
    timeout_seconds: int,
) -> ShallowResult:
    """Classify *notes* as SHALLOW or DEEP via the configured AI provider.

    Args:
        notes: List of ``(idx, game_number, path_key, preset, why)`` tuples.
               The ``idx`` values must be 0-based sequential integers matching
               the list positions (i.e. ``notes[i][0] == i``).
        provider: ``"anthropic"``, ``"openai"``, or ``"custom"``.
        model: Model ID string.
        api_key: Provider API key.
        base_url_override: Custom endpoint base URL; ``None`` for cloud providers.
        config: Optional config dict forwarded to AIService.
        timeout_seconds: Request timeout.

    Returns:
        A :class:`ShallowResult`.  On API failure ``success`` is ``False`` and
        ``shallow_keys`` is empty.  On a successful call with partial parse
        failures ``success`` is ``True``, ``shallow_keys`` holds the confirmed
        SHALLOW entries, and ``unparsed_indices`` lists the uncovered indices.
    """
    thinking = AIService.disable_thinking_for(model)
    notes_text = "\n".join(f"{i}: {why}" for (i, _gn, _pk, _pr, why) in notes)
    prompt = _CLASSIFIER_PROMPT + notes_text

    service = AIService(config=config)
    result = service.send_message(
        provider=provider,
        model=model,
        api_key=api_key,
        messages=[{"role": "user", "content": prompt}],
        base_url_override=base_url_override,
        timeout_seconds=timeout_seconds,
        thinking=thinking,
    )

    if not result.success:
        return ShallowResult(
            success=False,
            shallow_keys=frozenset(),
            error=result.error or "Classification failed.",
            usage=result.usage,
            model=result.model,
            unparsed_indices=tuple(range(len(notes))),
        )

    parsed: dict[int, str] = {}
    for line in result.text.splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        try:
            idx = int(m.group(1))
        except ValueError:
            continue
        verdict = _normalize_verdict(m.group(2))
        if verdict in ("SHALLOW", "DEEP") and 0 <= idx < len(notes):
            parsed[idx] = verdict

    shallow_keys: FrozenSet[Tuple[int, str, str]] = frozenset(
        (notes[i][1], notes[i][2], notes[i][3])
        for i, verdict in parsed.items()
        if verdict == "SHALLOW"
    )
    unparsed = tuple(i for i in range(len(notes)) if i not in parsed)

    return ShallowResult(
        success=True,
        shallow_keys=shallow_keys,
        error=None,
        usage=result.usage,
        model=result.model,
        unparsed_indices=unparsed,
    )
