"""
fetch_all.py

Runs every fetcher in this repo in one pass -- the five sources reachable
from most environments (CVDPREVENT, Fingertips, CQC, NHS England bulk, IMD)
and the two that specifically need to run from GitHub's infrastructure
(OpenPrescribing, NHS Digital, both of which reject the Claude sandbox's
outbound requests with a Cloudflare bot-challenge).

All seven write into data/raw/<source>/ and this then builds one manifest
covering the whole bank, so there's a single file that answers "what do we
actually have, and when was it last refreshed" without opening every folder.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_cvdprevent
import fetch_fingertips
import fetch_cqc
import fetch_nhs_england_bulk
import fetch_imd
import fetch_openprescribing
import fetch_nhs_digital

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw"
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "BANK-MANIFEST.json"


def build_manifest(fetch_results: dict) -> dict:
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fetch_status": {k: v.get("status", "see nested detail") for k, v in fetch_results.items()},
        "sources": {},
    }
    if DATA_ROOT.exists():
        for source_dir in sorted(DATA_ROOT.iterdir()):
            if not source_dir.is_dir():
                continue
            files = [
                {"path": str(f.relative_to(DATA_ROOT)), "bytes": f.stat().st_size}
                for f in source_dir.rglob("*") if f.is_file()
            ]
            manifest["sources"][source_dir.name] = {
                "file_count": len(files),
                "total_bytes": sum(f["bytes"] for f in files),
                "files": files,
            }
    return manifest


def run():
    results = {}

    print("=== CVDPREVENT ===")
    results["cvdprevent"] = fetch_cvdprevent.run()

    print("\n=== Fingertips ===")
    results["fingertips"] = fetch_fingertips.run()

    print("\n=== CQC ===")
    results["cqc"] = fetch_cqc.run()

    print("\n=== NHS England bulk (RTT, FFT) ===")
    results["nhs_england_bulk"] = fetch_nhs_england_bulk.run()

    print("\n=== IMD ===")
    results["imd"] = fetch_imd.run()

    print("\n=== OpenPrescribing ===")
    results["openprescribing"] = fetch_openprescribing.run()

    print("\n=== NHS Digital (National Diabetes Audit) ===")
    results["nhs_digital"] = fetch_nhs_digital.run()

    manifest = build_manifest(results)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("\n=== Run complete ===")
    for name, s in manifest["sources"].items():
        print(f"{name}: {s['file_count']} files, {s['total_bytes']:,} bytes")

    return manifest


if __name__ == "__main__":
    run()
