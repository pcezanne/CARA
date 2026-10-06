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
from app.services.logging_service import LoggingService


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
# Verdict parsing
# ---------------------------------------------------------------------------

# Matches a verdict line anchored to the start of the line (MULTILINE).
# Leading decoration: whitespace, markdown bullets/pipes/angles/brackets.
# Separators: the classic set plus `|` for markdown-table replies.
# Trailing content must be whitespace/decoration/end-of-line — anything else
# (e.g. "0: DEEP because of …") rejects the line so the parser never guesses.
_LINE_RE = re.compile(
    r'^[\s|*>_\-\[]*'      # leading markdown/bullet/bracket decoration
    r'(\d+)\s*'             # the index
    r'[-\]:.)|]\s*'         # separator — adds `|` for markdown-table shape
    r'[*_`]*\s*'            # optional bold/italic/code decoration
    r'(SHALLOW|DEEP)'       # the verdict — gated so prose can't sneak in
    r'\s*[*_`|.,!;]*\s*$',  # trailing decoration (incl. punct) + end-of-line
    re.IGNORECASE | re.MULTILINE,
)


def _parse_verdicts(reply_text: str, note_count: int) -> dict:
    """Return {idx: verdict_upper} from the model reply.

    Preprocessing step: insert a newline between SHALLOW/DEEP and a following
    digit so that adjacent text blocks joined without a separator
    (e.g. "0: SHALLOW1: DEEP") are split before the line regex runs.

    Last occurrence wins for any duplicate index (model may reconsider).
    """
    text = re.sub(r'\b(SHALLOW|DEEP)(\d)', r'\1\n\2', reply_text, flags=re.IGNORECASE)
    parsed: dict = {}
    for m in _LINE_RE.finditer(text):
        try:
            idx = int(m.group(1))
        except ValueError:
            continue
        verdict = m.group(2).upper()
        if verdict not in ("SHALLOW", "DEEP"):
            continue
        if 0 <= idx < note_count:
            parsed[idx] = verdict
    return parsed


# ---------------------------------------------------------------------------
# Token budget
# ---------------------------------------------------------------------------

def _classifier_token_limit(note_count: int) -> int:
    """Conservative output-token budget for the classifier.

    Measured at ~31 tokens/note on a 62-note CLAMP library.  Using 60/note
    (~2× observed) plus 500 for preamble avoids truncation before the verdict
    list on large libraries.  Floor of 2000 matches the former default so no
    small-library regression.
    """
    return max(2000, note_count * 60 + 500)


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
    classifier_body = (config or {}).get("prompts", {}).get("chess_log", {}).get("classifier")
    if not classifier_body:
        return ShallowResult(
            success=False,
            shallow_keys=frozenset(),
            error="Chess Log prompts are missing from config.json — reinstall or restore the file.",
            usage=None,
            model=model,
            unparsed_indices=tuple(i for i, *_ in notes),
        )
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
        token_limit=_classifier_token_limit(len(notes)),
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

    parsed = _parse_verdicts(result.text, len(notes))

    shallow_keys: FrozenSet[Tuple[int, str, str]] = frozenset(
        (notes[i][1], notes[i][2], notes[i][3])
        for i, verdict in parsed.items()
        if verdict == "SHALLOW"
    )
    unparsed = tuple(i for i in range(len(notes)) if i not in parsed)

    if unparsed:
        all_failed = len(parsed) == 0 and len(notes) > 0
        logger = LoggingService.get_instance()
        log = logger.warning if all_failed else logger.debug
        log(
            "chess_log classifier parsed %d of %d notes "
            "(model=%s, stop_reason=%r, block_count=%s, block_types=%s, "
            "usage=%s, reply_text=%r)"
            % (
                len(parsed), len(notes), result.model,
                result.stop_reason, result.content_block_count,
                result.content_block_types, result.usage,
                result.text[:4000],
            )
        )

    return ShallowResult(
        success=True,
        shallow_keys=shallow_keys,
        error=None,
        usage=result.usage,
        model=result.model,
        unparsed_indices=unparsed,
    )
