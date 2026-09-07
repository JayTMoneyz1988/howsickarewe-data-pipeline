"""
fetch_cvdprevent.py

Pulls CVDPREVENT audit data directly from the public API.

Confirmed reachable without authentication as of Sept 2026 (this was previously
documented as blocked from the Claude sandbox - that has changed; re-check
periodically by running check_reachable() before relying on this in a
scheduled job).

Endpoints used (per CVDPREVENT API, no key required):
    /timePeriod
    /area/systemLevel?timePeriodID=<id>
    /indicator/list?timePeriodID=<id>&systemLevelID=<id>
    /indicator/<indicatorID>/rawDataCSV?timePeriodID=<id>&systemLevelID=<id>
    /indicator/<indicatorID>/metaDataXLSX
    /dataAvailability?timePeriodID=<id>&systemLevelID=<id>

Output: one CSV per indicator per system level, written to
    data/raw/cvdprevent/<time_period_id>/<indicator_code>_<level_name>.csv
plus a manifest.json recording what was pulled and when.
"""

import csv
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://api.cvdprevent.nhs.uk"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "cvdprevent"

SYSTEM_LEVELS = {
    "england": 1,
    "region": 6,
    "icb": 7,
    "sub_icb": 8,   # only needed to join OpenPrescribing cost data
    "pcn": 4,
    "practice": 5,  # IsVisible may be "N" -- treat empty/error as suppression, not a bug
}

# The cascade indicator set agreed in HANDOVER-BRIEF-ADDENDUM-CVD.md section 3.
# IDs are stable per the addendum; codes are included for readability / sanity
# checking against /indicator/list output.
CASCADE_INDICATORS = {
    # Stage 1 - who isn't being found
    11: "CVDP001HYP", 20: "CVDP005HYP", 1: "CVDP001AF", 8: "CVDP001CKD",
    13: "CVDP002CKD", 12: "CVDP001CVD", 24: "CVDP001SMOK",
    # Stage 2 - who isn't being treated
    2: "CVDP002HYP", 3: "CVDP003HYP", 32: "CVDP007HYP", 7: "CVDP002AF",
    51: "CVDP005AF", 22: "CVDP006CHOL", 34: "CVDP009CHOL", 29: "CVDP006CKD",
    26: "CVDP002SMOK",
    # Stage 3 - who's being treated too much
    21: "CVDP006HYP",
}

HEADERS = {"User-Agent": "howsickarewe.com data pipeline (contact: James Tyson)"}


def check_reachable() -> bool:
    """Quick reachability probe. Run this before trusting the rest of the script."""
    try:
        r = requests.get(f"{BASE}/timePeriod", headers=HEADERS, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False


def get_latest_time_period_id() -> tuple[int, str]:
    """Return (TimePeriodID, TimePeriodName) for the most recent 'Standard' period.

    Do not hardcode TimePeriodID 33 going forward -- the addendum notes this
    was 'To March 2026' at the time it was written, but the audit adds a new
    period roughly quarterly, so the ID will keep changing.
    """
    r = requests.get(f"{BASE}/timePeriod", headers=HEADERS, timeout=15)
    r.raise_for_status()
    periods = r.json()["timePeriodList"]
    # Filter to Standard indicator type periods, take the highest ID (most recent)
    standard = [p for p in periods if p.get("IndicatorTypeName", "").lower() == "standard"]
    if not standard:
        standard = periods
    latest = max(standard, key=lambda p: p["TimePeriodID"])
    return latest["TimePeriodID"], latest.get("TimePeriodName", "")


def get_data_availability(time_period_id: int, system_level_id: int) -> dict:
    """Fetch the audit's own statement of what exists and why not, per indicator.

    Use this to distinguish 'suppressed for disclosure control' from 'no data'
    before writing any 'the data cannot answer this' copy -- see
    HANDOVER-BRIEF-ADDENDUM-CVD.md section 6.
    """
    r = requests.get(
        f"{BASE}/dataAvailability",
        params={"timePeriodID": time_period_id, "systemLevelID": system_level_id},
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def fetch_indicator_csv(indicator_id: int, time_period_id: int, system_level_id: int) -> str | None:
    r = requests.get(
        f"{BASE}/indicator/{indicator_id}/rawDataCSV",
        params={"timePeriodID": time_period_id, "systemLevelID": system_level_id},
        headers=HEADERS,
        timeout=30,
    )
    if r.status_code != 200 or not r.text.strip():
        return None
    return r.text


def run(indicators: dict[int, str] = None, levels: dict[str, int] = None) -> dict:
    indicators = indicators or CASCADE_INDICATORS
    levels = levels or {"england": 1, "region": 6, "icb": 7}

    if not check_reachable():
        print("CVDPREVENT API not reachable right now. Stopping -- do not fall "
              "back to fabricated or cached-looking data.", file=sys.stderr)
        return {"status": "unreachable"}

    time_period_id, time_period_name = get_latest_time_period_id()
    period_dir = OUT_DIR / str(time_period_id)
    period_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "time_period_id": time_period_id,
        "time_period_name": time_period_name,
        "files": [],
        "missing": [],
    }

    for level_name, level_id in levels.items():
        availability = get_data_availability(time_period_id, level_id)
        for indicator_id, code in indicators.items():
            csv_text = fetch_indicator_csv(indicator_id, time_period_id, level_id)
            fname = f"{code}_{level_name}.csv"
            if csv_text:
                (period_dir / fname).write_text(csv_text, encoding="utf-8")
                manifest["files"].append(fname)
            else:
                manifest["missing"].append({
                    "indicator_code": code,
                    "level": level_name,
                    "note": "empty response -- check dataAvailability for suppression reason",
                })
            time.sleep(0.3)  # be a polite client

    (period_dir / "dataAvailability.json").write_text(
        json.dumps(availability, indent=2), encoding="utf-8"
    )
    (period_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"CVDPREVENT: wrote {len(manifest['files'])} files, "
          f"{len(manifest['missing'])} missing, to {period_dir}")
    return manifest


if __name__ == "__main__":
    run()
