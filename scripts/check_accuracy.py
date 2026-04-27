import sys
import os
import cv2
from ultralytics import YOLO
import argparse

def main():
    parser = argparse.ArgumentParser(description="ThreatSense-AI Model Accuracy Check")
    parser.add_argument("--source", type=str, required=True, help="Path to image or video file")
    parser.add_argument("--person-model", type=str, default="yolov8m.pt")
    parser.add_argument("--weapon-model", type=str, default="models/weapon_detector.pt")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    args = parser.parse_args()

    if not os.path.exists(args.source):
        print(f"❌ Error: Source '{args.source}' not found.")
        sys.exit(1)

    print("--- Accuracy Check ---")
    print(f"Source: {args.source}")
    
    # Load models
    print("Loading models...")
    try:
        p_model = YOLO(args.person_model)
        w_model = YOLO(args.weapon_model)
        print("✅ Models loaded successfully.")
    except Exception as e:
        print(f"❌ Failed to load models: {e}")
        sys.exit(1)

    # Run inference
    print("Running inference...")
    results_p = p_model.predict(source=args.source, conf=args.conf, save=True)
    results_w = w_model.predict(source=args.source, conf=args.conf, save=True)

    print("\n--- Detection Results ---")
    
    # Count persons
    person_count = 0
    for r in results_p:
        person_count += len(r.boxes)
    print(f"Persons detected: {person_count}")

    # Count weapons
    weapon_count = 0
    weapons_found = []
    for r in results_w:
        for box in r.boxes:
            cls_id = int(box.cls[0])
            cls_name = w_model.names.get(cls_id, str(cls_id))
            conf = float(box.conf[0])
            weapons_found.append(f"{cls_name} ({conf:.2f})")
            weapon_count += 1
    
    print(f"Weapons detected: {weapon_count}")
    if weapons_found:
        print(f"Classes: {', '.join(weapons_found)}")

    print("\n✅ Inference complete.")
    print(f"Annotated images saved to: runs/detect/predict/")
    print("You can open those images to visually verify the accuracy.")

if __name__ == "__main__":
    main()
