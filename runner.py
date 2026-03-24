#!/usr/bin/env python3
"""Entry point for the scraper. Run: python runner.py [developer ...]"""
import asyncio
import sys
from scraper.main import run_all

if __name__ == "__main__":
    devs = sys.argv[1:] or None
    result = asyncio.run(run_all(devs))
    # Exit 1 only if ALL scrapers failed
    all_failed = all(
        d.get("error") for d in result.get("developers", {}).values()
    )
    sys.exit(1 if all_failed else 0)
