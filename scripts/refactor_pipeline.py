import re
from pathlib import Path

path = Path('core/pipeline.py')
content = path.read_text('utf-8')

# Find the inner loop body
match = re.search(r'# ── 1\. Person detection \+ tracking ─────────────────(.*?)# ── 10\. Stream \+ display ────────────────────────────', content, re.DOTALL)
if not match:
    print('Inner loop body not found')
    exit(1)

inner_body = match.group(0)

# Build the new block
new_block = '''
        IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
        is_image_source = isinstance(self.source, str) and Path(self.source).suffix.lower() in IMAGE_EXTS

        if is_image_source:
            frame = cv2.imread(str(self.source))
            if frame is None:
                print(f"[pipeline] Cannot read image: {self.source}")
                return
            print(f"[pipeline] Image source: {self.source} ({frame.shape[1]}x{frame.shape[0]})")
            for _ in range(30):  # simulate 30 frames for WeaponVerifier accumulation
                t0 = time.perf_counter()
'''

for line in inner_body.split('\n'):
    new_block += '        ' + line + '\n'

new_block += '''                stream_manager.update_frame(frame)
                self._frame_count += 1
                time.sleep(0.033)

            if incident_recorder is not None:
                if hasattr(incident_recorder, "flush_all"):
                    incident_recorder.flush_all()
            return
'''

# Find where to insert it: after `is_file_source = isinstance(self.source, str) and os.path.isfile(self.source)`
insert_target = 'is_file_source = isinstance(self.source, str) and os.path.isfile(self.source)'
if insert_target not in content:
    print('Insert target not found')
    exit(1)

new_content = content.replace(insert_target, insert_target + '\n' + new_block)
path.write_text(new_content, 'utf-8')
print('Success')
