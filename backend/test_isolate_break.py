"""
渐进测试：从能打开的模板出发，每次只改一件事，定位剪映拒绝的原因
"""
import json, os, uuid, subprocess, shutil, time, copy

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
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

def make_draft_dir(name):
    d = os.path.join(DRAFT_ROOT, name)
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    return d

def register(name, draft_dir, draft_id, total_mat_size=0):
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

# ======== 加载模板 ========
tmpl_enc = os.path.join(TEMPLATE_DIR, "draft_content.json")
tmpl_dec = os.path.join(TEMPLATE_DIR, "draft_content.iso.json")
decrypt(tmpl_enc, tmpl_dec)
with open(tmpl_dec, "r", encoding="utf-8") as f:
    template = json.load(f)

# Get our actual image paths
images_dir = os.path.join(TASK_DIR, "images")
img_files = sorted([f for f in os.listdir(images_dir) if f.endswith(".png") and f.startswith("seg_")])
our_images = [os.path.join(images_dir, f).replace("\\", "/") for f in img_files[:3]]
print(f"Our images: {our_images}")

# ======== Test A: 只改图片路径（不改结构/数量） ========
print("\n=== Test A: Change image paths only (same count) ===")
draft_a = copy.deepcopy(template)
for i, mat in enumerate(draft_a["materials"]["videos"]):
    if i < len(our_images):
        mat["path"] = our_images[i]
        mat["material_name"] = os.path.basename(our_images[i])

dir_a = make_draft_dir("TestA_PathOnly")
dc_a = os.path.join(dir_a, "draft_content.json")
with open(dc_a, "w", encoding="utf-8") as f:
    json.dump(draft_a, f, ensure_ascii=False, indent=2)

# Copy companion files
for fname in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
    sf = os.path.join(TEMPLATE_DIR, fname)
    if os.path.exists(sf):
        shutil.copy2(sf, os.path.join(dir_a, fname))
tl_src = os.path.join(TEMPLATE_DIR, "Timelines")
tl_dst = os.path.join(dir_a, "Timelines")
if os.path.exists(tl_dst): shutil.rmtree(tl_dst)
shutil.copytree(tl_src, tl_dst)
# Copy new dc to timeline
for d in os.listdir(tl_dst):
    dp = os.path.join(tl_dst, d)
    if os.path.isdir(dp) and d != "common_attachment":
        shutil.copy2(dc_a, os.path.join(dp, "draft_content.json"))

encrypt(dc_a)
for d in os.listdir(tl_dst):
    dp = os.path.join(tl_dst, d)
    if os.path.isdir(dp) and d != "common_attachment":
        tl_dc = os.path.join(dp, "draft_content.json")
        encrypt(tl_dc, dp)
register("TestA_PathOnly", dir_a, "TestA-" + str(int(time.time())))
print("Test A registered")

# ======== Test B: 只改 segment duration（结构不变） ========
print("\n=== Test B: Change durations only ===")
draft_b = copy.deepcopy(template)
new_dur = 3000000  # 3s per segment instead of 5s
for seg in draft_b["tracks"][0]["segments"]:
    seg["source_timerange"]["duration"] = new_dur
    seg["target_timerange"]["duration"] = new_dur
draft_b["duration"] = new_dur * len(draft_b["tracks"][0]["segments"])

dir_b = make_draft_dir("TestB_DurOnly")
dc_b = os.path.join(dir_b, "draft_content.json")
with open(dc_b, "w", encoding="utf-8") as f:
    json.dump(draft_b, f, ensure_ascii=False, indent=2)
for fname in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
    sf = os.path.join(TEMPLATE_DIR, fname)
    if os.path.exists(sf): shutil.copy2(sf, os.path.join(dir_b, fname))
if os.path.exists(os.path.join(dir_b, "Timelines")): shutil.rmtree(os.path.join(dir_b, "Timelines"))
shutil.copytree(tl_src, os.path.join(dir_b, "Timelines"))
for d in os.listdir(os.path.join(dir_b, "Timelines")):
    dp = os.path.join(dir_b, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        shutil.copy2(dc_b, os.path.join(dp, "draft_content.json"))
encrypt(dc_b)
for d in os.listdir(os.path.join(dir_b, "Timelines")):
    dp = os.path.join(dir_b, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        encrypt(os.path.join(dp, "draft_content.json"), dp)
register("TestB_DurOnly", dir_b, "TestB-" + str(int(time.time())))
print("Test B registered")

# ======== Test C: 只改 new_version（内容完全相同） ========
print("\n=== Test C: Change new_version only ===")
draft_c = copy.deepcopy(template)
draft_c["new_version"] = "177.0.0"

dir_c = make_draft_dir("TestC_VerOnly")
dc_c = os.path.join(dir_c, "draft_content.json")
with open(dc_c, "w", encoding="utf-8") as f:
    json.dump(draft_c, f, ensure_ascii=False, indent=2)
for fname in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
    sf = os.path.join(TEMPLATE_DIR, fname)
    if os.path.exists(sf): shutil.copy2(sf, os.path.join(dir_c, fname))
if os.path.exists(os.path.join(dir_c, "Timelines")): shutil.rmtree(os.path.join(dir_c, "Timelines"))
shutil.copytree(tl_src, os.path.join(dir_c, "Timelines"))
for d in os.listdir(os.path.join(dir_c, "Timelines")):
    dp = os.path.join(dir_c, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        shutil.copy2(dc_c, os.path.join(dp, "draft_content.json"))
encrypt(dc_c)
for d in os.listdir(os.path.join(dir_c, "Timelines")):
    dp = os.path.join(dir_c, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        encrypt(os.path.join(dp, "draft_content.json"), dp)
register("TestC_VerOnly", dir_c, "TestC-" + str(int(time.time())))
print("Test C registered")

# ======== Test D: 只改 material UUIDs（结构完全不变） ========
print("\n=== Test D: Regenerate all UUIDs (same structure) ===")
draft_d = copy.deepcopy(template)
id_map_d = {}  # old -> new

# Remap all material IDs
for cat in ["videos", "audios", "texts", "canvases", "speeds", "material_animations",
            "material_colors", "sound_channel_mappings", "loudnesses", "placeholder_infos",
            "vocal_separations"]:
    for mat in draft_d["materials"].get(cat, []):
        old_id = mat["id"]
        new_id = uid()
        id_map_d[old_id] = new_id
        mat["id"] = new_id
        if "material_id" in mat:
            mat["material_id"] = new_id
        if "music_id" in mat:
            mat["music_id"] = new_id
        if "local_material_id" in mat:
            mat["local_material_id"] = new_id

# Remap segment material_ids and extra_material_refs
for track in draft_d["tracks"]:
    for seg in track["segments"]:
        seg["id"] = uid()
        if seg.get("material_id") in id_map_d:
            seg["material_id"] = id_map_d[seg["material_id"]]
        refs = seg.get("extra_material_refs", [])
        seg["extra_material_refs"] = [id_map_d.get(r, r) for r in refs]

dir_d = make_draft_dir("TestD_NewUUIDs")
dc_d = os.path.join(dir_d, "draft_content.json")
with open(dc_d, "w", encoding="utf-8") as f:
    json.dump(draft_d, f, ensure_ascii=False, indent=2)
for fname in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
    sf = os.path.join(TEMPLATE_DIR, fname)
    if os.path.exists(sf): shutil.copy2(sf, os.path.join(dir_d, fname))
if os.path.exists(os.path.join(dir_d, "Timelines")): shutil.rmtree(os.path.join(dir_d, "Timelines"))
shutil.copytree(tl_src, os.path.join(dir_d, "Timelines"))
for d in os.listdir(os.path.join(dir_d, "Timelines")):
    dp = os.path.join(dir_d, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        shutil.copy2(dc_d, os.path.join(dp, "draft_content.json"))
encrypt(dc_d)
for d in os.listdir(os.path.join(dir_d, "Timelines")):
    dp = os.path.join(dir_d, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        encrypt(os.path.join(dp, "draft_content.json"), dp)
register("TestD_NewUUIDs", dir_d, "TestD-" + str(int(time.time())))
print("Test D registered")

# ======== Test E: 只增加视频段（2→3），其他不变 ========
print("\n=== Test E: Add 1 more video segment (2 → 3) ===")
draft_e = copy.deepcopy(template)
proto_vseg = copy.deepcopy(draft_e["tracks"][0]["segments"][0])
proto_vmat = copy.deepcopy(draft_e["materials"]["videos"][0])
proto_canvas = copy.deepcopy(draft_e["materials"]["canvases"][0])
proto_speed = copy.deepcopy(draft_e["materials"]["speeds"][0])
proto_anim = copy.deepcopy(draft_e["materials"]["material_animations"][0])
proto_color = copy.deepcopy(draft_e["materials"]["material_colors"][0])
proto_sound = copy.deepcopy(draft_e["materials"]["sound_channel_mappings"][0])
proto_loud = copy.deepcopy(draft_e["materials"]["loudnesses"][0])
proto_ph = copy.deepcopy(draft_e["materials"]["placeholder_infos"][0])
proto_vocal = copy.deepcopy(draft_e["materials"]["vocal_separations"][0])

# Generate new IDs
vmid = uid(); cid = uid(); sid = uid(); aid = uid()
coid = uid(); soid = uid(); lid = uid(); phid = uid(); vcid = uid()
seg_id = uid()

# New video material
new_vmat = copy.deepcopy(proto_vmat)
new_vmat["id"] = vmid; new_vmat["material_id"] = vmid

# New segment
last_seg = draft_e["tracks"][0]["segments"][-1]
last_end = last_seg["target_timerange"]["start"] + last_seg["target_timerange"]["duration"]
new_seg = copy.deepcopy(proto_vseg)
new_seg["id"] = seg_id
new_seg["material_id"] = vmid
new_seg["target_timerange"] = {"start": last_end, "duration": 5000000}
new_seg["extra_material_refs"] = [sid, phid, cid, aid, coid, soid, lid, vcid]

# New auxiliary materials
for lst, pid, proto in [
    (draft_e["materials"]["canvases"], cid, proto_canvas),
    (draft_e["materials"]["speeds"], sid, proto_speed),
    (draft_e["materials"]["material_animations"], aid, proto_anim),
    (draft_e["materials"]["material_colors"], coid, proto_color),
    (draft_e["materials"]["sound_channel_mappings"], soid, proto_sound),
    (draft_e["materials"]["loudnesses"], lid, proto_loud),
    (draft_e["materials"]["placeholder_infos"], phid, proto_ph),
    (draft_e["materials"]["vocal_separations"], vcid, proto_vocal),
]:
    m = copy.deepcopy(proto); m["id"] = pid; lst.append(m)

draft_e["materials"]["videos"].append(new_vmat)
draft_e["tracks"][0]["segments"].append(new_seg)
draft_e["duration"] = last_end + 5000000

dir_e = make_draft_dir("TestE_AddSeg")
dc_e = os.path.join(dir_e, "draft_content.json")
with open(dc_e, "w", encoding="utf-8") as f:
    json.dump(draft_e, f, ensure_ascii=False, indent=2)
for fname in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
    sf = os.path.join(TEMPLATE_DIR, fname)
    if os.path.exists(sf): shutil.copy2(sf, os.path.join(dir_e, fname))
if os.path.exists(os.path.join(dir_e, "Timelines")): shutil.rmtree(os.path.join(dir_e, "Timelines"))
shutil.copytree(tl_src, os.path.join(dir_e, "Timelines"))
for d in os.listdir(os.path.join(dir_e, "Timelines")):
    dp = os.path.join(dir_e, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        shutil.copy2(dc_e, os.path.join(dp, "draft_content.json"))
encrypt(dc_e)
for d in os.listdir(os.path.join(dir_e, "Timelines")):
    dp = os.path.join(dir_e, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        encrypt(os.path.join(dp, "draft_content.json"), dp)
register("TestE_AddSeg", dir_e, "TestE-" + str(int(time.time())))
print("Test E registered")

# ======== Test F: 移除 attachment 文件 ========
print("\n=== Test F: Remove attachment files (keep core only) ===")
draft_f = copy.deepcopy(template)
dir_f = make_draft_dir("TestF_NoAttachment")
dc_f = os.path.join(dir_f, "draft_content.json")
with open(dc_f, "w", encoding="utf-8") as f:
    json.dump(draft_f, f, ensure_ascii=False, indent=2)
for fname in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
    sf = os.path.join(TEMPLATE_DIR, fname)
    if os.path.exists(sf): shutil.copy2(sf, os.path.join(dir_f, fname))

# Manually build minimal Timelines/
tl_f = os.path.join(dir_f, "Timelines")
os.makedirs(tl_f)
# project.json
proj_f = {
    "id": str(uuid.uuid4()).upper(),
    "main_timeline_id": str(uuid.uuid4()).upper(),
    "create_time": NOW_US, "update_time": NOW_US,
    "default_timeline_params": {"aspect_ratio": "9:16"},
    "timelines": [{"id": str(uuid.uuid4()).upper(), "create_time": NOW_US, "update_time": NOW_US}]
}
with open(os.path.join(tl_f, "project.json"), "w", encoding="utf-8") as f:
    json.dump(proj_f, f, ensure_ascii=False, indent=2)

# Minimal timeline dir
tl_sub_f = os.path.join(tl_f, str(uuid.uuid4()).upper())
os.makedirs(tl_sub_f)
shutil.copy2(dc_f, os.path.join(tl_sub_f, "draft_content.json"))

encrypt(dc_f)
encrypt(os.path.join(tl_sub_f, "draft_content.json"), tl_sub_f)
register("TestF_NoAttachment", dir_f, "TestF-" + str(int(time.time())))
print("Test F registered")

# ======== Test G: 用 gen_v11_fixed 的方式生成，但只复制 attachments 不做 id mapping 更新 ========
print("\n=== Test G: Our full method but keep old attachment_id_mapping ===")
# This is same as our Task6_v11_fixed but without updating attachment_id_mapping
# (to isolate if that's still the issue)
# Skip for now - Test D already tests UUID changes with old attachments

print(f"\n{'='*60}")
print("ALL TESTS REGISTERED")
print("Tests A-F ready. Open 剪映 and report which can/cannot open.")
print("A: path change  B: duration  C: version  D: new UUIDs  E: +1 segment  F: no attachments")
