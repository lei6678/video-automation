"""Task 6 剪映草稿重新发布 — 复制到 E 盘并注册"""
import json
import os
import shutil
import time

DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
FOLDER_NAME = "Task6_王人美"
DRAFT_FOLDER = os.path.join(DRAFT_ROOT, FOLDER_NAME)

# 1. Create draft folder
os.makedirs(DRAFT_FOLDER, exist_ok=True)

# 2. Copy draft_content.json
src_json = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6/draft_content.json"
shutil.copy2(src_json, os.path.join(DRAFT_FOLDER, "draft_content.json"))

# 3. Copy cover (first image)
src_cover = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6/images/seg_000.png"
if os.path.exists(src_cover):
    shutil.copy2(src_cover, os.path.join(DRAFT_FOLDER, "draft_cover.jpg"))

# 4. Copy audio
src_audio = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6/final_audio.mp3"
if os.path.exists(src_audio):
    shutil.copy2(src_audio, os.path.join(DRAFT_FOLDER, "final_audio.mp3"))

# 5. Copy images folder
src_images = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6/images"
dst_images = os.path.join(DRAFT_FOLDER, "images")
if os.path.exists(dst_images):
    shutil.rmtree(dst_images)
shutil.copytree(src_images, dst_images)

# 6. Fix paths in draft_content.json
draft_path = os.path.join(DRAFT_FOLDER, "draft_content.json")
with open(draft_path, "r", encoding="utf-8") as f:
    draft = json.load(f)

# Fix material paths
for v in draft["draft"]["materials"]["videos"]:
    fname = os.path.basename(v["path"])
    v["path"] = os.path.join(DRAFT_FOLDER, "images", fname).replace("\\", "/")

for a in draft["draft"]["materials"]["audios"]:
    a["path"] = os.path.join(DRAFT_FOLDER, "final_audio.mp3").replace("\\", "/")

# Fix segment source_paths
for t in draft["draft"]["tracks"]:
    for s in t["segments"]:
        if "source_path" in s:
            fname = os.path.basename(s["source_path"])
            if fname.endswith(".png"):
                s["source_path"] = os.path.join(DRAFT_FOLDER, "images", fname).replace("\\", "/")
            elif fname.endswith(".mp3"):
                s["source_path"] = os.path.join(DRAFT_FOLDER, "final_audio.mp3").replace("\\", "/")

with open(draft_path, "w", encoding="utf-8") as f:
    json.dump(draft, f, ensure_ascii=False, indent=2)

print("OK - draft files ready at:", DRAFT_FOLDER)

# 7. Register in root_meta_info.json
meta_path = r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json"
with open(meta_path, "r", encoding="utf-8") as f:
    meta = json.load(f)

all_drafts = meta.get("all_draft_store", [])
# Remove old Task6 entries
all_drafts = [d for d in all_drafts
              if "Task6" not in d.get("draft_name", "")
              and "VideoAuto-6" not in d.get("draft_id", "")]

now_us = int(time.time() * 1000000)
draft_fold = DRAFT_FOLDER.replace("\\", "/")
new_entry = {
    "cloud_draft_cover": False,
    "cloud_draft_sync": False,
    "draft_cloud_last_action_download": False,
    "draft_cloud_purchase_info": "",
    "draft_cloud_template_id": "",
    "draft_cloud_tutorial_info": "",
    "draft_cloud_videocut_purchase_info": "",
    "draft_cover": draft_fold + "/draft_cover.jpg",
    "draft_fold_path": draft_fold,
    "draft_id": "VideoAuto-6-" + str(int(time.time())),
    "draft_is_ai_shorts": False,
    "draft_is_cloud_temp_draft": False,
    "draft_is_invisible": False,
    "draft_is_web_article_video": False,
    "draft_json_file": draft_fold + "/draft_content.json",
    "draft_name": FOLDER_NAME,
    "draft_new_version": "164.0.0",
    "draft_root_path": DRAFT_ROOT.replace("\\", "/"),
    "draft_timeline_materials_size": 0,
    "draft_type": "",
    "draft_web_article_video_enter_from": "",
    "streaming_edit_draft_ready": True,
    "tm_draft_cloud_completed": "",
    "tm_draft_cloud_entry_id": -1,
    "tm_draft_cloud_modified": 0,
    "tm_draft_cloud_parent_entry_id": -1,
    "tm_draft_cloud_space_id": -1,
    "tm_draft_cloud_user_id": -1,
    "tm_draft_create": now_us,
    "tm_draft_modified": now_us,
    "tm_draft_removed": 0,
}
all_drafts.insert(0, new_entry)
meta["all_draft_store"] = all_drafts

with open(meta_path, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print("OK - registered", len(all_drafts), "drafts in root_meta_info.json")
print("  Draft name:", FOLDER_NAME)
print("  Draft folder:", DRAFT_FOLDER)
