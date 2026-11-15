"""Fold old service-journal lines into access_day. Reads stdin.

    journalctl -u power-monitor -o short-unix --no-pager -g 'key=' \\
        | .venv/bin/python backfill_access_journal.py --before UNIX

--before skips lines at or after that timestamp so the live counter is not
added twice. Prints counts only. The key itself stays out of the output.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from access_stats import add_parsed, parse_access_line
from database import access_day_merge


def load_key_labels(env_path: Path) -> dict[str, str]:
    """Current env keys plus every key ever stored in the database."""
    labels: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("API_KEYS="):
                continue
            raw = line.split("=", 1)[1].strip().strip('"').strip("'")
            for part in raw.split(","):
                if ":" not in part:
                    continue
                label, key = part.split(":", 1)
                label = label.strip()
                key = key.strip()
                if label and key:
                    labels[key] = label
    from database import _conn

    with _conn() as db:
        rows = db.execute("SELECT key, label FROM api_keys WHERE key IS NOT NULL AND key != ''").fetchall()
    for row in rows:
        labels.setdefault(row["key"], row["label"])
    return labels


def main() -> int:
    parser = argparse.ArgumentParser(description="Import dashboard hits from a journal export.")
    parser.add_argument("--before", type=float, default=None, help="Skip lines at or after this unix time")
    parser.add_argument("--env", default=".env")
    args = parser.parse_args()
    labels = load_key_labels(Path(args.env))

    def lookup(key: str) -> str | None:
        return labels.get(key)

    acc: dict = {}
    seen = kept = 0
    for line in sys.stdin:
        seen += 1
        hit = parse_access_line(line, args.before)
        if hit is None:
            continue
        kept += 1
        add_parsed(acc, hit, lookup)
    rows = [
        (day, label, ip, hits[0], hits[1], hits[2])
        for (day, label, ip), hits in acc.items()
    ]
    if rows:
        access_day_merge(rows)
    days = sorted({row[0] for row in rows})
    unknown = sum(1 for row in rows if row[1] == "невідомий")
    print("seen", seen)
    print("kept", kept)
    print("rows", len(rows))
    print("unknown_rows", unknown)
    print("first_day", days[0] if days else None)
    print("last_day", days[-1] if days else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
