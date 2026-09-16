# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

CARA is a PyQt6-based desktop chess analysis application. Start it with:

```bash
python cara.py
```

On macOS, you may need `python3` instead. Requires Python 3.8+ and a UCI-compatible chess engine (Stockfish, Berserk, etc.) configured via the Engines menu.

**PyQt6 / PyQt6-Qt6 version pinning.** `requirements.txt` pins both `PyQt6` and `PyQt6-Qt6` to the same exact version. They must match — a mismatch produces a misleading error (`Could not find the Qt platform plugin "cocoa"`) that looks like a missing file, broken signature, or corrupt install, none of which is the actual cause. A plain `pip install -r requirements.txt` on a clean venv should no longer produce drift.

If you hit this error despite installing from `requirements.txt` (e.g. after manually upgrading one package), diagnose with:

```bash
pip show PyQt6 PyQt6-Qt6 | grep -E "Name|Version"
```

If the versions don't match, reinstall whichever one is ahead to match the other:

```bash
pip install --force-reinstall --no-deps PyQt6-Qt6==<matching version>
```

PyPI doesn't always have every point-release pair available for both packages — run `pip install PyQt6-Qt6==` (no version, to list what's available) if the exact match isn't found.

**macOS UF_HIDDEN platform-plugin flag.** PyQt6-Qt6, installed via pip, carries a `com.apple.provenance` extended attribute; on macOS this causes the OS to assert `UF_HIDDEN` on the installed dylibs, including `libqcocoa.dylib` and its sibling platform plugins. The flag is invisible to permissions, dlopen, and codesigning checks but prevents Qt plugin discovery, producing the same misleading "Could not find the Qt platform plugin 'cocoa'" error. (The same mechanism is documented for PyTorch wheels: https://github.com/pytorch/pytorch/issues/178841.) CARA clears this flag automatically at every startup (`app/utils/macos_startup.py` → `clear_platform_plugin_hidden_flags()` called in `cara.py` before `QApplication` is constructed). If you somehow still hit the error after startup has run (e.g., running Python directly without going through `cara.py`), clear manually:

```bash
python3 -c "
import os, glob
plugins = glob.glob(os.path.expanduser('~/.venv/lib/python*/site-packages/PyQt6/Qt6/plugins/platforms/*.dylib'))
for p in plugins:
    st = os.lstat(p)
    if hasattr(st, 'st_flags') and st.st_flags & 0x8000:
        os.chflags(p, st.st_flags & ~0x8000)
        print('cleared', p)
"
```

(Adjust the venv path to match yours.)

## Running Tests

Tests use Python's standard `unittest` framework, living in `tests/` as `test_*.py`.

```bash
# All tests
python -m unittest discover -s tests -p "test_*.py" -v

# A specific subdirectory
python -m unittest discover -s tests/services -p "test_*.py" -v

# A single file, class, or method — same dotted-path pattern
python -m unittest tests.services.test_pgn_service -v
python -m unittest tests.services.test_pgn_service.TestPgnServiceNormalizeMovesFixedWidth -v
```

**Note**: Tests in `tests/opening_integrity/` require local chess engine installations — local only, not run in CI.

**Test coverage is part of every item's definition of done — no exceptions for changes that seem purely cosmetic or UI-only.** "Just a label" or "just styling" is not a reason to skip a test; if it's worth shipping, it's worth a test confirming it shows what it's supposed to show. When implementing a batch of multiple fixes or features, treat "add tests" as part of each individual item, not a cleanup pass at the end. The last item in a batch is just as likely to need coverage as the first.

## Building

PyInstaller specs exist for macOS, Windows, and Linux (`CARA_macos.spec`, etc. — each requires its target OS to build).

```bash
pip install pyinstaller==6.17.0
pyinstaller CARA_macos.spec  # or _windows / _linux
```

Output bundles land in `dist/`.

## Dependencies

See `requirements.txt` for the full, versioned list. One choice worth knowing the reasoning behind: **asteval**, not raw `eval()`, is used for evaluating user-defined expressions — a deliberate safety choice, not an oversight.

```bash
pip install -r requirements.txt
```

## Architecture

CARA follows **PyQt's Model/View pattern with Controllers**, with signal/slot communication throughout.

1. **Models** (`app/models/`) — Qt data models holding application state. Table models (DatabaseModel, MovesListModel, MetadataModel) inherit `QAbstractTableModel`; state models (BoardModel, GameModel, EvaluationModel) inherit `QObject` and emit custom signals. UI-independent and testable in isolation.

2. **Views** (`app/views/`) — UI components. Display data by observing model signals; never modify model data directly — go through a controller instead. All styling comes from `app/config/config.json` (see Configuration below).

3. **Controllers** (`app/controllers/`) — Handle user interactions from views, update models, call services. No UI logic. Entry point: `AppController` wires all feature controllers together.

4. **Services** (`app/services/`, ~129 files) — Computation, file I/O, engine management, analysis algorithms. UI-independent and testable in isolation.

5. **Configuration** (`app/config/`) — see Configuration System below.

6. **Utils** (`app/utils/`) — Font, path, styling, and tooltip helpers.

### Signal/Slot Communication

- Model → View: models emit on data change, views observe and update automatically.
- View → Controller: views call controller methods on user interaction.
- Controller → Model / Controller → Service: controllers update models and invoke service logic.
- Thread → UI: worker threads emit signals for thread-safe UI updates.

## Configuration System

Three files loaded at startup: `app/config/config.json` (UI styling/dimensions/colors/fonts), `user_settings.json` (user preferences), `engine_parameters.json` (UCI engine parameters).

**Config is split by kind, not just by file.** `config.json` holds *behavioral* config; the `style_*.config.json` theme files hold *style/layout* config. ConfigLoader merges both into memory at startup — treat them as one logical config in code, but a new key's *home file* depends on whether it's behavior or presentation, not convenience.

**Convention for new config keys (confirmed by maintainer):** add every new key to ConfigLoader so a missing one fails loudly at startup. Whether the corresponding `.get()` call in code also carries an inline default doesn't matter either way — the loader is the actual gate, `.get()` defaults are just belt-and-suspenders. (The strict-validation-everywhere language elsewhere in this doc is aspirational, not fully true yet — it's known tech debt from a mid-project design shift, with a config-loader refactor planned but not yet done. Don't be surprised by `.get(..., default)` patterns in the existing code; follow the "always register in ConfigLoader" rule for anything new regardless.)

Style config files (`style_default.config.json`, `style_light.config.json`, `style_scholar.config.json`) define reusable constants with a `$_` prefix, referenced elsewhere via `{"$ref": "$_CONSTANT_NAME"}`. `config.json`'s `default_style_config` key selects the active style file.

Key sections: `ui.window`, `ui.panels`, `ui.dialogs.*`, `ui.styles`, `ui.colors`, `ui.fonts`, `version`.

### Configuration Access

```python
bg_color = config.get("ui", {}).get("dialogs", {}).get("my_dialog", {}).get("background_color", [40, 40, 45])
```

**Note:** the docs describe ConfigLoader as strictly validating at startup, but the pattern above uses `.get()` with an inline default — that's not a contradiction to resolve, it's the current transitional state (see Configuration System above). For new config-reading code: register the key in ConfigLoader regardless of whether you also add a `.get()` default.

### Dialog Implementation

Dialogs follow a standard constructor pattern: load config → build UI → apply styling via `StyleManager` (`app/views/style/style_manager.py`). Use `scale_font_size()` and `resolve_font_family()` from `app.utils.font_utils` for font values from config. See `app/views/dialogs/bulk_operations_dialog.py` as the living template rather than a static skeleton here.

## Threading

- **QThread** for I/O-bound engine operations (EvaluationEngineThread, GameAnalysisEngineThread, ManualAnalysisEngineThread) — Qt handles thread safety via signals/slots.
- **ProcessPoolExecutor** for CPU-bound work (player statistics, PGN parsing, multi-file opening), using `max(1, os.cpu_count() - 2)` workers to keep the UI responsive.

## Key Subsystems

### Game Analysis Pipeline
GameAnalysisController → GameAnalysisEngineService (runs engine per move, MultiPV) → MoveClassificationService (Good/Inaccuracy/Mistake/Blunder/Brilliancy by Centipawn Loss) → MovesListModel → GameSummaryService (aggregated statistics, highlights, top moves).

### Game Highlights
Rule-based detection of 44+ tactical/positional patterns, one rule per file in `app/services/game_highlights/rules/`, each implementing a common interface. Tests: one file per rule in `tests/highlight_rules/`. Extend by adding a new rule file.

### Positional Heatmap
Same extensible rule-based architecture as Game Highlights, in `app/services/positional_heatmap/rules/` — weak squares, passed pawns, outposts, piece activity, king safety.

### Player Statistics
Per-player aggregation: accuracy/progression charts, opening/endgame summaries, significant moves, activity heatmap, and **error pattern hints with pattern detection** — worth a direct look before building anything that tracks recurring mistakes, since it may already do part of that job.

### Chess Log (branch: `tagging`)
Human-authored move tagging layer — player self-diagnosis, complementing CARA's engine-based classification. Players tag up to three "moments" per game with a category and optional note.

**Storage**: `CARAChessLog` / `CARAChessLogInfo` / `CARAChessLogChecksum` PGN header triple (same gzip+base64 pattern as Annotations and Notes). Payload is JSON keyed by variation path (`encode_path` from `app/utils/pgn_variation_path.py`). One path = one moment; the 3-moment cap counts distinct non-empty path keys, not total entries (so a CCT moment with two letters = 1 moment).

**Vocabulary**: "moment" in all user-facing text; `tag` is fine in internal code. Avoids collision with `CARAGameTags` whole-game chips.

**Active preset model:** the player selects one active preset — CLAMP, CCT, 3x3, or Custom — in the Chess Log Settings dialog (Chess Log menu → "Chess Log Settings…"), mirroring the existing Engines/AI Summary setup pattern. CLAMP and CCT both allow multiple letters per moment. Custom is a Settings-managed picklist (add/remove), not free-form text at tag time. 3x3 is the sole preset with free-form text at tag time (its three Whys use GM Noel Studer's exact wording: "Why did I choose that move?", "Why is my move not ideal?", "Why is the better move better than my chosen move?"). These strings are defined in `_3X3_PROMPTS` in `moment_dialog.py`, `show_tags_dialog.py`, and `chess_log_pdf_service.py`. The active preset can change over time, so a library may end up with moments tagged under more than one preset — expected, not an error. See `chess-log-design-doc.md` §3.2–3.4 for full detail.

**Zero-category save (CLAMP, CCT, Custom-with-categories):** if no chips/checkboxes are checked but the why-field has content, the moment saves as a single entry with `cat=""` — genuinely uncategorized, not a fake "Other" category. Zero chips + empty why keeps OK blocked (hint shown). The Custom empty-picklist case (no categories defined at all) is distinct: that guard disables OK regardless of why content, because it's a configuration gap, not an honest non-match.

**"More than three moments?" nag:** when a player tries to add a *new* path (a fresh moment, not re-tagging an existing one) and the game already has ≥ 3 tagged moments, a soft "Are you sure?" dialog fires. The nag fires **before** Tag This Moment opens (checked in `DetailMovesListView._on_tag_moment` via `ChessLogController.should_confirm_extra_moment`) so the user is asked before investing typing effort. Once shown, it is suppressed for the rest of the session (`_nag_shown_this_session: bool`, global across all games) and for all future sessions for that specific game (`_nag_shown_by_game: Dict[int, bool]`, persisted in the `CARAChessLog` payload as `"nag_shown": true`). Persistence follows the explicit-save convention: the flag rides with the next Ctrl+Alt+L save; if the user never saves the game, the flag is lost along with the moment itself. Re-tagging an existing path (adding a second preset's entries to an already-tagged move) never counts as a new moment and never triggers the nag.

**CARA-namespaced PGN tags** (all read-only in metadata view and model):
- `CARAAnalysisData` / `CARAAnalysisInfo` / `CARAAnalysisChecksum` — per-move engine data
- `CARAAnnotations` / `CARAAnnotationsInfo` / `CARAAnnotationsChecksum` — board drawing annotations
- `CARANotes` / `CARANotesInfo` / `CARANotesChecksum` — whole-game text notes
- `CARAChessLog` / `CARAChessLogInfo` / `CARAChessLogChecksum` — Chess Log moments
- `CARAGameTags` — whole-game chip tags

**Key files**: `app/services/chess_log_storage_service.py`, `app/controllers/chess_log_controller.py`, `app/views/dialogs/moment_dialog.py`, `app/views/dialogs/chess_log_settings_dialog.py`, `app/views/menus/chess_log_menu.py`.

**Entry point**: first-time users should open Chess Log → Chess Log Settings to pick their preset (and, for Custom, populate the picklist). Then right-click a move in the Moves List → "Tag this moment…". Save via Chess Log menu → "Save Chess Log to current game" (`Ctrl+Alt+L`). Clear via `Ctrl+Shift+L`.

**Moves-list context menu structure** (right-click on any move):
1. Column profile (submenu)
2. --- separator ---
3. Copy value
4. Edit Comments (conditional — only when clicking a Comment cell)
5. --- separator ---
6. Tag this moment…
7. **Show Tags** — opens `ShowTagsDialog` scoped to the current game, sorted by ply ascending then preset in canonical order (CLAMP → CCT → 3x3 → Custom). Enabled iff the game has at least one tagged entry. Disabled with tooltip "No tagged moments in this game." when the game has zero tags.
8. --- separator ---
9. Copy Table as CSV / TSV (4 actions)

**Show Tags dialog** (`app/views/dialogs/show_tags_dialog.py`, class `ShowTagsDialog`): parameterized for single-game or multi-game — pass `games=[game]` for single-game (context-menu path), `games=[g1, g2, …]` for multi-game ("Show Chess Logs for all games" menu path). Each row represents one (move, preset) pair: board miniature, category checkboxes (blank for 3x3), why-note text. All fields editable on open. **Buffered editing** — OK persists changes to the in-memory cache via `replace_entries_at_path_for_game`; Cancel discards all edits. Multi-game usage inserts a game-header label (`White - Black Result (Date - N moves)`) between each game's rows; single-game usage shows no header. Zero-category saves (`cat=""`) round-trip correctly through OK. `ignore_shallow` field is transparently preserved through edits. Rows whose entries carry `is_shallow=True` render a **⚠️ + Ignore** group right-justified on the move-label line, same as in `ShowShallowTagsDialog` — `ShowTagsDialog` computes this per-row via `any(e.get("is_shallow") for e in entries)` and passes `show_ignore_checkbox=True` accordingly to `_TagRowWidget`. **Export to PDF** button (left of the button row) exports on-screen rows WYSIWYG — including in-progress buffered edits — via `ChessLogPDFService`. Rows are paginated atomically (no row straddles a page break); multi-game exports include per-game headers kept with their first row. `_TagRowWidget.snapshot()` captures the live widget state into a `TagRowSnapshot` dataclass used by the exporter.

**`ChessLogController` helpers**:
- `game_has_any_tags() -> bool` — True iff `_cached_paths_data` has any non-empty entry list.
- `replace_entries_at_path(path_key, preset, entries, view=None)` — replaces entries for the given preset at that path; preserves other presets. In-memory only.
- `replace_entries_at_path_for_game(game, path_key, preset, entries)` — same but takes a `GameData` object; correctly routes to either the active single-game cache or the multi-game cache depending on which game is active. Used by both `ShowTagsDialog` (on OK) and `ShowShallowTagsDialog` (live edit).

**"Show Chess Logs for all games"** (Chess Log menu, after "Save Chess Logs for all games"): opens `ShowTagsDialog` scoped to every game in the active database that has at least one tagged entry (`has_chess_log_tags=True`). Buffered editing — OK writes, Cancel discards. Handler: `MainWindow._show_chess_logs_for_all_games`.

**Out of scope for the `tagging` branch**: "highlight tagged moves" toggle.

### Chess Log Charts (branch: `chess-log-charts`, §5.1 + §5.2)

Reporting and visualization layer for Chess Log — the detail tab (index 9, F10) that lets players see how their mistake mix shifts over time and get an AI narrative summary.

**Presets in scope**: CLAMP, CCT, Custom. **3x3 deferred** — its Why1/2/3 entries aren't a comparable category axis and need separate design.

**Charting**: stacked vertical `ChessLogCategoryChartWidget` instances (one per preset) in a `QScrollArea`. Each is a fresh `QPainter` widget — not a subclass of `MoveQualityOverTimeChartWidget`. The four scaffolding helpers from `player_stats_service.py` (`_game_date_ordinal_for_trends`, `_ordinal_target_bin_count`, `_ordinal_fallback_mode`, `_calendar_bin_center_time_pct`) are reused; the bin-filling functions are fresh count-based implementations in `chess_log_stats_service.py`. Legend always shows the full canonical set for CLAMP (C,L,A,M,P) and CCT (Checks,Captures,Threats) — categories absent from the data appear dimmed (no line drawn, greyed text, 40% alpha swatch). Stale chart clears immediately on source/player/color change (via `charts_loading` signal); no visible loading indicator is shown. Player/color-filter changes are debounced (100ms) to prevent rapid-click flicker. **Player selection is required** — changing Data Source does not auto-chart; the Player dropdown starts unselected and shows "Select a player…" in the chart area until the user makes an explicit choice.

**Time series settings menu** (Chess Log → "Time series settings"): 6-item, 3-group menu mirroring Player Stats exactly. Group A — Binning: "Progression bins" (8/12/16/24/32, default 16) and "Binning mode" (quantile/equal_width, default quantile). Group B — X axis: "X axis layout" (uniform_bins/gap_compressed/calendar_linear, default uniform_bins) and "Max gap segment (calendar days)" (14/28/50/100, default 28). Group C — Line: "Progression line style" (smooth/straight, default smooth) and "Smoothing strength" (0.5/1.0/1.5/2.0, default 1.0). All 6 settings persist under `user_settings.chess_log.charts.{target_bins, binning_mode, x_axis_layout, max_gap_segment_days, line_style, smoothing_strength}`. Settings module: `app/services/chess_log_charts_user.py`. The old two-key schema (`x_axis_mode`, `game_count` binning) is removed — `normalize_chess_log_charts_settings()` migrates old `x_axis_mode` values on first load.

**Widget rendering**: `ChessLogCategoryChartWidget` supports three x-axis layouts. `uniform_bins` and `gap_compressed` both use equal pixel spacing by bin index (`gap_compressed` falls back to `uniform_bins` — full `GapCompressedTimeLayout` port from `detail_player_stats_view.py` is a TODO). `calendar_linear` draws a real fixed calendar-tick axis (ported verbatim from Player Stats): `_draw_calendar_axis()` generates monthly gridlines and labels from the full ordinal range (`ChessLogPresetSeries.t_min`/`t_max`) independently of bin layout, and `_bin_x()` positions each data bin at its calendar center (`(lab0_ord + lab1_ord) // 2`) using the same `_ordinal_to_chart_x()` helper — identical coordinate systems by construction. Empty months appear as genuine visible space between gridlines. Smooth Catmull-Rom lines via `_smooth_polyline_path()` (ported from Player Stats) are used when `series.line_style == "smooth"`. `ChessLogPresetSeries` carries `t_min`/`t_max` (day ordinals for the raw data extent) populated by `_bin_preset()` in `chess_log_stats_service.py`.

**DRY debt (future PR)**: `_smooth_polyline_path`, `_ordinal_to_chart_x`, `_calendar_axis_ticks`, and supporting helpers now exist in both `detail_player_stats_view.py` and `chess_log_category_chart_widget.py`. These should be extracted to `app/views/widgets/_chart_layout_helpers.py` (or `app/utils/chart_axis.py`) so a third chart tab doesn't produce a third copy. Similarly, `ChessLogChartsMenuController` and `PlayerStatsTimeSeriesMenuController` share ~80% structure — a `RadioMenuController` base class would remove ~150 lines of duplication. Both are deliberate additive ports; refactoring is a separate PR.

**Narrative**: LLM-gated (same provider config as AI Summary). Prompt assembled from a per-preset glossary block, trend-binned category counts (4 bins via `aggregate()`), why-notes, and whole-game notes. `_parse_response` always returns `(narrative, [])` — shallow-note flagging was removed from the prompt (step 2 deleted). LLM-not-configured state shows a hint and disables all narrative controls — no restart needed after configuring (AI Model Settings close triggers `set_user_settings`). The AI state is seeded at app startup (not only on dialog close), so the hint correctly reflects the user's saved provider settings from first view.

**Narrative prompt structure** (assembled in `chess_log_narrative_service.build_prompt`):
1. `## Glossary — <preset>` block for each preset present in the data (verbatim definitions only — never paraphrase or invent). CLAMP has full text (C=Checks, L=Loose Pieces and Squares, A=Alignments, M=Mobility Restrictions, P=Passed Pawns). CCT now has full text (Checks reuses CLAMP's Checks definition verbatim; Captures reuses CLAMP's L definition with commas replacing em dashes; Threats is Paul's new definition). Note: both Checks and Captures start with C, so a CCT rule in `_SYSTEM_PROMPT` tells the model to always use the full category name, never a bare letter. A second CCT rule tells the model that CCT tags are bidirectional — a tag may describe the player's candidate move OR the opponent's prior move; always read the why-note to tell which. 3x3 does not get a letter glossary; it gets a `## Why-note structure — 3x3` block (via `_format_3x3_structure` / `_3X3_STRUCTURE_BLOCK`) that explains GM Noel Studer's three Why-questions in numbered order and notes that missing answers are simply unanswered. Custom remains `""` (no glossary, undesigned).
2. `## Category counts by preset (over time)` — 4 trend bins from `aggregate(chart_cfg={"target_progression_bins": 4, "min_games_per_ordinal_bin": 1})`. Fallback to flat totals + note when aggregate returns empty (no dated games).
3. Why-notes and whole-game notes. A note-normalization one-liner above the whole-game notes section instructs the model to treat them as illustrative color only, not primary evidence.
4. Narrative instruction: three explicit sections in order — `## Patterns & Recurrent Themes` (2–4 paragraphs of cross-cutting behavioral themes; CLAMP letter/percentage framing is forbidden here), `## Tactical Breakdown` (a GFM pipe table with columns `Area | Observed Issue | Strategic Impact`; one row per CLAMP/CCT category supported by the data; this is where category-level detail belongs), and `## Key Takeaways` (1–3 short prose paragraphs, not a list, each anchored to a verbatim quote from the player's own notes). Additional system-prompt rules: full move+color citation pairing required (`16. b4, White vs Black`); verbatim quotes capped at 1–2 per theme/row/takeaway paragraph. Both surfaces render `**bold**` markdown and `##` headings natively. The pipe table renders as a real bordered table in the on-screen `QTextEdit` via `setMarkdown` (GFM tables supported in Qt 6.4+, requirements.txt pins 6.11) and as QPainter-drawn bordered cells in the PDF via `_draw_pipe_table_paginated`. Default token limit: **12000** (spinbox range 256–16000, ephemeral).

**Thinking/adaptive-reasoning gate**: `generate_narrative` (`chess_log_narrative_service.py`) detects next-gen Anthropic models with default adaptive thinking (Sonnet 5, Opus 5) and passes `thinking={"type": "disabled"}` on the `AIService.send_message` call. Detection is a case-insensitive substring check — `"sonnet-5" in model` or `"opus-5" in model` — so dated variants like `claude-opus-5-20260901` are also caught. All other providers and model families receive `thinking=None` (no change). `AIService.send_message` and `AIService._send_anthropic_message` both accept the optional `thinking: Dict | None` kwarg; it is added to the Anthropic request body when set and ignored for OpenAI/custom endpoints.

**Narrative panel controls** (visible when AI is configured): Model combo (ephemeral, lists models for the active provider from `ai_models.{provider}.models`), Timeout spinner (10–600s, shared with AI Summary via `ai_summary.request_timeout_seconds` — changing it here also changes it in the AI Summary tab), Tokens spinner (256–16000, default **12000**, ephemeral — not persisted to user_settings). A **"Show Shallow Tags"** button (`_show_shallow_btn`) sits between the model/timeout/tokens row and the Generate button — enabled when AI is configured. Clicking disables the button, starts a `BusySpinner` and shows "Generating Shallow Tags…" to the right, then calls `request_flag_shallow_notes()` on the controller. The spinner and label clear on `shallow_ready` / `shallow_failed`. If the key set is empty, shows "No shallow notes found"; otherwise opens `ShowShallowTagsDialog`. The controller's `get_available_models()` / `get_default_narrative_model()` / `get_narrative_timeout_seconds()` drive the view; `set_narrative_*()` setters update the in-memory state (timeout also persists).

**Show Shallow Tags dialog** (`app/views/dialogs/show_shallow_tags_dialog.py`, class `ShowShallowTagsDialog`): displays only the rows whose `(game_number, path_key, preset)` tuple is in the `shallow_keys` set returned by `request_flag_shallow_notes()`. **Live-edit** — every `_TagRowWidget.edited` signal immediately calls `replace_entries_at_path_for_game`; no OK button, no buffer, no diff. **Close** button plus an **Export to PDF** button (left of button row); export calls `ChessLogPDFService.export_tags(..., is_shallow_only=True)` with a WYSIWYG snapshot of current row state; rows paginated atomically. All rows include **⚠️ + Ignore** (`show_ignore_checkbox=True`) — when Ignore is checked, `ignore_shallow=True` is stored in each entry dict. Dismissed rows stay visible in the current dialog session (disappear only at the next Show Shallow Tags open, since `request_flag_shallow_notes()` skips entries with `ignore_shallow=True`).

**`ignore_shallow` schema field**: added to entry dicts via `ChessLogStorageService.make_entry(preset, cat, why, ignore_shallow=False)`. Omitted from the dict when `False` (backward-compatible — old entries read as `ignore_shallow=False` via `.get("ignore_shallow", False)`). Preserved through controller round-trips: both `replace_entries_at_path` and `replace_entries_at_path_for_game` pass `ignore_shallow=bool(e.get("ignore_shallow"))` when reconstructing entries via `make_entry`. `_TagRowWidget` without `show_ignore_checkbox` transparently carries the original moment-level flag through `get_current_entries()`.

**`is_shallow` schema field**: added to entry dicts via `ChessLogStorageService.make_entry(preset, cat, why, is_shallow=False)`. Omitted when `False` (backward-compatible). Written by `ChessLogChartsController._on_shallow_thread_ready()` after classification — full sync: entries in the result set get `is_shallow=True`; all others have `is_shallow` removed. Persisted to the PGN via the normal Save Chess Log flow (same lifecycle as `ignore_shallow`). Both `_TagRowWidget._preserved_is_shallow` and `get_current_entries()` carry the flag through edits so it survives round-trips in both dialogs.

**`request_flag_shallow_notes()` in `ChessLogChartsController`**: async replacement for the former synchronous `flag_shallow_notes()`. Spawns `ChessLogShallowThread`; on completion writes `is_shallow` onto all in-scope entries (via `replace_entries_at_path_for_game`), marks those games dirty, and emits `shallow_ready(Set[Tuple[int,str,str]])`. On error emits `shallow_failed(str)`. Skips entries with `ignore_shallow=True`. Public accessor `get_chess_log_controller()` exposes the underlying `ChessLogController` to the view.

**Chess Log Charts right-click context menu** (`app/views/menus/chess_log_charts_context_menu.py`): right-clicking any chart widget or the narrative panel opens a three-action menu. *Copy section to clipboard* — for charts, inserts a placeholder line ("Category chart \<preset\>: see Chess Log Charts tab"); for the narrative panel, inserts the current narrative text verbatim. *Copy log to clipboard* — text of all charts (as placeholder lines) + narrative + fresh shallow tags if available; format: one line per (game / move / preset / cat / why). *Export PDF Report* — same content as Copy Log as a PDF: chart widgets via `widget.grab()` embedded as images, narrative as text, shallow-tag row cards with atomic pagination. Each `ChessLogCategoryChartWidget` and the narrative `QFrame` carry a `section_name` property (`f"chart_{preset}"` / `"narrative"`) used for hit-testing in `contextMenuEvent`. `_narrative_edit` uses `Qt.ContextMenuPolicy.NoContextMenu` so right-clicks bubble up rather than opening the built-in text-edit menu.

**Shallow-tag freshness rule**: Copy Log and Export PDF include shallow tags only when fresh — `self._last_shallow_keys: Optional[FrozenSet[Tuple[int, str, str]]]` on the view is non-None. Set in `_on_shallow_ready` (after Show Shallow Tags runs); cleared in `_on_source_changed` and `_on_player_changed`. When stale or not yet run, shallow tags are silently omitted. Color filter is not yet wired to a UI control in this view — when a Color combo is added, its change handler must also clear `_last_shallow_keys`.

**Chess Log Charts right-click → Export PDF Report** source label: the PDF header reads `Source: <combo-text>: <pgn-stem>[, <pgn-stem>...]`. The filename list is built by `ChessLogChartsController.get_current_source_filenames()`, which mirrors the `_resolve_games` selection logic (active database → 1 name; all open → N names). `DatabaseModel.display_name` (Path stem or "Clipboard") is used for each entry.

**Tag row cards in PDFs** are sized dynamically: `card_h = pad*2 + header_h + 4 + max(board_sz, body_content_h)`. `body_content_h` is measured via `painter.boundingRect` (checkboxes×line_h vs. word-wrapped why-text for CLAMP/CCT/Custom; sum of prompt+answer pairs for 3x3). Cards are never taller than content requires. The helper `ChessLogPDFService._measure_tag_row_height(painter, content, row)` is called both by `_draw_tag_row` (for `_ensure_space`) and by `export_tags` / `export_charts_report` (for the `keep_with` parameter in `_section_heading`, ensuring game headers never orphan from their first row).

**Warning triangle in PDF**: drawn as a QPainter yellow-filled polygon with black exclamation mark (not a Unicode glyph — emoji doesn't render in PDF fonts). Positioned right-aligned on the header line, immediately to the left of "Ignore: Yes/No". Drawn via `ChessLogPDFService._draw_warning_triangle(painter, x, y, size)`.

**Narrative rendering**: `ChessLogPDFService._draw_narrative_paginated` is block-aware — it uses a `while` loop to detect GFM pipe tables (a `|`-starting line followed by an alignment separator row) and routes them to `_draw_pipe_table_paginated`, which renders bordered QPainter cells with a filled header row (`self._card` background, `_font_body_bold`) and word-wrapped body cells measured via `boundingRect`. Column widths: fixed 20/40/40 split for the canonical 3-column schema (Area narrower, Observed Issue and Strategic Impact each 40%). Rows are atomic (measure then `_ensure_space` then draw). Prose lines word-wrap as before via `_parse_bold_spans` + per-word x-cursor; `##` headings go through `_section_heading`. The on-screen `QTextEdit` uses `setMarkdown` (GFM pipe tables render natively at Qt 6.4+, requirements.txt pins 6.11); error and placeholder paths use `setPlainText`.

**Tech debt** (`widget.grab()` chart quality): `ChessLogPDFService.export_charts_report` embeds charts as screen-resolution pixmaps from `widget.grab()`. Player Stats re-renders charts natively via QPainter from series data. If PDF chart quality is inadequate, the upgrade path is a native-QPainter pipeline in `ChessLogPDFService` — flagged as tech debt; the existing path is upgradeable without API changes.

**Tech debt note**: `BusySpinner` (`app/views/widgets/busy_spinner.py`) and the private `_BusySpinner` inside `app/views/dialogs/bulk_operations_dialog.py` are independent copies of the same widget. The `bulk_operations_dialog.py` copy should be replaced with `BusySpinner` in a future PR coordinated with Philipp.

**AI provider config**: `app/utils/ai_provider_config.py` — shared `is_ai_configured` / `resolve_default_provider` helpers extracted from the inline logic in `AIChatController.get_default_model`. Used by both Chess Log Charts and AI Summary.

**Save Chess Logs for all games** (Chess Log menu, no shortcut): saves every game in `ChessLogController._dirty_games` via `ChessLogStorageService.store_tags` directly — does NOT flip the active game. Handler: `MainWindow._save_chess_logs_for_all_games` → `chess_log_controller.save_all_dirty_games()`. Reports count of saved/failed games in the status bar. Cache coherency across active-game transitions: Rule A (activation promotes from multi-cache before hitting disk) and Rule B (deactivation flushes single-game cache into multi-cache) ensure edits to inactive games are never silently discarded.

**Multi-game cache in ChessLogController**: `_multi_cache: Dict[int, Dict[str, List[Dict]]]` (keyed by game_number) holds moments for games not currently active; `_dirty_games: Dict[int, GameData]` tracks which games have unpersisted edits. Public API: `get_tags_for_game(game)`, `replace_entries_at_path_for_game(game, path_key, preset, entries)`, `save_all_dirty_games() -> Tuple[int, int]`, `has_dirty_games() -> bool`. A game lives in exactly one store at a time — single-game cache when active, multi-cache when not.

**Key files**: `app/services/chess_log_stats_service.py`, `app/services/chess_log_narrative_service.py`, `app/services/chess_log_pdf_service.py`, `app/controllers/chess_log_charts_controller.py`, `app/controllers/chess_log_controller.py`, `app/views/detail_chess_log_charts_view.py`, `app/views/widgets/chess_log_category_chart_widget.py`, `app/views/widgets/busy_spinner.py`, `app/views/menus/chess_log_charts_context_menu.py`, `app/views/dialogs/_tag_row_helpers.py` (holds `node_info` / `ply_for_path`; `_TagRowWidget` itself lives in `show_tags_dialog.py`), `app/views/dialogs/show_tags_dialog.py`, `app/views/dialogs/show_shallow_tags_dialog.py`, `app/utils/ai_provider_config.py`.

## Naming Conventions

- Controllers: `*_controller.py` / `*Controller`
- Models: `*_model.py` / `*Model`
- Services: `*_service.py` / `*Service`
- Views: `*_view.py` or `*_panel.py` / `*View` or `*Panel`
- Dialogs: `*_dialog.py` / `*Dialog`
- Tests: `test_*.py` / `Test*`
- Signals: `<noun>_changed` (e.g. `position_changed`, `evaluation_updated`)
- Config keys: dotted notation (`"ui.dialogs.my_dialog.width"`)

## Documentation

Architecture and feature docs live in `doc/` — `architecture_outline.md` for high-level design/threading/error handling, `dialog_style_guide.md` for the dialog pattern, plus feature-specific docs (game analysis, highlights, heatmap, player stats, annotations). Check there before re-deriving something already documented.

## Git Workflow

This fork has two `master` branches to keep straight:

- **This fork's `master`** — the integration branch for Chess Log development. Feature branches merge here via PR, reviewed by Paul.
- **Upstream CARA's `master`** (Philipp's) — a separate, later destination. Never push or target it directly. Reaching it happens via a deliberate PR once a feature is complete enough to integrate well into the app — config.json, the theme system, the manual (`resources/manual/index.html`), and any new keyboard shortcuts, per Philipp — not a partial/incremental PR (confirmed by Philipp, 2026-08-24).

Rules:
- **Never commit directly to either `master`.** Always work on a feature branch. If none exists for the current task, create one before the first commit — don't wait to be asked.
- **Never run `git push` on any branch without first showing Paul the exact commit(s) about to be pushed and getting explicit confirmation.** This applies universally — including pushes to this fork's own `origin`, not just pushes or PRs that reach upstream. No exceptions based on how minor or "obviously fine" a change seems. (Supersedes the earlier narrower rule that only required confirmation for upstream PRs — that distinction proved insufficient in practice.)
- Prefer small, focused commits (one logical change each) over large batched ones — easier to review, easier to revert if something's wrong.
- **After a conversation compaction, don't assume a multi-part directive is complete.** Compaction summarizes the conversation and can lose track of which parts of a multi-part directive were actually finished versus still pending — this has specifically happened with investigate-then-report steps being silently skipped in favor of jumping to whatever the last visible action was (e.g. a push). When resuming after compaction, check whether the directive in progress had multiple parts, and if so, confirm explicitly with Paul which parts are actually done before treating the task as finished.

## CI/CD

`.github/workflows/tests.yml` runs on Python 3.12 with `QT_QPA_PLATFORM=offscreen` for headless Qt testing, on push to `master`/`development` and on PRs. Manual-trigger build workflows (`build-appbundles.yml`, `build-linux-appbundles.yml`) produce macOS/Windows/Linux bundles as artifacts.

## Version and Release

Version lives in `app/config/config.json` under `"version"` — build scripts read it for bundle naming. Release notes in `RELEASE_NOTES.md`; pre-built bundles on the GitHub Releases page.
