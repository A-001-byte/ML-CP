import re
from pathlib import Path

path = Path('core/pipeline.py')
content = path.read_text('utf-8')

# Extract inner loop body
match = re.search(r'( {20}# ── 1\. Person detection \+ tracking ─────────────────.*?)( {20}# ── 10\. Stream \+ display ────────────────────────────\n {20}stream_manager\.update_frame\(frame\)\n {20}self\._frame_count \+= 1\n)', content, re.DOTALL)
if not match:
    print('Inner loop body not found')
    exit(1)

inner_body_raw = match.group(1)
# Unindent by 4 spaces (since it was at 20, now we want it at 16, under `for _ in range(30):` which is at 12)
inner_body = '\n'.join(line[4:] if line.startswith('    ') else line for line in inner_body_raw.split('\n'))

new_block = '''        from pathlib import Path
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
''' + inner_body + '''
                stream_manager.update_frame(frame)
                self._frame_count += 1
                time.sleep(0.033)

            if incident_recorder is not None:
                if hasattr(incident_recorder, "flush_all"):
                    incident_recorder.flush_all()
            return
'''

insert_target = 'is_file_source = isinstance(self.source, str) and os.path.isfile(self.source)'
if insert_target not in content:
    print('Insert target not found')
    exit(1)

new_content = content.replace(insert_target, insert_target + '\n' + new_block)
path.write_text(new_content, 'utf-8')
print('Success')
