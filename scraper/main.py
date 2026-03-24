"""Main entry point. Runs all developer scrapers concurrently and saves results."""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .developers import ALL_SCRAPERS

DATA_DIR = Path(__file__).parent.parent / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
LATEST_DIR = DATA_DIR / "latest"

# Limit concurrency so we don't hammer multiple sites at once
MAX_CONCURRENT = int(os.environ.get("SCRAPER_CONCURRENCY", "2"))
PROXY_URL = os.environ.get("PROXY_URL")  # Optional: set in GitHub Actions secrets


async def run_scraper(ScraperClass) -> dict:
    scraper = ScraperClass(proxy_url=PROXY_URL)
    snapshot = await scraper.run()
    return snapshot.to_dict()


async def run_all(developers: list[str] | None = None) -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshot_dir = SNAPSHOTS_DIR / today
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    LATEST_DIR.mkdir(parents=True, exist_ok=True)

    scrapers = [
        S for S in ALL_SCRAPERS
        if not developers or S.name.lower() in [d.lower() for d in developers]
    ]

    # Run with limited concurrency
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def run_with_semaphore(ScraperClass):
        async with semaphore:
            return ScraperClass.name, await run_scraper(ScraperClass)

    tasks = [run_with_semaphore(S) for S in scrapers]
    results_list = await asyncio.gather(*tasks)
    results = dict(results_list)

    # Write per-developer files
    for dev_name, data in results.items():
        fname = dev_name.lower().replace(" ", "_") + ".json"
        # History snapshot (don't overwrite if already exists for today)
        hist_path = snapshot_dir / fname
        if not hist_path.exists():
            hist_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        # Always update latest
        (LATEST_DIR / fname).write_text(json.dumps(data, ensure_ascii=False, indent=2))

    # Write combined latest (also used for history chart)
    combined = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "developers": results,
        "total_projects": sum(r["project_count"] for r in results.values()),
    }
    (LATEST_DIR / "all.json").write_text(json.dumps(combined, ensure_ascii=False, indent=2))
    # Also write combined into snapshot dir
    (snapshot_dir / "all.json").write_text(json.dumps(combined, ensure_ascii=False, indent=2))

    _update_index(today)

    # Summary
    failed = [name for name, d in results.items() if d.get("error")]
    total = combined["total_projects"]
    print(f"\n{'='*60}")
    print(f"Scraped: {total} projects across {len(results)} developers")
    if failed:
        print(f"Failed: {', '.join(failed)}")
    print(f"{'='*60}")

    return combined


def _update_index(date: str):
    index_path = DATA_DIR / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
    else:
        index = {"snapshots": []}
    if date not in index["snapshots"]:
        index["snapshots"].append(date)
        index["snapshots"].sort(reverse=True)
    index["latest"] = index["snapshots"][0]
    index["updated_at"] = datetime.now(timezone.utc).isoformat()
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    devs = sys.argv[1:] or None
    asyncio.run(run_all(devs))
