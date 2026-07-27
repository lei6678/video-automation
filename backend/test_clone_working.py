"""完整复制工作草稿文件夹 → 注册 → 测试"""
import os, shutil, json, time

DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
SRC = None
for root, dirs, files in os.walk(r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft"):
    for d in dirs:
        if d.startswith("_DraftFolder_API"):
            SRC = os.path.join(root, d)
            break
    if SRC:
        break

if not SRC:
    print("FAIL: source draft not found")
    exit(1)

print(f"Source: {SRC}")

# Copy everything
DST = os.path.join(DRAFT_ROOT, "TestCloneFull")
if os.path.exists(DST):
    shutil.rmtree(DST)
shutil.copytree(SRC, DST)
print(f"Copied to: {DST}")

# List what was copied
for root, dirs, files in os.walk(DST):
    for f in files:
        fp = os.path.join(root, f)
        print(f"  {os.path.relpath(fp, DST)} ({os.path.getsize(fp)} bytes)")

# Register
meta_path = r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json"
with open(meta_path, "r", encoding="utf-8") as f:
    meta = json.load(f)

all_drafts = meta.get("all_draft_store", [])
all_drafts = [d for d in all_drafts if "TestClone" not in d.get("draft_name", "")]

now_us = int(time.time() * 1000000)
dfold = DST.replace("\\", "/")
all_drafts.insert(0, {
    "cloud_draft_cover": False, "cloud_draft_sync": False,
    "draft_cloud_last_action_download": False,
    "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
    "draft_cloud_tutorial_info": "", "draft_cloud_videocut_purchase_info": "",
    "draft_cover": dfold + "/draft_cover.jpg",
    "draft_fold_path": dfold,
    "draft_id": "TestClone-" + str(int(time.time())),
    "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
    "draft_is_invisible": False, "draft_is_web_article_video": False,
    "draft_json_file": dfold + "/draft_content.json",
    "draft_name": "TestCloneFull",
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

print(f"DONE: TestCloneFull registered ({len(all_drafts)} total)")
print("If this appears in 剪映, the issue is with draft_content.json content.")
print("If NOT, the issue is with registration/location.")
