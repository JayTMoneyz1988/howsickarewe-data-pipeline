"""
update_manifest.py

Scans data/raw/ and rewrites data/BANK-MANIFEST.json. Split out from
fetch_all.py so it can run once, at the end of the SECOND job in the
two-job workflow (after both the cloud job and the self-hosted job have
committed their part) -- that way the manifest reflects everything, not
just whichever job happened to run last.

Explicitly flags any source folder that's empty or missing, rather than
letting a silent zero blend into an otherwise-successful-looking run --
that gap (a workflow reporting "Success" while two sources quietly wrote
nothing) is exactly what caused confusion the first time this pipeline ran
for real, so it gets a named warning now instead of just a file count.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw"
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "BANK-MANIFEST.json"

EXPECTED_SOURCES = [
    "cvdprevent", "fingertips", "cqc", "rtt", "fft", "imd",
    "openprescribing", "nda",
]


def run() -> dict:
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {},
        "warnings": [],
    }

    for source in EXPECTED_SOURCES:
        source_dir = DATA_ROOT / source
        if not source_dir.exists():
            manifest["sources"][source] = {"file_count": 0, "total_bytes": 0, "files": []}
            manifest["warnings"].append(f"{source}: folder does not exist -- this source has never run successfully")
            continue

        files = [
            {"path": str(f.relative_to(DATA_ROOT)), "bytes": f.stat().st_size}
            for f in source_dir.rglob("*") if f.is_file()
        ]
        manifest["sources"][source] = {
            "file_count": len(files),
            "total_bytes": sum(f["bytes"] for f in files),
            "files": files,
        }
        if not files:
            manifest["warnings"].append(f"{source}: folder exists but is empty -- check the most recent run's log for this source")

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Manifest updated: {MANIFEST_PATH}")
    for source, s in manifest["sources"].items():
        flag = " <-- WARNING" if s["file_count"] == 0 else ""
        print(f"  {source}: {s['file_count']} files, {s['total_bytes']:,} bytes{flag}")
    if manifest["warnings"]:
        print("\nWarnings:")
        for w in manifest["warnings"]:
            print(f"  - {w}")

    return manifest


if __name__ == "__main__":
    run()
