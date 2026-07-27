"""
Task 6 完整 v11 草稿生成 — 包含所有配套文件
"""
import json, os, uuid, subprocess, shutil, time

# ======== 配置 ========
JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
FONT_PATH = JY_DIR + "/Resources/Font/SystemFont/zh-hans.ttf"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
FOLDER_NAME = "Task6_王人美_v11"
DRAFT_DIR = os.path.join(DRAFT_ROOT, FOLDER_NAME)
TASK_DIR = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6"

DRAFT_NAME = FOLDER_NAME
DRAFT_ID = "Task6-v11-" + str(int(time.time()))
NOW_US = int(time.time() * 1000000)
NOW_S = int(time.time())

def uid():
    return uuid.uuid4().hex

# ======== 数据准备 ========
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
seg_durations = [d * 1_000_000 for d in tts_durs]
total_duration_us = int(sum(seg_durations))

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

print(f"Data: {len(sentences)} sentences, {total_duration_us/1e6:.1f}s, {len(image_paths)} images")

# ======== 1. 生成 draft_content.json (v11 格式) ========
def make_platform():
    return {
        "os": "windows", "os_version": "10.0.22631",
        "app_id": 3704, "app_version": "5.9.0", "app_source": "lv",
        "device_id": "2de63f9f29a84cbbc3a9c121477cc107",
        "hard_disk_id": "fe856f843f7d53ab533fdf51af180f48",
        "mac_address": "8e4ee548c0d202307fcb4b0b97d8afdc",
    }

def make_last_modified():
    p = make_platform()
    p["app_version"] = "11.0.0"
    return p

def make_text_style(text, font_size=5.0):
    return json.dumps({
        "styles": [{
            "fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}},
            "range": [0, len(text)], "size": font_size,
            "bold": True, "italic": False, "underline": False, "strokes": []
        }],
        "text": text
    }, ensure_ascii=False)

# 素材 ID
video_mat_ids = [uid() for _ in range(len(sentences))]
audio_mat_id = uid()
canvas_ids = [uid() for _ in range(len(sentences))]
speed_ids = [uid() for _ in range(len(sentences))]
anim_ids = [uid() for _ in range(len(sentences))]
color_ids = [uid() for _ in range(len(sentences))]
sound_ids = [uid() for _ in range(len(sentences))]
loud_ids = [uid() for _ in range(len(sentences))]
ph_ids = [uid() for _ in range(len(sentences))]
vocal_ids = [uid() for _ in range(len(sentences))]

# 视频素材
video_materials = []
for i, img_path in enumerate(image_paths):
    fname = os.path.basename(img_path)
    video_materials.append({
        "id": video_mat_ids[i], "type": "photo",
        "duration": 10800000000,
        "path": img_path, "width": 1080, "height": 1920,
        "category_name": "local", "material_id": video_mat_ids[i],
        "material_name": fname, "crop": {},
        "stable": {"time_range": {}}, "matting": {"path": ""},
        "check_flag": 62978047,
        "video_algorithm": {"path": "", "story_video_modify_video_config": {}},
        "beauty_face_auto_preset": {},
        "video_mask_stroke": {"resource_id": "", "path": "", "type": ""},
        "video_mask_shadow": {"resource_id": "", "path": ""},
    })

# 音频素材
audio_materials = [{
    "id": audio_mat_id, "type": "extract_music",
    "name": os.path.basename(audio_path),
    "duration": total_duration_us,
    "path": audio_path, "category_name": "local",
    "music_id": audio_mat_id, "resource_id": "",
    "check_flag": 3, "local_material_id": audio_mat_id,
    "similiar_music_info": {},
    "tts_benefit_info": {"benefit_type": "none"},
}]

# 字幕素材
text_mat_ids = []
text_materials = []
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
            "id": tid, "type": "text",
            "content": make_text_style(group["text"]),
            "words": {}, "current_words": {}, "combo_info": {},
            "caption_template_info": {"resource_id": "", "path": ""},
            "line_spacing": 0.02,
            "shadow_point": {"x": 0.0, "y": 0.0},
            "font_path": FONT_PATH,
            "lyrics_template": {"resource_id": "", "path": ""},
        })

# 辅助素材
canvases = [{"id": cid, "type": "canvas_color"} for cid in canvas_ids]
speeds = [{"id": sid, "type": "speed"} for sid in speed_ids]
anims = [{"id": aid, "type": "sticker_animation", "animations": []} for aid in anim_ids]
colors = [{"id": cid} for cid in color_ids]
sounds = [{"id": sid, "type": "none"} for sid in sound_ids]
louds = [{"id": lid} for lid in loud_ids]
placeholders = [{"id": pid, "type": "placeholder_info", "meta_type": "none"} for pid in ph_ids]
vocals = [{"id": vid, "type": "vocal_separation"} for vid in vocal_ids]

# 视频轨道
video_segments = []
time_cursor = 0.0
for i in range(len(sentences)):
    dur = seg_durations[i]
    if dur <= 0:
        continue
    video_segments.append({
        "id": uid(),
        "source_timerange": {"duration": int(dur)},
        "target_timerange": {"start": int(time_cursor), "duration": int(dur)},
        "render_timerange": {},
        "volume": 0.0,
        "clip": {"scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}, "flip": {}},
        "uniform_scale": {},
        "material_id": video_mat_ids[i],
        "extra_material_refs": [speed_ids[i], ph_ids[i], canvas_ids[i], anim_ids[i],
                                color_ids[i], sound_ids[i], loud_ids[i], vocal_ids[i]],
        "hdr_settings": {"mode": 1},
        "responsive_layout": {},
        "source": "segmentsourcenormal",
    })
    time_cursor += dur

# 音频轨道
audio_segments = [{
    "id": uid(),
    "source_timerange": {"duration": total_duration_us},
    "target_timerange": {"duration": total_duration_us},
    "render_timerange": {},
    "volume": 1.0,
    "material_id": audio_mat_id,
    "extra_material_refs": [uid(), uid(), uid(), uid()],
    "enable_lut": False, "enable_adjust": False, "enable_hsl": False,
    "responsive_layout": {}, "enable_adjust_mask": False,
    "source": "segmentsourcenormal",
}]

# 字幕轨道
text_segments = []
stime_cursor = 0.0
ti = 0
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
            "target_timerange": {"start": gstart, "duration": gdur},
            "render_timerange": {},
            "clip": {"scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": -0.8}, "flip": {}},
            "uniform_scale": {},
            "material_id": text_mat_ids[ti],
            "render_index": 14000 + ti,
            "enable_lut": False, "enable_adjust": False, "enable_hsl": False,
            "responsive_layout": {}, "enable_adjust_mask": False,
            "source": "segmentsourcenormal",
        })
        ti += 1
    stime_cursor += dur

# 组装
draft_content = {
    "canvas_config": {"width": 1080, "height": 1920},
    "color_space": 0, "config": {},
    "duration": total_duration_us,
    "fps": 60.0,
    "function_assistant_info": {"fps": {}},
    "id": str(uuid.uuid4()).upper(),
    "keyframes": {},
    "last_modified_platform": make_last_modified(),
    "materials": {
        "audios": audio_materials, "canvases": canvases,
        "loudnesses": louds, "material_animations": anims,
        "material_colors": colors, "placeholder_infos": placeholders,
        "sound_channel_mappings": sounds, "speeds": speeds,
        "texts": text_materials, "videos": video_materials,
        "vocal_separations": vocals,
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

# ======== 2. 生成 draft_meta_info.json ========
# 计算素材总大小
total_mat_size = 0
for img_path in image_paths:
    if os.path.exists(img_path):
        total_mat_size += os.path.getsize(img_path)
if os.path.exists(audio_path):
    total_mat_size += os.path.getsize(audio_path)

draft_meta = {
    "cloud_draft_cover": False, "cloud_draft_sync": False,
    "cloud_package_completed_time": "",
    "draft_cloud_capcut_purchase_info": "", "draft_cloud_last_action_download": False,
    "draft_cloud_package_type": "", "draft_cloud_purchase_info": "",
    "draft_cloud_template_id": "", "draft_cloud_tutorial_info": "",
    "draft_cloud_videocut_purchase_info": "",
    "draft_cover": "draft_cover.jpg",
    "draft_deeplink_url": "",
    "draft_enterprise_info": {"draft_enterprise_extra": "", "draft_enterprise_id": "", "draft_enterprise_name": "", "enterprise_material": []},
    "draft_fold_path": DRAFT_DIR.replace("\\", "/"),
    "draft_id": DRAFT_ID,
    "draft_is_ae_produce": False, "draft_is_ai_packaging_used": False,
    "draft_is_ai_shorts": False, "draft_is_ai_translate": False,
    "draft_is_article_video_draft": False, "draft_is_cloud_temp_draft": False,
    "draft_is_from_deeplink": "false", "draft_is_invisible": False,
    "draft_is_pippit_draft": False, "draft_is_web_article_video": False,
    "draft_materials": [
        {"type": 0, "value": [{
            "ai_group_type": "", "create_time": -1,
            "duration": total_duration_us, "enter_from": 0,
            "extra_info": os.path.basename(audio_path),
            "file_Path": "./" + os.path.basename(audio_path),
            "height": 0, "id": audio_mat_id,
            "import_time": -1, "import_time_ms": -1,
            "item_source": 1, "material_color_tag": "", "md5": "",
            "metetype": "music",
            "roughcut_time_range": {"duration": total_duration_us, "start": 0},
            "sub_time_range": {"duration": -1, "start": -1},
            "type": 0, "width": 0,
        }]},
        {"type": 1, "value": []},
        {"type": 2, "value": []},
        {"type": 3, "value": []},
        {"type": 6, "value": []},
        {"type": 7, "value": []},
        {"type": 8, "value": []},
    ],
    "draft_materials_copied_info": [],
    "draft_name": DRAFT_NAME,
    "draft_need_rename_folder": False,
    "draft_new_version": "164.0.0",
    "draft_removable_storage_device": "E:",
    "draft_root_path": DRAFT_ROOT.replace("\\", "/"),
    "draft_segment_extra_info": [],
    "draft_timeline_materials_size_": total_mat_size,
    "draft_type": "", "draft_web_article_video_enter_from": "",
    "pippit_avatar_url": "", "pippit_extra_info": "",
    "pippit_id": "", "pippit_user_name": "",
    "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1,
    "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
    "tm_draft_cloud_space_id": -1, "tm_draft_cloud_user_id": -1,
    "tm_draft_create": NOW_US, "tm_draft_modified": NOW_US,
    "tm_draft_removed": 0, "tm_duration": total_duration_us,
}

# ======== 3. Timelines/project.json ========
timeline_id = str(uuid.uuid4()).upper()
project_json = {
    "config": {"color_space": 0, "mixed_track_mode_on": False, "render_index_track_mode_on": False, "use_float_render": False},
    "create_time": NOW_US, "id": timeline_id,
    "main_timeline_id": timeline_id,
    "timelines": [{
        "create_time": NOW_US, "id": timeline_id,
        "is_marked_delete": False, "name": "时间线01", "update_time": NOW_US,
    }],
    "update_time": NOW_US, "version": 0,
}

# ======== 4. draft_settings ========
draft_settings_content = f"""[General]
cloud_last_modify_platform=windows
draft_create_time={NOW_S}
draft_last_edit_time={NOW_S}
real_edit_seconds=0
real_edit_keys=0
"""

# ======== 5. 写入文件 ========
os.makedirs(DRAFT_DIR, exist_ok=True)

# draft_content.json (plain → encrypt)
dc_path = os.path.join(DRAFT_DIR, "draft_content.json")
with open(dc_path, "w", encoding="utf-8") as f:
    json.dump(draft_content, f, ensure_ascii=False, indent=2)
print(f"draft_content.json: {os.path.getsize(dc_path)} bytes (plain)")

# draft_meta_info.json (plain → encrypt)
dm_path = os.path.join(DRAFT_DIR, "draft_meta_info.json")
with open(dm_path, "w", encoding="utf-8") as f:
    json.dump(draft_meta, f, ensure_ascii=False, indent=2)
print(f"draft_meta_info.json: {os.path.getsize(dm_path)} bytes (plain)")

# draft_settings
ds_path = os.path.join(DRAFT_DIR, "draft_settings")
with open(ds_path, "w", encoding="utf-8") as f:
    f.write(draft_settings_content)
print(f"draft_settings: OK")

# draft_cover.jpg (copy first image)
cover_src = image_paths[0] if image_paths else None
if cover_src:
    shutil.copy2(cover_src, os.path.join(DRAFT_DIR, "draft_cover.jpg"))
    print("draft_cover.jpg: copied")

# Timelines/
tl_dir = os.path.join(DRAFT_DIR, "Timelines")
tl_sub_dir = os.path.join(tl_dir, timeline_id)
os.makedirs(tl_sub_dir, exist_ok=True)

# Timelines/project.json
with open(os.path.join(tl_dir, "project.json"), "w", encoding="utf-8") as f:
    json.dump(project_json, f, ensure_ascii=False, indent=2)
print("Timelines/project.json: OK")

# Timelines/<id>/draft_content.json (same as root)
shutil.copy2(dc_path, os.path.join(tl_sub_dir, "draft_content.json"))
print("Timelines/<id>/draft_content.json: copied")

# Timelines/<id>/draft_cover.jpg
if cover_src:
    shutil.copy2(cover_src, os.path.join(tl_sub_dir, "draft_cover.jpg"))

# Empty companion files
for fname, content in [
    ("draft.extra", ""),
    ("attachment_editing.json", "{}"),
    ("attachment_pc_common.json", "{}"),
    ("template.tmp", ""),
    ("template-2.tmp", ""),
]:
    with open(os.path.join(tl_sub_dir, fname), "w", encoding="utf-8") as f:
        f.write(content + "\n" if not content else content)

# Timelines/<id>/common_attachment/
ca_dir = os.path.join(tl_sub_dir, "common_attachment")
os.makedirs(ca_dir, exist_ok=True)
for fname in ["attachment_action_scene.json", "attachment_id_mapping.json",
              "attachment_pc_timeline.json", "attachment_plugin_draft.json",
              "attachment_script_video.json", "coperate_create.json"]:
    with open(os.path.join(ca_dir, fname), "w", encoding="utf-8") as f:
        f.write("{}\n")

# ======== 6. 加密 ========
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR

for fname in ["draft_content.json", "draft_meta_info.json"]:
    fpath = os.path.join(DRAFT_DIR, fname)
    r = subprocess.run(["jy-draftc", "-e", fpath], cwd=DRAFT_DIR, env=env,
                       capture_output=True, text=True)
    enc_path = fpath + ".enc.json"
    if os.path.exists(enc_path):
        os.remove(fpath)
        os.rename(enc_path, fpath)
        print(f"{fname}: encrypted ({os.path.getsize(fpath)} bytes)")
    else:
        print(f"{fname}: encryption FAILED")
        print(r.stderr[:300])

# Also encrypt Timelines version
tl_dc = os.path.join(tl_sub_dir, "draft_content.json")
r = subprocess.run(["jy-draftc", "-e", tl_dc], cwd=tl_sub_dir, env=env,
                   capture_output=True, text=True)
enc_path = tl_dc + ".enc.json"
if os.path.exists(enc_path):
    os.remove(tl_dc)
    os.rename(enc_path, tl_dc)
    print("Timelines/draft_content.json: encrypted")

# ======== 7. 注册 ========
meta_path = r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json"
with open(meta_path, "r", encoding="utf-8") as f:
    meta = json.load(f)

all_drafts = meta.get("all_draft_store", [])
all_drafts = [d for d in all_drafts if "Task6_王人美_v11" not in d.get("draft_name", "")]

dfold = DRAFT_DIR.replace("\\", "/")
all_drafts.insert(0, {
    "cloud_draft_cover": False, "cloud_draft_sync": False,
    "draft_cloud_last_action_download": False,
    "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
    "draft_cloud_tutorial_info": "", "draft_cloud_videocut_purchase_info": "",
    "draft_cover": dfold + "/draft_cover.jpg",
    "draft_fold_path": dfold,
    "draft_id": DRAFT_ID,
    "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
    "draft_is_invisible": False, "draft_is_web_article_video": False,
    "draft_json_file": dfold + "/draft_content.json",
    "draft_name": DRAFT_NAME,
    "draft_new_version": "164.0.0",
    "draft_root_path": DRAFT_ROOT.replace("\\", "/"),
    "draft_timeline_materials_size": total_mat_size, "draft_type": "",
    "draft_web_article_video_enter_from": "",
    "streaming_edit_draft_ready": True,
    "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1,
    "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
    "tm_draft_cloud_space_id": -1, "tm_draft_cloud_user_id": -1,
    "tm_draft_create": NOW_US, "tm_draft_modified": NOW_US, "tm_draft_removed": 0,
})
meta["all_draft_store"] = all_drafts
with open(meta_path, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print(f"\n===== DONE =====")
print(f"Draft: {DRAFT_NAME}")
print(f"Folder: {DRAFT_DIR}")
print(f"Registered: {len(all_drafts)} drafts total")
print(f"Video segs: {len(video_segments)}, Text segs: {len(text_segments)}, Duration: {total_duration_us/1e6:.1f}s")
print(f"\nClose 剪映 and reopen to test.")
