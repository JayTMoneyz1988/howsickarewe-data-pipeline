"""
fetch_ae_attendances.py

A&E Attendances and Emergency Admissions -- confirmed reachable and
automatable, same domain and discover-the-current-link pattern as
fetch_nhs_england_bulk.py and fetch_dm01.py. Closes part of the Domain 4
(Access to Care) gap -- A&E pressure is relevant context for both CVD
(cardiac emergency presentations) and diabetes (DKA/hypoglycaemia admissions).

The site organises files by financial year sub-page, e.g.:
    .../ae-attendances-and-emergency-admissions-2026-27/
Each month has several files; this grabs the main monthly CSV (Trust-level
with a Parent Org column for ICB/region aggregation, same shape as RTT) and
the by-provider .xls summary.

Filenames include a random suffix code that changes every month (e.g.
"August-2026-CSV-De2k3n.csv") -- matched by pattern, not hardcoded.

Output: data/raw/ae_attendances/<filename>.csv, <filename>.xls
"""

import re
from pathlib import Path

import requests

HEADERS = {"User-Agent": "howsickarewe.com data pipeline (contact: James Tyson)"}
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "ae_attendances"

BASE_INDEX = "https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/"


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
        r'href="(https://www\.england\.nhs\.uk/statistics/[^"]*/(ae-attendances-and-emergency-admissions-(\d{4})-\d{2})/)"',
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

    csv_links = re.findall(
        r'href="(https://www\.england\.nhs\.uk/statistics/wp-content/uploads/[^"]*-CSV-[^"]*\.csv)"',
        r.text,
    )
    xls_links = re.findall(
        r'href="(https://www\.england\.nhs\.uk/statistics/wp-content/uploads/[^"]*-AE-by-provider-[^"]*\.xls)"',
        r.text,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for link in (csv_links[:1] + xls_links[:1]):
        resp = requests.get(link, headers=HEADERS, timeout=90)
        if resp.status_code != 200:
            continue
        fname = link.rsplit("/", 1)[-1]
        (OUT_DIR / fname).write_bytes(resp.content)
        saved.append(fname)

    print(f"A&E attendances: wrote {len(saved)} files from {subpage_url}")
    return {"status": "ok", "subpage_url": subpage_url, "files": saved}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
