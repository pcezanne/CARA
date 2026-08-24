# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

CARA is a PyQt6-based desktop chess analysis application. Start it with:

```bash
python cara.py
```

On macOS, you may need `python3` instead. Requires Python 3.8+ and a UCI-compatible chess engine (Stockfish, Berserk, etc.) configured via the Engines menu.

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

**Open question on validation strictness** (see note below in Configuration Access) — confirm with maintainer before relying on either behavior.

Style config files (`style_default.config.json`, `style_light.config.json`, `style_scholar.config.json`) define reusable constants with a `$_` prefix, referenced elsewhere via `{"$ref": "$_CONSTANT_NAME"}`. `config.json`'s `default_style_config` key selects the active style file.

Key sections: `ui.window`, `ui.panels`, `ui.dialogs.*`, `ui.styles`, `ui.colors`, `ui.fonts`, `version`.

### Configuration Access

```python
bg_color = config.get("ui", {}).get("dialogs", {}).get("my_dialog", {}).get("background_color", [40, 40, 45])
```

**Note:** ConfigLoader is documented as strictly validating config at startup (fails fast on missing required keys, no fallback logic) — but the pattern above shows `.get()` calls with inline defaults, which *is* fallback logic. Unconfirmed whether this means strict validation applies only to a specific set of required keys while everything else may use `.get()` defaults, or whether the two statements are in tension. Confirm the actual rule before writing new config-reading code, rather than copying this pattern blindly.

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

**CARA-namespaced PGN tags** (all read-only in metadata view and model):
- `CARAAnalysisData` / `CARAAnalysisInfo` / `CARAAnalysisChecksum` — per-move engine data
- `CARAAnnotations` / `CARAAnnotationsInfo` / `CARAAnnotationsChecksum` — board drawing annotations
- `CARANotes` / `CARANotesInfo` / `CARANotesChecksum` — whole-game text notes
- `CARAChessLog` / `CARAChessLogInfo` / `CARAChessLogChecksum` — Chess Log moments
- `CARAGameTags` — whole-game chip tags

**Key files**: `app/services/chess_log_storage_service.py`, `app/controllers/chess_log_controller.py`, `app/views/dialogs/moment_dialog.py`, `app/views/menus/chess_log_menu.py`.

**Entry point**: right-click a move in the Moves List → "Tag this moment…". Save via Chess Log menu → "Save Chess Log to current game" (`Ctrl+Alt+L`). Clear via `Ctrl+Shift+L`.

**Out of scope for this PR**: detail tab view/edit UI, "highlight tagged moves" toggle, 3x3 preset, trend charts, AI narrative summary.

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
- **Upstream CARA's `master`** (Philipp's) — a separate, later destination. Never push or target it directly. Reaching it happens via a deliberate PR once a feature (or the whole project) is ready for his review — exact PR granularity/cadence TBD, pending discussion with Philipp.

Rules:
- **Never commit directly to either `master`.** Always work on a feature branch. If none exists for the current task, create one before the first commit — don't wait to be asked.
- Prefer small, focused commits (one logical change each) over large batched ones — easier to review, easier to revert if something's wrong.

## CI/CD

`.github/workflows/tests.yml` runs on Python 3.12 with `QT_QPA_PLATFORM=offscreen` for headless Qt testing, on push to main/master/development and on PRs. Manual-trigger build workflows (`build-appbundles.yml`, `build-linux-appbundles.yml`) produce macOS/Windows/Linux bundles as artifacts.

## Version and Release

Version lives in `app/config/config.json` under `"version"` — build scripts read it for bundle naming. Release notes in `RELEASE_NOTES.md`; pre-built bundles on the GitHub Releases page.
