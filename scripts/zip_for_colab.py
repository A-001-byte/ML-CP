"""
zip_for_colab.py
────────────────
Zips the weapon_merged dataset for upload to Google Drive.
Run this AFTER merge_weapon_classes.py has finished.

Usage:
    python scripts/zip_for_colab.py

Output:
    weapon_merged.zip  (in project root, ~1 GB)

Then upload weapon_merged.zip to the root of your Google Drive
and run the threatsense_train.ipynb notebook in Google Colab.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC  = PROJECT_ROOT / "datasets" / "weapon_merged"
DST  = PROJECT_ROOT / "weapon_merged.zip"

def main() -> None:
    if not SRC.exists():
        sys.exit(
            "\n[X] datasets/weapon_merged/ not found.\n"
            "    Run scripts/merge_weapon_classes.py first.\n"
        )

    # Count images for a sanity check
    total = sum(1 for _ in SRC.rglob("*.jpg")) + sum(1 for _ in SRC.rglob("*.png"))
    print(f"\nSource : {SRC}")
    print(f"Images : {total:,}")

    if DST.exists():
        print(f"\n[!] {DST.name} already exists — overwriting.")
        DST.unlink()

    print(f"\nZipping to {DST} ...")
    t0 = time.time()
    shutil.make_archive(
        base_name = str(PROJECT_ROOT / "weapon_merged"),
        format    = "zip",
        root_dir  = str(SRC.parent),
        base_dir  = SRC.name,
    )
    elapsed = time.time() - t0
    size_mb = DST.stat().st_size / 1_000_000

    print(f"\n[OK] Done in {elapsed:.0f}s")
    print(f"     File : {DST}")
    print(f"     Size : {size_mb:.0f} MB")
    print(f"\nNext steps:")
    print(f"  1. Upload {DST.name} to the root of your Google Drive")
    print(f"  2. Open threatsense_train.ipynb in Google Colab")
    print(f"  3. Set Runtime -> Change runtime type -> GPU (T4)")
    print(f"  4. Run all cells top to bottom")

if __name__ == "__main__":
    main()
