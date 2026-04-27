"""
main.py
───────
Entry point for the ThreatSense-AI real-time surveillance system.

Usage:
    python main.py                           # webcam (default)
    python main.py --source rtsp://...       # RTSP stream
    python main.py --source video.mp4        # video file
    python main.py --person-conf 0.5 --weapon-conf 0.4
"""

from __future__ import annotations

import sys
import os
import argparse

# Ensure project root is in python path for module imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.pipeline import SurveillancePipeline

try:
    from backend.database import init_db
except Exception:
    init_db = None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ThreatSense-AI — real-time weapon surveillance",
    )
    p.add_argument(
        "--source",
        default="0",
        help="Video source: webcam index (0), file path, or RTSP URL "
             "(default: 0)",
    )
    p.add_argument(
        "--person-conf",
        type=float,
        default=0.4,
        help="Person detection confidence threshold (default: 0.4)",
    )
    p.add_argument(
        "--weapon-conf",
        type=float,
        default=0.3,
        help="Weapon detection confidence threshold (default: 0.3)",
    )
    p.add_argument(
        "--person-model",
        default="yolov8m.pt",
        help="Path to the person detector model (default: yolov8m.pt)",
    )
    p.add_argument(
        "--weapon-model",
        default="models/weapon_detector.pt",
        help="Path to the weapon detector model "
             "(default: models/weapon_detector.pt)",
    )
    p.add_argument(
        "--armed-threshold",
        type=float,
        default=0.65,
        help="Min weapon confidence to label person as armed (default: 0.65)",
    )
    p.add_argument(
        "--device",
        default=None,
        help="Inference device: GPU index (0), 'cpu', or None for auto (default: None)",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="Run without cv2.imshow (default: False)",
    )
    p.add_argument(
        "--cpu-optimized",
        action="store_true",
        help="Optimize for CPU: use Nano models, lower resolution, and frame skipping",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if init_db is not None:
        init_db()

    # Allow bare integer for webcam index
    source = int(args.source) if args.source.isdigit() else args.source

    # CPU Optimization Overrides
    person_model = args.person_model
    imgsz = 416       # Default to 416 for better FPS (was 640)
    weapon_skip = 5   # Default skip weapons every 5 frames
    risk_skip = 3     # Default skip risk engine every 3 frames
    
    if args.cpu_optimized:
        print("[main] CPU optimization active: Using Nano model and 320px resolution.")
        person_model = "yolov8m.pt"
        imgsz = 320                  # Even lower resolution for CPU
        weapon_skip = 8              # Check weapons every 8 frames
        risk_skip = 5                # Check risk every 5 frames
    
    pipeline = SurveillancePipeline(
        source=source,
        person_conf=args.person_conf,
        weapon_conf=args.weapon_conf,
        armed_threshold=args.armed_threshold,
        person_model=person_model,
        weapon_model=args.weapon_model,
        device=int(args.device) if args.device and args.device.isdigit() else args.device,
        headless=args.headless,
        weapon_skip=weapon_skip,
        risk_skip=risk_skip,
        imgsz=imgsz,
    )

    print("╔══════════════════════════════════════╗")
    print("║     ThreatSense-AI  •  Surveillance  ║")
    print("╚══════════════════════════════════════╝")
    pipeline.run()


if __name__ == "__main__":
    main()
