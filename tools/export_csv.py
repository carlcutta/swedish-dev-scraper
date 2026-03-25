"""Export apartment-level data from all data/latest/*.json files to a CSV.

Outputs: data/latest/apartments.csv

Each row = one apartment. Project-level fields are repeated on every row
so the CSV is self-contained and easy to open in Excel / Google Sheets.

Usage:
    python tools/export_csv.py
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LATEST_DIR = Path("data/latest")
OUT_FILE = LATEST_DIR / "apartments.csv"

# Project-level columns that appear on every row
PROJECT_COLS = [
    "scraped_at",
    "developer",
    "project",
    "project_url",
    "location",
    "municipality",
    "project_status",
]

# Preferred apartment column order (any extra columns are appended after)
APT_COL_ORDER = [
    "Nummer",
    "V\u00e5ning",
    "Antal rum",
    "Storlek",
    "Pris",
    "Avgift",
    "Status",
]


def load_snapshots() -> list[dict]:
    rows = []
    for json_file in sorted(LATEST_DIR.glob("*.json")):
        if json_file.name in ("all.json", "index.json"):
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  Skipping {json_file.name}: {exc}", file=sys.stderr)
            continue

        developer = data.get("developer", "")
        scraped_at = data.get("scraped_at", "")

        for project in data.get("projects", []):
            apartments = project.get("apartments", [])
            if not apartments:
                continue

            project_meta = {
                "scraped_at": scraped_at,
                "developer": developer,
                "project": project.get("name", ""),
                "project_url": project.get("url", ""),
                "location": project.get("location", ""),
                "municipality": project.get("municipality", ""),
                "project_status": project.get("status", ""),
            }

            for apt in apartments:
                row = {**project_meta, **apt}
                rows.append(row)

    return rows


def build_fieldnames(rows: list[dict]) -> list[str]:
    # Collect all apartment-level keys seen across all rows
    apt_keys: set[str] = set()
    for row in rows:
        for k in row:
            if k not in PROJECT_COLS:
                apt_keys.add(k)

    # Order: preferred apt cols first, then any extras alphabetically
    ordered_apt = [c for c in APT_COL_ORDER if c in apt_keys]
    extras = sorted(apt_keys - set(ordered_apt))
    return PROJECT_COLS + ordered_apt + extras


def main():
    LATEST_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading snapshots...")
    rows = load_snapshots()

    if not rows:
        print("No apartment data found. CSV not written.")
        return

    fieldnames = build_fieldnames(rows)
    with OUT_FILE.open("w", newline="", encoding="utf-8-sig") as f:
        # utf-8-sig adds BOM so Excel opens it correctly
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Written {len(rows)} apartment rows to {OUT_FILE}")
    print(f"Columns: {fieldnames}")


if __name__ == "__main__":
    main()
