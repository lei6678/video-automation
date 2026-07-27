"""
生成 Task 6 的剪映 v11 格式草稿
基于 _DraftFolder_API测试 的模板结构
"""
import json
import os
import uuid

TASK_DIR = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6"
DRAFT_DIR = r"E:/360Downloads/JianyingPro Drafts/Task6_王人美"
JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
FONT_PATH = JY_DIR + "/Resources/Font/SystemFont/zh-hans.ttf"

# ---- 数据准备 ----
from services.llm_service import split_into_short_sentences
from services.video_service import get_audio_duration, split_into_word_groups

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
seg_files = sorted([f for f in os.listdir(segments_dir)
                    if f.endswith(".mp3") and f.startswith("seg_")])
tts_durs = [get_audio_duration(os.path.join(segments_dir, sf)) for sf in seg_files]
seg_durations = [d * 1_000_000 for d in tts_durs]  # microseconds
total_duration_us = sum(seg_durations)

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

audio_path = os.path.join(TASK_DIR, "final_audio.mp3")
if not os.path.exists(audio_path):
    audio_path = os.path.join(TASK_DIR, "final_tts.mp3")
audio_path = audio_path.replace("\\", "/")

print(f"Data: {len(sentences)} sentences, {len(image_paths)} images, total {total_duration_us/1e6:.1f}s")


# ---- 辅助函数 ----
def uid():
    return uuid.uuid4().hex


def make_platform():
    return {
        "os": "windows",
        "os_version": "10.0.22631",
        "app_id": 3704,
        "app_version": "5.9.0",
        "app_source": "lv",
        "device_id": "2de63f9f29a84cbbc3a9c121477cc107",
        "hard_disk_id": "fe856f843f7d53ab533fdf51af180f48",
        "mac_address": "8e4ee548c0d202307fcb4b0b97d8afdc",
    }


def make_last_modified_platform():
    p = make_platform()
    p["app_version"] = "11.0.0"
    return p


def make_text_style(text, font_size=5.0):
    """Build the content JSON string for a text material."""
    return json.dumps({
        "styles": [{
            "fill": {
                "alpha": 1.0,
                "content": {
                    "render_type": "solid",
                    "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}  # yellow
                }
            },
            "range": [0, len(text)],
            "size": font_size,
            "bold": True,
            "italic": False,
            "underline": False,
            "strokes": []
        }],
        "text": text
    }, ensure_ascii=False)


# ---- 构建素材库 ----
draft_id = str(uuid.uuid4()).upper()

video_materials = []
audio_materials = []
text_materials = []
canvas_materials = []
speed_materials = []
animation_materials = []
color_materials = []
sound_materials = []
loudness_materials = []
placeholder_materials = []
vocal_sep_materials = []

# 视频素材
video_mat_ids = []
for i, img_path in enumerate(image_paths):
    mid = uid()
    video_mat_ids.append(mid)
    fname = os.path.basename(img_path)
    video_materials.append({
        "id": mid,
        "type": "photo",
        "duration": int(seg_durations[i]),
        "path": img_path,
        "width": 1080,
        "height": 1920,
        "category_name": "local",
        "material_id": mid,
        "material_name": fname,
        "crop": {},
        "stable": {"time_range": {}},
        "matting": {"path": ""},
        "check_flag": 62978047,
        "video_algorithm": {"path": "", "story_video_modify_video_config": {}},
        "beauty_face_auto_preset": {},
        "video_mask_stroke": {"resource_id": "", "path": "", "type": ""},
        "video_mask_shadow": {"resource_id": "", "path": ""},
    })

# 音频素材
audio_mat_id = uid()
fname = os.path.basename(audio_path)
audio_materials.append({
    "id": audio_mat_id,
    "type": "extract_music",
    "name": fname,
    "duration": int(total_duration_us),
    "path": audio_path,
    "category_name": "local",
    "music_id": audio_mat_id,
    "resource_id": "",
    "check_flag": 3,
    "local_material_id": audio_mat_id,
    "similiar_music_info": {},
    "tts_benefit_info": {"benefit_type": "none"},
})

# 每段视频的辅助素材
for i in range(len(sentences)):
    canvas_materials.append({"id": uid(), "type": "canvas_color"})
    speed_materials.append({"id": uid(), "type": "speed"})
    animation_materials.append({
        "id": uid(),
        "type": "sticker_animation",
        "animations": []
    })
    color_materials.append({"id": uid()})
    sound_materials.append({"id": uid(), "type": "none"})
    loudness_materials.append({"id": uid()})
    placeholder_materials.append({"id": uid(), "type": "placeholder_info", "meta_type": "none"})
    vocal_sep_materials.append({"id": uid(), "type": "vocal_separation"})

# 字幕素材（每段字幕一个 text material）
text_mat_ids = []
time_cursor = 0.0
for i, text in enumerate(sentences):
    dur = seg_durations[i]
    if dur <= 0:
        continue
    groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
    for group in groups:
        tid = uid()
        text_mat_ids.append(tid)
        text_materials.append({
            "id": tid,
            "type": "text",
            "content": make_text_style(group["text"]),
            "words": {},
            "current_words": {},
            "combo_info": {},
            "caption_template_info": {"resource_id": "", "path": ""},
            "line_spacing": 0.02,
            "shadow_point": {"x": 0.0, "y": 0.0},
            "font_path": FONT_PATH,
            "lyrics_template": {"resource_id": "", "path": ""},
        })


# ---- 构建轨道 ----

# 视频轨道
video_segments = []
time_cursor = 0.0
for i in range(len(sentences)):
    dur = seg_durations[i]
    if dur <= 0:
        continue
    seg_id = uid()
    video_segments.append({
        "id": seg_id,
        "source_timerange": {"duration": int(dur)},
        "target_timerange": {
            "start": int(time_cursor),
            "duration": int(dur),
        },
        "render_timerange": {},
        "volume": 0.0,
        "clip": {
            "scale": {"x": 1.0, "y": 1.0},
            "transform": {"x": 0.0, "y": 0.0},
            "flip": {},
        },
        "uniform_scale": {},
        "material_id": video_mat_ids[i],
        "extra_material_refs": [
            speed_materials[i]["id"],
            placeholder_materials[i]["id"],
            canvas_materials[i]["id"],
            animation_materials[i]["id"],
            color_materials[i]["id"],
            sound_materials[i]["id"],
            loudness_materials[i]["id"],
            vocal_sep_materials[i]["id"],
        ],
        "hdr_settings": {"mode": 1},
        "responsive_layout": {},
        "source": "segmentsourcenormal",
    })
    time_cursor += dur

# 音频轨道
audio_segments = [{
    "id": uid(),
    "source_timerange": {"duration": int(total_duration_us)},
    "target_timerange": {"duration": int(total_duration_us)},
    "render_timerange": {},
    "volume": 1.0,
    "material_id": audio_mat_id,
    "extra_material_refs": [
        uid(), uid(), uid(), uid(),
    ],
    "enable_lut": False,
    "enable_adjust": False,
    "enable_hsl": False,
    "responsive_layout": {},
    "enable_adjust_mask": False,
    "source": "segmentsourcenormal",
}]

# 字幕轨道（text track）
text_segments = []
stime_cursor = 0.0
ti = 0  # text material index
for i, text in enumerate(sentences):
    dur = seg_durations[i]
    if dur <= 0:
        continue
    groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
    for group in groups:
        gdur = int((group["end"] - group["start"]) * 1_000_000)
        gstart = int((stime_cursor + group["start"]) * 1_000_000)
        text_segments.append({
            "id": uid(),
            "target_timerange": {
                "start": gstart,
                "duration": gdur,
            },
            "render_timerange": {},
            "clip": {
                "scale": {"x": 1.0, "y": 1.0},
                "transform": {"x": 0.0, "y": -0.8},
                "flip": {},
            },
            "uniform_scale": {},
            "material_id": text_mat_ids[ti],
            "render_index": 14000 + ti,
            "enable_lut": False,
            "enable_adjust": False,
            "enable_hsl": False,
            "responsive_layout": {},
            "enable_adjust_mask": False,
            "source": "segmentsourcenormal",
        })
        ti += 1
    stime_cursor += dur


# ---- 组装完整草稿 ----
draft = {
    "canvas_config": {"width": 1080, "height": 1920},
    "color_space": 0,
    "config": {},
    "duration": int(total_duration_us),
    "fps": 60.0,
    "function_assistant_info": {"fps": {}},
    "id": draft_id,
    "keyframes": {},
    "last_modified_platform": make_last_modified_platform(),
    "materials": {
        "audios": audio_materials,
        "canvases": canvas_materials,
        "loudnesses": loudness_materials,
        "material_animations": animation_materials,
        "material_colors": color_materials,
        "placeholder_infos": placeholder_materials,
        "sound_channel_mappings": sound_materials,
        "speeds": speed_materials,
        "texts": text_materials,
        "videos": video_materials,
        "vocal_separations": vocal_sep_materials,
    },
    "new_version": "177.0.0",
    "path": "",
    "platform": make_platform(),
    "smart_ads_info": {},
    "tracks": [
        {"id": uid(), "type": "video", "segments": video_segments},
        {"id": uid(), "type": "audio", "segments": audio_segments},
        {"id": uid(), "type": "text", "segments": text_segments},
    ],
    "uneven_animation_template_info": {},
    "version": 360000,
}

# ---- 输出 ----
os.makedirs(DRAFT_DIR, exist_ok=True)
output_path = os.path.join(DRAFT_DIR, "draft_content_v11.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(draft, f, ensure_ascii=False, indent=2)

size_kb = os.path.getsize(output_path) / 1024
print(f"Generated: {output_path} ({size_kb:.1f} KB)")
print(f"  Videos: {len(video_materials)}")
print(f"  Audios: {len(audio_materials)}")
print(f"  Texts: {len(text_materials)}")
print(f"  Video segs: {len(video_segments)}")
print(f"  Text segs: {len(text_segments)}")
print(f"  Duration: {total_duration_us/1e6:.1f}s")

# ---- 加密并替换 ----
import subprocess

# Copy to draft directory and encrypt
draft_json_path = os.path.join(DRAFT_DIR, "draft_content.json")
# Backup old encrypted
if os.path.exists(draft_json_path):
    bak = draft_json_path + ".v11bak"
    os.rename(draft_json_path, bak)

# Copy v11 JSON
import shutil
shutil.copy2(output_path, draft_json_path)

# Encrypt
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR
result = subprocess.run(
    ["jy-draftc", "-e", draft_json_path],
    cwd=DRAFT_DIR,
    env=env,
    capture_output=True,
    text=True,
)
print(result.stdout)
if result.returncode != 0:
    print("STDERR:", result.stderr)
    print("[FAIL] Encryption failed")
else:
    # Replace with encrypted version
    enc_path = draft_json_path + ".enc.json"
    if os.path.exists(enc_path):
        os.remove(draft_json_path)  # remove plain
        os.rename(enc_path, draft_json_path)  # encrypted becomes draft_content.json
        print(f"[OK] Encrypted draft ready: {draft_json_path} ({os.path.getsize(draft_json_path)} bytes)")
    else:
        print("[FAIL] Encrypted file not found")
