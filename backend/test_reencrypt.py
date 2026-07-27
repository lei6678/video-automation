"""测试：解密→不改任何内容→重新加密，看剪映认不认"""
import os, shutil, json, subprocess, time

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"

# Find working draft
SRC = None
for root, dirs, files in os.walk(r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft"):
    for d in dirs:
        if d.startswith("_DraftFolder_API"):
            SRC = os.path.join(root, d)
            break
    if SRC:
        break

# 1. Decrypt working draft
enc_path = os.path.join(SRC, "draft_content.json")
dec_path = os.path.join(SRC, "draft_content.reenc_test.json")
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR
r = subprocess.run(["jy-draftc", "-d", enc_path, dec_path], env=env,
                   capture_output=True, text=True)
print(r.stdout.strip().split("\n")[-1])

# 2. Re-encrypt WITHOUT modifying
test_dir = os.path.join(DRAFT_ROOT, "TestReEncrypt")
os.makedirs(test_dir, exist_ok=True)
test_enc = os.path.join(test_dir, "draft_content.json")

# Copy decrypted content to test dir
with open(dec_path, "rb") as f:
    dec_data = f.read()
with open(test_enc, "w", encoding="utf-8") as f:
    f.write(dec_data.decode("utf-8"))

# Encrypt
r = subprocess.run(["jy-draftc", "-e", test_enc], cwd=test_dir, env=env,
                   capture_output=True, text=True)
print(r.stdout.strip().split("\n")[-1])

enc_out = test_enc + ".enc.json"
if os.path.exists(enc_out):
    os.remove(test_enc)
    os.rename(enc_out, test_enc)

    # Compare byte sizes
    orig_size = os.path.getsize(enc_path)
    new_size = os.path.getsize(test_enc)
    print(f"Original encrypted: {orig_size} bytes")
    print(f"Re-encrypted: {new_size} bytes")

    # Compare first bytes
    with open(enc_path, "rb") as f:
        orig_head = f.read(50)
    with open(test_enc, "rb") as f:
        new_head = f.read(50)
    print(f"Original head: {orig_head[:30].hex()}")
    print(f"New head: {new_head[:30].hex()}")
else:
    print("FAIL: re-encryption failed")
    exit(1)

# Also copy other required files (draft_meta_info.json, etc.)
for fname in ["draft_meta_info.json", "draft_cover.jpg", "draft_settings"]:
    src_f = os.path.join(SRC, fname)
    if os.path.exists(src_f):
        shutil.copy2(src_f, os.path.join(test_dir, fname))
        print(f"Copied: {fname}")

# Copy Timelines dir
src_tl = os.path.join(SRC, "Timelines")
if os.path.exists(src_tl):
    dst_tl = os.path.join(test_dir, "Timelines")
    if os.path.exists(dst_tl):
        shutil.rmtree(dst_tl)
    shutil.copytree(src_tl, dst_tl)
    print("Copied: Timelines/")

# Register
meta_path = r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json"
with open(meta_path, "r", encoding="utf-8") as f:
    meta = json.load(f)

all_drafts = meta.get("all_draft_store", [])
all_drafts = [d for d in all_drafts if "TestReEncrypt" not in d.get("draft_name", "")]
all_drafts = [d for d in all_drafts if "TestMinimal" not in d.get("draft_name", "")]
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
    "draft_id": "TestReEncrypt-" + str(int(time.time())),
    "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
    "draft_is_invisible": False, "draft_is_web_article_video": False,
    "draft_json_file": dfold + "/draft_content.json",
    "draft_name": "TestReEncrypt",
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

print(f"\nDONE: {len(all_drafts)} drafts")
print("TestReEncrypt = decrypt -> ZERO changes -> re-encrypt")
print("Close 剪映 and reopen to test.")
