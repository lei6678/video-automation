"""最小化 v11 草稿测试：1图5秒，无字幕无音频"""
import json, os, uuid, subprocess, time

def uid():
    return uuid.uuid4().hex

DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
FOLDER = "TestMinimal"
DRAFT_DIR = os.path.join(DRAFT_ROOT, FOLDER)
JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
TEST_IMG = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6/images/seg_000.png"

os.makedirs(DRAFT_DIR, exist_ok=True)

vid_mat_id = uid()
canvas_id = uid()
speed_id = uid()
anim_id = uid()
color_id = uid()
sound_id = uid()
loud_id = uid()
ph_id = uid()
vocal_id = uid()
seg_id = uid()
track_id = uid()
draft_id = str(uuid.uuid4()).upper()

draft = {
    "canvas_config": {"width": 1080, "height": 1920},
    "color_space": 0,
    "config": {},
    "duration": 5000000,
    "fps": 60.0,
    "function_assistant_info": {"fps": {}},
    "id": draft_id,
    "keyframes": {},
    "last_modified_platform": {
        "os": "windows", "os_version": "10.0.22631",
        "app_id": 3704, "app_version": "11.0.0", "app_source": "lv",
        "device_id": "2de63f9f29a84cbbc3a9c121477cc107",
        "hard_disk_id": "fe856f843f7d53ab533fdf51af180f48",
        "mac_address": "8e4ee548c0d202307fcb4b0b97d8afdc",
    },
    "materials": {
        "videos": [{
            "id": vid_mat_id, "type": "photo", "duration": 10800000000,
            "path": TEST_IMG, "width": 1080, "height": 1920,
            "category_name": "local", "material_id": vid_mat_id,
            "material_name": "seg_000.png",
            "crop": {}, "stable": {"time_range": {}}, "matting": {"path": ""},
            "check_flag": 62978047,
            "video_algorithm": {"path": "", "story_video_modify_video_config": {}},
            "beauty_face_auto_preset": {},
            "video_mask_stroke": {"resource_id": "", "path": "", "type": ""},
            "video_mask_shadow": {"resource_id": "", "path": ""},
        }],
        "audios": [],
        "texts": [],
        "canvases": [{"id": canvas_id, "type": "canvas_color"}],
        "speeds": [{"id": speed_id, "type": "speed"}],
        "material_animations": [{"id": anim_id, "type": "sticker_animation", "animations": []}],
        "material_colors": [{"id": color_id}],
        "sound_channel_mappings": [{"id": sound_id, "type": "none"}],
        "loudnesses": [{"id": loud_id}],
        "placeholder_infos": [{"id": ph_id, "type": "placeholder_info", "meta_type": "none"}],
        "vocal_separations": [{"id": vocal_id, "type": "vocal_separation"}],
    },
    "new_version": "177.0.0",
    "path": "",
    "platform": {
        "os": "windows", "os_version": "10.0.22631",
        "app_id": 3704, "app_version": "5.9.0", "app_source": "lv",
        "device_id": "2de63f9f29a84cbbc3a9c121477cc107",
        "hard_disk_id": "fe856f843f7d53ab533fdf51af180f48",
        "mac_address": "8e4ee548c0d202307fcb4b0b97d8afdc",
    },
    "smart_ads_info": {},
    "tracks": [{
        "id": track_id, "type": "video",
        "segments": [{
            "id": seg_id,
            "source_timerange": {"duration": 5000000},
            "target_timerange": {"duration": 5000000},
            "render_timerange": {},
            "volume": 0.0,
            "clip": {"scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}, "flip": {}},
            "uniform_scale": {},
            "material_id": vid_mat_id,
            "extra_material_refs": [speed_id, ph_id, canvas_id, anim_id, color_id, sound_id, loud_id, vocal_id],
            "hdr_settings": {"mode": 1},
            "responsive_layout": {},
            "source": "segmentsourcenormal",
        }],
    }],
    "uneven_animation_template_info": {},
    "version": 360000,
}

# Write + encrypt
json_path = os.path.join(DRAFT_DIR, "draft_content.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(draft, f, ensure_ascii=False, indent=2)

env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR
r = subprocess.run(["jy-draftc", "-e", json_path], cwd=DRAFT_DIR, env=env,
                   capture_output=True, text=True)
enc_path = json_path + ".enc.json"
if os.path.exists(enc_path):
    os.remove(json_path)
    os.rename(enc_path, json_path)
    print(f"Encrypted: {os.path.getsize(json_path)} bytes")
else:
    print("FAIL: encryption failed")
    print(r.stderr[:300])
    exit(1)

# Register
meta_path = r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json"
with open(meta_path, "r", encoding="utf-8") as f:
    meta = json.load(f)

all_drafts = meta.get("all_draft_store", [])
all_drafts = [d for d in all_drafts if "TestMinimal" not in d.get("draft_name", "")]

now_us = int(time.time() * 1000000)
dfold = DRAFT_DIR.replace("\\", "/")
all_drafts.insert(0, {
    "cloud_draft_cover": False, "cloud_draft_sync": False,
    "draft_cloud_last_action_download": False,
    "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
    "draft_cloud_tutorial_info": "", "draft_cloud_videocut_purchase_info": "",
    "draft_cover": dfold + "/draft_cover.jpg",
    "draft_fold_path": dfold,
    "draft_id": "TestMinimal-" + str(int(time.time())),
    "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
    "draft_is_invisible": False, "draft_is_web_article_video": False,
    "draft_json_file": dfold + "/draft_content.json",
    "draft_name": "TestMinimal",
    "draft_new_version": "177.0.0",
    "draft_root_path": DRAFT_ROOT.replace("\\", "/"),
    "draft_timeline_materials_size": 0, "draft_type": "",
    "draft_web_article_video_enter_from": "",
    "streaming_edit_draft_ready": True,
    "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1,
    "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
    "tm_draft_cloud_space_id": -1, "tm_draft_cloud_user_id": -1,
    "tm_draft_create": now_us, "tm_draft_modified": now_us, "tm_draft_removed": 0,
})
meta["all_draft_store"] = all_drafts
with open(meta_path, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print(f"DONE: TestMinimal registered ({len(all_drafts)} total)")
print(f"Folder: {DRAFT_DIR}")
