"""Task 6 自动发布到剪映草稿箱"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from services.video_service import auto_publish_to_jianying
from services.llm_service import split_into_short_sentences

TASK_DIR = os.path.join(os.path.dirname(__file__), "data", "tasks", "6")

# 收集图片路径（与 recompose 同源）
with open(os.path.join(TASK_DIR, "rewritten.txt"), "r", encoding="utf-8") as f:
    raw = f.read()
full_text = ""
for line in raw.strip().split("\n"):
    if not line.strip():
        continue
    parts = line.split("\t", 1)
    full_text += parts[1] if len(parts) > 1 else parts[0]
sentences = split_into_short_sentences(full_text, max_chars=80, min_chars=30)

images_dir = os.path.join(TASK_DIR, "images")
img_files = sorted([f for f in os.listdir(images_dir) if f.endswith(".png") and f.startswith("seg_")])
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

audio_path = os.path.join(TASK_DIR, "final_audio.mp3")
if not os.path.exists(audio_path):
    audio_path = os.path.join(TASK_DIR, "final_tts.mp3")

auto_publish_to_jianying(
    task_id=6,
    task_dir=TASK_DIR,
    image_paths=image_paths,
    audio_path=audio_path,
    draft_name="Task6-她主演作品国际获奖却被诬陷送入疯人院",
)
