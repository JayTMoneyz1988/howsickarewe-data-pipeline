"""
fetch_nhs_digital.py -- runs inside the GitHub Action, NOT in the Claude
sandbox (digital.nhs.uk returns a Cloudflare bot-challenge from this
sandbox's outbound IPs). Re-verify on the Action's first run.

Scrapes the National Diabetes Audit publication index for the most recent
release, then downloads every xlsx/csv resource linked from that release's
own page -- same "discover the current link, don't hardcode it" approach as
scripts/fetch_nhs_england_bulk.py in the main pipeline, because NHS Digital
publication URLs are unpredictable slugs (e.g. ".../nda-core-e2-22-23/"),
not a clean date pattern.

Index page confirmed via search (Sept 2026):
  https://digital.nhs.uk/data-and-information/publications/statistical/national-diabetes-audit

Output: data/raw/nda/<release_slug>/<filename>.xlsx
"""

import re
from pathlib import Path

import requests

INDEX_URL = "https://digital.nhs.uk/data-and-information/publications/statistical/national-diabetes-audit"
HEADERS = {"User-Agent": "howsickarewe.com data pipeline (contact: James Tyson)"}
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "nda"


def check_reachable() -> bool:
    try:
        r = requests.get(INDEX_URL, headers=HEADERS, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False


def find_latest_release_url() -> str | None:
    r = requests.get(INDEX_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    # "Past publications" entries link to individual release pages under the
    # same path prefix. The first ICB/PCN/GP-practice quarterly or core
    # report link is what we want -- skip anything that's clearly a
    # methodology note or feedback survey rather than a data release.
    candidates = re.findall(
        r'href="(/data-and-information/publications/statistical/national-diabetes-audit/[^"]+)"',
        r.text,
    )
    skip_terms = ["feedback", "methodology", "business-rules", "impact-of-audit-period"]
    for path in candidates:
        if not any(term in path.lower() for term in skip_terms):
            return "https://digital.nhs.uk" + path
    return None


def run() -> dict:
    if not check_reachable():
        status = "unreachable -- if this is the sandbox, expected; if this is the Action, investigate"
        print(status)
        return {"status": status}

    release_url = find_latest_release_url()
    if not release_url:
        return {"status": "could not find a release link on the index page -- check manually"}

    r = requests.get(release_url, headers=HEADERS, timeout=20)
    r.raise_for_status()

    file_links = sorted(set(re.findall(r'href="([^"]+\.(?:xlsx|csv))"', r.text)))
    # Links on digital.nhs.uk resource pages are sometimes relative -- normalise.
    file_links = [
        link if link.startswith("http") else "https://digital.nhs.uk" + link
        for link in file_links
    ]

    slug = release_url.rstrip("/").rsplit("/", 1)[-1]
    out_dir = OUT_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for link in file_links:
        resp = requests.get(link, headers=HEADERS, timeout=120)  # NDA workbooks run to ~10-30MB
        if resp.status_code != 200:
            continue
        fname = link.rsplit("/", 1)[-1]
        (out_dir / fname).write_bytes(resp.content)
        saved.append(fname)

    print(f"NDA: wrote {len(saved)} files from {release_url}")
    return {"status": "ok", "release_url": release_url, "files": saved}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
