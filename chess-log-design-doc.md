# Chess Log — Product Design Document

**Proposed as a new tab/feature addition to CARA (Chess Analysis and Review Application)**
**Status:** Draft for review
**Author:** Paul Cezanne
**Date:** August 2026

---

## Elevator Pitch

Right after a game, a player usually already senses what went wrong — but that instinct fades within days and never turns into data. **Chess Log** captures it: tag the handful of moments that mattered, in a preset vocabulary or your own words, and watch how the *pattern* of your mistakes shifts over weeks and months — not just whether you're making fewer of them, but whether you've graduated to harder ones.

---

## 1. Summary

Chess Log lets a player mark specific moments in a reviewed game with a short, self-defined reason, then view how those reasons trend over time — by category, with a narrative summary alongside the charts.

The goal is not engine-driven move classification (CARA already does that well). It's **player self-diagnosis**: the human decides what mattered and why, the system remembers it, and helps them see the shape of their own game over time.

### 1.1 Existing Frameworks

Chess Log adapts existing frameworks rather than inventing new methodology:

- **CLAMP** — a categorization of common cognitive failure modes in a player's thinking process, developed by **Dr. Can Kabadayi**.
- **CCT** (Checks, Captures, Threats) — long-standing, widely used chess wisdom rather than one person's named framework.
- **The 3x3 Method** — a structured post-game reflection technique developed by **GM Noel Studer**: find exactly three moments per game worth a takeaway, and for each one ask three "Whys." Reference: [YouTube — "How To Analyze Your Chess Games (the simple way)"](https://www.youtube.com/watch?v=shma5hsckww), [written summary](https://chemcoolchess.co.za/blog/Better-Chess-Analysis-The-3x3-Method).

Chess Log's own contribution is the tagging/recording layer and the trend reporting built on top of them. Other related checklists (TRC, CCTB, Silman's Imbalances) exist and could be added as presets later if the feature takes off — not needed for v1.

---

## 2. Problem Statement

Players who review their games regularly still struggle to answer: *"What do I actually keep doing wrong?"*

- Engine evaluation tells you *that* a move was bad, not *why* it happened from the player's own perspective.
- Without a record, patterns fade from memory fast.
- Even a player who notices a pattern has no easy way to confirm it's improving, or whether it's just been replaced by a subtler one.
- Many chess coaches say keeping a log of your game analysis is important — but rarely explain how to actually do it in practice.

---

## 3. Core Concepts

### 3.1 Tagging a moment
While reviewing a game (ideally right after playing it, but equally usable on old games from the library), the player marks specific moments worth a takeaway. Following Studer's method, the target is **at most three per game** — a guiding constraint, not a hard limit. The UI encourages this in the product's own words (piling on more takeaways dilutes the lesson rather than sharpening it) and asks "Are you sure?" if the player tries to tag a fourth — a nudge, not a block.

Tagging is always a manual, human act; the system never suggests or auto-detects tag-worthy moments.

### 3.2 Two reflection methods: 3x1 and 3x3
Both share the "at most three spots" philosophy, aimed at different skill levels:

- **3x3 (Studer's method, advanced)** — three guided Whys per moment: *Why did I make this move? Why was it suboptimal? Why is the engine's suggestion better?*
- **3x1 (Paul Cezanne's adaptation, beginner/intermediate)** — one action per moment: assign whichever categories apply from a chosen preset (CLAMP or CCT). Trades the depth of three Whys for speed and a low barrier to entry.

The player can use either method, on any game, without committing to one permanently.

### 3.3 Category presets
- **CLAMP** (Dr. Kabadayi) — the vocabulary behind 3x1:
  - **C**hecks — missed or overlooked checking moves, for either side.
  - **L**oose Pieces — a piece or a square left undefended or insufficiently defended.
  - **A**lignment — pieces sharing a file, rank, or diagonal in a way that creates a tactic (pins, skewers, discovered attacks), as well as knight forks.
  - **M**obility — a piece that's trapped, has no safe squares, or lacks the mobility the position calls for.
  - **P**awn Promotion — miscalculating or overlooking promotion races and endgame dynamics.
- **CCT** — the checks/captures/threats framing, more widely known than CLAMP among improving players. Used the same way as CLAMP under the 3x1 method: for a tagged moment, the player marks which of the three — Checks, Captures, or Threats — they missed (more than one can apply to a single moment), with an optional why note.
  - **C**hecks — a checking move, by either side, that wasn't considered.
  - **C**aptures — a capture, by either side, that wasn't considered.
  - **T**hreats — a non-capturing threat (to a piece, square, or plan) that wasn't considered.
- **The Three Studer Whys** — the guided prompts behind 3x3, offered as a preset so players aren't left with a blank field.

Custom categories are also supported and tracked in the same charts as presets.

### 3.4 The tag pair: what + why
Each tagged moment is really a pair: the **what** (the category — e.g. "M" for a trapped rook) and, optionally, the **why** — a short note in the player's own words, not menu-driven, explaining the category. Example: category **M**, note: *"Rook became trapped when I moved my bishop, cutting off the Rook escape square."*

The why stays optional — the category alone is enough to satisfy a tag — but framing it explicitly as a pair (not just "a category, plus some loose freeform field bolted on") makes clear what the note is *for*: not a general comment, but the reason behind the specific category just chosen.

This pairing is also where the 3x3 method's three Whys live — the same what+why mechanism, guided by three prompts instead of one open field. The why half may be the richest data Chess Log collects: the what says *what kind* of mistake recurred; the why says *why*, and an AI reading it across months can surface patterns the player wouldn't spot from tag counts alone.

### 3.5 Prompting the existing whole-game note
CARA already has a whole-game note field — Chess Log doesn't add a new one. What changes: when the player tags a moment in a game that doesn't yet have that note filled in, Chess Log prompts them to add one. Still optional, still just a nudge — but it captures the reflection while the player is already in that frame of mind, and the AI narrative summary draws on it.

---

## 4. Workflow

1. Player finishes a game and reviews it in CARA, as they already do today.
2. While stepping through the moves, they tag up to three moments — 3x1, 3x3, or a custom category — with an optional why note on any of them.
3. If the game's whole-game note isn't filled in, tagging a moment prompts the player to add one.
4. Tags and notes accumulate across the library over time — including backfilled older games, an explicit, expected use case.
5. Whenever the player opens the Chess Log charts view, the trend charts and narrative summary are there — with a brief generation pause, the same way CARA's existing Player Stats view behaves today.

---

## 5. Reporting & Visualization

### 5.1 Trend charts
- Uses CARA's existing timeline groupings rather than introducing a new time-window concept.
- A line chart of tag frequency by category over time, matching CARA's existing charting style.
- The chart should make **category mix shift** visible, not just total count. A player who traded hanging pieces for endgame promotion mistakes hasn't failed to improve — they've moved on to a harder problem. Total count alone hides that; the per-category breakdown reveals it.
- Implementation note: CARA already has a time-series charting engine in `player_stats_service.py` (date binning, per-color series, configurable charts) behind its existing accuracy/move-quality trend charts. Chess Log's category-frequency chart should plug into that existing machinery rather than build parallel charting logic.

### 5.2 Narrative summary
Appears on the Chess Log charts view, for whatever time window the player selects there, with a brief generation pause like the rest of the view. **Only available if the player has configured an LLM in CARA** — an existing, optional CARA setting, not something Chess Log requires. Without one configured, the charts still work; there's just no narrative summary.

Generated by an LLM from the accumulated category tags, why notes, and whole-game notes, surfacing recurring themes in plain language. The why notes are expected to carry the most weight, since they say *why* a pattern recurs in the player's own words, not just that it did.

As part of the same read-through, the AI also flags notes that are too shallow to be useful — e.g. a why note that just restates the category ("I hung my bishop" for a tag already categorized as **L**, with no actual reason given). These are surfaced informationally alongside the summary, not as a separate nag or notification; there's no revisit workflow yet for jumping back to fix a flagged note — that's a later problem. The AI never rewrites or drafts a better note on the player's behalf; it only flags.

---

## 6. Success Criteria

No single hard KPI — this is a reflection tool, not a performance-management tool. Signals of success:

- The trend chart is genuinely informative about how the *mix* of mistakes changes over time, not just whether a count goes up or down.
- The narrative summary — especially from the player's own why notes — surfaces patterns the player hadn't consciously noticed.
- Tagging stays fast enough to survive real post-game habits rather than becoming a chore.

A rising or falling raw tag count is not, by itself, a meaningful signal.
