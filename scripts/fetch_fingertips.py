"""
fetch_fingertips.py

Pulls OHID Fingertips indicator data via the official `fingertips_py` client.
Confirmed working Sept 2026 -- see AREA_TYPE_IDS below for the geography IDs
Fingertips actually uses (these are NOT self-evident from the site UI and are
easy to get wrong; verified live against the API, do not guess new ones without
checking get_area_types_as_dict() first).

Note: Fingertips does not carry an ICB-level "PCN" split the way CVDPREVENT
does -- its finest routine geography for most indicators is ICB (221) or
Sub-ICB/former-CCG (66). Practice-level Fingertips coverage is patchy; check
per-indicator before assuming it exists.

Output: one CSV per indicator, at every geography level requested, written to
    data/raw/fingertips/<indicator_id>_<area_type_name>.csv
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import fingertips_py as ftp

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "fingertips"

# Verified via ftp.get_area_types_as_dict() -- re-check if indicators start
# returning empty, Fingertips does occasionally retire/replace area type IDs.
AREA_TYPE_IDS = {
    "england": 15,
    "region": 223,       # "NHS regions"
    "icb": 221,           # "ICBs, former STPs"
    "sub_icb": 66,        # "Sub-ICB, former CCGs" -- for OpenPrescribing joins
    "local_authority": 502,  # Upper-tier local authority (2023) -- check before use,
                              # Fingertips renumbers LA geographies most often
}

# A starting indicator set spanning the domains identified as Fingertips'
# strongest fit (Burden of Disease, Prevention, Outcomes, Inequality) --
# see NHS-DATA-SOURCE-LIBRARY.md.
#
# IMPORTANT: every ID below was verified against the live metadata (see
# find_indicators() below) by matching it back to its actual returned
# "Indicator" name -- do not add an ID to this dict from memory or from a
# guess. A wrong ID does not error, it just silently returns a different
# indicator's data under the label you gave it. Verify first.
STARTER_INDICATORS = {
    93722: "Under 75 mortality rate from cardiovascular disease considered preventable",
    93255: "Mortality from cardiovascular disease",
    241: "Diabetes: QOF prevalence",
    91547: "Smoking prevalence in adults (aged 15+) - current smokers (QOF)",
    93881: "Obesity prevalence in adults (self-reported height/weight)",
    93015: "Percentage of physically inactive adults",
    93465: "Alcohol-related conditions: admission episodes",
    90362: "Healthy life expectancy at birth",
}


def find_indicators(keyword: str, limit: int = 15) -> None:
    """Search the real Fingertips indicator catalogue by keyword and print
    (ID, name) pairs. Run this and read the output before adding anything
    to STARTER_INDICATORS -- never guess an ID.

        python3 fetch_fingertips.py --find "heart failure"
    """
    df = ftp.get_metadata_for_all_indicators_from_csv()
    matches = df[df["Indicator"].str.contains(keyword, case=False, regex=False, na=False)]
    if matches.empty:
        print(f"No indicators matched '{keyword}'. Try a shorter or different term.")
        return
    for _, row in matches.head(limit).iterrows():
        print(f"{int(row['Indicator ID'])} | {row['Indicator']}")


def check_reachable() -> bool:
    try:
        areas = ftp.get_area_types_as_dict()
        return bool(areas)
    except Exception:
        return False


def run(indicators: dict[int, str] = None, area_levels: dict[str, int] = None) -> dict:
    indicators = indicators or STARTER_INDICATORS
    area_levels = area_levels or {
        "england": AREA_TYPE_IDS["england"],
        "region": AREA_TYPE_IDS["region"],
        "icb": AREA_TYPE_IDS["icb"],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = {
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": [],
        "failed": [],
    }

    for indicator_id, label in indicators.items():
        for level_name, area_type_id in area_levels.items():
            try:
                df = ftp.get_all_data_for_indicators(
                    indicators=[indicator_id],
                    area_type_id=area_type_id,
                    parent_area_type_id=AREA_TYPE_IDS["england"],
                )
                if df is None or df.empty:
                    manifest["failed"].append({
                        "indicator_id": indicator_id, "level": level_name,
                        "note": "empty -- indicator may not publish at this geography",
                    })
                    continue
                fname = f"{indicator_id}_{level_name}.csv"
                df.to_csv(OUT_DIR / fname, index=False)
                manifest["files"].append(fname)
            except Exception as e:
                manifest["failed"].append({
                    "indicator_id": indicator_id, "level": level_name, "error": str(e),
                })

    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Fingertips: wrote {len(manifest['files'])} files, "
          f"{len(manifest['failed'])} failed/empty, to {OUT_DIR}")
    return manifest


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--find":
        find_indicators(sys.argv[2])
    else:
        run()
