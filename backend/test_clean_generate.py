"""生成全新的干净草稿，验证 service 是否在旧目录累积了垃圾"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from services.jianying_v11_service import export_jianying_draft_v11
from services.llm_service import split_into_short_sentences
from services.video_service import get_audio_duration

TASK_DIR = os.path.join(os.path.dirname(__file__), "data", "tasks", "6")

with open(os.path.join(TASK_DIR, "rewritten.txt"), "r", encoding="utf-8") as f:
    raw = f.read()
full_text = ""
for line in raw.strip().split("\n"):
    if not line.strip():
        continue
    parts = line.split("\t", 1)
    full_text += parts[1] if len(parts) > 1 else parts[0]
sentences = split_into_short_sentences(full_text, max_chars=80, min_chars=30)

segments_dir = os.path.join(TASK_DIR, "segments")
seg_files = sorted([f for f in os.listdir(segments_dir) if f.endswith(".mp3") and f.startswith("seg_")])
tts_durs = [get_audio_duration(os.path.join(segments_dir, sf)) for sf in seg_files]
seg_durations_us = [d * 1_000_000 for d in tts_durs]

images_dir = os.path.join(TASK_DIR, "images")
img_files = sorted([f for f in os.listdir(images_dir) if f.endswith(".png") and f.startswith("seg_")])
img_map = {}
for f in img_files:
    seg_idx = int(f.replace("seg_", "").replace(".png", ""))
    img_map[seg_idx] = os.path.join(images_dir, f).replace("\\", "/")
image_paths = [img_map.get(i, img_map.get(0, "")) for i in range(len(sentences))]

audio_path = os.path.join(TASK_DIR, "final_audio.mp3")
if not os.path.exists(audio_path):
    audio_path = os.path.join(TASK_DIR, "final_tts.mp3")
audio_path = audio_path.replace("\\", "/")

draft_name = "FreshV11_" + str(int(time.time()))
print(f"Generating {draft_name}...")
draft_dir = export_jianying_draft_v11(
    sentences=sentences,
    image_paths=image_paths,
    audio_path=audio_path,
    seg_durations_us=seg_durations_us,
    draft_name=draft_name,
)
print(f"Done: {draft_dir}")
