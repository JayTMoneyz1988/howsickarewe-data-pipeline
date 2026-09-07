"""
fetch_openprescribing.py -- runs inside the GitHub Action, NOT in the Claude
sandbox (openprescribing.net returns a Cloudflare bot-challenge from this
sandbox's outbound IPs; a normal GitHub-hosted runner is not challenged the
same way, but re-verify this on the Action's first run -- Cloudflare rules
change without notice, and if this starts failing there, that's the sign).

Pulls prescribing spend by BNF chapter for both live conditions:
  - BNF chapter 2  (cardiovascular)
  - BNF chapter 6.1 (drugs used in diabetes)

at ICB level (the level the site's cost chapter and comparison tool use) and
sub-ICB level (needed to join against CVDPREVENT/NDA geographies, per the
handover briefs).

API pattern confirmed in HANDOVER-BRIEF.md section 8:
  https://openprescribing.net/api/1.0/spending_by_org/?org_type=<type>&code=<bnf_code>&date=<YYYY-MM-01>&format=csv

Output: data/raw/openprescribing/<bnf_code>_<org_type>_<YYYY-MM>.csv
"""

import time
from datetime import date, timedelta
from pathlib import Path

import requests

BASE = "https://openprescribing.net/api/1.0/spending_by_org/"
HEADERS = {"User-Agent": "howsickarewe.com data pipeline (contact: James Tyson)"}
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "openprescribing"

BNF_CHAPTERS = {
    "0102": "cardiovascular (BNF ch 2)",   # NOTE: verify exact chapter code format --
    "0601": "diabetes (BNF ch 6.1)",        # OpenPrescribing uses its own zero-padded
}                                            # BNF codes; confirm against
                                             # https://openprescribing.net/bnf/ before
                                             # the first real run, don't assume these
                                             # two are exactly right.

ORG_TYPES = ["icb", "ccg"]  # "ccg" endpoint is OpenPrescribing's legacy name for sub-ICB


def latest_available_month() -> str:
    # OpenPrescribing publishes with roughly a 2-month lag.
    d = date.today().replace(day=1) - timedelta(days=62)
    return d.replace(day=1).isoformat()


def check_reachable() -> bool:
    try:
        r = requests.get("https://openprescribing.net", headers=HEADERS, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    month = latest_available_month()
    results = {"month_requested": month, "files": [], "failed": []}

    if not check_reachable():
        results["status"] = "unreachable -- if this is the sandbox, expected; if this is the Action, investigate"
        print(results["status"])
        return results

    for bnf_code, label in BNF_CHAPTERS.items():
        for org_type in ORG_TYPES:
            params = {"org_type": org_type, "code": bnf_code, "date": month, "format": "csv"}
            r = requests.get(BASE, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 200 and r.text.strip():
                fname = f"{bnf_code}_{org_type}_{month[:7]}.csv"
                (OUT_DIR / fname).write_text(r.text, encoding="utf-8")
                results["files"].append(fname)
            else:
                results["failed"].append({
                    "bnf_code": bnf_code, "org_type": org_type,
                    "status_code": r.status_code,
                })
            time.sleep(1)  # OpenPrescribing asks API users to be polite; don't hammer it

    print(f"OpenPrescribing: wrote {len(results['files'])} files, {len(results['failed'])} failed")
    return results


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
