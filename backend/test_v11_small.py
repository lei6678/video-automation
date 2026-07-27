"""小规模测试：3句 6轨 v11 草稿"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))

from services.jianying_v11_service import (
    export_jianying_draft_v11, _load_template, _decrypt_file
)
from services.llm_service import split_into_short_sentences
from services.video_service import get_audio_duration

TASK_DIR = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6"

# Load 3 sentences
with open(os.path.join(TASK_DIR, "rewritten.txt"), "r", encoding="utf-8") as f:
    raw = f.read()
full_text = ""
for line in raw.strip().split("\n")[:3]:
    if not line.strip():
        continue
    parts = line.split("\t", 1)
    full_text += parts[1] if len(parts) > 1 else parts[0]
sentences = split_into_short_sentences(full_text, max_chars=80, min_chars=30)[:3]

# 3 durations
seg_dir = os.path.join(TASK_DIR, "segments")
seg_files = sorted([f for f in os.listdir(seg_dir) if f.endswith(".mp3") and f.startswith("seg_")])[:3]
durs = [get_audio_duration(os.path.join(seg_dir, sf)) for sf in seg_files]
seg_durations_us = [d * 1_000_000 for d in durs]

# 3 images
img_dir = os.path.join(TASK_DIR, "images")
img_files = sorted([f for f in os.listdir(img_dir) if f.endswith(".png") and f.startswith("seg_")])[:3]
image_paths = [os.path.join(img_dir, f).replace("\\", "/") for f in img_files]

audio_path = os.path.join(TASK_DIR, "final_audio.mp3")
if not os.path.exists(audio_path):
    audio_path = os.path.join(TASK_DIR, "final_tts.mp3")
audio_path = audio_path.replace("\\", "/")

print(f"Test: {len(sentences)} sentences, {sum(durs):.1f}s")

draft_dir = export_jianying_draft_v11(
    sentences=sentences,
    image_paths=image_paths,
    audio_path=audio_path,
    seg_durations_us=seg_durations_us,
    draft_name="Test6T_Small",
    upper_title="Test Title Line",
    lower_title_1="- Test Slogan -",
    lower_title_2="AI Generated | For Education Only",
)

# Verify
dc = _decrypt_file(os.path.join(draft_dir, "draft_content.json"))
tracks = dc["tracks"]
print(f"\nGenerated: {os.path.basename(draft_dir)}")
for ti, t in enumerate(tracks):
    print(f"  track[{ti}]: type={t['type']}, {len(t['segments'])} segments")
print(f"  dc.id: {dc['id'][:20]}...")

# Check text materials content
for i, tm in enumerate(dc["materials"]["texts"]):
    ct = json.loads(tm["content"])
    print(f"  text[{i}]: '{ct['text'][:50]}'")
