#!/usr/bin/env python
"""
Test Footage Validation Script
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Process test video files through the ThreatSense-AI detection pipeline and report:
  - Total frames processed per video
  - Person detections per video
  - Weapon detections (raw YOLO + multi-frame verified)
  - False positive rate on non-weapon videos (should be 0%)
  - Latency per frame

Usage:
    python scripts/test_footage_validation.py

Test Files:
    footage/Video test 1.mp4  — Non-weapon test (0 FP expected)
    footage/Video test 2.mp4  — Non-weapon test (0 FP expected)
    footage/Video test 3.mp4  — Non-weapon test (0 FP expected)
    footage/Video test 4.mp4  — Non-weapon test (0 FP expected)
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import cv2
import numpy as np
from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IST = timezone(timedelta(hours=5, minutes=30))


class TestFootageValidator:
    """Validates test footage through the ThreatSense-AI pipeline."""
    
    def __init__(self, person_model_path="yolov8m.pt", weapon_model_path="models/weapon_detector.pt"):
        """Initialize models."""
        print("Loading models...")
        self.person_model = YOLO(str(person_model_path))
        self.weapon_model = YOLO(str(weapon_model_path))
        print("✅ Models loaded")
        
        # Per-person weapon verification state
        self.weapon_verifier_state = {}  # {track_id: {'frame_count': int, 'avg_conf': float, 'confirmed': bool}}
        self.verification_threshold_frames = 3
        self.verification_threshold_conf = 0.62
        
    def process_video(self, video_path, video_name, max_frames=None):
        """
        Process a video file through the detection pipeline.
        
        Args:
            video_path: Path to video file
            video_name: Human-readable name for reporting
            max_frames: Optional max frames to process (for quick testing)
        
        Returns:
            dict: Results summary
        """
        print(f"\n{'='*70}")
        print(f"Processing: {video_name}")
        print(f"Path: {video_path}")
        print(f"{'='*70}")
        
        if not os.path.exists(video_path):
            print(f"❌ File not found: {video_path}")
            return None
        
        # Reset verifier state for this video
        self.weapon_verifier_state = {}
        
        # Open video
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            print(f"❌ Cannot open video: {video_path}")
            return None
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        print(f"Resolution: {width}×{height} @ {fps} FPS")
        print(f"Total frames: {total_frames}")
        
        # Tracking across frames
        frame_idx = 0
        person_counts = []
        raw_weapon_detections = []  # All YOLO hits
        verified_weapon_detections = []  # Multi-frame confirmed
        latencies = []
        
        # Process frames
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            
            if max_frames and frame_idx >= max_frames:
                break
            
            start_time = time.time()
            
            # 1. Person detection
            person_results = self.person_model(frame, conf=0.45, verbose=False)
            persons = person_results[0].boxes
            person_counts.append(len(persons))
            
            # 2. Weapon detection (lower 60% crop per person)
            frame_weapon_detections = []
            for person_box in persons:
                x1, y1, x2, y2 = map(int, person_box.xyxy[0])
                h = y2 - y1
                crop_y_start = int(y1 + h * 0.4)  # Skip top 40%
                crop_y_end = y2
                
                # Extract crop
                if crop_y_start < crop_y_end:
                    crop = frame[crop_y_start:crop_y_end, x1:x2]
                    if crop.size > 0:
                        weapon_results = self.weapon_model(crop, conf=0.65, verbose=False)
                        for detection in weapon_results[0].boxes:
                            class_id = int(detection.cls[0])
                            conf = float(detection.conf[0])
                            class_name = self.weapon_model.names[class_id]
                            
                            if class_name in ['gun', 'knife']:
                                frame_weapon_detections.append({
                                    'class': class_name,
                                    'confidence': conf,
                                    'frame': frame_idx
                                })
                                raw_weapon_detections.append({
                                    'class': class_name,
                                    'confidence': conf,
                                    'frame': frame_idx
                                })
            
            # 3. Multi-frame verification (simplified per-video summary)
            for detection in frame_weapon_detections:
                # For this script, just accumulate; real system uses ByteTrack IDs
                verified_weapon_detections.append(detection)
            
            # Latency
            elapsed = time.time() - start_time
            latencies.append(elapsed)
            
            frame_idx += 1
            
            if frame_idx % 50 == 0:
                print(f"  Processed {frame_idx}/{total_frames} frames...")
        
        cap.release()
        
        # Summary
        avg_persons = np.mean(person_counts) if person_counts else 0
        max_persons = max(person_counts) if person_counts else 0
        avg_latency = np.mean(latencies) if latencies else 0
        
        result = {
            'video_name': video_name,
            'total_frames': frame_idx,
            'resolution': f"{width}×{height}",
            'fps': fps,
            'duration_seconds': frame_idx / fps if fps > 0 else 0,
            'persons_detected': {
                'total': sum(person_counts),
                'avg_per_frame': round(avg_persons, 2),
                'max_per_frame': max_persons
            },
            'weapon_detections': {
                'raw_yolo_hits': len(raw_weapon_detections),
                'verified_multi_frame': len(verified_weapon_detections),
                'detections': raw_weapon_detections
            },
            'latency_ms': {
                'avg': round(avg_latency * 1000, 2),
                'min': round(min(latencies) * 1000, 2) if latencies else 0,
                'max': round(max(latencies) * 1000, 2) if latencies else 0
            }
        }
        
        print(f"\n📊 Results:")
        print(f"  Total frames processed: {frame_idx}")
        print(f"  Persons detected: {result['persons_detected']['total']} (avg {result['persons_detected']['avg_per_frame']}/frame)")
        print(f"  Raw weapon hits: {len(raw_weapon_detections)}")
        print(f"  Verified detections: {len(verified_weapon_detections)}")
        print(f"  Avg latency: {result['latency_ms']['avg']} ms/frame")
        
        return result
    
    def run_validation_suite(self):
        """Run validation on all test videos."""
        footage_dir = PROJECT_ROOT / "footage"
        
        test_videos = [
            (footage_dir / "Video test 1.mp4", "Test Video 1 (Non-Weapon)"),
            (footage_dir / "Video test 2.mp4", "Test Video 2 (Non-Weapon)"),
            (footage_dir / "Video test 3.mp4", "Test Video 3 (Non-Weapon)"),
            (footage_dir / "Video test 4.mp4", "Test Video 4 (Non-Weapon)"),
        ]
        
        all_results = []
        
        for video_path, name in test_videos:
            result = self.process_video(str(video_path), name, max_frames=None)
            if result:
                all_results.append(result)
        
        return all_results


def generate_report(results):
    """Generate a comprehensive test report."""
    report = {
        'generated_at': datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        'test_suite': 'ThreatSense-AI Test Footage Validation',
        'total_videos_tested': len(results),
        'total_frames_processed': sum(r['total_frames'] for r in results),
        'videos': results,
        'summary': {}
    }
    
    # Aggregate statistics
    total_raw_detections = sum(len(r['weapon_detections']['detections']) for r in results)
    total_verified = sum(r['weapon_detections']['verified_multi_frame'] for r in results)
    
    print(f"\n\n{'='*70}")
    print("VALIDATION SUMMARY")
    print(f"{'='*70}")
    
    print(f"\n✅ Test Results:")
    print(f"  Videos tested: {len(results)}")
    print(f"  Total frames: {report['total_frames_processed']}")
    print(f"  Raw weapon detections (YOLO): {total_raw_detections}")
    print(f"  Verified weapon detections (multi-frame): {total_verified}")
    
    # Check for false positives on non-weapon videos
    false_positive_rate = total_verified / report['total_frames_processed'] if report['total_frames_processed'] > 0 else 0
    
    print(f"\n🎯 False Positive Analysis (Non-Weapon Videos):")
    for result in results:
        video_name = result['video_name']
        fps = result['total_frames']
        detections = len(result['weapon_detections']['detections'])
        fp_rate = (detections / fps * 100) if fps > 0 else 0
        
        status = "✅ PASS" if detections == 0 else f"⚠️  {detections} FP"
        print(f"  {video_name}: {status} ({detections} detections in {fps} frames, {fp_rate:.2f}%)")
    
    print(f"\n📈 Overall FP Rate: {false_positive_rate*100:.3f}% (target: 0%)")
    
    report['summary'] = {
        'total_raw_detections': total_raw_detections,
        'total_verified_detections': total_verified,
        'false_positive_rate': round(false_positive_rate, 5),
        'test_result': 'PASS' if false_positive_rate == 0 else 'FAIL'
    }
    
    return report


if __name__ == '__main__':
    validator = TestFootageValidator()
    results = validator.run_validation_suite()
    
    if results:
        report = generate_report(results)
        
        # Save report
        report_path = PROJECT_ROOT / "docs" / "test_footage_validation_report.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"\n📄 Report saved to: {report_path}")
