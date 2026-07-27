"""
第四轮：project.json 问题定位 + gen_v11 内容逐字段比对
"""
import json, os, uuid, subprocess, shutil, time, copy

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
FONT_PATH = JY_DIR + "/Resources/Font/SystemFont/zh-hans.ttf"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
TEMPLATE_DIR = r"E:/360Downloads/JianyingPro Drafts/TestReEncrypt"
TASK_DIR = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6"
NOW_US = int(time.time() * 1000000)
NOW_S = int(time.time())
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR

def uid():
    return uuid.uuid4().hex

def decrypt(enc_path, out_path):
    subprocess.run(["jy-draftc", "-d", enc_path, out_path], env=env,
                   capture_output=True, text=True)

def encrypt(filepath, cwd=None):
    subprocess.run(["jy-draftc", "-e", filepath], cwd=cwd or os.path.dirname(filepath),
                   env=env, capture_output=True, text=True)
    enc_out = filepath + ".enc.json"
    if os.path.exists(enc_out):
        os.remove(filepath)
        os.rename(enc_out, filepath)
        return True
    return False

def make_dir(name):
    d = os.path.join(DRAFT_ROOT, name)
    if os.path.exists(d): shutil.rmtree(d)
    os.makedirs(d)
    return d

def register(name, draft_dir, draft_id):
    meta_path = r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json"
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    all_drafts = meta.get("all_draft_store", [])
    all_drafts = [d for d in all_drafts if draft_id not in str(d.get("draft_id", ""))]
    dfold = draft_dir.replace("\\", "/")
    all_drafts.insert(0, {
        "cloud_draft_cover": False, "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False,
        "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "", "draft_cloud_videocut_purchase_info": "",
        "draft_cover": dfold + "/draft_cover.jpg",
        "draft_fold_path": dfold,
        "draft_id": draft_id,
        "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
        "draft_is_invisible": False, "draft_is_web_article_video": False,
        "draft_json_file": dfold + "/draft_content.json",
        "draft_name": name,
        "draft_new_version": "164.0.0",
        "draft_root_path": DRAFT_ROOT.replace("\\", "/"),
        "draft_timeline_materials_size": 0, "draft_type": "",
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

# ======== Load template ========
tmpl_enc = os.path.join(TEMPLATE_DIR, "draft_content.json")
tmpl_dec = os.path.join(TEMPLATE_DIR, "draft_content.iso4.json")
decrypt(tmpl_enc, tmpl_dec)
with open(tmpl_dec, "r", encoding="utf-8") as f:
    template = json.load(f)

tl_src = os.path.join(TEMPLATE_DIR, "Timelines")

# ======== Test N2: project.json UUID change + fix proj.id + delete .bak ========
print("=== Test N2: Fix project.json properly ===")
draft_n2 = copy.deepcopy(template)

dir_n2 = make_dir("TestN2_ProjFix")
dc_n2 = os.path.join(dir_n2, "draft_content.json")
with open(dc_n2, "w", encoding="utf-8") as f:
    json.dump(draft_n2, f, ensure_ascii=False, indent=2)

for fn in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
    sf = os.path.join(TEMPLATE_DIR, fn)
    if os.path.exists(sf): shutil.copy2(sf, os.path.join(dir_n2, fn))

tl_dst_n2 = os.path.join(dir_n2, "Timelines")
shutil.copytree(tl_src, tl_dst_n2)

# Fix project.json - update ALL UUID references
proj_path = os.path.join(tl_dst_n2, "project.json")
with open(proj_path, "r", encoding="utf-8") as f:
    proj = json.load(f)

print(f"  Template project.json:")
print(f"    id: {proj.get('id')}")
print(f"    main_timeline_id: {proj.get('main_timeline_id')}")
print(f"    timelines: {len(proj.get('timelines', []))} entries")
for i, tl in enumerate(proj.get("timelines", [])):
    print(f"      [{i}] id: {tl.get('id')}")

# Read the existing timeline UUID from first entry
old_tl_id = proj["timelines"][0]["id"]
new_tl_id = str(uuid.uuid4()).upper()

# Update ALL references
proj["id"] = new_tl_id  # <-- THIS WAS MISSING BEFORE!
proj["main_timeline_id"] = new_tl_id
proj["create_time"] = NOW_US
proj["update_time"] = NOW_US
proj["timelines"][0]["id"] = new_tl_id
proj["timelines"][0]["create_time"] = NOW_US
proj["timelines"][0]["update_time"] = NOW_US

with open(proj_path, "w", encoding="utf-8") as f:
    json.dump(proj, f, ensure_ascii=False, indent=2)

# Delete .bak
bak_path = os.path.join(tl_dst_n2, "project.json.bak")
if os.path.exists(bak_path):
    os.remove(bak_path)
    print("  Deleted project.json.bak")

# Rename timeline dir
for d in os.listdir(tl_dst_n2):
    dp = os.path.join(tl_dst_n2, d)
    if os.path.isdir(dp) and d != "common_attachment" and d.upper() != new_tl_id.upper():
        os.rename(dp, os.path.join(tl_dst_n2, new_tl_id))
        print(f"  Renamed: {d} -> {new_tl_id}")
        # Copy dc
        shutil.copy2(dc_n2, os.path.join(tl_dst_n2, new_tl_id, "draft_content.json"))
        break

encrypt(dc_n2)
for d in os.listdir(tl_dst_n2):
    dp = os.path.join(tl_dst_n2, d)
    if os.path.isdir(dp) and d != "common_attachment":
        encrypt(os.path.join(dp, "draft_content.json"), dp)
register("TestN2_ProjFix", dir_n2, "TestN2-" + str(int(time.time())))
print("Test N2 registered")

# ======== DETAILED COMPARISON: TestP vs Template ========
print("\n" + "=" * 60)
print("DETAILED FIELD-BY-FIELD: Template vs TestP draft_content.json")
print("=" * 60)

# Decrypt TestP
testp_enc = os.path.join(DRAFT_ROOT, "TestP_NoProjChg", "draft_content.json")
if not os.path.exists(testp_enc):
    print("TestP not found, comparing TestO instead")
    testp_enc = os.path.join(DRAFT_ROOT, "TestO_SmallFull", "draft_content.json")

testp_dec = testp_enc.replace(".json", ".debug.json")
decrypt(testp_enc, testp_dec)
with open(testp_dec, "r", encoding="utf-8") as f:
    testp = json.load(f)

def compare_structures(t, g, prefix="", max_diffs=30):
    """Deep compare but stop after max_diffs"""
    diffs = []

    if type(t) != type(g):
        diffs.append(f"{prefix}: TYPE {type(t).__name__} vs {type(g).__name__}")
        return diffs

    if isinstance(t, dict):
        t_keys = set(t.keys())
        g_keys = set(g.keys())
        for k in sorted(t_keys - g_keys):
            diffs.append(f"{prefix}.{k}: MISSING")
            if len(diffs) >= max_diffs: return diffs
        for k in sorted(g_keys - t_keys):
            diffs.append(f"{prefix}.{k}: EXTRA (val={str(g[k])[:80]})")
            if len(diffs) >= max_diffs: return diffs
        for k in sorted(t_keys & g_keys):
            if len(diffs) >= max_diffs: return diffs
            sub = compare_structures(t[k], g[k], f"{prefix}.{k}", max_diffs - len(diffs))
            diffs.extend(sub)
    elif isinstance(t, list):
        if len(t) != len(g):
            diffs.append(f"{prefix}: LEN {len(t)} vs {len(g)}")
            if len(diffs) >= max_diffs: return diffs
        for i in range(min(len(t), len(g))):
            if len(diffs) >= max_diffs: return diffs
            sub = compare_structures(t[i], g[i], f"{prefix}[{i}]", max_diffs - len(diffs))
            diffs.extend(sub)
    else:
        if t != g:
            ts = str(t)
            gs = str(g)
            if len(ts) > 100: ts = ts[:100] + "..."
            if len(gs) > 100: gs = gs[:100] + "..."
            diffs.append(f"{prefix}: T={ts}  G={gs}")

    return diffs

# First compare top-level
print("\n--- Top-level keys ---")
t_keys = set(template.keys())
g_keys = set(testp.keys())
for k in sorted(t_keys - g_keys): print(f"  MISSING: {k}")
for k in sorted(g_keys - t_keys): print(f"  EXTRA: {k}")

# Compare each track type
print("\n--- Track 0 (video): first segment comparison ---")
tv = template["tracks"][0]["segments"][0]
gv = testp["tracks"][0]["segments"][0]
diffs = compare_structures(tv, gv, "video_seg")
for d in diffs:
    print(f"  {d}")

# Compare video material
print("\n--- First video material ---")
tm = template["materials"]["videos"][0]
gm = testp["materials"]["videos"][0]
diffs = compare_structures(tm, gm, "video_mat")
for d in diffs:
    print(f"  {d}")

# Compare text material
print("\n--- First text material ---")
tm = template["materials"]["texts"][0]
gm = testp["materials"]["texts"][0]
diffs = compare_structures(tm, gm, "text_mat")
for d in diffs:
    print(f"  {d}")

# Compare audio material
print("\n--- Audio material ---")
tm = template["materials"]["audios"][0]
gm = testp["materials"]["audios"][0]
diffs = compare_structures(tm, gm, "audio_mat")
for d in diffs:
    print(f"  {d}")

# Compare canvas_config
print("\n--- canvas_config ---")
diffs = compare_structures(template.get("canvas_config", {}), testp.get("canvas_config", {}), "canvas_config")
for d in diffs:
    print(f"  {d}")

# Check specific sensitive fields
print("\n--- Check audio music_id vs id ---")
ta = template["materials"]["audios"][0]
ga = testp["materials"]["audios"][0]
print(f"  Template: id={ta['id'][:12]}... music_id={ta.get('music_id', 'N/A')[:12] if ta.get('music_id') else 'N/A'}...")
print(f"  TestP:    id={ga['id'][:12]}... music_id={ga.get('music_id', 'N/A')[:12] if ga.get('music_id') else 'N/A'}...")

print("\n--- Check text segment target_timerange ---")
tt = template["tracks"][2]["segments"][0]["target_timerange"]
gt = testp["tracks"][2]["segments"][0]["target_timerange"]
print(f"  Template: {tt}")
print(f"  TestP:    {gt}")

print("\n--- Check video segment extra_material_refs count ---")
tv_refs = template["tracks"][0]["segments"][0].get("extra_material_refs", [])
gv_refs = testp["tracks"][0]["segments"][0].get("extra_material_refs", [])
print(f"  Template: {len(tv_refs)} refs")
print(f"  TestP:    {len(gv_refs)} refs")

# TYPE check all materials
print("\n--- Material type checks ---")
for cat in template["materials"]:
    tmats = template["materials"].get(cat, [])
    gmats = testp["materials"].get(cat, [])
    if tmats and gmats:
        t0 = tmats[0]
        g0 = gmats[0]
        # Compare keys
        tk = set(t0.keys())
        gk = set(g0.keys())
        extra = gk - tk
        missing = tk - gk
        if extra or missing:
            print(f"  {cat}: T_keys={sorted(tk)}, G_keys={sorted(gk)}")
            if missing: print(f"    MISSING keys: {missing}")
            if extra: print(f"    EXTRA keys: {extra}")

# Check if any material has "type" field difference
print("\n--- Material 'type' field values ---")
for cat in template["materials"]:
    tmats = template["materials"].get(cat, [])
    gmats = testp["materials"].get(cat, [])
    if tmats and gmats:
        tt_val = tmats[0].get("type", "N/A")
        gt_val = gmats[0].get("type", "N/A")
        if tt_val != gt_val:
            print(f"  {cat}: T={tt_val} vs G={gt_val}")

# Check track ordering/types
print("\n--- Track types ---")
for i, (tt, gt) in enumerate(zip(template["tracks"], testp["tracks"])):
    print(f"  [{i}] T: type={tt['type']}, segs={len(tt['segments'])}")
    print(f"  [{i}] G: type={gt['type']}, segs={len(gt['segments'])}")

print("\nDone comparing")
