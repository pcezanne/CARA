"""Generate synthetic Chess Log test data for full-year binning validation.

Takes a real tagged PGN file (e.g. TaggingTestGames.pgn), clones games across
a full calendar year with deliberate density variation, and writes a new PGN.

CARAChessLog / CARAChessLogInfo / CARAChessLogChecksum triples are copied
verbatim — checksums only cover the JSON payload (keyed by variation path),
not by Date/Round/UTCDate, so they remain valid after header rewriting.

Usage:
    python scripts/generate_synthetic_chess_log_data.py
    python scripts/generate_synthetic_chess_log_data.py --input TaggingTestGames.pgn
    python scripts/generate_synthetic_chess_log_data.py --output out.pgn --seed 42
"""

from __future__ import annotations

import argparse
import calendar
import random
import re
import sys
from pathlib import Path

# ── Month distribution for the target year ────────────────────────────────────
# Two empty months (Jan, Jun), two sparse (Feb, Nov), two dense (May, Oct).
MONTH_COUNTS = {
    1: 0,   # empty
    2: 2,   # sparse
    3: 6,
    4: 4,
    5: 12,  # dense
    6: 0,   # empty
    7: 3,
    8: 8,
    9: 5,
    10: 10, # dense
    11: 1,  # sparse
    12: 4,
}

_DATE_RE = re.compile(r'^(\[Date\s+")\d{4}\.\d{2}\.\d{2}("\])$')
_UTCDATE_RE = re.compile(r'^(\[UTCDate\s+")\d{4}\.\d{2}\.\d{2}("\])$')
_ROUND_RE = re.compile(r'^\[Round\s+"[^"]*"\]$')


def _split_games(text: str) -> list[str]:
    """Split a PGN file text into individual raw game blocks."""
    blocks: list[str] = []
    current: list[str] = []
    in_movetext = False

    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[Event "):
            if current:
                blocks.append("".join(current).rstrip() + "\n")
            current = [line]
            in_movetext = False
        elif current:
            current.append(line)
            if not stripped.startswith("[") and stripped:
                in_movetext = True

    if current:
        blocks.append("".join(current).rstrip() + "\n")

    return [b for b in blocks if b.strip()]


def _rewrite_game(block: str, year: int, month: int, day: int, slot: int) -> str:
    """Return block with Date/UTCDate/Round rewritten; all other headers untouched."""
    date_str = f"{year:04d}.{month:02d}.{day:02d}"
    lines = block.splitlines(keepends=True)
    out: list[str] = []
    for line in lines:
        stripped = line.rstrip("\n").rstrip("\r")
        if _DATE_RE.match(stripped):
            m = _DATE_RE.match(stripped)
            out.append(f'{m.group(1)}{date_str}{m.group(2)}\n')
        elif _UTCDATE_RE.match(stripped):
            m = _UTCDATE_RE.match(stripped)
            out.append(f'{m.group(1)}{date_str}{m.group(2)}\n')
        elif _ROUND_RE.match(stripped):
            out.append(f'[Round "syn-{slot:03d}"]\n')
        else:
            out.append(line if line.endswith("\n") else line + "\n")
    return "".join(out)


def generate(
    input_path: Path,
    output_path: Path,
    year: int,
    seed: int,
    month_counts: dict[int, int] | None = None,
) -> None:
    if month_counts is None:
        month_counts = MONTH_COUNTS

    text = input_path.read_text(encoding="utf-8")
    source_games = _split_games(text)
    if not source_games:
        print(f"ERROR: no games found in {input_path}", file=sys.stderr)
        sys.exit(1)

    rng = random.Random(seed)

    # Build the target slot list: (month, day) pairs in chronological order.
    slots: list[tuple[int, int]] = []
    for month in range(1, 13):
        count = month_counts.get(month, 0)
        _, days_in_month = calendar.monthrange(year, month)
        days = sorted(rng.sample(range(1, days_in_month + 1), min(count, days_in_month)))
        for day in days:
            slots.append((month, day))

    total = len(slots)
    out_blocks: list[str] = []
    for slot_idx, (month, day) in enumerate(slots):
        src = source_games[slot_idx % len(source_games)]
        out_blocks.append(_rewrite_game(src, year, month, day, slot_idx + 1))

    output_path.write_text("\n".join(out_blocks) + "\n", encoding="utf-8")

    # ── Report ────────────────────────────────────────────────────────────────
    month_names = [calendar.month_abbr[m] for m in range(1, 13)]
    print(f"Written {total} games to {output_path}")
    print(f"Source: {len(source_games)} games from {input_path}")
    print()
    print(f"{'Month':<6}  {'Count':>5}  {'Bar'}")
    for month in range(1, 13):
        count = sum(1 for m, _ in slots if m == month)
        bar = "█" * count
        print(f"{month_names[month-1]:<6}  {count:>5}  {bar}")

    # Verify CARAChessLog triples survived bit-identical.
    original_cl_lines = [l for l in text.splitlines() if l.startswith("[CARAChessLog ")]
    output_text = output_path.read_text(encoding="utf-8")
    output_cl_lines = [l for l in output_text.splitlines() if l.startswith("[CARAChessLog ")]
    original_values = {l for l in original_cl_lines}
    missing = original_values - set(output_cl_lines)
    if missing:
        print(f"\nWARNING: {len(missing)} CARAChessLog value(s) not found in output — header rewrite may have corrupted them.")
    else:
        tagged_src = len(original_cl_lines)
        tagged_out = len(output_cl_lines)
        print(f"\nCARAChessLog: {tagged_src} unique value(s) in source, {tagged_out} instances in output — all values preserved bit-identical.")


def main() -> None:
    repo_root = Path(__file__).parent.parent

    parser = argparse.ArgumentParser(description="Generate synthetic Chess Log test PGN")
    parser.add_argument("--input", default=str(repo_root / "TaggingTestGames.pgn"),
                        help="Input PGN file (default: TaggingTestGames.pgn at repo root)")
    parser.add_argument("--output", default=str(repo_root / "TaggingTestGames_synthetic_2026.pgn"),
                        help="Output PGN file (default: TaggingTestGames_synthetic_2026.pgn at repo root)")
    parser.add_argument("--year", type=int, default=2026,
                        help="Target year for synthesized dates (default: 2026)")
    parser.add_argument("--seed", type=int, default=20260830,
                        help="RNG seed for reproducibility (default: 20260830)")
    args = parser.parse_args()

    generate(
        input_path=Path(args.input),
        output_path=Path(args.output),
        year=args.year,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
