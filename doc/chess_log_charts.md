# Chess Log Charts

Reporting and visualization layer for Chess Log — the detail tab (index 9, F10) that lets players see how their mistake mix shifts over time and get an AI narrative summary.

**Presets in scope**: CLAMP, CCT. **3x3 deferred** — its Why1/2/3/4 entries aren't a comparable category axis and need separate design.

See also: `doc/chess_log.md` for the tagging layer itself.

## Charting widget

Stacked vertical `ChessLogCategoryChartWidget` instances (one per preset) in a `QScrollArea`. Each is a fresh `QPainter` widget — not a subclass of `MoveQualityOverTimeChartWidget`. The four scaffolding helpers from `player_stats_service.py` (`_game_date_ordinal_for_trends`, `_ordinal_target_bin_count`, `_ordinal_fallback_mode`, `_calendar_bin_center_time_pct`) are reused; the bin-filling functions are fresh count-based implementations in `chess_log_stats_service.py`.

Legend always shows the full canonical set for CLAMP (C,L,A,M,P) and CCT (Checks,Captures,Threats) — categories absent from the data appear dimmed (no line drawn, greyed text, 40% alpha swatch). Stale chart clears immediately on source/player/color change (via `charts_loading` signal); no visible loading indicator is shown. Player/color-filter changes are debounced (100ms) to prevent rapid-click flicker.

**Player selection is required** — changing Data Source does not auto-chart; the Player dropdown starts unselected and shows "Select a player…" in the chart area until the user makes an explicit choice.

## Time series settings menu

Chess Log → "Time series settings": 6-item, 3-group menu mirroring Player Stats exactly.

- **Group A — Binning**: "Progression bins" (8/12/16/24/32, default 16) and "Binning mode" (quantile/equal_width, default quantile).
- **Group B — X axis**: "X axis layout" (uniform_bins/gap_compressed/calendar_linear, default uniform_bins) and "Max gap segment (calendar days)" (14/28/50/100, default 28).
- **Group C — Line**: "Progression line style" (smooth/straight, default smooth) and "Smoothing strength" (0.5/1.0/1.5/2.0, default 1.0).

All 6 settings persist under `user_settings.chess_log.charts.{target_progression_bins, ordinal_fallback_mode, progression_x_axis_mode, compress_gap_max_segment_days, progression_line_style, progression_line_smooth_strength}` — leaf names aligned with Player Stats. Settings module: `app/services/chess_log_charts_user.py`. `normalize_chess_log_charts_settings()` handles settings migration on first load.

## Widget rendering

`ChessLogCategoryChartWidget` supports three x-axis layouts:

- `uniform_bins` — bins spaced evenly by index.
- `gap_compressed` — uses `GapCompressedTimeLayout` (built from bin center ordinals in `set_series`) so long game-free spans compress horizontally.
- `calendar_linear` — real fixed calendar-tick axis: `_draw_calendar_axis()` generates monthly gridlines from the full ordinal range (`ChessLogPresetSeries.t_min`/`t_max`) and `_bin_x()` places each bin at its calendar center via `ordinal_to_chart_x()` — identical coordinate systems by construction.

Smooth Catmull-Rom lines via `smooth_polyline_path()` when `series.progression_line_style == "smooth"`. `ChessLogPresetSeries` carries `t_min`/`t_max` populated by `_bin_preset()` in `chess_log_stats_service.py`.

## Shared helpers

**Shared chart helpers** (`app/views/widgets/_chart_layout_helpers.py`): `smooth_polyline_path`, `ordinal_to_chart_x`, `calendar_axis_ticks`, `effective_calendar_mode`, `week_start_monday_ordinal`, `GapCompressedTimeLayout`, `build_gap_compressed_time_layout` — used by both `ChessLogCategoryChartWidget` and the Player Stats chart widgets. A third chart tab can import from this module without creating a third copy.

**Shared menu base** (`app/views/menus/_radio_menu_controller.py`): `RadioMenuController` is the abstract base for both `ChessLogChartsMenuController` and `PlayerStatsTimeSeriesMenuController`. It owns all 6 action groups, `attach_to_parent_menu`, `sync_from_settings`, and all 6 handler methods (`_on_target_bins_selected`, `_on_ordinal_mode_selected`, `_on_x_axis_mode_selected`, `_on_gap_segment_days_selected`, `_on_line_style_selected`, `_on_smooth_strength_selected`). Subclasses only implement `_read_settings() -> Dict` and `_apply(key, value)`. Player Stats menu also adds `append_to_context_menu`. Handler methods that require the action objects guard with `RuntimeError("call _ensure_actions() first")` instead of bare asserts so the error survives Python's `-O` flag and names the violated precondition explicitly.

## Narrative

LLM-gated (same provider config as AI Summary). Prompt assembled from a per-preset glossary block, trend-binned category counts (4 bins via `aggregate()`), why-notes, and whole-game notes. `_parse_response` always returns `(narrative, [])`. `generate_narrative()` returns a `NarrativeResult` frozen dataclass: `success: bool`, `text: str`, `shallow_flags: List[str]` (always `[]`), `usage: Optional[TokenUsage]`, `model: str`. LLM-not-configured state shows a rich-text hint label (`_ai_hint`) with a clickable `<a href="ai-model-settings">AI Model Settings</a>` link — clicking it calls `main_window._show_ai_model_settings()` via `_on_ai_hint_link_clicked`. All narrative controls are disabled until AI is configured — no restart needed (AI Model Settings close triggers `set_user_settings`). The AI state is seeded at app startup (not only on dialog close), so the hint correctly reflects the user's saved provider settings from first view. Link color per theme: `ui.panels.detail.chess_log_charts.colors.link`.

### Narrative prompt structure (assembled in `chess_log_narrative_service.build_prompt`)

1. `## Glossary — <preset>` block for each preset present in the data (verbatim definitions only — never paraphrase or invent). CLAMP has full text (C=Checks, L=Loose Pieces and Squares, A=Alignments, M=Mobility Restrictions, P=Passed Pawns). CCT has full text (Checks reuses CLAMP's Checks definition verbatim; Captures reuses CLAMP's L definition with commas replacing em dashes; Threats is Paul's new definition). Note: both Checks and Captures start with C, so a CCT rule in `_SYSTEM_PROMPT` tells the model to always use the full category name, never a bare letter. A second CCT rule tells the model that CCT tags are bidirectional — a tag may describe the player's candidate move OR the opponent's prior move; always read the why-note to tell which. 3x3 does not get a letter glossary; it gets a `## Why-note structure — 3x3` block (via `_format_3x3_structure` / `_3X3_STRUCTURE_BLOCK`) that explains GM Noel Studer's four Why-questions in numbered order and states that the four answers form one connected reasoning chain: Why1=intent, Why2=what was wrong with the chosen move, Why3=why the better move is better (often the same underlying point as Why2 restated from a different angle, not always a distinct second step), Why4=lesson for next time. Either Why2 or Why3, or both, may be blank — treated as unanswered, not a break in the chain. In addition, `build_prompt` injects a `_3X3_MOMENT_SENTINEL` tuple into the `why_notes` list before each moment's block of Why-answers; `_format_why_notes` detects the sentinel and emits a `_3X3_MOMENT_FRAMING` line that repeats the chain relationship inline, immediately before each moment's notes, so the model sees the framing at the point in the prompt where it reads the actual data.
2. `## Category counts by preset (over time)` — 4 trend bins from `aggregate(chart_cfg={"target_progression_bins": 4, "min_games_per_ordinal_bin": 1})`. Fallback to flat totals + note when aggregate returns empty (no dated games).
3. Why-notes and whole-game notes. A note-normalization one-liner above the whole-game notes section instructs the model to treat them as illustrative color only, not primary evidence.
4. Narrative instruction: three sections in order — `## Patterns & Recurrent Themes` (GFM bullets, 2–4 per theme, bold lead-in; no CLAMP letter/% framing), `## Tactical Breakdown` (pipe table: `Skill | Observed Issue | Strategic Impact`; Skill = generic chess concepts — King Safety, Piece Coordination, etc.; **never** CLAMP/CCT/3x3 vocab in Skill column), `## Key Takeaways` (1–3 prose paragraphs, bold lead-in, anchored to verbatim player quote). Rules: full move+color citation required (`16. b4, White vs Black`); ≤ 1–2 verbatim quotes per section. Both surfaces render `**bold**` and `##` natively; pipe table via `setMarkdown` / `_draw_pipe_table_paginated`; bullets via `_draw_bullet_line_paginated`. Default token limit: **12000**. Constants: `_SYSTEM_PROMPT` and `_NARRATIVE_STEP` in `chess_log_narrative_service.py`; no `mode` param.

### Thinking/adaptive-reasoning gate

`generate_narrative` (`chess_log_narrative_service.py`) detects next-gen Anthropic models with default adaptive thinking (Sonnet 5, Opus 5) and passes `thinking={"type": "disabled"}` on the `AIService.send_message` call. Detection is a case-insensitive substring check — `"sonnet-5" in model` or `"opus-5" in model` — so dated variants like `claude-opus-5-20260901` are also caught. All other providers and model families receive `thinking=None` (no change). `AIService.send_message` and `AIService._send_anthropic_message` both accept the optional `thinking: Dict | None` kwarg; it is added to the Anthropic request body when set and ignored for OpenAI/custom endpoints.

### Narrative panel controls (visible when AI is configured)

Model combo (ephemeral, lists models for the active provider from `ai_models.{provider}.models`), Timeout spinner (10–600s, shared with AI Summary via `ai_summary.request_timeout_seconds` — changing it here also changes it in the AI Summary tab), Tokens spinner (256–16000, default **12000**, ephemeral — not persisted to user_settings).

A **"Show Shallow Tags"** button (`_show_shallow_btn`) sits between the model/timeout/tokens row and the generate button — enabled when AI is configured. A single **"Generate Narrative"** button (`_generate_btn`) triggers narrative generation; clicking disables it, sets the edit to "Generating…", then calls `request_narrative()` on the controller. It re-enables when `narrative_ready` or `narrative_failed` fires.

Clicking "Show Shallow Tags" disables the button, starts a `BusySpinner` and shows "Generating Shallow Tags…" to the right, then calls `request_flag_shallow_notes()` on the controller. The spinner and label clear on `shallow_ready` / `shallow_failed`. If the key set is empty, shows "No shallow notes found"; otherwise opens `ShowShallowTagsDialog`.

**Token usage labels.** Two right-aligned `QLabel` instances appear after runs: `_narrative_token_label` (below `_narrative_edit`) and `_shallow_token_label` (below the Show Shallow Notes row). Lifecycle: cleared when a request *starts* and when a request *fails* — never show stale counts. Format when usage is reported: `Tokens: {in:,} in / {out:,} out`; appends ` / {thinking:,} thinking` when `reasoning_tokens > 0`. When usage is absent from the provider response: `Token usage not reported by this provider`. Styled via `ui.panels.detail.chess_log_charts.token_usage_label.{color, font_size}` in all three theme JSONs (registered in `config_loader`; covered by `test_theme_coverage`). Labels are pure view widgets — not passed to `ChessLogPDFService`; a PDF absence test in `tests/services/test_chess_log_pdf_service.py` confirms this.

**Signal arity.** `narrative_ready = pyqtSignal(str, list, object)` carries `(text, shallow_flags, usage: Optional[TokenUsage])`; `shallow_ready = pyqtSignal(object, object)` carries `(shallow_keys, usage: Optional[TokenUsage])`. Both thread classes and the controller class use the widened arities. Every consumer (`_on_narrative_ready`, `_on_shallow_ready`, all test stubs) must accept both arguments.

The controller's `get_available_models()` / `get_default_narrative_model()` / `get_narrative_timeout_seconds()` drive the view; `set_narrative_*()` setters update the in-memory state (timeout also persists).

### Narrative sanitization

`sanitize_narrative_markdown(text)` in `chess_log_narrative_service.py` is the single gate that cleans LLM output before it reaches either rendering surface. It drops (1) bare thematic-break lines (`---`/`***`/`___` alone on a line — the PDF renderer has no HR branch and would draw them as literal text) and (2) pipe-table body rows whose any cell is empty after stripping (defense in depth against blank Strategic Impact cells the model occasionally emits). Both `detail_chess_log_charts_view._on_narrative_ready` (the `setMarkdown` call) and `ChessLogPDFService._draw_narrative_paginated` call it on the raw string so both surfaces are guaranteed identical clean input. Table separator rows (`| --- | --- | --- |`) are preserved — the thematic-break rule requires no `|` in the line.

### Narrative rendering

`ChessLogPDFService._draw_narrative_paginated` is block-aware: (1) `##` headings via `_section_heading`; (2) pipe tables via `_draw_pipe_table_paginated` — bordered QPainter cells, filled header row, word-wrapped body cells, column widths from `table_col_widths_pct` (default `[20, 40, 40]`); (3) GFM bullets via `_draw_bullet_line_paginated` — hanging-indent `•` with `_draw_wrapped_spans`. All blocks atomic (measure → `_ensure_space` → draw); prose falls to `_parse_bold_spans`. Screen: `setMarkdown`; errors: `setPlainText`. Pipe table: header row and Skill column always bold; other cells via `_parse_bold_spans`. `_measure_bullet_line` uses `_count_cell_lines` (not `boundingRect`) — `boundingRect` underestimates height for bold lead-ins, causing overlap. PDF header: logo ≤ 36pt; HR at `max(text_bottom, logo_bottom + 4)`; `export_charts_report` adds "Generated: YYYY-MM-DD HH:MM" after Source.

## Shallow tags

### Show Shallow Tags dialog

`app/views/dialogs/show_shallow_tags_dialog.py`, class `ShowShallowTagsDialog`. Displays only the rows whose `(game_number, path_key, preset)` tuple is in the `shallow_keys` set returned by `request_flag_shallow_notes()`. **Live-edit** — every `_TagRowWidget.edited` signal immediately calls `replace_entries_at_path_for_game`; no OK button, no buffer, no diff. **Close** button plus an **Export to PDF** button (left of button row); export calls `ChessLogPDFService.export_tags(..., is_shallow_only=True)` with a WYSIWYG snapshot of current row state; rows paginated atomically. All rows include **⚠️ + Ignore** (`show_ignore_checkbox=True`) — when Ignore is checked, `ignore_shallow=True` is stored in each entry dict. Dismissed rows stay visible in the current dialog session (disappear only at the next Show Shallow Tags open, since `request_flag_shallow_notes()` skips entries with `ignore_shallow=True`).

Each row's miniature board is oriented so the mover at the tagged ply is at the bottom — see the "Miniature board orientation" note in `doc/chess_log.md`. The `_export_pdf_report` path on `DetailChessLogChartsView` synthesizes `TagRowSnapshot` objects directly (bypassing the dialog) and populates `is_flipped` from `node_info()` the same way, so charts-tab PDF exports orient shallow rows identically.

### `ignore_shallow` schema field

Added to entry dicts via `ChessLogStorageService.make_entry(preset, cat, why, ignore_shallow=False)`. Omitted from the dict when `False` (backward-compatible — old entries read as `ignore_shallow=False` via `.get("ignore_shallow", False)`). Preserved through controller round-trips: both `replace_entries_at_path` and `replace_entries_at_path_for_game` pass `ignore_shallow=bool(e.get("ignore_shallow"))` when reconstructing entries via `make_entry`. `_TagRowWidget` without `show_ignore_checkbox` transparently carries the original moment-level flag through `get_current_entries()`.

### `is_shallow` schema field

Added to entry dicts via `ChessLogStorageService.make_entry(preset, cat, why, is_shallow=False)`. Omitted when `False` (backward-compatible). Written by `ChessLogChartsController._on_shallow_thread_ready()` after classification — full sync: entries in the result set get `is_shallow=True`; all others have `is_shallow` removed. Persisted to the PGN via the normal Save Chess Log flow (same lifecycle as `ignore_shallow`). Both `_TagRowWidget._preserved_is_shallow` and `get_current_entries()` carry the flag through edits so it survives round-trips in both dialogs.

**`is_shallow` is written per `(game_number, path_key, preset)` key, not per note.** A position tagged with two CLAMP letters (e.g. C and L) produces two entries and two classifier indices, but shares one key — if the classifier returns SHALLOW for either, the whole key is flagged and both entries get `is_shallow=True`. This is pre-existing behavior unchanged in this branch; it becomes relevant when the token label shows "Marked N positions shallow," where N counts distinct keys, not individual classified notes.

### `request_flag_shallow_notes()` in `ChessLogChartsController`

Spawns `ChessLogShallowThread`; on completion writes `is_shallow` onto all in-scope entries (via `replace_entries_at_path_for_game`), marks those games dirty, and emits `shallow_ready(shallow_keys, usage)` — see Signal arity note above. On error emits `shallow_failed(str)`. Skips entries with `ignore_shallow=True`. Public accessor `get_chess_log_controller()` exposes the underlying `ChessLogController` to the view.

### `ChessLogShallowService` — classifier service

Classification logic lives in `app/services/chess_log_shallow_service.py` (extracted from the controller thread in commit 4). `ChessLogShallowThread` is now a thin QThread wrapper that calls `classify_notes()` and handles signals.

**Behavior change (from commit 4 onward):** Previously an empty or unparseable classifier reply was a silent no-op — every note stayed DEEP with no record of what the model failed to classify. Now every input index is accounted for:

- An index is "parsed" when the reply contains `<idx>: SHALLOW` or `<idx>: DEEP` for it.
- Unparsed indices are returned in `ShallowResult.unparsed_indices`.
- An unparsed index is **never** marked SHALLOW — it stays DEEP unchanged.
- When `unparsed_indices` is non-empty, `ChessLogShallowThread` emits `shallow_failed` with the notice *"N notes couldn't be classified — left unchanged. Marked M shallow."* before emitting `shallow_ready` with the partial results.

This means the old no-op case (model returns prose, markdown fences, empty text, or garbled output) now surfaces a warning to the user instead of silently passing.

## Right-click context menu

`app/views/menus/chess_log_charts_context_menu.py`: right-clicking any chart widget or the narrative panel opens a three-action menu.

- *Copy section to clipboard* — for charts, inserts a placeholder line ("Category chart \<preset\>: see Chess Log Charts tab"); for the narrative panel, inserts the current narrative text verbatim.
- *Copy log to clipboard* — text of all charts (as placeholder lines) + narrative + fresh shallow tags if available; format: one line per (game / move / preset / cat / why).
- *Export PDF Report* — same content as Copy Log as a PDF: chart widgets via `widget.grab()` embedded as images, narrative as text, shallow-tag row cards with atomic pagination.

Each `ChessLogCategoryChartWidget` and the narrative `QFrame` carry a `section_name` property (`f"chart_{preset}"` / `"narrative"`) used for hit-testing in `contextMenuEvent`. `_narrative_edit` uses `Qt.ContextMenuPolicy.NoContextMenu` so right-clicks bubble up rather than opening the built-in text-edit menu.

**Shallow-tag freshness rule**: Copy Log and Export PDF include shallow tags only when fresh — `self._last_shallow_keys: Optional[FrozenSet[Tuple[int, str, str]]]` on the view is non-None. Set in `_on_shallow_ready` (after Show Shallow Tags runs); cleared in `_on_source_changed` and `_on_player_changed`. When stale or not yet run, shallow tags are silently omitted. Color filter is not yet wired to a UI control in this view — when a Color combo is added, its change handler must also clear `_last_shallow_keys`.

## PDF export

**Export PDF Report source label**: the PDF header reads `Source: <combo-text>: <pgn-stem>[, <pgn-stem>...]`. The filename list is built by `ChessLogChartsController.get_current_source_filenames()`, which mirrors the `_resolve_games` selection logic (active database → 1 name; all open → N names). `DatabaseModel.display_name` (Path stem or "Clipboard") is used for each entry.

**Tag row cards in PDFs** are sized dynamically: `card_h = pad*2 + header_h + 4 + max(board_sz, body_content_h)`. `body_content_h` is measured via `painter.boundingRect` (checkboxes×line_h vs. word-wrapped why-text for CLAMP/CCT; sum of prompt+answer pairs for 3x3). Cards are never taller than content requires. The helper `ChessLogPDFService._measure_tag_row_height(painter, content, row)` is called both by `_draw_tag_row` (for `_ensure_space`) and by `export_tags` / `export_charts_report` (for the `keep_with` parameter in `_section_heading`, ensuring game headers never orphan from their first row).

**Warning triangle in PDF**: drawn as a QPainter yellow-filled polygon with black exclamation mark (not a Unicode glyph — emoji doesn't render in PDF fonts). Positioned right-aligned on the header line, immediately to the left of "Ignore: Yes/No". Drawn via `ChessLogPDFService._draw_warning_triangle(painter, x, y, size)`. Colors come from `chess_log_charts.pdf_report.colors.warning_fill` / `warning_outline` — resolved at `__init__` time into `self._warn_fill` / `self._warn_outline`; defaults are `[241, 196, 15]` (yellow) and `[30, 30, 30]` (near-black).

**Chess Log PDF print theme**: `ChessLogPDFService.__init__` extracts `ui.panels.detail.chess_log_charts.pdf_report` and passes it as `report_cfg` to `BasePDFReportService.__init__`, which deep-merges it over `ui.pdf`. The `pdf_report` block is defined in all three theme JSON files under `chess_log_charts.pdf_report.colors`; values are print-safe (dark ink on light page) and identical across themes. Callers pass `config` only — no API change.

**Tech debt** (`widget.grab()` chart quality): `ChessLogPDFService.export_charts_report` embeds charts as screen-resolution pixmaps from `widget.grab()`. Player Stats re-renders charts natively via QPainter from series data. If PDF chart quality is inadequate, the upgrade path is a native-QPainter pipeline in `ChessLogPDFService` — flagged as tech debt; the existing path is upgradeable without API changes.

## Multi-game cache and save-all

**Save Chess Logs for all games** (Chess Log menu, no shortcut): saves every game in `ChessLogController._dirty_games` via `ChessLogStorageService.store_tags` directly — does NOT flip the active game. Handler: `MainWindow._save_chess_logs_for_all_games` → `chess_log_controller.save_all_dirty_games()`. Reports count of saved/failed games in the status bar. Cache coherency across active-game transitions: Rule A (activation promotes from multi-cache before hitting disk) and Rule B (deactivation flushes single-game cache into multi-cache) ensure edits to inactive games are never silently discarded.

**Multi-game cache in ChessLogController**: `_multi_cache: Dict[int, Dict[str, List[Dict]]]` (keyed by game_number) holds moments for games not currently active; `_dirty_games: Dict[int, GameData]` tracks which games have unpersisted edits. Public API: `get_tags_for_game(game)`, `replace_entries_at_path_for_game(game, path_key, preset, entries)`, `save_all_dirty_games() -> Tuple[int, int]`, `has_dirty_games() -> bool`. A game lives in exactly one store at a time — single-game cache when active, multi-cache when not.

## Theming

`DetailChessLogChartsView` reads all colors from `ui.panels.detail.chess_log_charts` in the merged config. Color values live exclusively in the three theme JSON files (`style_default`, `style_light`, `style_scholar`) under `ui.panels.detail.chess_log_charts.{chart,colors,pdf_report,category_colors}` — **never in `config.json`**, because `config.json` takes precedence in the merge and would block style overrides.

The tab is non-modal (embedded in the central widget); `MainWindow.apply_theme()` calls `takeCentralWidget()` + `_setup_ui()`, which destroys and rebuilds the entire central widget including this tab — so a fresh `__init__` with the new config IS the live-update mechanism; no theme-changed signal is needed.

`BusySpinner` color and all `setStyleSheet` colors must be config-driven (`_apply_styling` reads from `colors.*`).

**Theme coverage test**: `tests/config/test_theme_coverage.py` asserts that all curated `chess_log_charts.*` key paths exist in all three theme files — add new color keys there whenever a new config-driven color is introduced. Manual QA via `debug.enable_debug_rand_colors: true` (in `config.json:1087`) can be used to confirm no hardcoded colors survive theme switching.

## Shared utilities

**BusySpinner**: `app/views/widgets/busy_spinner.py` is the single canonical spinner widget used throughout Chess Log (Charts tab, dialogs) and by `BulkOperationsDialog`.

**AI provider config**: `app/utils/ai_provider_config.py` — `is_ai_configured` / `resolve_default_provider` helpers used by both Chess Log Charts and AI Summary.

## AI integration

### Prompt storage in `config.json`

All LLM prompt strings live under a top-level `prompts` section with two siblings:

```
prompts.chess_log.narrative_system        — system prompt passed to AIService
prompts.chess_log.narrative_preamble      — user message template (4 placeholders)
prompts.chess_log.narrative_step          — appended after the preamble
prompts.chess_log.narrative_glossaries    — dict: {"CLAMP": "…", "CCT": "…", "3x3": ""}
prompts.chess_log.narrative_3x3_structure — Why-note structure block
prompts.chess_log.narrative_3x3_moment_framing — per-moment inline framing line
prompts.chess_log.classifier              — classifier system prompt
prompts.ai_chat.system_preamble           — AI Chat system prompt preamble
prompts.ai_chat.formatting_rules          — AI Chat formatting directives
```

All 11 keys are registered in `ConfigLoader._REQUIRED_CONFIG_KEY_PATHS` — a missing key causes a `ValueError` at startup with a clear message naming the absent path, not a silent KeyError mid-request.

`_generate_initial_prompt()` in `ai_chat_controller.py` stays in Python: it embeds live FEN, PGN, ply index, and optional analysis JSON via f-strings. There is no equivalent for Chess Log's assembly either — `build_prompt()` and `classify_notes()` read prompts from config but all data interpolation happens in Python.

### Placeholder contract

`narrative_preamble` uses Python `.format()` with four named placeholders:

- `{glossary_section}` — preset glossary + 3x3 structure block, or `\n` if none
- `{category_counts_block}` — 4-bin trend table from `aggregate()`
- `{why_notes_block}` — player's why-notes, one per line; sentinel separates moments
- `{game_notes_block}` — whole-game notes, or "(no whole-game notes)"

`ConfigLoader._validate_prompt_placeholders()` checks all four are present using `string.Formatter().parse()` at startup — a load-time error, not a silent mid-run KeyError.

**Why this differs from the Elo validation pattern**: Elo has `value_on_error` as a graceful fallback when a key is missing. Prompts have no equivalent — a missing `{placeholder}` silently drops that section from the assembled prompt with no error; an extra `{placeholder}` (unknown key) raises `KeyError` inside a `QThread` mid-request, leaving the UI blank with no message. The load-time validator makes either failure loud at startup instead of silent at runtime.

### Missing-config guards

`generate_narrative()` checks `(config or {}).get("prompts", {}).get("chess_log")` before calling `build_prompt()`. If the section is absent it returns `NarrativeResult(success=False, text="Chess Log prompts are missing from config.json — reinstall or restore the file.")` without touching the network. `classify_notes()` does the same, returning a `ShallowResult(success=False, …)`. `AIChatController.send_message()` emits `error_occurred` and returns `False` before appending any message to the conversation. The guards fire before state is mutated — they mirror the existing model-config checks at lines 476–484 of `ai_chat_controller.py`.

Tests: `TestNarrativeMissingConfig`, `TestClassifyNotesMissingConfig`, `TestAIChatMissingConfig` in the relevant test files.

### `THREE_BY_THREE_PROMPTS` and config divergence

The four Why-question strings in `app/utils/chess_log_prompts.py` (`THREE_BY_THREE_PROMPTS`) are the live source for the moment dialog, tags dialog, and PDF export. `prompts.chess_log.narrative_3x3_structure` must contain each verbatim — `test_config_3x3_structure_matches_three_by_three_prompts` enforces this at test time. Editing a Why question without updating `config.json` produces a test failure.

### Editing prompts

Multi-line prompt strings are stored as single JSON string values with `\n` escapes (e.g. `"Line one.\nLine two."`). This is JSON's native format — no array-join trick — but it makes hand-editing in a text editor awkward: the entire prompt appears as one long line. To edit, search for a distinctive phrase, make the change, and keep the `\n` separators intact. A JSON formatter (e.g. `python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin), indent=2))" < config.json`) can pretty-print the file temporarily for easier editing, though the committed form stays compact.

## Manual test checklist

### What Paul can test before the PR

1. **Narrative Summary** — run on the logged-game library and compare output quality with the pre-change baseline. The golden fixture tests in `tests/services/test_chess_log_prompts_config_roundtrip.py` prove prompt assembly is byte-identical before and after the config move; the comparison is a spot-check for quality, not a byte diff.

2. **AI Chat** — run a normal analysis session. The golden fixture tests in `tests/services/test_ai_chat_prompts_golden.py` prove system_prompt assembly is byte-identical.

3. **Prompt editing** — open `app/config/config.json`, append a visible marker to `prompts.chess_log.narrative_system` (e.g. `" [TEST]"` at the end). Restart CARA, run Narrative Summary, verify the marker appears in the AI's reply or in the logs. Revert the change. Repeat for `prompts.ai_chat.system_preamble`.

4. **Token labels** — confirm `Tokens: N in / M out` appears below the narrative and near the Show Shallow Notes button after each run. Confirm both labels clear when a new run starts and when a run fails. Export the narrative to PDF and confirm no "Tokens:" text appears in the exported file.

5. **Placeholder validator** — edit `narrative_preamble` in `config.json` to remove one of the four required placeholders (e.g. delete `{glossary_section}`). Restart CARA — it should fail at startup with a clear error naming the missing placeholder. Restore the file.

6. **Failure notice** — close the network connection or use a bad API key; confirm the failure message ("Couldn't reach …" or "API key missing …") appears in the UI rather than a blank panel.

### What's left for Philipp at PR review

1. **Local endpoint (CUSTOM provider)** — test both Narrative Summary and Show Shallow Notes against LM Studio / llama.cpp / Ollama in OpenAI-compatible mode. Paul does not have a local endpoint set up. Automated CUSTOM-path coverage is in `tests/services/test_ai_service_custom_provider.py` but live-endpoint testing is deferred to PR review.

2. **Garbled classifier reply from a small local model** — deliberately point at a tiny model that returns prose instead of `0: SHALLOW` lines. Confirm the UI shows "N notes couldn't be classified — left unchanged" and no notes are marked shallow. Mocked coverage is in `tests/services/test_chess_log_shallow_service.py`; this is the live-endpoint equivalent.

3. **Provider Paul doesn't have a key for** — test any cloud provider Paul doesn't have configured; confirm the error notice appears.

4. **Multi-line prompt editing** — hand-edit a prompt in `config.json`, restart, confirm the edit is picked up. A reformatter (`python3 -m json.tool config.json`) can pretty-print the file to make editing easier.

5. **Placeholder validator message quality** — remove a required placeholder, restart, confirm the error message is clear enough for a non-developer to act on.

## Key files

- `app/services/chess_log_stats_service.py`
- `app/services/chess_log_narrative_service.py`
- `app/services/chess_log_pdf_service.py`
- `app/controllers/chess_log_charts_controller.py`
- `app/controllers/chess_log_controller.py`
- `app/views/detail_chess_log_charts_view.py`
- `app/views/widgets/chess_log_category_chart_widget.py`
- `app/views/widgets/busy_spinner.py`
- `app/views/menus/chess_log_charts_context_menu.py`
- `app/views/dialogs/_tag_row_helpers.py` — holds `node_info` / `ply_for_path`; `_TagRowWidget` itself lives in `show_tags_dialog.py`
- `app/views/dialogs/show_tags_dialog.py`
- `app/views/dialogs/show_shallow_tags_dialog.py`
- `app/utils/ai_provider_config.py`
- `app/utils/chess_log_best_move.py` — `resolve_best_move_for_path` (reads `CARAAnalysisData` for the best move at a tagged position)
