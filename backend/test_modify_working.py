"""对照实验：修改工作草稿 → 注册 → 测试"""
import json, os, uuid, subprocess, shutil, time, glob

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
TEST_IMG = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6/images/seg_000.png"

# 1. Find and decrypt working draft
draft_dir = r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft"
dec_path = None
for root, dirs, files in os.walk(draft_dir):
    for f in files:
        if f == "draft_content.json" and "_DraftFolder_API" in root:
            enc_path = os.path.join(root, f)
            # Decrypt
            env = os.environ.copy()
            env["JY_INSTALL_DIR"] = JY_DIR
            out = enc_path.replace(".json", ".mod.json")
            r = subprocess.run(["jy-draftc", "-d", enc_path, out], env=env,
                             capture_output=True, text=True, cwd=root)
            if os.path.exists(out):
                dec_path = out
                print(f"Decrypted: {dec_path}")
            break
    if dec_path:
        break

if not dec_path:
    print("FAIL: couldn't decrypt working draft")
    exit(1)

# 2. Modify: only change image path
with open(dec_path, "r", encoding="utf-8") as f:
    draft = json.load(f)

# Change video material paths to our test image
for v in draft["materials"]["videos"]:
    old_path = v["path"]
    v["path"] = TEST_IMG
    v["material_name"] = "seg_000.png"
    print(f"Path: {old_path} -> {TEST_IMG}")

# Change audio path too if exists
for a in draft["materials"]["audios"]:
    old = a["path"]
    a["path"] = TEST_IMG.replace(".png", ".mp3")  # won't play but path is valid
    print(f"Audio: {old} -> {a['path']}")

# 3. Save as new test draft
TEST_FOLDER = "TestModWorking"
test_dir = os.path.join(DRAFT_ROOT, TEST_FOLDER)
os.makedirs(test_dir, exist_ok=True)

mod_path = os.path.join(test_dir, "draft_content.json")
with open(mod_path, "w", encoding="utf-8") as f:
    json.dump(draft, f, ensure_ascii=False, indent=2)

# 4. Encrypt
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR
r = subprocess.run(["jy-draftc", "-e", mod_path], cwd=test_dir, env=env,
                   capture_output=True, text=True)
enc_path = mod_path + ".enc.json"
if os.path.exists(enc_path):
    os.remove(mod_path)
    os.rename(enc_path, mod_path)
    print(f"Encrypted: {os.path.getsize(mod_path)} bytes")
else:
    print("FAIL: encryption failed")
    print(r.stderr)
    exit(1)

# 5. Register
meta_path = r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json"
with open(meta_path, "r", encoding="utf-8") as f:
    meta = json.load(f)

all_drafts = meta.get("all_draft_store", [])
all_drafts = [d for d in all_drafts if "TestMod" not in d.get("draft_name", "")]

now_us = int(time.time() * 1000000)
dfold = test_dir.replace("\\", "/")
all_drafts.insert(0, {
    "cloud_draft_cover": False, "cloud_draft_sync": False,
    "draft_cloud_last_action_download": False,
    "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
    "draft_cloud_tutorial_info": "", "draft_cloud_videocut_purchase_info": "",
    "draft_cover": dfold + "/draft_cover.jpg",
    "draft_fold_path": dfold,
    "draft_id": "TestMod-" + str(int(time.time())),
    "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
    "draft_is_invisible": False, "draft_is_web_article_video": False,
    "draft_json_file": dfold + "/draft_content.json",
    "draft_name": "TestModWorking",
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

print(f"DONE: TestModWorking registered")
print(f"Total drafts: {len(all_drafts)}")
