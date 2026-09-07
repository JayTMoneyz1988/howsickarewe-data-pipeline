"""
fetch_cqc.py

Downloads the CQC's bulk "care directory with ratings" file -- a weekly
snapshot of every CQC-regulated location in England including its current
rating. No API key needed for this file (the full REST API does require one,
via registration at https://api.portal.cqc.org.uk -- only bother with that if
a future need goes beyond what the bulk file covers, e.g. historical rating
changes over time).

The download link is NOT static -- the filename embeds the publish date
(e.g. "02_september_2026_CQC_directory.csv") so this script scrapes the
"Using CQC data" page each run to find the current link rather than
hardcoding one that will go stale.

Output: data/raw/cqc/<YYYY-MM-DD>_CQC_directory.csv
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import requests

PAGE_URL = "https://www.cqc.org.uk/about-us/transparency/using-cqc-data"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "cqc"
HEADERS = {"User-Agent": "howsickarewe.com data pipeline (contact: James Tyson)"}


def check_reachable() -> bool:
    try:
        r = requests.get(PAGE_URL, headers=HEADERS, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False


def find_current_csv_url() -> str | None:
    r = requests.get(PAGE_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    # The "care directory" (ratings + locations) csv link, not the
    # "care directory with filters" ODS -- both are on the page, keep them separate.
    matches = re.findall(r'href="(https://www\.cqc\.org\.uk/system/files/[^"]*CQC_directory\.csv)"', r.text)
    return matches[0] if matches else None


def run() -> dict:
    if not check_reachable():
        print("CQC site not reachable right now.")
        return {"status": "unreachable"}

    url = find_current_csv_url()
    if not url:
        print("Could not find a current CQC directory CSV link on the page -- "
              "the page layout may have changed. Check manually: " + PAGE_URL)
        return {"status": "link_not_found"}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = OUT_DIR / f"{date_str}_CQC_directory.csv"
    out_path.write_bytes(r.content)

    print(f"CQC: wrote {out_path} ({len(r.content):,} bytes) from {url}")
    return {"status": "ok", "path": str(out_path), "source_url": url, "bytes": len(r.content)}


if __name__ == "__main__":
    run()
