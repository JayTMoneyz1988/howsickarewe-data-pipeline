"""
fetch_nhs_england_bulk.py

NHS England's statistics pages publish monthly files at predictable-but-not-
static URLs (the month and a revision suffix are baked into the filename and
the folder date, e.g. .../2026/07/Full-CSV-data-file-Mar26-ZIP-3M-revised.zip).
Rather than guess the current filename, this script scrapes each publication's
index page for the most recent link and downloads that.

Covers two publications for now (both confirmed reachable Sept 2026):
  - Referral to Treatment (RTT) Waiting Times -- full CSV data file (by provider)
  - Friends and Family Test (FFT) -- data collection overview + per-setting tables

Output:
  data/raw/rtt/<YYYY-MM>_full_csv.zip
  data/raw/fft/<YYYY-MM>_<setting>.xlsx
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import requests

HEADERS = {"User-Agent": "howsickarewe.com data pipeline (contact: James Tyson)"}
DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw"

RTT_INDEX_URL = "https://www.england.nhs.uk/statistics/statistical-work-areas/rtt-waiting-times/rtt-data-2025-26/"

# FFT publishes one page per month with a predictable slug; there is no single
# "latest" index page, so we derive the current month's slug from today's date.
# NHS England publishes with roughly a 6-8 week lag, so we try this month and
# walk backwards until one resolves.
FFT_BASE = "https://www.england.nhs.uk/publication/friends-and-family-test-data-{month}-{year}/"


def check_reachable(url: str) -> bool:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False


def fetch_rtt() -> dict:
    out_dir = DATA_ROOT / "rtt"
    out_dir.mkdir(parents=True, exist_ok=True)

    r = requests.get(RTT_INDEX_URL, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return {"status": f"index page unreachable ({r.status_code})"}

    # The most recent "Full CSV data file" link appears first on the page.
    links = re.findall(r'href="(https://www\.england\.nhs\.uk/statistics/wp-content/uploads/[^"]*Full-CSV[^"]*\.zip)"', r.text)
    if not links:
        return {"status": "no RTT zip link found -- page layout may have changed"}

    url = links[0]
    resp = requests.get(url, headers=HEADERS, timeout=90)
    resp.raise_for_status()

    fname = url.rsplit("/", 1)[-1]
    out_path = out_dir / fname
    out_path.write_bytes(resp.content)
    print(f"RTT: wrote {out_path} ({len(resp.content):,} bytes)")
    return {"status": "ok", "path": str(out_path), "source_url": url}


def fetch_fft() -> dict:
    out_dir = DATA_ROOT / "fft"
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    months_tried = []
    best_page_url = None
    best_links: list[str] = []
    # NHS England's page for a month can go live before every per-setting
    # file is attached to it (a partially-populated month is a real, quiet
    # failure mode, not a hypothetical). Walk back up to 5 months and keep
    # the most complete page found rather than stopping at the first 200.
    for offset in range(5):
        month_idx = now.month - offset
        year = now.year
        while month_idx <= 0:
            month_idx += 12
            year -= 1
        month_name = datetime(year, month_idx, 1).strftime("%B").lower()
        candidate = FFT_BASE.format(month=month_name, year=year)
        months_tried.append(candidate)
        r = requests.get(candidate, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            continue
        # Per-setting files (A&E, GP, maternity, etc.) are published as
        # .xlsm, not .xlsx -- easy to miss with only one extension pattern.
        links = sorted(set(re.findall(
            r'href="(https://www\.england\.nhs\.uk/wp-content/uploads/[^"]*\.xls[mx])"', r.text
        )))
        if len(links) > len(best_links):
            best_page_url, best_links = candidate, links
        if len(best_links) >= 8:  # a fully-populated month has ~13 files
            break

    if best_page_url is None:
        return {"status": "no recent FFT page found", "tried": months_tried}

    saved = []
    for link in best_links:
        resp = requests.get(link, headers=HEADERS, timeout=60)
        if resp.status_code != 200:
            continue
        fname = link.rsplit("/", 1)[-1]
        (out_dir / fname).write_bytes(resp.content)
        saved.append(fname)

    print(f"FFT: wrote {len(saved)} files from {best_page_url}")
    if len(saved) < 8:
        print("Note: fewer files than a fully-populated month usually has -- "
              "the most recent complete month may be the one before this.")
    return {"status": "ok", "page_url": best_page_url, "files": saved}


def run() -> dict:
    return {"rtt": fetch_rtt(), "fft": fetch_fft()}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
