"""
第二轮隔离测试：定位 Task6_v11 打不开的真正原因
已知：A-E 都能开，F 不能 → attachment 必须存在但内容可能冲突
"""
import json, os, uuid, subprocess, shutil, time, copy

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
FONT_PATH = JY_DIR + "/Resources/Font/SystemFont/zh-hans.ttf"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
TEMPLATE_DIR = r"E:/360Downloads/JianyingPro Drafts/TestReEncrypt"
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

def copy_companion(src_dir, dst_dir):
    for fn in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
        sf = os.path.join(src_dir, fn)
        if os.path.exists(sf): shutil.copy2(sf, os.path.join(dst_dir, fn))
    tl_src = os.path.join(src_dir, "Timelines")
    tl_dst = os.path.join(dst_dir, "Timelines")
    if os.path.exists(tl_dst): shutil.rmtree(tl_dst)
    shutil.copytree(tl_src, tl_dst)

def copy_dc_to_timeline(dc_path, tl_dir):
    for d in os.listdir(tl_dir):
        dp = os.path.join(tl_dir, d)
        if os.path.isdir(dp) and d != "common_attachment":
            shutil.copy2(dc_path, os.path.join(dp, "draft_content.json"))

def encrypt_all(dir_path):
    dc = os.path.join(dir_path, "draft_content.json")
    encrypt(dc)
    tl = os.path.join(dir_path, "Timelines")
    for d in os.listdir(tl):
        dp = os.path.join(tl, d)
        if os.path.isdir(dp) and d != "common_attachment":
            encrypt(os.path.join(dp, "draft_content.json"), dp)

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

# ======== 加载模板 ========
tmpl_enc = os.path.join(TEMPLATE_DIR, "draft_content.json")
tmpl_dec = os.path.join(TEMPLATE_DIR, "draft_content.iso2.json")
decrypt(tmpl_enc, tmpl_dec)
with open(tmpl_dec, "r", encoding="utf-8") as f:
    template = json.load(f)

proto_text_mat = copy.deepcopy(template["materials"]["texts"][0])
proto_text_seg = copy.deepcopy(template["tracks"][2]["segments"][0])

# Print template text material for reference
print("=== Template text material ===")
print(f"  content: {proto_text_mat.get('content', 'N/A')[:200]}")
print(f"  font_path: {proto_text_mat.get('font_path', 'N/A')}")
print(f"  Keys: {list(proto_text_mat.keys())}")

# ======== Test G: 只多加 text segment (不改 font/content) ========
print("\n=== Test G: Add text segments (clone template's text exactly) ===")
draft_g = copy.deepcopy(template)
last_text_seg = draft_g["tracks"][2]["segments"][-1]
last_text_end = last_text_seg["target_timerange"].get("start", 0) + last_text_seg["target_timerange"]["duration"]

new_text_mat = copy.deepcopy(proto_text_mat)
new_text_mat["id"] = uid()
new_text_seg = copy.deepcopy(proto_text_seg)
new_text_seg["id"] = uid()
new_text_seg["material_id"] = new_text_mat["id"]
new_text_seg["target_timerange"] = {"start": last_text_end, "duration": 3000000}

draft_g["materials"]["texts"].append(new_text_mat)
draft_g["tracks"][2]["segments"].append(new_text_seg)

dir_g = make_dir("TestG_AddText")
dc_g = os.path.join(dir_g, "draft_content.json")
with open(dc_g, "w", encoding="utf-8") as f:
    json.dump(draft_g, f, ensure_ascii=False, indent=2)
copy_companion(TEMPLATE_DIR, dir_g)
copy_dc_to_timeline(dc_g, os.path.join(dir_g, "Timelines"))
encrypt_all(dir_g)
register("TestG_AddText", dir_g, "TestG-" + str(int(time.time())))
print("Test G registered")

# ======== Test H: 改 font_path ========
print("\n=== Test H: Change font_path ===")
draft_h = copy.deepcopy(template)
draft_h["materials"]["texts"][0]["font_path"] = FONT_PATH

dir_h = make_dir("TestH_FontPath")
dc_h = os.path.join(dir_h, "draft_content.json")
with open(dc_h, "w", encoding="utf-8") as f:
    json.dump(draft_h, f, ensure_ascii=False, indent=2)
copy_companion(TEMPLATE_DIR, dir_h)
copy_dc_to_timeline(dc_h, os.path.join(dir_h, "Timelines"))
encrypt_all(dir_h)
register("TestH_FontPath", dir_h, "TestH-" + str(int(time.time())))
print("Test H registered")

# ======== Test I: 改 text content ========
print("\n=== Test I: Change text content (same structure) ===")
draft_i = copy.deepcopy(template)
old_content = json.loads(draft_i["materials"]["texts"][0]["content"])
old_text = old_content.get("text", "")
new_content_json = json.dumps({
    "styles": old_content.get("styles", []),
    "text": "测试文字替换" + old_text[:10]
}, ensure_ascii=False)
draft_i["materials"]["texts"][0]["content"] = new_content_json

dir_i = make_dir("TestI_TextContent")
dc_i = os.path.join(dir_i, "draft_content.json")
with open(dc_i, "w", encoding="utf-8") as f:
    json.dump(draft_i, f, ensure_ascii=False, indent=2)
copy_companion(TEMPLATE_DIR, dir_i)
copy_dc_to_timeline(dc_i, os.path.join(dir_i, "Timelines"))
encrypt_all(dir_i)
register("TestI_TextContent", dir_i, "TestI-" + str(int(time.time())))
print("Test I registered")

# ======== Test J: 改 audio path ========
print("\n=== Test J: Change audio path ===")
audio_path = "D:/VideoWorkstation_Deploy/backend/data/tasks/6/final_audio.mp3"
if not os.path.exists(audio_path):
    audio_path = "D:/VideoWorkstation_Deploy/backend/data/tasks/6/final_tts.mp3"
audio_path = audio_path.replace("\\", "/")
draft_j = copy.deepcopy(template)
draft_j["materials"]["audios"][0]["path"] = audio_path
draft_j["materials"]["audios"][0]["name"] = os.path.basename(audio_path)

dir_j = make_dir("TestJ_AudioPath")
dc_j = os.path.join(dir_j, "draft_content.json")
with open(dc_j, "w", encoding="utf-8") as f:
    json.dump(draft_j, f, ensure_ascii=False, indent=2)
copy_companion(TEMPLATE_DIR, dir_j)
copy_dc_to_timeline(dc_j, os.path.join(dir_j, "Timelines"))
encrypt_all(dir_j)
register("TestJ_AudioPath", dir_j, "TestJ-" + str(int(time.time())))
print("Test J registered")

# ======== Test K: 修改 draft_meta_info.json (改 duration + audio info) ========
print("\n=== Test K: Modify draft_meta_info.json ===")
draft_k = copy.deepcopy(template)  # content unchanged
dir_k = make_dir("TestK_MetaInfo")
dc_k = os.path.join(dir_k, "draft_content.json")
with open(dc_k, "w", encoding="utf-8") as f:
    json.dump(draft_k, f, ensure_ascii=False, indent=2)

# Copy companion files
for fn in ["draft_settings", "draft_cover.jpg"]:
    sf = os.path.join(TEMPLATE_DIR, fn)
    if os.path.exists(sf): shutil.copy2(sf, os.path.join(dir_k, fn))

# Modify draft_meta_info
tmpl_meta_enc = os.path.join(TEMPLATE_DIR, "draft_meta_info.json")
tmpl_meta_dec = os.path.join(TEMPLATE_DIR, "draft_meta_info.k.json")
decrypt(tmpl_meta_enc, tmpl_meta_dec)
with open(tmpl_meta_dec, "r", encoding="utf-8") as f:
    meta_k = json.load(f)
meta_k["draft_id"] = "TestK-" + str(int(time.time()))
meta_k["draft_name"] = "TestK_MetaInfo"
meta_k["draft_fold_path"] = dir_k.replace("\\", "/")
meta_k["tm_duration"] = 20000000  # 20s instead of 10s
meta_k["tm_draft_create"] = NOW_US
meta_k["tm_draft_modified"] = NOW_US
dm_path = os.path.join(dir_k, "draft_meta_info.json")
with open(dm_path, "w", encoding="utf-8") as f:
    json.dump(meta_k, f, ensure_ascii=False, indent=2)

# Copy Timelines
tl_src = os.path.join(TEMPLATE_DIR, "Timelines")
tl_dst = os.path.join(dir_k, "Timelines")
shutil.copytree(tl_src, tl_dst)
copy_dc_to_timeline(dc_k, tl_dst)

# Encrypt both dc AND meta
encrypt(dc_k)
encrypt(dm_path)
for d in os.listdir(tl_dst):
    dp = os.path.join(tl_dst, d)
    if os.path.isdir(dp) and d != "common_attachment":
        encrypt(os.path.join(dp, "draft_content.json"), dp)
register("TestK_MetaInfo", dir_k, "TestK-" + str(int(time.time())))
print("Test K registered")

# ======== Test L: 只增文字段 + 更新 attachment_id_mapping ========
print("\n=== Test L: Add text + update id_mapping ===")
draft_l = copy.deepcopy(template)
last_text_seg_l = draft_l["tracks"][2]["segments"][-1]
last_text_end_l = last_text_seg_l["target_timerange"].get("start", 0) + last_text_seg_l["target_timerange"]["duration"]

new_text_mat_l = copy.deepcopy(proto_text_mat)
new_text_mat_l["id"] = uid()
new_text_seg_l = copy.deepcopy(proto_text_seg)
new_text_seg_l["id"] = uid()
new_text_seg_l["material_id"] = new_text_mat_l["id"]
new_text_seg_l["target_timerange"] = {"start": last_text_end_l, "duration": 3000000}

draft_l["materials"]["texts"].append(new_text_mat_l)
draft_l["tracks"][2]["segments"].append(new_text_seg_l)

# Collect all segment IDs for mapping
all_seg_ids_l = []
for track in draft_l["tracks"]:
    for seg in track["segments"]:
        all_seg_ids_l.append(seg["id"])

dir_l = make_dir("TestL_TextAndMap")
dc_l = os.path.join(dir_l, "draft_content.json")
with open(dc_l, "w", encoding="utf-8") as f:
    json.dump(draft_l, f, ensure_ascii=False, indent=2)
copy_companion(TEMPLATE_DIR, dir_l)
copy_dc_to_timeline(dc_l, os.path.join(dir_l, "Timelines"))

# Update attachment_id_mapping
for d in os.listdir(os.path.join(dir_l, "Timelines")):
    dp = os.path.join(dir_l, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        id_map_path = os.path.join(dp, "common_attachment", "attachment_id_mapping.json")
        if os.path.exists(id_map_path):
            with open(id_map_path, "r", encoding="utf-8") as f:
                id_map = json.load(f)
            new_mappings = [{"short_id": str(1000 + i), "uuid": sid} for i, sid in enumerate(all_seg_ids_l)]
            id_map["id_mapping"]["mapping"] = new_mappings
            with open(id_map_path, "w", encoding="utf-8") as f:
                json.dump(id_map, f, ensure_ascii=False, indent=2)
            print(f"Updated id_mapping: {len(new_mappings)} entries")

encrypt_all(dir_l)
register("TestL_TextAndMap", dir_l, "TestL-" + str(int(time.time())))
print("Test L registered")

# ======== Test M: 大量增文字段 (像 Task6 一样多) ========
print("\n=== Test M: Many text segments (like Task6, ~20) ===")
draft_m = copy.deepcopy(template)
new_texts_m = []
new_segs_m = []
cursor_m = draft_m["tracks"][2]["segments"][-1]["target_timerange"].get("start", 0) + \
            draft_m["tracks"][2]["segments"][-1]["target_timerange"]["duration"]
for i in range(20):
    tmat = copy.deepcopy(proto_text_mat)
    tmat["id"] = uid()
    new_texts_m.append(tmat)
    tseg = copy.deepcopy(proto_text_seg)
    tseg["id"] = uid()
    tseg["material_id"] = tmat["id"]
    tseg["target_timerange"] = {"start": cursor_m, "duration": 2000000}
    new_segs_m.append(tseg)
    cursor_m += 2000000

draft_m["materials"]["texts"] = new_texts_m + draft_m["materials"]["texts"]  # prepend
draft_m["tracks"][2]["segments"] = new_segs_m + draft_m["tracks"][2]["segments"]

all_seg_ids_m = []
for track in draft_m["tracks"]:
    for seg in track["segments"]:
        all_seg_ids_m.append(seg["id"])

dir_m = make_dir("TestM_ManyTexts")
dc_m = os.path.join(dir_m, "draft_content.json")
with open(dc_m, "w", encoding="utf-8") as f:
    json.dump(draft_m, f, ensure_ascii=False, indent=2)
copy_companion(TEMPLATE_DIR, dir_m)
copy_dc_to_timeline(dc_m, os.path.join(dir_m, "Timelines"))

# Update id_mapping
for d in os.listdir(os.path.join(dir_m, "Timelines")):
    dp = os.path.join(dir_m, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        id_map_path = os.path.join(dp, "common_attachment", "attachment_id_mapping.json")
        if os.path.exists(id_map_path):
            with open(id_map_path, "r", encoding="utf-8") as f:
                id_map = json.load(f)
            new_mappings = [{"short_id": str(1000 + i), "uuid": sid} for i, sid in enumerate(all_seg_ids_m)]
            id_map["id_mapping"]["mapping"] = new_mappings
            with open(id_map_path, "w", encoding="utf-8") as f:
                json.dump(id_map, f, ensure_ascii=False, indent=2)
            print(f"Updated id_mapping: {len(new_mappings)} entries")

encrypt_all(dir_m)
register("TestM_ManyTexts", dir_m, "TestM-" + str(int(time.time())))
print("Test M registered")

print(f"\n{'='*60}")
print("Tests G-M registered. Open 剪映 and check each.")
print("G: +1 text (exact clone)  H: font_path  I: text content")
print("J: audio path  K: draft_meta_info  L: +text+idmap  M: many texts")
