"""修复 Task6_v11_final: 对齐 Timelines 目录名 + 清理残留"""
import json, os, subprocess, shutil, time, uuid

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
DRAFT_DIR = os.path.join(DRAFT_ROOT, "Task6_v11_final")
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR

# ===== 1. 读取 project.json，获取正确的 timeline UUID =====
proj_path = os.path.join(DRAFT_DIR, "Timelines", "project.json")
with open(proj_path, "r", encoding="utf-8") as f:
    proj = json.load(f)
correct_uuid = proj["main_timeline_id"]
print(f"project.json main_timeline_id: {correct_uuid}")

# ===== 2. 找到旧 UUID 目录 =====
tl_dir = os.path.join(DRAFT_DIR, "Timelines")
old_uuid_dirs = [d for d in os.listdir(tl_dir) 
                 if os.path.isdir(os.path.join(tl_dir, d)) and d != "common_attachment"]
print(f"Existing UUID dirs: {old_uuid_dirs}")

# 找出不是新 UUID 的目录
for old_dir in old_uuid_dirs:
    if old_dir.upper() != correct_uuid.upper():
        old_path = os.path.join(tl_dir, old_dir)
        new_path = os.path.join(tl_dir, correct_uuid)
        print(f"Rename: {old_dir} -> {correct_uuid}")
        # 如果新目录已存在，先删除
        if os.path.exists(new_path):
            shutil.rmtree(new_path)
        os.rename(old_path, new_path)

# ===== 3. 清理 .tmp 和 .bak 文件 =====
target_dir = os.path.join(tl_dir, correct_uuid)
if os.path.exists(target_dir):
    for f in os.listdir(target_dir):
        if f.endswith(".tmp") or f.endswith(".bak"):
            fp = os.path.join(target_dir, f)
            os.remove(fp)
            print(f"Cleaned: {f}")
else:
    print(f"ERROR: Target dir {correct_uuid} not found!")
    # Try to find it
    for d in os.listdir(tl_dir):
        dp = os.path.join(tl_dir, d)
        if os.path.isdir(dp) and d != "common_attachment":
            print(f"  Found: {d}")
            # Just rename it
            os.rename(dp, os.path.join(tl_dir, correct_uuid))
            print(f"  Renamed {d} -> {correct_uuid}")

# ===== 4. 验证目录结构 =====
print("\nFinal Timelines structure:")
for root, dirs, files in os.walk(tl_dir):
    level = root.replace(tl_dir, "").count(os.sep)
    indent = "  " * level
    print(f"{indent}{os.path.basename(root)}/")
    for f in sorted(files):
        print(f"{indent}  {f}")

# ===== 5. 检查 draft_meta_info.json =====
print("\n===== draft_meta_info.json =====")
dm_enc = os.path.join(DRAFT_DIR, "draft_meta_info.json")
dm_dec = os.path.join(DRAFT_DIR, "draft_meta_info.debug.json")
subprocess.run(["jy-draftc", "-d", dm_enc, dm_dec], env=env, capture_output=True, text=True)
with open(dm_dec, "r", encoding="utf-8") as f:
    dm = json.load(f)
print(f"draft_id: {dm.get('draft_id')}")
print(f"draft_name: {dm.get('draft_name')}")
print(f"draft_fold_path: {dm.get('draft_fold_path')}")
print(f"tm_duration: {dm.get('tm_duration')}")
# Check materials
for i, mat_grp in enumerate(dm.get("draft_materials", [])):
    print(f"  material group {i} ({mat_grp.get('type')}): {len(mat_grp.get('value', []))} items")
    for v in mat_grp.get("value", [])[:2]:
        print(f"    id={v.get('id')}, path={v.get('file_Path', v.get('path', 'N/A'))[:80]}")

# ===== 6. 重新加密 Timelines 下的 draft_content.json（如果需要）=====
tl_dc = os.path.join(target_dir, "draft_content.json")
# Check if it's already encrypted
with open(tl_dc, "rb") as f:
    head = f.read(4)
if head[0] == 0x7b:  # '{' = plain JSON
    print("\nTimelines draft_content.json is PLAIN, encrypting...")
    subprocess.run(["jy-draftc", "-e", tl_dc], cwd=target_dir, env=env, capture_output=True, text=True)
    enc_out = tl_dc + ".enc.json"
    if os.path.exists(enc_out):
        os.remove(tl_dc)
        os.rename(enc_out, tl_dc)
        print(f"Encrypted: {os.path.getsize(tl_dc)} bytes")
else:
    print(f"\nTimelines draft_content.json already encrypted ({os.path.getsize(tl_dc)} bytes)")

# ===== 7. 检查 Timelines/<uuid>/ 下的 attachment 文件 =====
print("\n===== Attachment files =====")
for fname in ["attachment_editing.json", "attachment_pc_common.json"]:
    fp = os.path.join(target_dir, fname)
    if os.path.exists(fp):
        with open(fp, "r", encoding="utf-8") as f:
            att = json.load(f)
        print(f"{fname}: {json.dumps(att, ensure_ascii=False)[:200]}")

# ===== 8. 检查 common_attachment 文件 =====
ca_dir = os.path.join(target_dir, "common_attachment")
if os.path.exists(ca_dir):
    print(f"\n===== common_attachment files =====")
    for fname in os.listdir(ca_dir):
        fp = os.path.join(ca_dir, fname)
        try:
            with open(fp, "r", encoding="utf-8") as f:
                content = json.load(f)
            print(f"  {fname}: {json.dumps(content, ensure_ascii=False)[:200]}")
        except:
            print(f"  {fname}: <binary or parse error>")

# ===== 9. 检查 root draft_content.json 是否需要重加密 =====
root_dc = os.path.join(DRAFT_DIR, "draft_content.json")
with open(root_dc, "rb") as f:
    head = f.read(4)
print(f"\nRoot draft_content.json head: {head.hex()}")
print("DONE - close 剪映 and test")
