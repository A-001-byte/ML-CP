"""
merge_weapon_classes.py
-----------------------
Merges one or more YOLO weapon-detection datasets (each with their own class
schema) into a single unified dataset at datasets/weapon_merged/.

Unified 4-class scheme:
    0: gun          ← pistol, rifle, shot-gun, submachine-gun, firearm, Gunmen…
    1: knife        ← knife, blade, sword, knife_attacker…
    2: blunt_weapon ← bat, club, baton, blunt_object…
    3: person       ← person (kept as background/context class)

----------------------------------------------------------------
HOW TO ADD MORE DATASETS
----------------------------------------------------------------
1. Download from Roboflow in **YOLOv8 format**.
   Recommended extra datasets:
     * "Weapon Detection" by weapon-detect-buxhm  (diverse real-world guns)
     * "Pistol Detection" by various authors       (pistol close-ups)
     * "Knife Detection"  by various authors       (blade diversity)
     * "Security Weapon" by any                   (surveillance context)

2. Extract to  datasets/<folder-name>/

3. Add a new entry to DATASET_CONFIGS below.
   - "name"        : human-readable label (just for logging)
   - "path"        : Path to the dataset root
   - "splits"      : list of split folder names to look for (tries each in order)
   - "class_remap" : dict mapping original class index -> unified index
                     Use None to DROP a class entirely (row is skipped)
----------------------------------------------------------------

Usage:
    python scripts/merge_weapon_classes.py              # full run
    python scripts/merge_weapon_classes.py --dry-run    # preview only
    python scripts/merge_weapon_classes.py --list       # list configured datasets
"""

from __future__ import annotations

import argparse
import shutil
import sys
import textwrap
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# -- Configuration ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DST_DATASET  = PROJECT_ROOT / "datasets" / "weapon_merged"

# Unified output class scheme.
# blunt_weapon is excluded until a proper dataset is added — the existing
# dataset has only 5 blunt_object annotations which is insufficient to train.
NEW_CLASSES = ["gun", "knife", "person"]

# Canonical split names we will write to
CANONICAL_SPLITS = ["train", "valid", "test"]

# Map each dataset's split folder names -> canonical split name
SPLIT_ALIASES: Dict[str, str] = {
    "train": "train",
    "valid": "valid",
    "val":   "valid",
    "test":  "test",
}


@dataclass
class DatasetConfig:
    name: str
    path: Path
    # Original class names ordered by index (index = position in list)
    original_classes: List[str]
    # original_index -> unified_index  (None = drop the annotation row)
    class_remap: Dict[int, Optional[int]]
    # Split folder names to look for inside this dataset
    splits: List[str] = field(default_factory=lambda: ["train", "valid", "val", "test"])


# -- Dataset registry ---------------------------------------------------------

DATASET_CONFIGS: List[DatasetConfig] = [

    # -- 1. Existing Roboflow dataset (already in repo) -----------------------
    DatasetConfig(
        name = "yolo-weapon-detection (Roboflow)",
        path = PROJECT_ROOT / "datasets" / "yolo-weapon-detection",
        original_classes = [
            "Gunmen",           # 0
            "Rifle",            # 1
            "blunt_object",     # 2
            "knife",            # 3
            "knife_attacker",   # 4
            "person",           # 5
            "pistol",           # 6
            "shot-gun",         # 7
            "submachine-gun",   # 8
        ],
        class_remap = {
            0: 0,      # Gunmen         -> gun
            1: 0,      # Rifle          -> gun
            2: None,   # blunt_object   -> DROPPED (only 5 samples)
            3: 1,      # knife          -> knife
            4: 1,      # knife_attacker -> knife
            5: 2,      # person         -> person
            6: 0,      # pistol         -> gun
            7: 0,      # shot-gun       -> gun
            8: 0,      # submachine-gun -> gun
        },
    ),

    # -- 2. Weapon Detection v2 (edi-izdgg workspace, extracted to datasets/ root) ---
    # NOTE: This dataset was extracted directly into datasets/ so its split dirs
    # sit at datasets/train, datasets/valid, datasets/test (not in a subfolder).
    DatasetConfig(
        name = "yolo-weapon-detection-v2 (edi-izdgg/Roboflow)",
        path = PROJECT_ROOT / "datasets",
        original_classes = [
            "Gunmen",           # 0
            "Rifle",            # 1
            "blunt object",     # 2  (note: space, not underscore)
            "knife",            # 3
            "knife_attacker",   # 4
            "person",           # 5
            "pistol",           # 6
            "shot-gun",         # 7
            "submachine-gun",   # 8
        ],
        class_remap = {
            0: 0,      # Gunmen         -> gun
            1: 0,      # Rifle          -> gun
            2: None,   # blunt object   -> DROPPED (only 1 sample)
            3: 1,      # knife          -> knife
            4: 1,      # knife_attacker -> knife
            5: 2,      # person         -> person
            6: 0,      # pistol         -> gun
            7: 0,      # shot-gun       -> gun
            8: 0,      # submachine-gun -> gun
        },
        splits = ["train", "valid", "test"],
    ),

    # -- 3. Pistol Close-up (edi-izdgg/pistol, 374 train images) ----------------
    DatasetConfig(
        name = "Pistol Close-up (Roboflow)",
        path = PROJECT_ROOT / "datasets" / "Pistol Close-up",
        original_classes = ["Pistol"],
        class_remap = {
            0: 0,   # Pistol -> gun
        },
        splits = ["train", "valid", "val", "test"],
    ),

    # -- 4. Knife Detection YOLOv8 (edi-izdgg/knife, 2562 train images) ---------
    DatasetConfig(
        name = "Knife Detection YOLOv8 (Roboflow)",
        path = PROJECT_ROOT / "datasets" / "knife detection yolov8",
        original_classes = ["knife"],
        class_remap = {
            0: 1,   # knife -> knife
        },
        splits = ["train", "valid", "val", "test"],
    ),
]


# -- Helpers ------------------------------------------------------------------

def remap_label_line(line: str, cfg: DatasetConfig) -> Optional[str]:
    """Remap one YOLO annotation line using cfg.class_remap. Returns None to drop."""
    line = line.strip()
    if not line:
        return None

    parts = line.split()
    old_cls = int(parts[0])

    if old_cls < 0 or old_cls >= len(cfg.original_classes):
        print(f"    [!]  class id {old_cls} out of bounds in {cfg.name}, dropping line")
        return None

    new_cls = cfg.class_remap.get(old_cls)
    if new_cls is None:
        return None  # intentionally dropped class

    parts[0] = str(new_cls)
    return " ".join(parts)


def resolve_split_dir(dataset_path: Path, cfg_splits: List[str], subdir: str) -> Optional[Path]:
    """
    Find <images|labels> dir for a split.  Tries each alias in cfg_splits,
    returns the first existing one, or None.
    """
    for split_name in cfg_splits:
        candidate = dataset_path / split_name / subdir
        if candidate.exists():
            return candidate, split_name
    return None, None


def write_data_yaml(dst: Path) -> None:
    content = textwrap.dedent(f"""\
        train: train/images
        val:   valid/images
        test:  test/images

        nc: {len(NEW_CLASSES)}
        names: {NEW_CLASSES}
    """)
    dst.write_text(content, encoding="utf-8")


# -- Core logic ---------------------------------------------------------------

def process_dataset(dry_run: bool = False) -> None:

    available = [cfg for cfg in DATASET_CONFIGS if cfg.path.exists()]
    missing   = [cfg for cfg in DATASET_CONFIGS if not cfg.path.exists()]

    if missing:
        print("\n[!]  The following configured datasets were NOT found and will be skipped:")
        for cfg in missing:
            print(f"   * {cfg.name}  ->  {cfg.path}")

    if not available:
        sys.exit(
            "\n[X]  No datasets found.  Download at least one dataset and place it in\n"
            "    datasets/<name>/ then re-run this script.\n"
        )

    print(f"\n{'=' * 62}")
    print(f"  Merging {len(available)} dataset(s) -> {DST_DATASET.name}/")
    print(f"  Output classes: {NEW_CLASSES}")
    print(f"{'=' * 62}")

    grand_old_counter: Counter[str] = Counter()
    grand_new_counter: Counter[str] = Counter()
    grand_images = 0
    grand_labels = 0

    # Counters per canonical split — for duplication avoidance via filename
    # prefix: <dataset_index>_<original_name>
    dst_image_counts: Dict[str, int] = {s: 0 for s in CANONICAL_SPLITS}

    for ds_idx, cfg in enumerate(available):
        print(f"\n  [{ds_idx + 1}/{len(available)}] {cfg.name}")
        print(f"  {'-' * 58}")

        for canonical in CANONICAL_SPLITS:
            # Resolve image and label directories for this split
            img_dir, found_split = resolve_split_dir(cfg.path, cfg.splits, "images")
            lbl_dir, _           = resolve_split_dir(cfg.path, cfg.splits, "labels")

            # Look for this specific canonical split (or its alias)
            # Try matching the canonical name and common aliases
            img_dir = lbl_dir = None
            for split_name in cfg.splits:
                if SPLIT_ALIASES.get(split_name) == canonical:
                    img_candidate = cfg.path / split_name / "images"
                    lbl_candidate = cfg.path / split_name / "labels"
                    if img_candidate.exists():
                        img_dir = img_candidate
                        lbl_dir = lbl_candidate if lbl_candidate.exists() else None
                        break

            if img_dir is None:
                continue

            image_files = sorted(f for f in img_dir.iterdir() if f.is_file())
            if not image_files:
                continue

            print(f"    {canonical:8s} — {len(image_files)} images")
            grand_images += len(image_files)

            dst_img_dir = DST_DATASET / canonical / "images"
            dst_lbl_dir = DST_DATASET / canonical / "labels"

            if not dry_run:
                dst_img_dir.mkdir(parents=True, exist_ok=True)
                dst_lbl_dir.mkdir(parents=True, exist_ok=True)

            for img in image_files:
                # Prefix with dataset index to avoid filename collisions
                new_name = f"ds{ds_idx:02d}_{img.name}"
                if not dry_run:
                    shutil.copy2(img, dst_img_dir / new_name)

            if lbl_dir is None:
                continue

            label_files = sorted(
                f for f in lbl_dir.iterdir()
                if f.is_file() and f.suffix == ".txt"
            )
            grand_labels += len(label_files)

            for lbl in label_files:
                lines = lbl.read_text(encoding="utf-8").strip().splitlines()
                remapped: list[str] = []

                for raw_line in lines:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue

                    old_cls = int(raw_line.split()[0])
                    if 0 <= old_cls < len(cfg.original_classes):
                        grand_old_counter[cfg.original_classes[old_cls]] += 1

                    new_line = remap_label_line(raw_line, cfg)
                    if new_line is not None:
                        new_cls = int(new_line.split()[0])
                        if 0 <= new_cls < len(NEW_CLASSES):
                            grand_new_counter[NEW_CLASSES[new_cls]] += 1
                        remapped.append(new_line)

                if not dry_run:
                    new_lbl_name = f"ds{ds_idx:02d}_{lbl.name}"
                    (dst_lbl_dir / new_lbl_name).write_text(
                        "\n".join(remapped) + ("\n" if remapped else ""),
                        encoding="utf-8",
                    )

    # -- Write data.yaml ------------------------------------------------------
    if not dry_run:
        write_data_yaml(DST_DATASET / "data.yaml")

    # -- Summary --------------------------------------------------------------
    print(f"\n{'=' * 62}")
    print(f"  {'[DRY RUN] ' if dry_run else ''}Final Summary")
    print(f"{'=' * 62}")
    print(f"  Total images processed : {grand_images:,}")
    print(f"  Total label files      : {grand_labels:,}")

    print("\n  Original class distribution (all datasets combined):")
    for name, count in sorted(grand_old_counter.items(), key=lambda x: -x[1]):
        print(f"    {name:25s}  {count:>7,}")

    print("\n  Unified class distribution:")
    for name in NEW_CLASSES:
        count = grand_new_counter.get(name, 0)
        print(f"    {name:25s}  {count:>7,}")

    if not dry_run:
        print(f"\n  [OK]  Merged dataset saved to: {DST_DATASET}")
        print(f"  data.yaml: {DST_DATASET / 'data.yaml'}")
        print(f"\n  Next step:")
        print(f"    python training/train_weapon_detector.py")
    else:
        print("\n  [i]  Dry run — no files written.")


# -- CLI ----------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge multiple weapon-detection datasets into a unified YOLO dataset."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview remapping without writing any files.")
    parser.add_argument("--list", action="store_true",
                        help="List all configured datasets and exit.")
    args = parser.parse_args()

    if args.list:
        print(f"\nConfigured datasets ({len(DATASET_CONFIGS)} total):\n")
        for i, cfg in enumerate(DATASET_CONFIGS):
            status = "[OK] found" if cfg.path.exists() else "[X] not found"
            print(f"  [{i+1}] {cfg.name}")
            print(f"       {cfg.path}  [{status}]")
            print(f"       Classes: {cfg.original_classes}")
            print()
        return

    process_dataset(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
