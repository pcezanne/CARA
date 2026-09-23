# Chess Log

Human-authored move tagging layer — player self-diagnosis, complementing CARA's engine-based classification. Players tag up to three "moments" per game with a category and optional note.

See also: `doc/chess_log_charts.md` for the Charts tab (reporting and narrative); `chess-log-design-doc.md` §3.2–3.4 for the full preset design.

## Storage format

`CARAChessLog` / `CARAChessLogInfo` / `CARAChessLogChecksum` PGN header triple (same gzip+base64 pattern as Annotations and Notes). Payload is JSON keyed by variation path (`encode_path` from `app/utils/pgn_variation_path.py`). One path = one moment; the 3-moment cap counts distinct non-empty path keys, not total entries (so a CCT moment with two letters = 1 moment).

### CARA-namespaced PGN tags (all read-only in metadata view and model)

- `CARAAnalysisData` / `CARAAnalysisInfo` / `CARAAnalysisChecksum` — per-move engine data
- `CARAAnnotations` / `CARAAnnotationsInfo` / `CARAAnnotationsChecksum` — board drawing annotations
- `CARANotes` / `CARANotesInfo` / `CARANotesChecksum` — whole-game text notes
- `CARAChessLog` / `CARAChessLogInfo` / `CARAChessLogChecksum` — Chess Log moments
- `CARAGameTags` — whole-game chip tags

## Vocabulary

"moment" in all user-facing text; `tag` is fine in internal code. Avoids collision with `CARAGameTags` whole-game chips.

## Presets

Three presets: **CLAMP**, **CCT**, **3x3**. The player selects one active preset in the Chess Log Settings dialog (Chess Log menu → "Chess Log Settings…"), mirroring the Engines/AI Summary setup pattern. CLAMP and CCT both allow multiple letters per moment.

3x3 is the sole preset with free-form text at tag time. Its four Whys use GM Noel Studer's exact wording:
- "Why did I choose that move?"
- "Why is my move not ideal?"
- "Why is the better move better than my chosen move?"
- "What do I do in the future so this doesn't happen again?"

Storage keys: `Why1` / `Why2` / `Why3` / `Why4`. These strings are defined once in `app/utils/chess_log_prompts.py` (`THREE_BY_THREE_PROMPTS` dict) and imported by `moment_dialog.py`, `show_tags_dialog.py`, and `chess_log_pdf_service.py`.

The active preset can change over time — a library may end up with moments tagged under more than one preset. This is expected, not an error.

## Tagging behavior

### Zero-category save (CLAMP, CCT)

If no chips are checked but the why-field has content, the moment saves as a single entry with `cat=""` — genuinely uncategorized, not a fake "Other" category. Zero chips + empty why keeps OK blocked (hint shown).

### "More than three moments?" nag

When a player tries to add a *new* path (a fresh moment, not re-tagging an existing one) and the game already has ≥ 3 tagged moments, a soft "Are you sure?" dialog fires. The nag fires **before** Tag This Moment opens (checked in `DetailMovesListView._on_tag_moment` via `ChessLogController.should_confirm_extra_moment`) so the user is asked before investing typing effort.

Once shown, the nag is suppressed for:
- The rest of the session (`_nag_shown_this_session: bool`, global across all games).
- All future sessions for that specific game (`_nag_shown_by_game: Dict[int, bool]`, persisted in the `CARAChessLog` payload as `"nag_shown": true`).

Persistence follows the explicit-save convention: the flag rides with the next Ctrl+Alt+L save; if the user never saves the game, the flag is lost along with the moment itself. Re-tagging an existing path (adding a second preset's entries to an already-tagged move) never counts as a new moment and never triggers the nag.

## User interface

### Entry point

First-time users: Chess Log → Chess Log Settings to pick their preset (CLAMP, CCT, or 3x3). Then right-click a move in the Moves List → "Tag this moment…". Save via Chess Log menu → "Save Chess Log to current game" (`Ctrl+Alt+L`). Clear via `Ctrl+Shift+L`.

### Moves-list context menu structure (right-click on any move)

1. Column profile (submenu)
2. --- separator ---
3. Copy value
4. Edit Comments (conditional — only when clicking a Comment cell)
5. --- separator ---
6. Tag this moment…
7. **Show Tags** — opens `ShowTagsDialog` scoped to the current game, sorted by ply ascending then preset in canonical order (CLAMP → CCT → 3x3). Enabled iff the game has at least one tagged entry. Disabled with tooltip "No tagged moments in this game." when the game has zero tags.
8. --- separator ---
9. Copy Table as CSV / TSV (4 actions)

### Show Tags dialog

`app/views/dialogs/show_tags_dialog.py`, class `ShowTagsDialog`. Parameterized for single-game or multi-game — pass `games=[game]` for single-game (context-menu path), `games=[g1, g2, …]` for multi-game ("Show Chess Logs for all games" menu path). Each row represents one (move, preset) pair: board miniature, category checkboxes (blank for 3x3), why-note text. All fields editable on open.

**Buffered editing** — OK persists changes to the in-memory cache via `replace_entries_at_path_for_game`; Cancel discards all edits. Multi-game usage inserts a game-header label (`White - Black Result (Date - N moves)`) between each game's rows; single-game usage shows no header. Zero-category saves (`cat=""`) round-trip correctly through OK. `ignore_shallow` field is transparently preserved through edits.

Rows whose entries carry `is_shallow=True` render a **⚠️ + Ignore** group right-justified on the move-label line — `ShowTagsDialog` computes this per-row via `any(e.get("is_shallow") for e in entries)` and passes `show_ignore_checkbox=True` accordingly to `_TagRowWidget`.

**Export to PDF** button (left of the button row) exports on-screen rows WYSIWYG — including in-progress buffered edits — via `ChessLogPDFService`. Rows are paginated atomically (no row straddles a page break); multi-game exports include per-game headers kept with their first row.

`_TagRowWidget.snapshot()` captures the live widget state into a `TagRowSnapshot` dataclass (`app/models/chess_log_snapshot.py`) used by the exporter. `TagRowSnapshot` carries a `best_move: Optional[chess.Move]` field (default `None`) resolved at row-construction time via `resolve_best_move_for_path` (`app/utils/chess_log_best_move.py`).

**Miniature board arrows** — each row's board thumbnail uses `MiniChessBoardWidget.set_played_and_best(played, best)` (opt-in two-arrow mode): played move in yellow (`playedmove_arrow.color`, default `[255,255,0]`), best move in reddish (`bestalternativemove_arrow.color`, default `[200,0,100]`). The best arrow is suppressed when `best_move` is None or equals the played move. Variation-move tags and tags on unanalyzed games show played-arrow only. Non-Chess-Log call sites (`set_move(...)`) are unaffected — their single-arrow default (blue) is unchanged.

### "Show Chess Logs for all games"

Chess Log menu item (after "Save Chess Logs for all games"): opens `ShowTagsDialog` scoped to every game in the active database that has at least one tagged entry (`has_chess_log_tags=True`). Buffered editing — OK writes, Cancel discards. Handler: `MainWindow._show_chess_logs_for_all_games`.

## Dialog theming

`MomentDialog`, `ShowTagsDialog`, and `ShowShallowTagsDialog` all share the `ui.dialogs.moment` config namespace; `ChessLogSettingsDialog` uses `ui.dialogs.chess_log_settings`. Both blocks exist in all three theme JSON files (`style_default`, `style_light`, `style_scholar`) with theme-appropriate `$_ref` tokens, so the dialogs repaint correctly when CARA's theme is changed.

Every color used in these dialogs' `setStyleSheet` calls must be read from config (via `dc.get(...)`) — **no hardcoded `rgb(…)` literals are permitted**.

All four dialogs are opened via `.exec()` (modal), so "repaint on next open" matches `BulkOperationsDialog`'s behavior; no theme-changed signal infrastructure is needed.

## Controller API

### ChessLogController helpers

- `game_has_any_tags() -> bool` — True iff `_cached_paths_data` has any non-empty entry list.
- `replace_entries_at_path(path_key, preset, entries, view=None)` — replaces entries for the given preset at that path; preserves other presets. In-memory only.
- `replace_entries_at_path_for_game(game, path_key, preset, entries)` — same but takes a `GameData` object; correctly routes to either the active single-game cache or the multi-game cache depending on which game is active. Used by both `ShowTagsDialog` (on OK) and `ShowShallowTagsDialog` (live edit). **This is the only method that explicitly marks a game dirty.**

## Unbuilt

"highlight tagged moves" toggle — not yet implemented.

## Key files

- `app/services/chess_log_storage_service.py`
- `app/controllers/chess_log_controller.py`
- `app/views/dialogs/moment_dialog.py`
- `app/views/dialogs/chess_log_settings_dialog.py`
- `app/views/menus/chess_log_menu.py`
- `app/utils/chess_log_prompts.py` — `THREE_BY_THREE_PROMPTS` dict
- `app/utils/pgn_variation_path.py` — `encode_path`
