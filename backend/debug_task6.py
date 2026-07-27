import json, os, subprocess, sys

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR

def decrypt(enc_path, out_path):
    subprocess.run(["jy-draftc", "-d", enc_path, out_path], env=env, capture_output=True, text=True)

# Decrypt Task6
t6_enc = r"E:/360Downloads/JianyingPro Drafts/Task6/draft_content.json"
t6_dec = t6_enc + ".debug.json"
decrypt(t6_enc, t6_dec)
with open(t6_dec, "r", encoding="utf-8") as f:
    t6 = json.load(f)

# Decrypt S20
s20_enc = r"E:/360Downloads/JianyingPro Drafts/TestS20_Transform/draft_content.json"
s20_dec = s20_enc + ".debug.json"
decrypt(s20_enc, s20_dec)
with open(s20_dec, "r", encoding="utf-8") as f:
    s20 = json.load(f)

# Check video extra_material_refs index correctness
print("=== Task6: Video segment aux refs ===")
for cat in ["speeds", "placeholder_infos", "canvases", "material_animations",
            "sound_channel_mappings", "material_colors", "loudnesses", "vocal_separations"]:
    print(f"  {cat}: {len(t6['materials'][cat])} items")

print("\n=== First 3 video segment refs ===")
VIDEO_REF_ORDER = ["speeds", "placeholder_infos", "canvases", "material_animations",
                   "sound_channel_mappings", "material_colors", "loudnesses", "vocal_separations"]
for seg_idx in range(min(3, len(t6["tracks"][0]["segments"]))):
    seg = t6["tracks"][0]["segments"][seg_idx]
    refs = seg["extra_material_refs"]
    print(f"\n  Video seg {seg_idx}:")
    for ri, rid in enumerate(refs):
        # Find which cat and index
        found = []
        for cat in VIDEO_REF_ORDER:
            for idx, item in enumerate(t6["materials"][cat]):
                if item["id"] == rid:
                    found.append(f"{cat}[{idx}]")
        print(f"    [{ri}] {rid[:16]}... → {found}")

# Check audio refs
print("\n=== Audio segment refs ===")
aseg = t6["tracks"][1]["segments"][0]
for ri, rid in enumerate(aseg["extra_material_refs"]):
    found = []
    for cat in ["speeds", "placeholder_infos", "sound_channel_mappings", "vocal_separations"]:
        for idx, item in enumerate(t6["materials"][cat]):
            if item["id"] == rid:
                found.append(f"{cat}[{idx}]")
    print(f"  [{ri}] {rid[:16]}... → {found}")

# Check target_timerange pattern
print("\n=== target_timerange pattern ===")
for ti, track in enumerate(t6["tracks"]):
    print(f"\n  Track {ti} ({track['type']}): {len(track['segments'])} segments")
    for si, seg in enumerate(track["segments"][:3]):
        tr = seg["target_timerange"]
        has_start = "start" in tr
        print(f"    seg[{si}]: has_start={has_start}, keys={sorted(tr.keys())}")

# Compare with S20
print("\n=== S20: First 3 video segment refs ===")
for seg_idx in range(min(3, len(s20["tracks"][0]["segments"]))):
    seg = s20["tracks"][0]["segments"][seg_idx]
    refs = seg["extra_material_refs"]
    print(f"\n  Video seg {seg_idx}:")
    for ri, rid in enumerate(refs):
        found = []
        for cat in VIDEO_REF_ORDER:
            for idx, item in enumerate(s20["materials"][cat]):
                if item["id"] == rid:
                    found.append(f"{cat}[{idx}]")
        print(f"    [{ri}] {rid[:16]}... → {found}")

# Check material counts
print("\n=== Material counts ===")
for cat in ["videos", "audios", "texts", "canvases", "speeds", "material_animations",
            "material_colors", "sound_channel_mappings", "loudnesses", "placeholder_infos", "vocal_separations"]:
    t6c = len(t6["materials"].get(cat, []))
    s20c = len(s20["materials"].get(cat, []))
    flag = " ***" if t6c != s20c else ""
    print(f"  {cat}: T6={t6c}, S20={s20c}{flag}")

# Check text material fields
print("\n=== Task6 text material first vs S20 ===")
t6_tm = t6["materials"]["texts"][0]
s20_tm = s20["materials"]["texts"][0]
print(f"  T6 keys: {sorted(t6_tm.keys())}")
print(f"  S20 keys: {sorted(s20_tm.keys())}")
extra = set(t6_tm.keys()) - set(s20_tm.keys())
missing = set(s20_tm.keys()) - set(t6_tm.keys())
if extra: print(f"  T6 EXTRA: {extra}")
if missing: print(f"  T6 MISSING: {missing}")

# Check for any null/None values
print("\n=== Checking for null values in Task6 ===")
def check_nulls(obj, path=""):
    issues = []
    if obj is None:
        issues.append(f"{path}: None")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            issues.extend(check_nulls(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            issues.extend(check_nulls(v, f"{path}[{i}]"))
    return issues

nulls = check_nulls(t6, "draft")
if nulls:
    print(f"  Found {len(nulls)} null values:")
    for n in nulls[:20]:
        print(f"    {n}")
else:
    print("  No null values found")

