"""
Fetch GP Patient Survey (GPPS) data for howsickarewe.com.

Pulls four small files in full (national, region, ICS, PCN) and a slimmed-down
version of the practice-level file. The full practice-level file (~600 columns,
every survey question broken down by demographic) runs close to 100MB - right at
GitHub's hard per-file limit - so only a fixed set of columns is kept.

If NHS England renames a column, the practice count shifts sharply, or the file
grows past the safety ceilings below, this script exits with a non-zero status and
a REVIEW NEEDED message rather than silently committing bad or oversized data.
That failure shows as a red X in the GitHub Actions run.

Source: https://www.gp-patient.co.uk/surveysandreports
"""

import csv
import io
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw" / "gp_patient_survey"
DATA_ROOT.mkdir(parents=True, exist_ok=True)

# Update this each year when GPPS publishes new results (usually mid-year).
SURVEY_YEAR = 2026

BASE_URL = "https://www.gp-patient.co.uk/FileDownload/Download?fileRedirect="

FILE_PATHS = {
    "national": f"{SURVEY_YEAR}/survey-results/national-results/national-data-csv/GPPS_{SURVEY_YEAR}_National_data_(weighted)_(csv)_PUBLIC.csv",
    "region":   f"{SURVEY_YEAR}/survey-results/region-results/region-data-csv/GPPS_{SURVEY_YEAR}_Region_data_(weighted)_(csv)_PUBLIC.csv",
    "ics":      f"{SURVEY_YEAR}/survey-results/ics-results/ics-data-csv/GPPS_{SURVEY_YEAR}_ICS_data_(weighted)_(csv)_PUBLIC.csv",
    "pcn":      f"{SURVEY_YEAR}/survey-results/pcn-results/pcn-data-csv/GPPS_{SURVEY_YEAR}_PCN_data_(weighted)_(csv)_PUBLIC.csv",
    "practice": f"{SURVEY_YEAR}/survey-results/practice-results/practice-data-csv/GPPS_{SURVEY_YEAR}_Practice_data_(weighted)_(csv)_PUBLIC.csv",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (howsickarewe.com data pipeline)"}

GEOGRAPHY_COLUMNS = [
    "ad_practicecode", "ad_practicename",
    "ad_icscode", "ad_icsname", "ad_icscodeons",
    "ad_commissioningregioncode", "ad_commissioningregionname",
    "ad_pcncode", "ad_pcnname",
]
DENOMINATOR_COLUMNS = ["distributed", "received", "resprate", "popsize"]

# Headline metrics for the practice-level file - one indicator per site domain, not the
# full ~600-column question set. Each prefix pulls in every sub-column that question
# generates (counts, weighted %, base sizes, confidence intervals), because the number of
# answer options varies by question and hardcoding suffixes would break silently if NHS
# England adds or removes an answer option.
METRIC_PREFIXES = [
    "overallexp",          # Overall experience of GP practice
    "gpcontactoverall",    # Ease of contacting the practice
    "lastgpapptneeds",     # Needs met at last appointment
    "healthconfidence",    # Confidence managing own health
    "lastgpapptwait",      # Wait time for last appointment
    "lastgpapptlisten",    # Felt listened to by clinician
    "lastgpapptdecision",  # Involved in care decisions
    "healthltcondition",   # Long-term condition prevalence
    "pharmacyoverall",     # Overall pharmacy experience
]

MIN_EXPECTED_PRACTICES = 5000   # ~6,300 GP practices in England as of 2026 - guards against a wrong-level file
MAX_EXPECTED_PRACTICES = 8000
MAX_RAW_SIZE_BYTES = 99 * 1024 * 1024        # stop before filtering if the raw file is nearly at GitHub's 100MB hard limit
MAX_FILTERED_SIZE_BYTES = 40 * 1024 * 1024   # safety ceiling for the filtered file, well under the hard limit


def fetch(name, path):
    url = BASE_URL + urllib.parse.quote(path, safe="")
    print(f"Fetching {name}: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=180)
    resp.raise_for_status()
    print(f"  -> {len(resp.content):,} bytes")
    return resp.content


def save(content, filename):
    out_path = DATA_ROOT / filename
    out_path.write_bytes(content)
    print(f"Saved: {out_path} ({len(content):,} bytes)")


def filter_practice_file(raw_bytes):
    text = raw_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames
    if not header:
        sys.exit("REVIEW NEEDED: practice-level file has no header row. Fetch aborted - check the source file manually.")

    missing_core = [c for c in GEOGRAPHY_COLUMNS + DENOMINATOR_COLUMNS if c not in header]
    if missing_core:
        sys.exit(f"REVIEW NEEDED: expected column(s) missing from practice-level file: {missing_core}. "
                  f"NHS England may have renamed a column - check the source before proceeding.")

    keep_columns = list(GEOGRAPHY_COLUMNS) + list(DENOMINATOR_COLUMNS)
    for prefix in METRIC_PREFIXES:
        matched = [c for c in header if c == prefix or c.startswith(prefix + "_") or c.startswith(prefix + ".")]
        if not matched:
            sys.exit(f"REVIEW NEEDED: expected metric '{prefix}' not found in practice-level file header. "
                      f"NHS England may have renamed or dropped this question - check the source before proceeding.")
        keep_columns.extend(matched)

    rows = list(reader)
    row_count = len(rows)
    if not (MIN_EXPECTED_PRACTICES <= row_count <= MAX_EXPECTED_PRACTICES):
        sys.exit(f"REVIEW NEEDED: practice-level file has {row_count} rows - expected roughly "
                 f"{MIN_EXPECTED_PRACTICES}-{MAX_EXPECTED_PRACTICES}. This may be the wrong file "
                 f"(e.g. a different geography level under the practice URL), or NHS England's "
                 f"practice count has moved sharply. Check the source before proceeding.")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=keep_columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    filtered_bytes = output.getvalue().encode("utf-8")

    if len(filtered_bytes) > MAX_FILTERED_SIZE_BYTES:
        sys.exit(f"REVIEW NEEDED: filtered practice-level file is {len(filtered_bytes):,} bytes, "
                 f"over the {MAX_FILTERED_SIZE_BYTES:,} byte safety ceiling. The column list may "
                 f"need trimming further before this can be committed safely.")

    return filtered_bytes, row_count


def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for name in ("national", "region", "ics", "pcn"):
        content = fetch(name, FILE_PATHS[name])
        save(content, f"GPPS-{timestamp}-{name}.csv")

    raw_practice = fetch("practice", FILE_PATHS["practice"])
    if len(raw_practice) > MAX_RAW_SIZE_BYTES:
        sys.exit(f"REVIEW NEEDED: raw practice-level file is {len(raw_practice):,} bytes, "
                 f"approaching GitHub's 100MB hard limit even before filtering. NHS England has "
                 f"likely expanded the survey - check the source before proceeding.")

    filtered_bytes, row_count = filter_practice_file(raw_practice)
    save(filtered_bytes, f"GPPS-{timestamp}-practice-filtered.csv")
    print(f"Practice-level: {row_count} practices, {len(filtered_bytes):,} filtered bytes "
          f"(raw was {len(raw_practice):,} bytes)")


if __name__ == "__main__":
    main()
