"""
fetch_imd.py

Downloads the English Indices of Deprivation directly from GOV.UK's asset
host. MHCLG's own "Open Data Communities" portal (opendatacommunities.org)
returns a hard 403 from this environment (Azure Front Door bot protection,
confirmed Sept 2026) -- but the same files are mirrored on
assets.publishing.service.gov.uk, which is not blocked. Use that host.

IMPORTANT PROJECT DECISION NEEDED (see NHS-DATA-SOURCE-LIBRARY.md, Domain 12):
IMD2025 (published 30 Oct 2025) superseded IMD2019 and uses different LSOA
boundaries (2021 Census geography, 33,755 areas) to IMD2019 (2011 Census
geography, 32,844 areas). This script can pull either vintage but does NOT
decide which one the site should standardise on -- that's James's call.
Do not silently mix the two across pages.

Output:
    data/raw/imd/2025/File_<n>_<name>.xlsx
    data/raw/imd/2019/... (if requested)
"""

import re
from pathlib import Path

import requests

HEADERS = {"User-Agent": "howsickarewe.com data pipeline (contact: James Tyson)"}
OUT_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw" / "imd"

RELEASE_PAGES = {
    "2025": "https://www.gov.uk/government/statistics/english-indices-of-deprivation-2025",
    "2019": "https://www.gov.uk/government/statistics/english-indices-of-deprivation-2019",
}


def check_reachable() -> bool:
    try:
        r = requests.get(RELEASE_PAGES["2025"], headers=HEADERS, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False


def fetch_vintage(vintage: str) -> dict:
    if vintage not in RELEASE_PAGES:
        raise ValueError(f"Unknown IMD vintage '{vintage}', expected one of {list(RELEASE_PAGES)}")

    out_dir = OUT_ROOT / vintage
    out_dir.mkdir(parents=True, exist_ok=True)

    r = requests.get(RELEASE_PAGES[vintage], headers=HEADERS, timeout=20)
    r.raise_for_status()

    links = sorted(set(re.findall(
        r'href="(https://assets\.publishing\.service\.gov\.uk/media/[^"]*\.(?:xlsx|ods|csv))"',
        r.text,
    )))
    saved = []
    for link in links:
        resp = requests.get(link, headers=HEADERS, timeout=60)
        if resp.status_code != 200:
            continue
        fname = link.rsplit("/", 1)[-1]
        (out_dir / fname).write_bytes(resp.content)
        saved.append(fname)

    print(f"IMD {vintage}: wrote {len(saved)} files to {out_dir}")
    return {"status": "ok", "vintage": vintage, "files": saved}


def run(vintages: list[str] = None) -> dict:
    vintages = vintages or ["2025"]  # default to current; add "2019" explicitly if needed for continuity
    if not check_reachable():
        return {"status": "unreachable"}
    return {v: fetch_vintage(v) for v in vintages}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
