# Chess Log

Human-authored move logging layer — player self-diagnosis, complementing CARA's engine-based classification. Players log up to three "moments" per game with a category and optional note.

See also: `doc/chess_log_charts.md` for the Charts tab (reporting and narrative); `chess-log-design-doc.md` §3.2–3.4 for the full preset design.

## Storage format

`CARAChessLog` / `CARAChessLogInfo` / `CARAChessLogChecksum` PGN header triple (same gzip+base64 pattern as Annotations and Notes). Payload is JSON keyed by variation path (`encode_path` from `app/utils/pgn_variation_path.py`). One path = one moment; the 3-moment cap counts distinct non-empty path keys, not total entries (so a CCT moment with two letters = 1 moment).

Chess Log writes only its own `CARAChessLog*` headers — it does **not** inject anything into `CARAGameTags`. The `has_chess_log_tags` field on `GameData` (set from the presence of `CARAChessLog` in the PGN at load time) drives the **Log** column in the database panel independently of any game-tag chip.

### CARA-namespaced PGN tags (all read-only in metadata view and model)

- `CARAAnalysisData` / `CARAAnalysisInfo` / `CARAAnalysisChecksum` — per-move engine data
- `CARAAnnotations` / `CARAAnnotationsInfo` / `CARAAnnotationsChecksum` — board drawing annotations
- `CARANotes` / `CARANotesInfo` / `CARANotesChecksum` — whole-game text notes
- `CARAChessLog` / `CARAChessLogInfo` / `CARAChessLogChecksum` — Chess Log moments
- `CARAGameTags` — whole-game chip tags (independent of Chess Log)

## Vocabulary

"Moment" in all user-facing text; `tag`/`tagged` is acceptable in internal code. Avoids collision with `CARAGameTags` whole-game chips.

## Log column

`COL_LOG = 18` in `DatabaseModel` — shows `✓` for games where `has_chess_log_tags` is `True`. Sits between Annotated/Notes and Source DB in the column order. Backed by `"CARAChessLog": DatabaseModel.COL_LOG` in the metadata controller's header-tag map, so the column lights up whenever the PGN carries a `CARAChessLog` header.

Column width key: `"col_log"` in `ui.panels.database.table.column_widths` (all three theme files). Existing saved column profiles that predate `col_log` get it appended automatically (see `ColumnProfile.get_column_order`).

## Presets

Three presets: **CLAMP**, **CCT**, **3x3**. The player selects one active preset in the Chess Log Settings dialog (Chess Log menu → "Chess Log Settings…"), mirroring the Engines/AI Summary setup pattern. CLAMP and CCT both allow multiple letters per moment.

3x3 is the sole preset with free-form text at log time. Its four Whys use GM Noel Studer's exact wording:
- "Why did I choose that move?"
- "Why is my move not ideal?"
- "Why is the better move better than my chosen move?"
- "What do I do in the future so this doesn't happen again?"

Storage keys: `Why1` / `Why2` / `Why3` / `Why4`. These strings are defined once in `app/utils/chess_log_prompts.py` (`THREE_BY_THREE_PROMPTS` dict) and imported by `moment_dialog.py`, `show_tags_dialog.py`, and `chess_log_pdf_service.py`.

The active preset can change over time — a library may end up with moments logged under more than one preset. This is expected, not an error.

## Logging behavior

### Zero-category save (CLAMP, CCT)

If no chips are checked but the why-field has content, the moment saves as a single entry with `cat=""` — genuinely uncategorized, not a fake "Other" category. Zero chips + empty why keeps OK blocked (hint shown).

### "More than three moments?" nag

When a player tries to add a *new* path (a fresh moment, not re-logging an existing one) and the game already has ≥ 3 logged moments, a soft "Are you sure?" dialog fires. The nag fires **before** Log This Moment opens (checked in `DetailMovesListView._on_tag_moment` via `ChessLogController.should_confirm_extra_moment`) so the user is asked before investing typing effort.

Once shown, the nag is suppressed for:
- The rest of the session (`_nag_shown_this_session: bool`, global across all games).
- All future sessions for that specific game (`_nag_shown_by_game: Dict[int, bool]`, persisted in the `CARAChessLog` payload as `"nag_shown": true`).

Persistence follows the explicit-save convention: the flag rides with the next Ctrl+Alt+L save; if the user never saves the game, the flag is lost along with the moment itself. Re-logging an existing path (adding a second preset's entries to an already-logged move) never counts as a new moment and never triggers the nag.

## User interface

### Entry point

First-time users: Chess Log → Chess Log Settings to pick their preset (CLAMP, CCT, or 3x3). Then right-click a move in the Moves List → "Log this moment…". Save via Chess Log menu → "Save Chess Log to current game" (`Ctrl+Alt+L`). Clear via `Ctrl+Shift+L`.

### Moves-list context menu structure (right-click on any move)

1. Column profile (submenu)
2. --- separator ---
3. Copy value
4. Edit Comments (conditional — only when clicking a Comment cell)
5. --- separator ---
6. Log this moment…
7. **Show Logged Moments** — opens `ShowTagsDialog` scoped to the current game, sorted by ply ascending then preset in canonical order (CLAMP → CCT → 3x3). Enabled iff the game has at least one logged entry. Disabled with tooltip "No logged moments in this game." when the game has zero moments.
8. --- separator ---
9. Copy Table as CSV / TSV (4 actions)

### Show Logged Moments dialog

`app/views/dialogs/show_tags_dialog.py`, class `ShowTagsDialog`. Parameterized for single-game or multi-game — pass `games=[game]` for single-game (context-menu path), `games=[g1, g2, …]` for multi-game ("Show Logged Moments for All Games" menu path). Each row represents one (move, preset) pair: board miniature, category checkboxes (blank for 3x3), why-note text. All fields editable on open.

**Buffered editing** — OK persists changes to the in-memory cache via `replace_entries_at_path_for_game`; Cancel discards all edits. Multi-game usage inserts a game-header label (`White - Black Result (Date - N moves)`) between each game's rows; single-game usage shows no header. Zero-category saves (`cat=""`) round-trip correctly through OK. `ignore_shallow` field is transparently preserved through edits.

Rows whose entries carry `is_shallow=True` render a **⚠️ + Ignore** group right-justified on the move-label line — `ShowTagsDialog` computes this per-row via `any(e.get("is_shallow") for e in entries)` and passes `show_ignore_checkbox=True` accordingly to `_TagRowWidget`.

**Export to PDF** button (left of the button row) exports on-screen rows WYSIWYG — including in-progress buffered edits — via `ChessLogPDFService`. Rows are paginated atomically (no row straddles a page break); multi-game exports include per-game headers kept with their first row.

`_TagRowWidget.snapshot()` captures the live widget state into a `TagRowSnapshot` dataclass (`app/models/chess_log_snapshot.py`) used by the exporter. `TagRowSnapshot` carries a `best_move: Optional[chess.Move]` field (default `None`) resolved at row-construction time via `resolve_best_move_for_path` (`app/utils/chess_log_best_move.py`).

**Miniature board arrows** — each row's board thumbnail uses `MiniChessBoardWidget.set_played_and_best(played, best)` (opt-in two-arrow mode): played move in yellow (`playedmove_arrow.color`, default `[255,255,0]`), best move in reddish (`bestalternativemove_arrow.color`, default `[200,0,100]`). The best arrow is suppressed when `best_move` is None or equals the played move. Variation-move moments and moments on unanalyzed games show played-arrow only. Non-Chess-Log call sites (`set_move(...)`) are unaffected — their single-arrow default (blue) is unchanged.

**Miniature board orientation** — each row's board is oriented so the **mover at the logged ply** is at the bottom. Orientation is derived per row from `pre_board.turn` inside `node_info()` (`app/views/dialogs/_tag_row_helpers.py`): `mover_is_black = pre_board.turn == chess.BLACK`. No player-selection dependency — works correctly on first open, for right-click Show Logged Moments, and for CCT entries at either color. Independent of the main detail board's flip toggle. The value is carried on `TagRowSnapshot.is_flipped` so PDF export stays WYSIWYG with the on-screen dialog.

### "Show Logged Moments for All Games"

Chess Log menu item (after "Save Chess Logs for all games"): opens `ShowTagsDialog` scoped to every game in the active database that has at least one logged entry (`has_chess_log_tags=True`). Buffered editing — OK writes, Cancel discards. Handler: `MainWindow._show_chess_logs_for_all_games`.

### Moves List highlight

Chess Log menu → "Highlight Logged Moments in Moves List" (checkable toggle): when on, moves that have at least one logged entry in the current game's in-memory cache render a themed "logged moment" icon (`app/resources/icons/chess_log_moment.svg`) to the **left** of the move text in the Moves List. Returned via `Qt.DecorationRole` on `COL_WHITE` / `COL_BLACK`; Qt's default delegate handles the left-of-text placement — no custom delegate. Tinting follows the Moves List's own theme colors (normal move-text color on regular rows; `active_move.text_color` on the current-move row; `selection_text_color` via the icon's `QIcon.Mode.Selected` pixmap when a row is selected), rebuilt from `ChessLogMomentIconProvider` on each theme change. The state is persisted to `user_settings.json` under `chess_log_settings.highlight_chess_log_moves_in_list` and restored on startup. The highlight is applied by `MovesListModel.set_highlight_chess_log_moves` and refreshed automatically via `notify_chess_log_changed` whenever Chess Log entries are added, saved, or cleared.

**No emoji on Chess Log surfaces.** All Chess Log indicators that would otherwise be pictographic characters ship as themed SVGs loaded through `app/utils/themed_icon.py`, so they recolor with the active theme and render identically across platforms.

## Dialog theming

`MomentDialog`, `ShowTagsDialog`, and `ShowShallowTagsDialog` use separate config namespaces. `MomentDialog` uses `ui.dialogs.moment`; `ShowTagsDialog` and `ShowShallowTagsDialog` use `ui.dialogs.show_tags` for font family/size and text-edit heights, and continue to use `ui.dialogs.moment` for colors (background, text, border, separator, inputs.background/border). `ChessLogSettingsDialog` uses `ui.dialogs.chess_log_settings`. All blocks exist in all three theme JSON files (`style_default`, `style_light`, `style_scholar`) with theme-appropriate `$_ref` tokens, so the dialogs repaint correctly when CARA's theme is changed.

Every color used in these dialogs' `setStyleSheet` calls must be read from config (via `dc.get(...)`) — **no hardcoded `rgb(…)` literals are permitted**.

All four dialogs are opened via `.exec()` (modal), so "repaint on next open" matches `BulkOperationsDialog`'s behavior; no theme-changed signal infrastructure is needed.

### MomentDialog layout

`MomentDialog` (used by all three presets — CLAMP, CCT, 3x3) is user-resizable via CARA's standard themed resize grip (`install_themed_dialog_resize_grip`). Dialog height is layout-driven; there is no fixed height. Spacing, margins, chip minimum widths, and text-field minimum heights are all theme-driven config under `ui.dialogs.moment` — specifically `layout.margins`, `layout.spacing`, `bottom_button_top_padding`, `buttons.spacing`, `chips.min_width`, `chips.cct_min_width`, `why.minimum_height`, and `three_by_three.edit_minimum_height`. All new sizing keys are registered in `_REQUIRED_CONFIG_KEY_PATHS` and present in all three theme files. 3x3 answer fields use equal stretch factors so they share vertical space when the dialog is enlarged.

### ShowTagsDialog / ShowShallowTagsDialog layout

Both dialogs render rows through the shared `_TagRowWidget`, which reads its font and height config from `ui.dialogs.show_tags.*`:

| Key | Default | Purpose |
| --- | --- | --- |
| `label_font_family` | `"Helvetica Neue"` | Row header + 3x3 prompt labels |
| `label_font_size` | `11` | Row header font size (scaled via `scale_font_size`) |
| `inputs.font_family` | `"Helvetica Neue"` | `QPlainTextEdit` (why + 3x3 answers) |
| `inputs.font_size` | `11` | Text-edit font size (scaled) |
| `why_minimum_lines` | `3` | CLAMP/CCT single why-field min visible lines |
| `three_by_three_edit_minimum_lines` | `3` | Each 3x3 answer field min visible lines |

Font sizes use `QFont.setFont()` (not stylesheet px values) so they scale correctly on HiDPI displays. Min heights for text-edit fields are computed at widget construction time via `_plain_text_edit_min_height_for_lines()` — reads `fontMetrics().lineSpacing()` from the styled widget after `ensurePolished()`, so the pixel height is always correct for the actual rendered font regardless of DPI. Both dialogs are user-resizable via `install_themed_dialog_resize_grip`. All six keys are registered in `_REQUIRED_CONFIG_KEY_PATHS` and verified in `tests/config/test_theme_coverage.py` (`_SHOW_TAGS_DIALOG_KEYS`). Fonts must not be read from the `moment` namespace — keep the two namespaces independent so tuning one dialog doesn't silently affect the other.

## Controller API

### ChessLogController helpers

- `game_has_any_tags() -> bool` — True iff `_cached_paths_data` has any non-empty entry list.
- `replace_entries_at_path(path_key, preset, entries, view=None)` — replaces entries for the given preset at that path; preserves other presets. In-memory only.
- `replace_entries_at_path_for_game(game, path_key, preset, entries)` — same but takes a `GameData` object; correctly routes to either the active single-game cache or the multi-game cache depending on which game is active. Used by `ShowTagsDialog._on_save` and `ShowShallowTagsDialog._on_save`. In-memory only; does not mark the DB unsaved. **This is the only method that explicitly marks a game dirty** (populates `_dirty_games`).
- `save_games(games: Iterable) -> Tuple[int, int]` — writes `game.pgn` for each game via `_save_single_game`, marks the owning database unsaved, clears `_dirty_games` for each saved game. Returns `(n_saved, n_failed)`. Called by dialog Save handlers to commit all edits made in that dialog session. The commit granularity is the **game**: `save_games([game])` writes the full pending cache for that game — including any unsaved Log-this-Moment edits on the same game — in a single `store_tags` call. Chess Log edits on the same game cannot be committed selectively.

## Caching & Database-Switch

### Per-game cache keying

`ChessLogController` maintains several in-memory caches, all keyed by **`id(game)`** (Python object identity), not by `game.game_number`:

| Field | Purpose |
|---|---|
| `_cached_paths_data` / `_cached_game_id` | Single-slot cache for the currently active game |
| `_multi_cache: Dict[int, Dict[str, List[Dict]]]` | Inactive games loaded for ShowTagsDialog / ShowShallowTagsDialog |
| `_dirty_games: Dict[int, GameData]` | Games with in-memory edits pending `save_all_dirty_games()` |
| `_nag_shown_by_game: Dict[int, bool]` | Per-game session flag for the "more than three moments?" nag |
| `_cached_original_paths: Dict[int, Dict[str, List[Dict]]]` | On-disk snapshot captured at load; passed as `original_paths=` to the save-side orphan guard |
| `_resolved_cache: Dict[int, Tuple[int, str, Dict]]` | Memoized orphan-filtered view — `(write_version, pgn_blake2b_hex, resolved_dict)` |
| `_cache_version_by_game: Dict[int, int]` | Write counter per game; bumped by every in-memory mutation; reset to 0 on `_load_into_cache` |

**Why `id(game)` and not `game.game_number`?** Each database assigns `game_number` as a sequential integer starting at 1. Two databases can (and do in practice) produce `GameData` objects with identical `game_number` values. Using `id(game)` (the Python object's memory address) is collision-impossible because different objects have different identities, and the cache dicts hold references so GC cannot reuse the address while the entry lives.

### Database-switch behaviour

`ChessLogController` connects to `DatabasePanelModel.active_database_changed` via `_connect_to_database_panel_model()` (called at the end of `__init__`). On each switch, `_on_active_database_changed()`:

1. **Flushes** the outgoing active game's real edits into `_multi_cache` + `_dirty_games` — but only if `_outgoing_has_real_edits()` returns True. This helper compares `_cached_paths_data` against `load_tags(_cached_game)` (the outgoing game's own disk snapshot), **not** against `has_unsaved_changes()` which reads the game model's current `active_game` — which may already be `None` or the newly-switched game by the time the handler runs.
2. **Clears** the active-game pointers (`_cached_paths_data`, `_cached_game_id`, `_cached_game`).
3. **Prunes** `_dirty_games` entries whose `GameData` is no longer in any open database (via `_prune_dirty_games_against_open_databases`). This handles reload (`reload_database_from_file`) and close events — stale object references cannot be written to by `save_all_dirty_games`.
4. **Preserves** the rest of `_dirty_games` byte-for-byte; drops cache-only entries (`_multi_cache`, `_nag_shown_by_game`, `_cached_original_paths`, `_resolved_cache`, `_cache_version_by_game`) for gids no longer in `_dirty_games`.

The same flush-and-prune logic runs in `_on_active_game_changed(game=None)` for clipboard-clear, database-close, and reload events.

### Save model

Chess Log has two distinct commit layers:

- **Cache edits** (`add_moment_at_active_path`, `replace_entries_at_path`, `replace_entries_at_path_for_game`) — in-memory only. No tab pulse. The edit lands in `_cached_paths_data` or `_multi_cache` and the game is added to `_dirty_games`.
- **Save operations** — write `game.pgn` and mark the owning database unsaved (tab pulse):
  - **Log this Moment → Save Chess Log for Current Game** (`save_tags_for_current_game`) — commits the active game's cache.
  - **Save Chess Logs for All Games** (`save_all_dirty_games`) — commits every game in `_dirty_games`.
  - **Dialog Save** (`save_games(games)`) — commits each game passed in. Called by `ShowTagsDialog._on_save` and `ShowShallowTagsDialog._on_save`.

**Dialog Save/Cancel semantics:**

- `ShowTagsDialog` (Show Logged Moments): **Save** applies every changed row by calling `replace_entries_at_path_for_game` for each, then calls `save_games(affected_games)`. **Cancel** (and the window close button) discards all row edits — nothing was written to the controller cache, so reject is a true no-op.
- `ShowShallowTagsDialog` (Check Logs): **Save** writes `is_shallow=True` for every shown row, clears stale `is_shallow` flags on entries in `classified_keys` that were classified DEEP this run, then calls `save_games(affected_games)`. **Cancel** discards all pending shallow verdicts. The dialog's Save is the **only** place `is_shallow` is committed; `_on_shallow_thread_ready` now just emits the `shallow_ready` signal with `(shallow_keys, classified_keys, usage)` without writing to the cache.
- The "touchable set" (`classified_keys`) is the authoritative scope for the shallow dialog's clear-stale-flag loop. Entries with `ignore_shallow=True`, entries the classifier could not parse, and entries with no `why`-note were excluded from the classifier run and are **never** touched by the dialog's Save — clearing them would silently violate the user's intent.

**Dirty-marking**: databases are marked unsaved only from `_save_single_game` (called by `save_tags_for_current_game`, `save_all_dirty_games`, and `save_games`) and from `clear_tags_for_current_game`. The three edit methods do **not** mark the DB unsaved. Between a Log-this-Moment OK and the user running one of the Save commands, there is no visible indicator that Chess Log work is pending — the design deliberately defers the pulse to the explicit save step.

**Commit granularity**: `save_games([game])` calls `store_tags(game, full_cache_for_game)` — the full pending cache for that game, not just the dialog's edits. If the user had a pending Log-this-Moment edit on game A and then edits game A's note in Show Logged Moments and clicks Save, both edits land in `game.pgn` in a single commit. This is intentional: Chess Log edits on the same game cannot be committed selectively.

### Orphan path_keys

A **path_key** in a game's `CARAChessLog` payload is an **orphan** if its decoded path (e.g. `(99, 0)`) cannot be walked to a node in that game's current move tree. Orphans arise legitimately when moves are edited after a moment was logged, and also from the historical `game_number` collision bug.

Policy:
- **Load side**: `ChessLogStorageService.load_resolved_paths(game)` returns only the path_keys that resolve in the parsed chess game; orphans are logged at WARNING and excluded. `load_tags(game)` still returns the full dict byte-for-byte for save-time round-trip preservation.
- **Save side**: `ChessLogStorageService.store_tags(..., original_paths=...)` refuses to write **new** orphan path_keys (logged at ERROR) but passes through **pre-existing** orphan keys unchanged, so historical data is never silently destroyed. All production save paths route through `_save_single_game`, which supplies `original_paths=self._cached_original_paths.get(gid)`. After a successful save the snapshot is refreshed from disk via `load_tags(game)` — **not** from the `paths_data` dict just written — so a refused orphan stays "new" on the next save and is refused again.
- **Feature code (resolved view)**: `get_tags_for_current_game()`, `get_tags_for_game()`, and `should_confirm_extra_moment()` consume `_resolved_view(raw, game)` — an orphan-filtered copy memoized per `id(game)`. The memoization key is `(write_version, blake2b-16 hash of game.pgn)`. The content hash (not `len(pgn)`) is used so same-length move substitutions (e.g. `Nf3` → `Nc3`) also invalidate the cache. The method always returns a **shallow copy** of the memoized dict so caller mutation cannot corrupt the cache. Background service callers (charts aggregation, narrative prompt, charts controller fallback) call `load_resolved_paths` directly — they read from disk and never see in-session edits, so the one-level disk filter is correct.
- **Display**: `ShowTagsDialog` and `ShowShallowTagsDialog` detect orphan rows by checking `move_label == path_key` (the fallback when `node_at_path` returns `None` in `_tag_row_helpers.node_info`), skip them silently, and append a single notice at the bottom of the dialog listing the count of unreachable moments.

## Key files

- `app/services/chess_log_storage_service.py`
- `app/controllers/chess_log_controller.py`
- `app/views/dialogs/moment_dialog.py`
- `app/views/dialogs/chess_log_settings_dialog.py`
- `app/views/menus/chess_log_menu.py`
- `app/utils/chess_log_prompts.py` — `THREE_BY_THREE_PROMPTS` dict
- `app/utils/pgn_variation_path.py` — `encode_path`
