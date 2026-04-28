"""
Test all footage files through the weapon detection pipeline and print a results table.
Usage: python scripts/test_footage.py
"""
import sys, os, time, cv2, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection.person_detector import PersonDetector
from detection.weapon_detector import WeaponDetector
from pathlib import Path

person_det = PersonDetector(model_path='yolov8m.pt', device='cuda:0', imgsz=416, half=True)
weapon_det = WeaponDetector()

FOOTAGE_DIR = Path('footage')
results = []

for video_path in sorted(FOOTAGE_DIR.glob('*.mp4')):
    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    person_frames = 0
    weapon_hits = []
    
    for i in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            break
        
        persons = person_det.detect(frame, conf=0.4)
        if persons:
            person_frames += 1
            for px1, py1, px2, py2, pconf in persons:
                # Try at lowered threshold 0.45 for real footage
                hits = weapon_det.detect_in_region(frame, (px1, py1, px2, py2), conf=0.45)
                for hit in hits:
                    weapon_hits.append({'frame': i, 'class': hit[5], 'conf': round(hit[4], 3)})
    
    cap.release()
    results.append({
        'file': video_path.name,
        'resolution': f'{w}x{h}',
        'duration_s': round(total_frames / fps, 1),
        'frames': total_frames,
        'person_detection_rate': f'{(person_frames/total_frames*100):.0f}%',
        'weapon_detections': len(weapon_hits),
        'weapon_hits': weapon_hits[:5]  # first 5
    })
    print(f'{video_path.name}: persons={person_frames}/{total_frames} frames, weapons={len(weapon_hits)}')

# Save results
Path('docs/footage_test_results.json').write_text(json.dumps(results, indent=2))
print('\nSaved to docs/footage_test_results.json')

# Print summary table
print(f'\n{"File":<25} {"Res":<12} {"Dur":>5} {"Person%":>8} {"Weapons":>8}')
print('-' * 65)
for r in results:
    print(f'{r["file"]:<25} {r["resolution"]:<12} {r["duration_s"]:>5}s {r["person_detection_rate"]:>8} {r["weapon_detections"]:>8}')
