# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

CARA is a PyQt6-based desktop chess analysis application. Start it with:

```bash
python cara.py
```

On macOS, you may need `python3` instead. Requires Python 3.8+ and a UCI-compatible chess engine (Stockfish, Berserk, etc.) configured via the Engines menu.

**Qt platform-plugin error** (`Could not find the Qt platform plugin "cocoa"`): almost always a PyQt6 / PyQt6-Qt6 version mismatch or a macOS `UF_HIDDEN` flag on installed dylibs — not a corrupt install. `cara.py` auto-clears the hidden flag at startup. See `doc/troubleshooting.md` for diagnosis commands and the manual fix.

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

**Convention for new config keys:** add every new key to ConfigLoader so a missing one fails loudly at startup. The loader is the gate; `.get()` defaults in code are belt-and-suspenders. Existing code uses `.get(..., default)` patterns throughout — known tech debt, not an error. Always register new keys in ConfigLoader regardless.

Style config files (`style_default.config.json`, `style_light.config.json`, `style_scholar.config.json`) define reusable constants with a `$_` prefix, referenced elsewhere via `{"$ref": "$_CONSTANT_NAME"}`. `config.json`'s `default_style_config` key selects the active style file.

Key sections: `ui.window`, `ui.panels`, `ui.dialogs.*`, `ui.styles`, `ui.colors`, `ui.fonts`, `version`.

### Configuration Access

```python
bg_color = config.get("ui", {}).get("dialogs", {}).get("my_dialog", {}).get("background_color", [40, 40, 45])
```

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

### Chess Log

Human-authored move tagging layer — player self-diagnosis, complementing CARA's engine-based classification. Active preset is one of CLAMP, CCT, or 3x3, selected in Chess Log Settings; a library may contain moments from multiple presets (expected, not an error).

- **No hardcoded colors**: all Chess Log dialog `setStyleSheet` calls must read from config — never bare `rgb(…)` literals. Both `ui.dialogs.moment` and `ui.dialogs.chess_log_settings` blocks must exist in all three theme files.
- **Dirty-marking**: only `replace_entries_at_path_for_game` explicitly marks a game dirty. `add_moment_at_active_path` and `replace_entries_at_path` write only to `_cached_paths_data`; `save_all_dirty_games` recovers the active game via `has_unsaved_changes()`.

**Key files**: `app/services/chess_log_storage_service.py`, `app/controllers/chess_log_controller.py`, `app/views/dialogs/moment_dialog.py`, `app/views/dialogs/chess_log_settings_dialog.py`, `app/views/menus/chess_log_menu.py`.

See `doc/chess_log.md` for full detail: storage format, presets, nag dialog, ShowTags dialog, controller helpers, context menu structure, dialog theming.

### Chess Log Charts

Reporting layer for Chess Log — detail tab (index 9, F10) showing per-preset category trends and an LLM narrative summary. CLAMP and CCT only; 3x3 deferred (Why1–4 aren't a comparable category axis).

- **Narrative**: LLM-gated, same provider as AI Summary. Thinking disabled for Sonnet-5/Opus-5 models. Default token limit 12000.
- **No hardcoded colors**: chart colors go in the theme JSON files under `ui.panels.detail.chess_log_charts` — **never in `config.json`** (takes precedence in the merge, blocks overrides). Add new keys to `tests/config/test_theme_coverage.py`.
- **Theme updates**: `MainWindow.apply_theme()` destroys/rebuilds the central widget — fresh `__init__` IS the live-update mechanism, no signal needed.
- **Shared helpers**: chart layout in `app/views/widgets/_chart_layout_helpers.py`; time-series menu base in `app/views/menus/_radio_menu_controller.py`.
- **Shallow-tag freshness**: `_last_shallow_keys` on the view clears on source/player change; stale shallow tags are silently omitted from exports. When a Color combo is added, its handler must also clear this field.

**Key files**: `app/services/chess_log_stats_service.py`, `app/services/chess_log_narrative_service.py`, `app/services/chess_log_pdf_service.py`, `app/controllers/chess_log_charts_controller.py`, `app/views/detail_chess_log_charts_view.py`, `app/views/widgets/chess_log_category_chart_widget.py`, `app/views/widgets/busy_spinner.py`, `app/views/menus/chess_log_charts_context_menu.py`, `app/views/dialogs/show_tags_dialog.py`, `app/views/dialogs/show_shallow_tags_dialog.py`, `app/utils/ai_provider_config.py`, `app/utils/chess_log_best_move.py`.

See `doc/chess_log_charts.md` for full detail: charting widget, time-series settings, narrative prompt structure, PDF export, shallow-tag flow, theming, PDF rendering.

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

Architecture and feature docs live in `doc/` — `architecture_outline.md` for high-level design/threading/error handling, `dialog_style_guide.md` for the dialog pattern, `chess_log.md` / `chess_log_charts.md` for the tagging and charts features, `troubleshooting.md` for the Qt platform-plugin error, plus feature-specific docs (game analysis, highlights, heatmap, player stats, annotations). Check there before re-deriving something already documented.

## Git Workflow

This fork has two `master` branches to keep straight:

- **This fork's `master`** — the integration branch for Chess Log development. Feature branches merge here via PR, reviewed by Paul.
- **Upstream CARA's `master`** (Philipp's) — a separate, later destination. Never push or target it directly. Reaching it happens via a deliberate PR once a feature is complete enough to integrate well into the app — config.json, the theme system, the manual (`resources/manual/index.html`), and any new keyboard shortcuts, per Philipp — not a partial/incremental PR.

Rules:
- **Never commit directly to either `master`.** Always work on a feature branch. If none exists for the current task, create one before the first commit — don't wait to be asked.
- **Never run `git push` on any branch without first showing Paul the exact commit(s) about to be pushed and getting explicit confirmation.** This applies universally — including pushes to this fork's own `origin`, not just pushes or PRs that reach upstream. No exceptions based on how minor or "obviously fine" a change seems.
- Prefer small, focused commits (one logical change each) over large batched ones — easier to review, easier to revert if something's wrong.
- **After a conversation compaction, don't assume a multi-part directive is complete.** Compaction summarizes the conversation and can lose track of which parts of a multi-part directive were actually finished versus still pending. When resuming after compaction, check whether the directive in progress had multiple parts, and if so, confirm explicitly with Paul which parts are actually done before treating the task as finished.

## CI/CD

`.github/workflows/tests.yml` runs on Python 3.12 with `QT_QPA_PLATFORM=offscreen` for headless Qt testing, on push to `master`/`development` and on PRs. Manual-trigger build workflows (`build-appbundles.yml`, `build-linux-appbundles.yml`) produce macOS/Windows/Linux bundles as artifacts.

## Version and Release

Version lives in `app/config/config.json` under `"version"` — build scripts read it for bundle naming. Release notes in `RELEASE_NOTES.md`; pre-built bundles on the GitHub Releases page.
