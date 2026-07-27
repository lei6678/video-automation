"""精确对比 Task6 (service 生成, 打不开) vs ComboC (手动复制 service 逻辑, 能打开)"""
import json, os, subprocess

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR

def decrypt(enc_path, out_path):
    subprocess.run(["jy-draftc", "-d", enc_path, out_path], env=env, capture_output=True, text=True)

# Decrypt both
task6_enc = os.path.join(DRAFT_ROOT, "Task6", "draft_content.json")
combo_enc = os.path.join(DRAFT_ROOT, "ComboC_FullService", "draft_content.json")

task6_dec = os.path.join(DRAFT_ROOT, "Task6", "_task6_dec.json")
combo_dec = os.path.join(DRAFT_ROOT, "ComboC_FullService", "_combo_dec.json")

decrypt(task6_enc, task6_dec)
decrypt(combo_enc, combo_dec)

with open(task6_dec, "r", encoding="utf-8") as f:
    t6 = json.load(f)
with open(combo_dec, "r", encoding="utf-8") as f:
    cb = json.load(f)

print(f"Task6:  {len(t6['tracks'][0]['segments'])}v, {len(t6['tracks'][2]['segments'])}t")
print(f"ComboC: {len(cb['tracks'][0]['segments'])}v, {len(cb['tracks'][2]['segments'])}t")

# ======== 1. 顶层字段逐项对比 ========
print("\n=== 1. Top-level fields ===")
ignore_keys = {"id", "duration", "tracks", "materials", "last_modified_time",
               "created_at", "updated_at", "name", "draft_id"}
for k in sorted(set(t6.keys()) | set(cb.keys())):
    if k in ignore_keys:
        continue
    v6 = t6.get(k)
    vc = cb.get(k)
    if v6 != vc:
        if isinstance(v6, (dict, list)):
            print(f"  {k}: DIFF (complex type)")
        else:
            print(f"  {k}: T6={v6!r:.100} vs C={vc!r:.100} [DIFF]")

# ======== 2. Materials 每类数量 ========
print("\n=== 2. Material counts ===")
for cat in ["videos", "audios", "texts", "canvases", "speeds",
            "material_animations", "material_colors", "sound_channel_mappings",
            "loudnesses", "placeholder_infos", "vocal_separations"]:
    c6 = len(t6["materials"].get(cat, []))
    cc = len(cb["materials"].get(cat, []))
    flag = " [DIFF!]" if c6 != cc else ""
    print(f"  {cat}: T6={c6}, C={cc}{flag}")

# ======== 3. 视频材料字段对比 ========
print("\n=== 3. Video material[0] keys ===")
t6v0 = t6["materials"]["videos"][0]
cbv0 = cb["materials"]["videos"][0]
t6k = set(t6v0.keys())
cbk = set(cbv0.keys())
if t6k - cbk:
    print(f"  Only in T6: {t6k - cbk}")
if cbk - t6k:
    print(f"  Only in C:  {cbk - t6k}")

for k in sorted(t6k | cbk):
    v6 = t6v0.get(k)
    vc = cbv0.get(k)
    if v6 != vc and k not in ("id", "material_id", "path", "material_name",
                               "extra_info", "local_material_id", "file_Path",
                               "roughcut_time_range", "duration"):
        print(f"  {k}: T6={v6!r:.100} vs C={vc!r:.100} [DIFF]")

# ======== 4. 音频材料字段 ========
print("\n=== 4. Audio material[0] ===")
t6a = t6["materials"]["audios"][0]
cba = cb["materials"]["audios"][0]
for k in sorted(set(t6a.keys()) | set(cba.keys())):
    v6 = t6a.get(k)
    vc = cba.get(k)
    if v6 != vc and k not in ("id", "music_id", "local_material_id", "path", "name",
                               "duration", "extra_info", "file_Path"):
        print(f"  {k}: T6={v6!r:.100} vs C={vc!r:.100} [DIFF]")

if "material_id" in t6a:
    print(f"  [BAD] T6 audio has material_id: {t6a['material_id']}")
if "material_id" in cba:
    print(f"  [BAD] C audio has material_id: {cba['material_id']}")

# ======== 5. 文字材料字段 ========
print("\n=== 5. Text material[0] ===")
t6t0 = t6["materials"]["texts"][0]
cbt0 = cb["materials"]["texts"][0]
t6tk = set(t6t0.keys())
cbtk = set(cbt0.keys())
if t6tk - cbtk:
    print(f"  Only in T6: {t6tk - cbtk}")
if cbtk - t6tk:
    print(f"  Only in C:  {cbtk - t6tk}")
if "material_id" in t6t0:
    print(f"  [BAD] T6 text has material_id")

# ======== 6. 视频段对比 (前5个) ========
print("\n=== 6. Video segment target_timerange ===")
for i in range(min(5, len(t6["tracks"][0]["segments"]))):
    t6tr = t6["tracks"][0]["segments"][i]["target_timerange"]
    cbtr = cb["tracks"][0]["segments"][i]["target_timerange"]
    if t6tr != cbtr:
        print(f"  seg[{i}]: T6={t6tr} vs C={cbtr} [DIFF]")
    else:
        print(f"  seg[{i}]: OK")

# ======== 7. 视频段 refs 类别 ========
print("\n=== 7. Video seg[2] ref categories ===")
def cat_of_ref(draft, ref_id):
    for cat in ["speeds", "placeholder_infos", "canvases", "material_animations",
                "sound_channel_mappings", "material_colors", "loudnesses", "vocal_separations"]:
        for item in draft["materials"].get(cat, []):
            if item["id"] == ref_id:
                return cat
    return "UNKNOWN"

t6_refs = t6["tracks"][0]["segments"][2]["extra_material_refs"]
cb_refs = cb["tracks"][0]["segments"][2]["extra_material_refs"]
print(f"  T6: {[cat_of_ref(t6, r) for r in t6_refs]}")
print(f"  C:  {[cat_of_ref(cb, r) for r in cb_refs]}")

# ======== 8. 音频段 refs ========
print("\n=== 8. Audio segment refs ===")
t6_arefs = t6["tracks"][1]["segments"][0]["extra_material_refs"]
cb_arefs = cb["tracks"][1]["segments"][0]["extra_material_refs"]
print(f"  T6: {[cat_of_ref(t6, r) for r in t6_arefs]}")
print(f"  C:  {[cat_of_ref(cb, r) for r in cb_arefs]}")

# Check indices
for ci, cat in enumerate(["speeds", "placeholder_infos", "sound_channel_mappings", "vocal_separations"]):
    t6_idx = next((idx for idx, item in enumerate(t6["materials"][cat]) if item["id"] == t6_arefs[ci]), None)
    cb_idx = next((idx for idx, item in enumerate(cb["materials"][cat]) if item["id"] == cb_arefs[ci]), None)
    flag = " [DIFF]" if t6_idx != cb_idx else ""
    print(f"  {cat}: T6[{t6_idx}] vs C[{cb_idx}]{flag}")

# ======== 9. 全文对比 (JSON dump 后逐行 diff) ========
print("\n=== 9. Deep structural diff ===")
def normalize(obj):
    """递归标准化 JSON: 把所有 ID/路径字段替换为占位符"""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if k in ("id", "material_id", "music_id", "local_material_id",
                     "draft_id", "path", "material_name", "name", "font_path",
                     "file_Path", "draft_fold_path", "draft_root_path",
                     "draft_json_file", "draft_cover", "tm_draft_create",
                     "tm_draft_modified"):
                result[k] = "<NORMALIZED>"
            elif k == "content":
                # Text content: normalize the text, keep structure
                try:
                    content = json.loads(v)
                    if "text" in content:
                        content["text"] = "<NORMALIZED>"
                    result[k] = json.dumps(content, ensure_ascii=False)
                except:
                    result[k] = "<NORMALIZED>"
            else:
                result[k] = normalize(v)
        return result
    elif isinstance(obj, list):
        return [normalize(item) for item in obj]
    else:
        return obj

t6_norm = normalize(t6)
cb_norm = normalize(cb)

# Compare normalized versions
import difflib
t6_lines = json.dumps(t6_norm, ensure_ascii=False, indent=2).split("\n")
cb_lines = json.dumps(cb_norm, ensure_ascii=False, indent=2).split("\n")

diff = list(difflib.unified_diff(t6_lines, cb_lines, fromfile="Task6", tofile="ComboC", lineterm=""))
if diff:
    print(f"  Found {len(diff)} diff lines (normalized)")
    # Print first 50 diffs
    for line in diff[:80]:
        print(f"    {line}")
    if len(diff) > 80:
        print(f"  ... and {len(diff) - 80} more lines")
else:
    print("  NO DIFFERENCES (normalized)")

# ======== 10. Check for non-normalized differences ========
print("\n=== 10. Non-normalized key differences ===")

# Check tracks structure
for ti in range(len(t6["tracks"])):
    t6_track = t6["tracks"][ti]
    cb_track = cb["tracks"][ti]
    t6_seg_count = len(t6_track["segments"])
    cb_seg_count = len(cb_track["segments"])
    if t6_seg_count != cb_seg_count:
        print(f"  track[{ti}] seg count: T6={t6_seg_count} vs C={cb_seg_count} [DIFF!]")

# Check first segment of each track for extra fields
for ti in range(len(t6["tracks"])):
    t6_keys = set(t6["tracks"][ti].keys())
    cb_keys = set(cb["tracks"][ti].keys())
    if t6_keys != cb_keys:
        print(f"  track[{ti}] keys: T6_only={t6_keys-cb_keys}, C_only={cb_keys-t6_keys}")

    t6_seg_keys = set(t6["tracks"][ti]["segments"][0].keys())
    cb_seg_keys = set(cb["tracks"][ti]["segments"][0].keys())
    if t6_seg_keys != cb_seg_keys:
        print(f"  track[{ti}] seg[0] keys: T6_only={t6_seg_keys-cb_seg_keys}, C_only={cb_seg_keys-t6_seg_keys}")

print("\n=== DONE ===")
