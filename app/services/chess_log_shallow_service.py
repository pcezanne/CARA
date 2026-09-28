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
    classifier_body = (config or {}).get("prompts", {}).get("chess_log", {}).get("classifier", "")
    prompt = classifier_body + notes_text

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
