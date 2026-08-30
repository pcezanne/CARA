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

**Active preset model:** the player selects one active preset — CLAMP, CCT, 3x3, or Custom — in the Chess Log Settings dialog (Chess Log menu → "Chess Log Settings…"), mirroring the existing Engines/AI Summary setup pattern. CLAMP and CCT both allow multiple letters per moment. Custom is a Settings-managed picklist (add/remove), not free-form text at tag time. 3x3 is the sole preset with free-form text at tag time (its three Whys: "Why did I make this move?", "Why was it suboptimal?", "Why is the engine's suggestion better?"). The active preset can change over time, so a library may end up with moments tagged under more than one preset — expected, not an error. See `chess-log-design-doc.md` §3.2–3.4 for full detail.

**Zero-category save (CLAMP, CCT, Custom-with-categories):** if no chips/checkboxes are checked but the why-field has content, the moment saves as a single entry with `cat=""` — genuinely uncategorized, not a fake "Other" category. Zero chips + empty why keeps OK blocked (hint shown). The Custom empty-picklist case (no categories defined at all) is distinct: that guard disables OK regardless of why content, because it's a configuration gap, not an honest non-match.

**CARA-namespaced PGN tags** (all read-only in metadata view and model):
- `CARAAnalysisData` / `CARAAnalysisInfo` / `CARAAnalysisChecksum` — per-move engine data
- `CARAAnnotations` / `CARAAnnotationsInfo` / `CARAAnnotationsChecksum` — board drawing annotations
- `CARANotes` / `CARANotesInfo` / `CARANotesChecksum` — whole-game text notes
- `CARAChessLog` / `CARAChessLogInfo` / `CARAChessLogChecksum` — Chess Log moments
- `CARAGameTags` — whole-game chip tags

**Key files**: `app/services/chess_log_storage_service.py`, `app/controllers/chess_log_controller.py`, `app/views/dialogs/moment_dialog.py`, `app/views/dialogs/chess_log_settings_dialog.py`, `app/views/menus/chess_log_menu.py`.

**Entry point**: first-time users should open Chess Log → Chess Log Settings to pick their preset (and, for Custom, populate the picklist). Then right-click a move in the Moves List → "Tag this moment…". Save via Chess Log menu → "Save Chess Log to current game" (`Ctrl+Alt+L`). Clear via `Ctrl+Shift+L`.

**Out of scope for the `tagging` branch**: "highlight tagged moves" toggle.

### Chess Log Charts (branch: `chess-log-charts`, §5.1 + §5.2)

Reporting and visualization layer for Chess Log — the detail tab (index 9, F10) that lets players see how their mistake mix shifts over time and get an AI narrative summary.

**Presets in scope**: CLAMP, CCT, Custom. **3x3 deferred** — its Why1/2/3 entries aren't a comparable category axis and need separate design.

**Charting**: stacked vertical `ChessLogCategoryChartWidget` instances (one per preset) in a `QScrollArea`. Each is a fresh `QPainter` widget — not a subclass of `MoveQualityOverTimeChartWidget`. The four scaffolding helpers from `player_stats_service.py` (`_game_date_ordinal_for_trends`, `_ordinal_target_bin_count`, `_ordinal_fallback_mode`, `_calendar_bin_center_time_pct`) are reused; the bin-filling functions are fresh count-based implementations in `chess_log_stats_service.py`. Legend always shows the full canonical set for CLAMP (C,L,A,M,P) and CCT (Checks,Captures,Threats) — categories absent from the data appear dimmed (no line drawn, greyed text, 40% alpha swatch). Stale chart clears immediately on source/player/color change (via `charts_loading` signal); no visible loading indicator is shown. Player/color-filter changes are debounced (100ms) to prevent rapid-click flicker. **Player selection is required** — changing Data Source does not auto-chart; the Player dropdown starts unselected and shows "Select a player…" in the chart area until the user makes an explicit choice. "All players" is a valid selection (aggregates across all players), but is never the silent default.

**Narrative**: LLM-gated (same provider config as AI Summary). Prompt assembled from category counts + why-notes + whole-game notes. Response split into narrative text + optional "Also flagged" shallow-note list at the `## Also flagged` sentinel. LLM-not-configured state shows a hint and disables the Generate button — no restart needed after configuring (AI Model Settings close triggers `set_user_settings`). The AI state is seeded at app startup (not only on dialog close), so the hint correctly reflects the user's saved provider settings from first view.

**AI provider config**: `app/utils/ai_provider_config.py` — shared `is_ai_configured` / `resolve_default_provider` helpers extracted from the inline logic in `AIChatController.get_default_model`. Used by both Chess Log Charts and AI Summary.

**Key files**: `app/services/chess_log_stats_service.py`, `app/services/chess_log_narrative_service.py`, `app/controllers/chess_log_charts_controller.py`, `app/views/detail_chess_log_charts_view.py`, `app/views/widgets/chess_log_category_chart_widget.py`, `app/utils/ai_provider_config.py`.

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
