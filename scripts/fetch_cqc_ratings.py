"""
fetch_cqc_ratings.py

CQC location ratings for GP practices - closes Domain 7 (Safety).

The bulk "care directory" file already in the data bank (fetch_cqc.py) is a
locations directory only - no ratings. Ratings require the Syndication API
with a subscription key (CQC_API_KEY), and only come back from a per-location
detail call - the list endpoint never includes them.

Two-step process:
  1. List every location under CQC's "GP Practices" inspection category
     (code P2, confirmed against a live record). This includes historic and
     deregistered practices, so the raw candidate count (~12,000) is roughly
     double the ~6,000-8,000 currently active GP practices in England.
  2. Fetch each candidate's full detail record, keep only those still
     actively Registered, and extract the overall rating plus the five
     key-question domain ratings (Safe, Effective, Caring, Responsive,
     Well-led). Safe is what actually serves Domain 7.

No CQC partner code is in use yet (see project notes - one may be requested
later as the tool develops further). Without one, requests are paced
conservatively (one every 0.5s) to stay clear of any throttle. A full run
takes roughly 1.5-2 hours - expected, not a fault.

If CQC restructure their category codes, or the active-practice count lands
far outside the expected range, this exits with REVIEW NEEDED rather than
silently committing bad data - same pattern as the other fetch scripts in
this pipeline.
"""

import csv
import io
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw" / "cqc_ratings"
DATA_ROOT.mkdir(parents=True, exist_ok=True)

API_BASE = "https://api.service.cqc.org.uk/public/v1"
API_KEY = os.environ.get("CQC_API_KEY")

if not API_KEY:
    sys.exit("REVIEW NEEDED: CQC_API_KEY environment variable is not set. "
              "Check the repository secret and the workflow's env: block for this step.")

HEADERS = {"Ocp-Apim-Subscription-Key": API_KEY}

# Confirmed live against a real GP practice record:
# "inspectionCategories": [{"code": "P2", "primary": "true", "name": "GP Practices"}]
GP_PRACTICE_CATEGORY_CODE = "P2"

REQUEST_DELAY_SECONDS = 0.5   # conservative pace - no partner code registered yet
MAX_RETRIES = 4

MIN_EXPECTED_ACTIVE_PRACTICES = 5000   # same expected range as the GP Patient Survey practice count
MAX_EXPECTED_ACTIVE_PRACTICES = 8000

KEY_QUESTIONS = ["Safe", "Effective", "Caring", "Responsive", "Well-led"]


def get_with_retry(url, params=None):
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 502, 503, 504):
            wait = REQUEST_DELAY_SECONDS * (2 ** attempt)
            print(f"  {resp.status_code} on {url} - retrying in {wait:.1f}s (attempt {attempt})")
            time.sleep(wait)
            continue
        sys.exit(f"REVIEW NEEDED: unexpected {resp.status_code} from {url}: {resp.text[:300]}")
    sys.exit(f"REVIEW NEEDED: {url} failed after {MAX_RETRIES} retries.")


def list_gp_practice_ids():
    ids = []
    page = 1
    per_page = 500
    while True:
        data = get_with_retry(f"{API_BASE}/locations", params={
            "page": page, "perPage": per_page,
            "primaryInspectionCategoryCode": GP_PRACTICE_CATEGORY_CODE,
        })
        ids.extend(loc["locationId"] for loc in data.get("locations", []))
        print(f"  Listed page {page}/{data.get('totalPages')} - {len(ids)} candidate IDs so far")
        if page >= data.get("totalPages", page):
            break
        page += 1
        time.sleep(REQUEST_DELAY_SECONDS)
    return ids


def extract_ratings(detail):
    current = detail.get("currentRatings") or {}
    overall = current.get("overall") or {}
    key_questions = {kq["name"]: kq.get("rating") for kq in overall.get("keyQuestionRatings", [])}

    row = {
        "locationId": detail.get("locationId"),
        "odsCode": detail.get("odsCode"),
        "name": detail.get("name"),
        "region": detail.get("region"),
        "localAuthority": detail.get("localAuthority"),
        "postalCode": detail.get("postalCode"),
        "onspdIcbCode": detail.get("onspdIcbCode"),
        "onspdIcbName": detail.get("onspdIcbName"),
        "registrationStatus": detail.get("registrationStatus"),
        "overallRating": overall.get("rating"),
        "overallReportDate": overall.get("reportDate"),
    }
    for q in KEY_QUESTIONS:
        row[f"{q.lower()}Rating"] = key_questions.get(q)
    return row


def main():
    print("Listing GP Practice candidates (CQC category P2)...")
    candidate_ids = list_gp_practice_ids()
    print(f"Total candidates: {len(candidate_ids)} (includes deregistered/historic practices - filtered below)")

    rows = []
    deregistered_count = 0
    for i, location_id in enumerate(candidate_ids, start=1):
        detail = get_with_retry(f"{API_BASE}/locations/{location_id}")
        if detail.get("registrationStatus") != "Registered":
            deregistered_count += 1
            time.sleep(REQUEST_DELAY_SECONDS)
            continue
        rows.append(extract_ratings(detail))
        if i % 250 == 0:
            print(f"  Processed {i}/{len(candidate_ids)} ({len(rows)} active so far)")
        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Active GP practices: {len(rows)} (excluded {deregistered_count} deregistered/closed)")

    if not (MIN_EXPECTED_ACTIVE_PRACTICES <= len(rows) <= MAX_EXPECTED_ACTIVE_PRACTICES):
        sys.exit(f"REVIEW NEEDED: {len(rows)} active GP practices found - expected roughly "
                  f"{MIN_EXPECTED_ACTIVE_PRACTICES}-{MAX_EXPECTED_ACTIVE_PRACTICES}. CQC's category "
                  f"coding or registration statuses may have changed - check before proceeding.")

    fieldnames = list(rows[0].keys()) if rows else []
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = DATA_ROOT / f"CQC-ratings-{timestamp}.csv"
    out_path.write_text(output.getvalue(), encoding="utf-8")
    print(f"Saved: {out_path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
