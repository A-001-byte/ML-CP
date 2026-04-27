"""
train_weapon_detector.py
────────────────────────
YOLOv8m training script for weapon detection using the merged dataset.

Optimised for real-world surveillance weapon detection with:
  • 640 px input  (2× faster than 960 while maintaining accuracy)
  • AdamW + cosine LR schedule
  • Aggressive augmentation (HSV, scale, mosaic, randaugment) for real-world robustness
  • Early stopping (patience = 20 epochs on val mAP)
  • Mixed-precision (AMP) training

After training, copy the best weights to your models/ directory:
    cp runs/detect/weapon_training/weights/best.pt models/weapon_detector.pt

Usage:
    python training/train_weapon_detector.py
    python training/train_weapon_detector.py --epochs 200 --batch 8
    python training/train_weapon_detector.py --device cpu
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from ultralytics import YOLO

# ── Paths ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_YAML    = PROJECT_ROOT / "datasets" / "weapon_merged" / "data.yaml"
SAVE_DIR     = PROJECT_ROOT / "runs" / "detect" / "weapon_training"

# ── Training ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Train YOLOv8m weapon detection model.")
    parser.add_argument(
        "--device", type=str, default="0",
        help="Training device: '0' for GPU 0, 'cpu', or 'auto' (default: '0').",
    )
    parser.add_argument(
        "--epochs", type=int, default=150,
        help="Max epochs — early stopping kicks in at patience=20 (default: 150).",
    )
    parser.add_argument(
        "--batch", type=int, default=16,
        help="Batch size — reduce to 8 if GPU runs out of memory (default: 16).",
    )
    parser.add_argument(
        "--imgsz", type=int, default=640,
        help="Input image size (default: 640).",
    )
    args = parser.parse_args()

    if not DATA_YAML.exists():
        sys.exit(
            f"\n❌  Dataset config not found: {DATA_YAML}\n"
            "    Run the merge script first:\n"
            "        python scripts/merge_weapon_classes.py\n"
        )

    print(f"\n{'═' * 60}")
    print(f"  YOLOv8m Weapon Detector Training")
    print(f"{'═' * 60}")
    print(f"  Dataset : {DATA_YAML}")
    print(f"  Device  : {args.device}")
    print(f"  Epochs  : {args.epochs}  (early-stop patience=20)")
    print(f"  Batch   : {args.batch}")
    print(f"  Image   : {args.imgsz}px")
    print(f"  Output  : {SAVE_DIR}")
    print(f"{'═' * 60}\n")

    model = YOLO("yolov8m.pt")
    device_arg = int(args.device) if args.device.isdigit() else args.device

    model.train(
        data    = str(DATA_YAML),
        imgsz   = args.imgsz,
        epochs  = args.epochs,
        batch   = args.batch,
        device  = device_arg,
        workers = 4,
        amp     = True,

        # ── Optimizer ────────────────────────────────────────────────
        optimizer     = "AdamW",
        lr0           = 0.001,
        lrf           = 0.01,      # final LR = lr0 * lrf
        weight_decay  = 0.0005,
        warmup_epochs = 3,
        cos_lr        = True,      # cosine annealing schedule

        # ── Early stopping ───────────────────────────────────────────
        patience = 20,
        cache    = "disk",

        # ── Augmentation ─────────────────────────────────────────────
        # Tuned for real-world surveillance: variable lighting, motion
        # partial occlusion, different distances/angles, variable lighting.
        hsv_h     = 0.015,  # hue jitter
        hsv_s     = 0.7,    # saturation jitter
        hsv_v     = 0.4,    # brightness jitter
        degrees   = 10,     # rotation ±10°
        translate = 0.1,    # translation
        scale     = 0.5,    # scale variance (simulates near/far subjects)
        fliplr    = 0.5,    # horizontal flip
        mosaic    = 1.0,    # mosaic augmentation (4-image composite)
        mixup     = 0.1,    # blend two images — adds appearance diversity
        auto_augment = "randaugment",  # applies random policy incl. blur/noise

        project  = str(SAVE_DIR.parent),
        name     = SAVE_DIR.name,
        exist_ok = True,
        verbose  = True,
    )

    best_weights = SAVE_DIR / "weights" / "best.pt"
    print(f"\n{'═' * 60}")
    print(f"  ✅  Training complete")
    print(f"{'═' * 60}")
    print(f"  Best weights : {best_weights}")
    print(f"\n  Next steps:")
    print(f"    1. Check val mAP in {SAVE_DIR / 'results.csv'}")
    print(f"    2. Copy best.pt:")
    print(f"       copy \"{best_weights}\" models\\weapon_detector.pt")
    print(f"    3. Update DEFAULT_MODEL in detection/weapon_detector.py if needed")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    main()
