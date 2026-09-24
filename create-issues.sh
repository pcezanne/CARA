#!/bin/bash
# Run from inside the local CARA fork's repo directory — gh infers the
# repo from the git remote, no --repo flag needed. Requires `gh auth status`
# to already be logged in.
#
# NOTE: GitHub assigns its own issue numbers automatically, in creation
# order — they will NOT match the numbers below (those are from the old
# memory-based tracking system, kept here only as a cross-reference during
# migration). Once these are created, GitHub's own issue numbers are the
# new permanent reference — "number 8" going forward means GitHub issue #8,
# not old-system item 8.
set -e

# ============================================================
# PHILIPP-DISCUSSION ITEMS (old #8-14)
# ============================================================

gh issue create --label "philipp-discussion" \
  --title "[old #8] Chess Log chip in board panel's tag cloud — right place for it?" \
  --body "Not a bug — direct consequence of a deliberate design choice to reuse the existing Game Tags system, since both render paths (Game Table delegate, board panel widget) pick up any chip automatically with zero extra wiring. That simplicity means the chip shows everywhere Game Tags show, including the board panel, which may not be the right place for it.

Product/UI question, not technical — parking for discussion with Philipp rather than deciding unilaterally."

gh issue create --label "philipp-discussion" \
  --title "[old #9] Chess Log's Timeout control shares AI Summary's setting — confirm this is the right call" \
  --body "Chess Log Charts' Model/Timeout/Token controls write Timeout into the same \`ai_summary.request_timeout_seconds\` key AI Summary already uses — changing it on one tab silently changes it on the other. Model and Tokens stay independent/ephemeral per tab; only Timeout is shared.

Deliberate simplification (one timeout preference rather than two), but worth explicit sign-off during PR review rather than assuming it's the right long-term behavior — could just as easily be \"mirror the behavior, store independently\" instead."

gh issue create --label "philipp-discussion" \
  --title "[old #10] CARA cannot merge OTB and chess.com games under one player identity" \
  --body "Already emailed Philipp about this directly. Not Chess-Log-specific — a CARA-level limitation (single username per Player selection, matched against White/Black PGN headers).

Until resolved, Chess Log charts/narrative can't show a unified view across both game sources — OTB games and chess.com games (different usernames) are two separate, unmergeable player identities for aggregation purposes.

Tracking only — Philipp owns this. See also: multi-alias player identity feasibility investigation (separate issue)."

gh issue create --label "philipp-discussion" \
  --title "[old #11] Should Chess Log's charts and Narrative Summary live inside Player Stats instead of their own tab?" \
  --body "A more radical resolution to the same underlying tension as the DRY/shared-component question — instead of just sharing code between two separate tabs, this asks whether they should even be two separate tabs at all.

Not fleshed out yet — worth raising later, no detail beyond the question itself."

gh issue create --label "philipp-discussion" \
  --title "[old #12] Chess Log keeps independently re-deriving existing CARA UI/logic instead of reusing it (6 instances)" \
  --body "A recurring pattern across multiple CARA features, not just Player Stats. Worth raising as its own thing with Philipp — a general \"extract shared components as they're identified\" conversation, not a one-off refactor request.

**Instance 1 — Time series settings menu.** Mirrors Player Stats' structure/pattern without sharing code.

**Instance 2 — gap_compressed X-axis layout.** ~500 lines of view code duplicated from Player Stats, not just a small submenu shape.

**Instance 3 — calendar_linear date-math.** The binning bug (misaligned X-axis spacing, two rounds of fix attempts) was ultimately resolved by directly copying Player Stats' proven date-to-position math, rather than re-deriving similar logic — re-derivation is what produced the subtly-wrong first fix attempt in the first place.

**Instance 4 — player-matching logic.** \`get_all_players()\`, \`aggregate()\`'s player filter, \`_game_matches_player_color\` were independently reimplemented and diverged in real ways (case-sensitivity, whitespace-stripping, sort order) from Player Stats' equivalent. Fixed by copying Player Stats' exact behavior.

**Instance 5 — player-dropdown filter/sort.** Player Stats filters to players with ≥2 qualifying games and sorts by count descending then name; Chess Log's dropdown had neither. Fixed by copying the exact mechanism, with one necessary translation: Player Stats filters on \"games analyzed\" (an engine-analysis concept), Chess Log filters on \"games with Chess Log moments tagged\" — same algorithm, domain-appropriate count.

**Instance 6 — AI model/timeout/token controls.** Chess Log's narrative generation built its own handling instead of reusing AI Summary's existing controls for the same three things.

Extracting any of this into shared components would mean refactoring Philipp's existing code, which this project has consistently avoided doing unilaterally. All six instances were built as Chess Log's own copies, mirroring the pattern without touching the source files. Six real instances now — not a hypothetical DRY nice-to-have."

gh issue create --label "philipp-discussion" \
  --title "[old #13] Games without a valid date are silently skipped from Chess Log charting" \
  --body "Chess Log's stats service already has test coverage for \"games with undateable dates are skipped\" (\`TestDateFiltering\`) — but nothing surfaces this to the player.

Player Stats' own docs state its convention directly: \"Some sections (activity heatmap, date-based progression charts) use the game dates stored in the PGN headers. If dates are missing or incomplete, those sections may be hidden and a short notice will be shown at the top of view.\"

Chess Log should handle missing dates the same way — hide the affected chart, show a short notice explaining why, rather than silently omitting data with no explanation. No longer an open design question (there's a concrete existing pattern to mirror) — still worth a quick confirmation with Philipp at PR review."

gh issue create --label "philipp-discussion" \
  --title "[old #14] Does using Game Summary's \"Missed Tactics\"/CPL data in Narrative Summary cross Chess Log's domain boundary?" \
  --body "Potentially fundamental question, needs real discussion, not a unilateral call.

**Broad version:** Is Game Summary's \"Missed Tactics\" detection actually saved/persisted, or computed transiently? If saved, could Narrative Summary pull it in to enrich synthesis? If so, Narrative Summary would no longer be synthesizing purely from player-authored self-diagnosis — it'd draw on engine-detected data, which is exactly what Chess Log's design doc opens by explicitly NOT being (\"The goal is not engine-driven move classification — CARA already does that well. It's player self-diagnosis.\"). Possible conclusion: engine-augmented synthesis might not belong inside Chess Log at all — could be a broader, separate CARA feature.

**Narrower, more defensible variant, worth deciding separately:** when a why-note itself expresses unresolved confusion (\"I don't understand why the engine move is better\"), that moment's CPL (already persisted in \`CARAAnalysisData\`, no schema change needed) could be tracked as a severity signal — a 900-CPL moment never understood is meaningfully different from a 200-CPL one. This only ever attaches engine data to a moment the player already flagged as confusing in their own words — never used to independently decide what's narrative-worthy. Mechanically connects to the shallow-note-flagging mechanism (§5.2) for detecting \"this why-note expresses confusion.\"

Still unresolved whether the narrower version needs the same sign-off as the broad one, or is different enough in kind to decide without Philipp. Raise both versions together."

# ============================================================
# STILL OPEN — INTERNAL (old #2-7)
# ============================================================

gh issue create \
  --title "[old #2] CCT and 3x3 glossary text for the narrative prompt" \
  --body "CLAMP's glossary is already built. CCT and 3x3 were intentionally scoped out of that pass since tagged data is CLAMP-primary — credit-conservation decision, not a design gap.

**Key principle to carry forward:** CLAMP/CCT are bidirectional checklists — applied once to the opponent's last move (did they just create a check, loose piece, alignment, etc. that went unanswered?) and again to the player's own candidate move before playing it (does my move create the same problem?). A tag isn't only ever about \"what my move did wrong\" — it can equally mean \"I missed what their move set up.\"

**Draft CCT text (needs confirmation when this resumes, not yet finalized):** C reuses CLAMP's Checks definition; Captures mirrors CLAMP's Loose Pieces framing (a capture opportunity — an undefended piece, either side's — that wasn't taken); Threats (non-capturing pressure that wasn't addressed) still needs drafting.

3x3 doesn't need a glossary in the same sense — its three Whys are free text, already self-explanatory to an LLM reading them; just needs its three prompt questions stated once so the model knows what \"Why1/Why2/Why3\" represent structurally.

**Custom tagging's glossary is \"wide open,\" explicitly deferred, not designed at all.** Since Custom categories are player-defined text with no fixed vocabulary, there's no glossary to write in the same sense — worth figuring out later whether Custom needs anything beyond just passing the player's own category names through as-is."

gh issue create \
  --title "[old #3] Per-game Chess Log summary (same as the deferred detail-tab view/edit UI)" \
  --body "Idea: show a summary of a specific game's tagged moments somewhere convenient.

Explicitly should NOT live inside the Chess Log Charts tab itself — that tab's whole design metaphor is a cumulative report across selected games, and a per-game summary embedded there would blur that boundary.

Natural alternative home: behind the existing 🏷 per-move indicator in the Moves List (right-click, or a small popup), since that's already where \"this game has tagged moments\" is surfaced.

Not started — this is the same feature as the already-deferred detail-tab view/edit UI, not new scope."

gh issue create \
  --title "[old #4] Narrative prompt should distinguish opening/middlegame/endgame" \
  --body "CARA already knows where phase transitions occur — visible in the existing \"ACPL progression by phase\" chart, which already breaks games into Opening/Middlegame/Endgame as distinct series.

The narrative prompt should use this existing phase data to frame its synthesis of the player's own tagged moments and why-notes (e.g. \"your L tags cluster in the middlegame\"), not to introduce independent engine judgment as new content.

This seems safely inside Chess Log's own domain — phase is structural game metadata (which ply range a move falls in), not an engine evaluation of move quality, so it doesn't raise the same domain-boundary concern as the CPL/Missed-Tactics question. Worth confirming that read once real narrative prompt work resumes."

gh issue create \
  --title "[old #5, #6] Confirm Sonnet 5's adaptive thinking is disabled before switching narrative generation to it; investigate cross-model prompt compliance" \
  --body "Sonnet 5 turns on adaptive thinking by default (a real behavior change from Sonnet 4.6, where thinking was opt-in), and thinking tokens share the exact same \`max_tokens\` budget as the visible response text — the precise mechanism behind a token-exhaustion bug already fixed for Sonnet 4.6. Switching models without confirming this could silently reintroduce that bug under a new name.

Sonnet 5 also uses a new tokenizer producing ~30% more tokens for the same input text — a second, independent reason its real token consumption could exceed expectations even before thinking is factored in.

Pricing is effectively the same as Sonnet 4.6 either way — this isn't a cost tradeoff, it's a reliability one.

**Recommendation until confirmed:** use Sonnet 4.6 for Chess Log narrative generation — mature, predictable, opt-in thinking, and the model this whole debugging thread was actually tested against.

**Related finding, deferred until current prompt work is stable:** while stress-testing the narrative with garbage input, accidentally had Fable or Haiku selected instead of Sonnet 4.6 — the output STRUCTURE diverged (two headed sections like \"Personal Reflections\"/\"Key Takeaways\" instead of the single continuous-prose \"Narrative Summary\" format). Every prompt-engineering fix this session has only been validated against Sonnet 4.6's behavior — other models may not reliably follow the same structural instructions at all. Worth a real cross-model investigation once current Sonnet-4.6-targeted work is fully stable — explicitly sequenced after, not now."

gh issue create \
  --title "[old #7] Confirm §3.5 (whole-game-note nudge) implementation status" \
  --body "Small remaining thread from the original narrative-review item — most of what that item originally flagged (wording issues, missing whole-game-note data) has since been fixed through later prompt-engineering work.

Remaining open question: was the §3.5 whole-game-note prompt (\"if a tagged game has no note, nudge the player to add one\") ever actually implemented, or was it deferred out of scope back in the original tagging PR and never built? Confirm either way.

**Design constraint already decided, regardless of §3.5's status:** whole-game notes should never be auto-generated or auto-drafted from a game's tagged-moment summary, even as a convenience/starting point. Rolling up existing tags/why-notes into note text is repackaging data that already exists, not genuine reflection. If §3.5 or any future feature is built, it should prompt the player to write freely, never pre-fill from tagged data."

# ============================================================
# PRE-PR CHECKLIST (old #15-17)
# ============================================================

gh issue create --label "pre-pr" \
  --title "[old #15] Write resources/manual/index.html entry for Chess Log (+ instructional video)" \
  --body "Every directive so far has touched code + CLAUDE.md (fork-local dev doc, never reaches Philipp) — the actual user-facing HTML manual Philipp asked for hasn't been written at all. Also planned for an instructional video, not just the written manual.

Needs its own pass once the feature surface stabilizes (tagging, Settings, charts, narrative). Should incorporate:

- Explanation of CLAMP/CCT/3x3/Custom terms and the 3-moment guidance, so a narrative shared with someone unfamiliar with the terms is still understandable (decided: not building an in-app legend/explainer for this — pointing people to this documentation instead).
- The bishop-pair oversimplification example (an AI game summary cited \"wins the bishop pair\" as justification for a move, stated as if universally good — but bishop pair value is position-dependent, not an unconditional principle) and the escalation-discipline lesson: teach the practice (struggle first, ask a narrow hint if stuck, full explanation only once genuinely earned), never present \"ask AI when stuck\" as a first-resort shortcut.
- The Anthropic API cost dashboard link: platform.claude.com/cost (Anthropic keys only, no known equivalent for other providers).
- Workflow reminder: check Game Summary's \"Top 3 Worst Moves\" list every game rather than relying on eyeballing — especially for Miss-classified moves, which aren't self-signaling the way blunders are; for large CPL swings (300+) look at the actual position, not just the one-line alternative.
- Workflow preference: use CARA's own engine analysis board instead of paying for chess.com's analysis feature, since CARA already has this capability and it's more consolidated."

gh issue create --label "pre-pr" \
  --title "[old #16] Confirm keyboard shortcuts are documented" \
  --body "Confirm any new bindable shortcuts added during Chess Log development are documented per Philipp's original ask, not just functional."

gh issue create --label "pre-pr" \
  --title "[old #17] Final config/theme system integration check" \
  --body "Confirm nothing was left as a one-off special case outside config.json's and the theme files' normal patterns (already mostly handled via the ConfigLoader convention) — final check before PR."

# ============================================================
# DEFERRED / FUTURE (old #21-27)
# ============================================================

gh issue create --label "deferred" \
  --title "[old #21] \"Save Narrative Summary\" feature" \
  --body "Let the player save/export a generated narrative summary (to a file, or persisted somewhere in CARA) rather than it only existing transiently in the UI until the next Generate click. Not yet designed."

gh issue create --label "deferred" \
  --title "[old #22] Could Narrative Summary recommend a training program, not just describe patterns?" \
  --body "Real risk: this could easily become simplistic and repetitive (\"you keep hanging pieces, practice tactics\") and get ignored as a result rather than being useful — worth designing carefully if pursued at all, not just bolted on.

No design yet — noting the risk so it isn't lost if revisited later."

gh issue create --label "deferred" \
  --title "[old #23] \"Export to PDF\" for Chess Log" \
  --body "Player Stats already has this: right-click anywhere → \"Export PDF Report\" saves a multi-page report, including only the sections currently visible for the active profile, with the profile name shown in the header.

Chess Log should follow the same pattern rather than inventing a new export UX — right-click → Export PDF Report, covering whichever of charts/narrative are currently visible, with the player name in the header. Not yet designed for Chess Log specifically, but now has a concrete existing convention to copy instead of building from scratch."

gh issue create --label "deferred" \
  --title "[old #24] Multiple custom tagging sets" \
  --body "Currently Custom is a single flat list of player-defined categories. A case could be made for letting the player maintain more than one named set (e.g. different vocabularies for different training focuses) rather than one shared list. No immediate need identified — just worth remembering as a possibility."

gh issue create --label "deferred" \
  --title "[old #25] \"Tagged\" column on the Game Table (alternative to the chip approach)" \
  --body "Original idea before the Game Tags chip was chosen instead — icon count + ellipsis for 4+, mirroring the existing \"Annotated\" column. Kept as a fallback if the chip approach's bugs prove stubborn or the chip turns out not to be the right long-term home. Performance concern if revisited: needs a real per-game count, not just a boolean, unlike has_notes/annotated."

gh issue create --label "deferred" \
  --title "[old #26] Revisit whether the charting feature is the right direction at all" \
  --body "Not convinced the charts are useful yet, but explicitly attributing this to too small a sample, not necessarily to the feature itself.

**Plan:** tag many more games first, then come back and discuss how to make the charts genuinely useful once there's enough real data to judge them properly — rather than deciding based on a small, noisy sample.

**Related note:** tagged games were loss-only at first, but that was just a bootstrapping choice to get real data flowing quickly, not an intended long-term pattern — wins are being included going forward too (with extra value in shaky/close wins specifically, since those are more likely to have real taggable moments than a clean win)."

gh issue create --label "deferred" \
  --title "[old #27] Multi-alias player identity (CARA-wide, not Chess Log-specific)" \
  --body "Idea: let CARA aggregate games across more than one player name (e.g. an OTB name and a chess.com username) as one logical identity, rather than requiring bulk-renaming games to force a single shared name (Philipp's suggested interim workaround).

**Feasibility investigated — summary:** no deep architectural blocker found. Player Stats and Chess Log currently have completely independent player-matching implementations with no shared alias concept anywhere in CARA. Rough combined estimate: 3-5 days, mostly weighted toward designing and building the alias configuration/settings UI (doesn't exist yet in any form) rather than the matching-logic changes themselves. Player Stats' matching logic is spread across ~20 comparison sites in 3 files (heavier wiring lift); Chess Log's is already centralized behind 1-2 helpers (lighter lift). No player name is persisted anywhere as a stored identifier currently, so no migration/compatibility concern.

Explicitly deferred — future work after Chess Log ships, not something to pull forward now."

echo "Done. Run 'gh issue list' to verify. 23 issues created (7 philipp-discussion, 3 pre-pr, 13 open/deferred)."
