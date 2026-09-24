Batch of UI/UX fixes for the Chess Log Charts view, based on real usage.
Most items are ready to implement directly; two (marked INVESTIGATE /
DISCUSS) need a report back before any code changes.

## 1. Rename "Chess Log Charts" to "Chess Log"

Everywhere the longer name currently appears — tab label, F10 menu entry,
view title, any log/comment strings that reference it in user-facing text.
Internal code/file/class names (ChessLogChartsController,
detail_chess_log_charts_view.py, etc.) can stay as-is; this is a
user-facing label change only, not a rename of the feature internally.

## 2. Full-height layout, whole-pane scrolling — mirror Player Stats exactly

Current layout constrains the chart and narrative areas into small boxes
with their own internal scroll behavior. Player Stats doesn't do this even
with large datasets — the whole pane scrolls as one unit, individual
sections render at their natural full height. Restructure
DetailChessLogChartsView to match: charts render full height (not
squeezed into a fixed box), narrative text area renders full height, and
a single QScrollArea wraps the entire pane content, not per-widget mini
scrollers. Check exactly how Player Stats' view achieves this and mirror
it directly rather than inventing a different scrolling structure.

## 3. Data Source / Player dropdowns — full width, matching Player Stats

Currently narrower than Player Stats' equivalent controls. Match the
layout/sizing exactly.

## 4. Surface Model, Timeout, and Token controls for narrative generation

Mirror the AI Summary tab's UI — it already exposes these knobs for tuning
generation. Chess Log's narrative generation should offer the same
controls rather than using fixed/hidden defaults. Reuse whatever
config/settings mechanism AI Summary already uses for these, don't invent
a parallel one.

## 5. "Also Flagged" text isn't selectable for copy/paste

Whatever widget renders this section currently doesn't support text
selection. Fix so the shallow-note-flag text can be selected/copied —
likely means using a read-only QTextEdit/QTextBrowser with selection
enabled, or setTextInteractionFlags(Qt.TextSelectableByMouse) if it's
currently a plain QLabel.

## 6. "Also Flagged" checkbox — confirmed: must be prompt-side

Decided: this controls whether the "also flag shallow notes" instruction
is included in the prompt sent to the LLM (saves tokens when off), not
just whether an already-generated section is shown/hidden. If it's
currently implemented as display-side only, fix it to actually gate the
prompt content. Because it affects what gets sent, it must be visible and
set BEFORE the Generate button is clicked — verify its current placement
achieves this; move it if it's currently positioned as a post-generation
option.

## 7. Chart legend order should follow each preset's canonical letter order

Currently appears to follow encounter/alphabetical order (per screenshot:
A, C, L, P, uncategorized). Should be CLAMP's defined order — C, L, A, M,
P — for the CLAMP chart, and C, C, T (Checks, Captures, Threats) for CCT.
"(uncategorized)" stays last regardless of preset, which is already
correct per existing test coverage (test_uncategorized_is_last_in_
categories) — don't disturb that, just fix the ordering of the real
categories before it.

## 8. Binning strategy — build a user-selectable X-axis mode, not a single
   fixed approach

Resolved direction (confirmed with Paul): rather than choosing one
binning strategy, add a toggle between TIME-BASED (current behavior —
reuses Player Stats' date-ordinal binner) and GAME-COUNT-BASED (bin by
N tagged games regardless of calendar span) binning. Both are genuinely
useful for different questions — time-based answers "what changed since I
started learning X in April," game-count-based answers "what's my actual
pattern, independent of how bursty my tagging habit is" — and Chess Log's
inherently sparse tagging (max 3 moments/game, not every game tagged)
means the current time-only approach produces choppy, hard-to-read charts
exactly like Paul's 12-game screenshot.

Design constraints for the implementation:
- ONE shared toggle for the whole Chess Log Charts view, not per-chart —
  if CLAMP/CCT/Custom are stacked together, they should all re-render in
  the same mode at once for consistent cross-chart comparison.
- Default to time-based, matching the existing design intent and Player
  Stats convention.
- Persist the player's choice (sticky across sessions), same pattern as
  the existing target_progression_bins setting.

Before implementing, report:
1. Can game-count binning reuse the existing bin-count-driven helpers
   (_move_quality_bins_ordinal_quantile etc.) with a different input — an
   ordinal game-index sequence instead of a date-ordinal sequence — or
   does it need genuinely new binning logic?
2. Whether this needs to change per-preset or can stay uniform across
   CLAMP/CCT/Custom.
3. Honest effort estimate before starting — this is a real architectural
   addition (a second binning mode plus the toggle UI), not a small
   tweak.

## Standard rules apply

- Confirm before any push, every branch, no exceptions.
- One commit per logical change (items 1, 2, 3, 5, 6, 7 can each be their
  own small commit or grouped sensibly; item 8 is the largest single
  piece — report effort per its own step 3 before implementing, then
  proceed once scoped, no need to pause for a separate go-ahead beyond
  that report).
- Test coverage part of each item's definition of done.
- Report scope/effort honestly, especially for item 8.
