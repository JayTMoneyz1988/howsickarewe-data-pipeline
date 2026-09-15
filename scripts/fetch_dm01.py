"""
fetch_dm01.py

Diagnostic Waiting Times and Activity (DM01) -- confirmed reachable and
automatable, same domain and same discover-the-current-link pattern as
fetch_nhs_england_bulk.py. This closes the Domain 4 (Access to Care)
diagnostic-waits gap for both CVD and diabetes (many of the 15 tests DM01
covers -- e.g. echocardiography, non-obstetric ultrasound -- are directly
relevant to the CVD diagnostic pathway).

The site organises files by financial year sub-page, e.g.:
    .../monthly-diagnostics-data-2026-27/
Each sub-page lists three files per month: Provider level, Commissioner
level (= ICB, the one that matters for this project), and a "full extract"
zip. This script grabs the most recent month's Commissioner file plus the
full extract.

Output: data/raw/dm01/<month>_Commissioner.xls, <month>_full_extract.zip
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import requests

HEADERS = {"User-Agent": "howsickarewe.com data pipeline (contact: James Tyson)"}
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "dm01"

BASE_INDEX = "https://www.england.nhs.uk/statistics/statistical-work-areas/diagnostics-waiting-times-and-activity/monthly-diagnostics-waiting-times-and-activity/"


def check_reachable() -> bool:
    try:
        r = requests.get(BASE_INDEX, headers=HEADERS, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False


def find_current_year_subpage() -> str | None:
    r = requests.get(BASE_INDEX, headers=HEADERS, timeout=20)
    r.raise_for_status()
    matches = re.findall(
        r'href="(https://www\.england\.nhs\.uk/statistics/[^"]*/(monthly-diagnostics-data-(\d{4})-\d{2})/)"',
        r.text,
    )
    if not matches:
        return None
    best = max(matches, key=lambda m: int(m[2]))
    return best[0]


def run() -> dict:
    if not check_reachable():
        return {"status": "unreachable"}

    subpage_url = find_current_year_subpage()
    if not subpage_url:
        return {"status": "no year subpage found -- check manually: " + BASE_INDEX}

    r = requests.get(subpage_url, headers=HEADERS, timeout=20)
    r.raise_for_status()

    commissioner_links = re.findall(
        r'href="(https://www\.england\.nhs\.uk/statistics/wp-content/uploads/[^"]*Commissioner[^"]*\.xls)"',
        r.text,
    )
    extract_links = re.findall(
        r'href="(https://www\.england\.nhs\.uk/statistics/wp-content/uploads/[^"]*full-extract[^"]*\.zip)"',
        r.text,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for link in (commissioner_links[:1] + extract_links[:1]):
        resp = requests.get(link, headers=HEADERS, timeout=90)
        if resp.status_code != 200:
            continue
        fname = link.rsplit("/", 1)[-1]
        (OUT_DIR / fname).write_bytes(resp.content)
        saved.append(fname)

    print(f"DM01: wrote {len(saved)} files from {subpage_url}")
    return {"status": "ok", "subpage_url": subpage_url, "files": saved}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
