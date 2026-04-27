"""
evaluate_model.py
─────────────────
Evaluate the trained weapon detector on the test split and produce:
  - Per-class mAP50 / mAP50-95 / Precision / Recall
  - Confusion matrix plot
  - Precision-Recall curve per class
  - Sample detection images (random from test set)
  - JSON summary saved to docs/evaluation_results.json

Usage:
    python scripts/evaluate_model.py
    python scripts/evaluate_model.py --model models/weapon_detector.pt --split test
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from datetime import datetime, timezone, timedelta

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IST = timezone(timedelta(hours=5, minutes=30))


def run_evaluation(model_path: Path, data_yaml: Path, split: str, output_dir: Path) -> dict:
    from ultralytics import YOLO

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  ThreatSense-AI — Model Evaluation")
    print(f"{'='*60}")
    print(f"  Model : {model_path}")
    print(f"  Data  : {data_yaml}")
    print(f"  Split : {split}")
    print(f"  Output: {output_dir}\n")

    model = YOLO(str(model_path))

    # ── Run validation ────────────────────────────────────────────────
    metrics = model.val(
        data=str(data_yaml),
        split=split,
        imgsz=640,
        conf=0.25,
        iou=0.5,
        plots=True,
        save_json=True,
        project=str(output_dir),
        name="eval",
        exist_ok=True,
        verbose=True,
    )

    class_names = model.names

    # ── Per-class breakdown ───────────────────────────────────────────
    results_per_class = {}
    try:
        maps   = metrics.box.maps          # mAP50-95 per class
        map50s = metrics.box.ap50          # mAP50 per class (if available)
        ps     = metrics.box.p             # precision per class
        rs     = metrics.box.r             # recall per class

        for i, name in class_names.items():
            if i < len(maps):
                results_per_class[name] = {
                    "mAP50-95":  round(float(maps[i]),  4),
                    "precision": round(float(ps[i]),    4) if i < len(ps)    else None,
                    "recall":    round(float(rs[i]),    4) if i < len(rs)    else None,
                }
    except Exception as e:
        print(f"[warn] Could not extract per-class metrics: {e}")

    summary = {
        "evaluated_at":     datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        "model":            str(model_path.name),
        "dataset":          str(data_yaml),
        "split":            split,
        "classes":          list(class_names.values()),
        "overall": {
            "mAP50":        round(float(metrics.box.map50),  4),
            "mAP50-95":     round(float(metrics.box.map),    4),
            "precision":    round(float(metrics.box.mp),     4),
            "recall":       round(float(metrics.box.mr),     4),
        },
        "per_class": results_per_class,
    }

    # ── Save JSON summary ─────────────────────────────────────────────
    docs_dir = PROJECT_ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)
    json_path = docs_dir / "evaluation_results.json"
    json_path.write_text(json.dumps(summary, indent=2))
    print(f"\n[OK] Summary saved to {json_path}")

    # ── Sample detections ─────────────────────────────────────────────
    _save_sample_detections(model, data_yaml, output_dir, n=9)

    # ── Print summary table ───────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Overall Results")
    print(f"{'='*60}")
    for k, v in summary["overall"].items():
        print(f"  {k:15s}: {v:.4f}")

    if results_per_class:
        print(f"\n{'='*60}")
        print(f"  Per-Class Results")
        print(f"{'='*60}")
        print(f"  {'Class':15s} {'mAP50-95':>10s} {'Precision':>10s} {'Recall':>10s}")
        for cls, vals in results_per_class.items():
            mp  = f"{vals['mAP50-95']:.4f}"
            p   = f"{vals['precision']:.4f}" if vals["precision"] is not None else "  —  "
            r   = f"{vals['recall']:.4f}"    if vals["recall"]    is not None else "  —  "
            print(f"  {cls:15s} {mp:>10s} {p:>10s} {r:>10s}")

    print(f"\n  Plots saved to: {output_dir / 'eval'}")
    print(f"{'='*60}\n")

    return summary


def _save_sample_detections(model, data_yaml, output_dir: Path, n: int = 9):
    """Run inference on N random test images and save an image grid."""
    import yaml

    try:
        cfg = yaml.safe_load(Path(data_yaml).read_text())
        data_root = Path(data_yaml).parent
        test_img_dir = data_root / cfg.get("test", "test/images")
        if not test_img_dir.exists():
            return

        images = list(test_img_dir.glob("*.jpg")) + list(test_img_dir.glob("*.png"))
        if not images:
            return

        samples = random.sample(images, min(n, len(images)))
        drawn   = []

        for img_path in samples:
            frame  = cv2.imread(str(img_path))
            if frame is None:
                continue
            results = model.predict(str(img_path), conf=0.40, verbose=False)
            annotated = results[0].plot()
            annotated = cv2.resize(annotated, (320, 240))
            drawn.append(annotated)

        if not drawn:
            return

        cols = 3
        rows = (len(drawn) + cols - 1) // cols
        while len(drawn) < rows * cols:
            drawn.append(np.zeros((240, 320, 3), dtype=np.uint8))

        grid_rows = [np.hstack(drawn[i*cols:(i+1)*cols]) for i in range(rows)]
        grid = np.vstack(grid_rows)

        out_path = output_dir / "sample_detections.jpg"
        cv2.imwrite(str(out_path), grid)
        print(f"[OK] Sample detections saved to {out_path}")

    except Exception as e:
        print(f"[warn] Could not generate sample detections: {e}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate ThreatSense-AI weapon detector.")
    parser.add_argument("--model",  default=str(PROJECT_ROOT / "models" / "weapon_detector.pt"))
    parser.add_argument("--data",   default=str(PROJECT_ROOT / "datasets" / "weapon_merged" / "data.yaml"))
    parser.add_argument("--split",  default="test")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "docs" / "evaluation"))
    args = parser.parse_args()

    model_path = Path(args.model)
    data_yaml  = Path(args.data)
    output_dir = Path(args.output)

    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")
    if not data_yaml.exists():
        raise FileNotFoundError(f"Dataset config not found: {data_yaml}\n"
                                "Run scripts/merge_weapon_classes.py first.")

    run_evaluation(model_path, data_yaml, args.split, output_dir)


if __name__ == "__main__":
    main()
