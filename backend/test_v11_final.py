"""测试：用 6轨正式版 v11 service 生成 Task6 草稿"""
import os, sys, json

sys.path.insert(0, os.path.dirname(__file__))

from services.jianying_v11_service import export_jianying_draft_v11
from services.llm_service import split_into_short_sentences
from services.video_service import get_audio_duration

TASK_DIR = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6"

# Load rewritten text
with open(os.path.join(TASK_DIR, "rewritten.txt"), "r", encoding="utf-8") as f:
    raw = f.read()

full_text = ""
for line in raw.strip().split("\n"):
    if not line.strip():
        continue
    parts = line.split("\t", 1)
    full_text += parts[1] if len(parts) > 1 else parts[0]

sentences = split_into_short_sentences(full_text, max_chars=80, min_chars=30)
print(f"Sentences: {len(sentences)}")

# Load segment durations
segments_dir = os.path.join(TASK_DIR, "segments")
seg_files = sorted([f for f in os.listdir(segments_dir)
                    if f.endswith(".mp3") and f.startswith("seg_")])
tts_durs = [get_audio_duration(os.path.join(segments_dir, sf)) for sf in seg_files]
seg_durations_us = [d * 1_000_000 for d in tts_durs]
total_dur = sum(tts_durs)
print(f"Total duration: {total_dur:.1f}s ({len(seg_files)} segments)")

# Load image paths
images_dir = os.path.join(TASK_DIR, "images")
img_files = sorted([f for f in os.listdir(images_dir)
                    if f.endswith(".png") and f.startswith("seg_")])
img_map = {}
for f in img_files:
    seg_idx = int(f.replace("seg_", "").replace(".png", ""))
    img_map[seg_idx] = os.path.join(images_dir, f).replace("\\", "/")

image_paths = []
for i in range(len(sentences)):
    if i in img_map:
        image_paths.append(img_map[i])
    else:
        image_paths.append(image_paths[-1] if image_paths else None)

print(f"Images: {len(image_paths)}")

# Audio path
audio_path = os.path.join(TASK_DIR, "final_audio.mp3")
if not os.path.exists(audio_path):
    audio_path = os.path.join(TASK_DIR, "final_tts.mp3")
audio_path = audio_path.replace("\\", "/")
print(f"Audio: {audio_path}")

# Titles
import sqlite3
db = sqlite3.connect(os.path.join(os.path.dirname(__file__), "data", "app.db"))
db.row_factory = sqlite3.Row
task = db.execute("SELECT video_title FROM tasks WHERE id = 6").fetchone()
db.close()

video_title = task["video_title"] or ""

# Generate
print("\nGenerating 6-track v11 draft...")
draft_dir = export_jianying_draft_v11(
    sentences=sentences,
    image_paths=image_paths,
    audio_path=audio_path,
    seg_durations_us=seg_durations_us,
    draft_name="Task6_6T",
    upper_title=video_title,
    lower_title_1="- 品读传奇人生 -",
    lower_title_2="图片由AI生成与网络下载  科普视频 无不良引导",
)

print(f"\nDone! Draft folder: {draft_dir}")
print("Close + reopen 剪映 to test.")
