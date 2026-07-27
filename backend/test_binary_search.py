"""
终极调试：从模板出发，逐步替换成gen_v11内容，每步独立注册
Step 1: 只改 video material 路径 (2个, 不改数量)
Step 2: 只改 text material 内容和字体 (1个, 不改数量)
Step 3: 只改 audio material 路径
Step 4: 只改辅助材料 UUID (不改数量)
Step 5: 增加 video segment (2→3)
Step 6: 增加 text segment (1→5)
Step 7: 以上全部叠加
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
    subprocess.run(["jy-draftc", "-d", enc_path, out_path], env=env, capture_output=True, text=True)

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

def mk_tr(start_us, duration_us):
    if start_us == 0:
        return {"duration": int(duration_us)}
    return {"start": int(start_us), "duration": int(duration_us)}

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

def build_and_register(name, draft_id, draft, image_paths, audio_path, total_dur, modify_meta=False, update_idmap=False):
    """Build draft folder and register it"""
    dir_path = make_dir(name)
    dc_path = os.path.join(dir_path, "draft_content.json")
    with open(dc_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    # Copy companions
    for fn in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
        sf = os.path.join(TEMPLATE_DIR, fn)
        if os.path.exists(sf): shutil.copy2(sf, os.path.join(dir_path, fn))

    # Copy Timelines
    tl_src = os.path.join(TEMPLATE_DIR, "Timelines")
    tl_dst = os.path.join(dir_path, "Timelines")
    shutil.copytree(tl_src, tl_dst)

    # Copy dc to timeline dir
    for d in os.listdir(tl_dst):
        dp = os.path.join(tl_dst, d)
        if os.path.isdir(dp) and d != "common_attachment":
            shutil.copy2(dc_path, os.path.join(dp, "draft_content.json"))
            if update_idmap:
                all_seg_ids = []
                for track in draft["tracks"]:
                    for seg in track["segments"]:
                        all_seg_ids.append(seg["id"])
                id_map_path = os.path.join(dp, "common_attachment", "attachment_id_mapping.json")
                if os.path.exists(id_map_path):
                    with open(id_map_path, "r", encoding="utf-8") as f:
                        id_map = json.load(f)
                    id_map["id_mapping"]["mapping"] = [{"short_id": str(1000 + i), "uuid": sid} for i, sid in enumerate(all_seg_ids)]
                    with open(id_map_path, "w", encoding="utf-8") as f:
                        json.dump(id_map, f, ensure_ascii=False, indent=2)
            break

    # Modify draft_meta_info if needed
    if modify_meta:
        dm_enc = os.path.join(dir_path, "draft_meta_info.json")
        dm_dec = os.path.join(dir_path, "draft_meta_info.dec.json")
        decrypt(dm_enc, dm_dec)
        with open(dm_dec, "r", encoding="utf-8") as f:
            dmeta = json.load(f)
        dmeta["draft_id"] = draft_id
        dmeta["draft_name"] = name
        dmeta["draft_fold_path"] = dir_path.replace("\\", "/")
        dmeta["draft_root_path"] = DRAFT_ROOT.replace("\\", "/")
        dmeta["tm_duration"] = total_dur
        dmeta["tm_draft_create"] = NOW_US
        dmeta["tm_draft_modified"] = NOW_US
        if dmeta.get("draft_materials"):
            for grp in dmeta["draft_materials"]:
                if grp.get("type") == 0 and grp.get("value"):
                    grp["value"][0]["duration"] = total_dur
                    if "roughcut_time_range" in grp["value"][0]:
                        grp["value"][0]["roughcut_time_range"]["duration"] = total_dur
        with open(dm_dec, "w", encoding="utf-8") as f:
            json.dump(dmeta, f, ensure_ascii=False, indent=2)
        os.remove(dm_enc)  # Remove encrypted copy
        os.rename(dm_dec, dm_enc)

    # Cover
    if image_paths:
        cov_path = os.path.join(dir_path, "draft_cover.jpg")
        if os.path.exists(image_paths[0]):
            shutil.copy2(image_paths[0], cov_path)

    # Encrypt
    encrypt(dc_path)
    if modify_meta:
        encrypt(os.path.join(dir_path, "draft_meta_info.json"))
    for d in os.listdir(tl_dst):
        dp = os.path.join(tl_dst, d)
        if os.path.isdir(dp) and d != "common_attachment":
            encrypt(os.path.join(dp, "draft_content.json"), dp)

    register(name, dir_path, draft_id)
    return True

# ======== Load template & data ========
tmpl_enc = os.path.join(TEMPLATE_DIR, "draft_content.json")
tmpl_dec = os.path.join(TEMPLATE_DIR, "draft_content.bs.json")
decrypt(tmpl_enc, tmpl_dec)
with open(tmpl_dec, "r", encoding="utf-8") as f:
    template = json.load(f)

from services.llm_service import split_into_short_sentences
from services.video_service import get_audio_duration, split_into_word_groups

images_dir = os.path.join(TASK_DIR, "images")
img_files = sorted([f for f in os.listdir(images_dir) if f.endswith(".png") and f.startswith("seg_")])[:5]
img_map = {}
for f in img_files:
    seg_idx = int(f.replace("seg_", "").replace(".png", ""))
    img_map[seg_idx] = os.path.join(images_dir, f).replace("\\", "/")
image_paths = [img_map.get(i, img_map.get(0, "")) for i in range(5)]

segments_dir = os.path.join(TASK_DIR, "segments")
seg_files = sorted([f for f in os.listdir(segments_dir) if f.endswith(".mp3") and f.startswith("seg_")])[:5]
tts_durs = [get_audio_duration(os.path.join(segments_dir, sf)) for sf in seg_files]
seg_durations = [d * 1_000_000 for d in tts_durs]
total_dur = int(sum(seg_durations))

with open(os.path.join(TASK_DIR, "rewritten.txt"), "r", encoding="utf-8") as f:
    raw = f.read()
full_text = ""
for line in raw.strip().split("\n")[:3]:
    if not line.strip(): continue
    parts = line.split("\t", 1)
    full_text += parts[1] if len(parts) > 1 else parts[0]
sentences = split_into_short_sentences(full_text, max_chars=80, min_chars=30)[:5]

# ======== Test S1: ONLY change video material paths (count 2) ========
print("=== S1: Only change video material paths ===")
d1 = copy.deepcopy(template)
for i in range(min(2, len(image_paths))):
    d1["materials"]["videos"][i]["path"] = image_paths[i]
    d1["materials"]["videos"][i]["material_name"] = os.path.basename(image_paths[i])
build_and_register("TestS1_VideoPath", "TestS1-" + str(int(time.time())), d1, image_paths, "", 0)
print("S1 done")

# ======== Test S2: S1 + change text content (count 1) ========
print("=== S2: S1 + change text content ===")
d2 = copy.deepcopy(d1)
if sentences:
    new_content = json.dumps({
        "styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}},
                    "range": [0, len(sentences[0])], "size": 5.0, "bold": True, "italic": False, "underline": False, "strokes": []}],
        "text": sentences[0]
    }, ensure_ascii=False)
    d2["materials"]["texts"][0]["content"] = new_content
build_and_register("TestS2_TextContent", "TestS2-" + str(int(time.time())), d2, image_paths, "", 0)
print("S2 done")

# ======== Test S3: S2 + change audio path ========
print("=== S3: S2 + change audio path ===")
audio_path = os.path.join(TASK_DIR, "final_audio.mp3")
if not os.path.exists(audio_path):
    audio_path = os.path.join(TASK_DIR, "final_tts.mp3")
audio_path = audio_path.replace("\\", "/")
d3 = copy.deepcopy(d2)
d3["materials"]["audios"][0]["path"] = audio_path
d3["materials"]["audios"][0]["name"] = os.path.basename(audio_path)
build_and_register("TestS3_AudioPath", "TestS3-" + str(int(time.time())), d3, image_paths, audio_path, 0)
print("S3 done")

# ======== Test S4: S3 + add 1 more video segment (2→3) ========
print("=== S4: S3 + add 1 video segment ===")
d4 = copy.deepcopy(d3)
proto_vseg = copy.deepcopy(d4["tracks"][0]["segments"][0])
proto_vmat = copy.deepcopy(d4["materials"]["videos"][0])
proto_canvas = copy.deepcopy(d4["materials"]["canvases"][0])
proto_speed = copy.deepcopy(d4["materials"]["speeds"][0])
proto_anim = copy.deepcopy(d4["materials"]["material_animations"][0])
proto_color = copy.deepcopy(d4["materials"]["material_colors"][0])
proto_sound = copy.deepcopy(d4["materials"]["sound_channel_mappings"][0])
proto_loud = copy.deepcopy(d4["materials"]["loudnesses"][0])
proto_ph = copy.deepcopy(d4["materials"]["placeholder_infos"][0])
proto_vocal = copy.deepcopy(d4["materials"]["vocal_separations"][0])

vmid, cid, sid, aid = uid(), uid(), uid(), uid()
coid, soid, lid, phid, vcid = uid(), uid(), uid(), uid(), uid()
seg_id = uid()

new_vmat = copy.deepcopy(proto_vmat); new_vmat["id"] = vmid; new_vmat["material_id"] = vmid
last_seg = d4["tracks"][0]["segments"][-1]
last_end = last_seg["target_timerange"].get("start", 0) + last_seg["target_timerange"]["duration"]
new_seg = copy.deepcopy(proto_vseg); new_seg["id"] = seg_id; new_seg["material_id"] = vmid
new_seg["target_timerange"] = {"start": last_end, "duration": 5000000}
new_seg["extra_material_refs"] = [sid, phid, cid, aid, coid, soid, lid, vcid]

for lst, pid, proto in [
    (d4["materials"]["canvases"], cid, proto_canvas),
    (d4["materials"]["speeds"], sid, proto_speed),
    (d4["materials"]["material_animations"], aid, proto_anim),
    (d4["materials"]["material_colors"], coid, proto_color),
    (d4["materials"]["sound_channel_mappings"], soid, proto_sound),
    (d4["materials"]["loudnesses"], lid, proto_loud),
    (d4["materials"]["placeholder_infos"], phid, proto_ph),
    (d4["materials"]["vocal_separations"], vcid, proto_vocal),
]:
    m = copy.deepcopy(proto); m["id"] = pid; lst.append(m)

d4["materials"]["videos"].append(new_vmat)
d4["tracks"][0]["segments"].append(new_seg)
d4["duration"] = last_end + 5000000
build_and_register("TestS4_AddVideo", "TestS4-" + str(int(time.time())), d4, image_paths, audio_path, d4["duration"])
print("S4 done")

# ======== Test S5: S3 + replace ALL video/audio/text materials with gen_v11-style ========
print("=== S5: S3 + full material replacement (same counts) ===")
d5 = copy.deepcopy(d3)
proto_vm = copy.deepcopy(d5["materials"]["videos"][0])
proto_tm = copy.deepcopy(d5["materials"]["texts"][0])
proto_am = copy.deepcopy(d5["materials"]["audios"][0])

# Replace ALL video materials (same count 2)
new_vids = []
for i in range(2):
    m = copy.deepcopy(proto_vm); m["id"] = uid(); m["material_id"] = m["id"]
    m["path"] = image_paths[i]; m["material_name"] = os.path.basename(image_paths[i])
    new_vids.append(m)
d5["materials"]["videos"] = new_vids

# Replace text material (same count 1)
m = copy.deepcopy(proto_tm); m["id"] = uid()
m["content"] = json.dumps({
    "styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}},
                "range": [0, len(sentences[0])], "size": 5.0, "bold": True, "italic": False, "underline": False, "strokes": []}],
    "text": sentences[0]
}, ensure_ascii=False)
d5["materials"]["texts"] = [m]

# Replace audio material (same count 1)
m = copy.deepcopy(proto_am); m["id"] = uid(); m["music_id"] = m["id"]
m["local_material_id"] = m["id"]; m["path"] = audio_path
m["name"] = os.path.basename(audio_path); m["duration"] = total_dur
d5["materials"]["audios"] = [m]

# Update segment references
d5["tracks"][0]["segments"][0]["material_id"] = new_vids[0]["id"]
d5["tracks"][0]["segments"][1]["material_id"] = new_vids[1]["id"]
d5["tracks"][1]["segments"][0]["material_id"] = d5["materials"]["audios"][0]["id"]
d5["tracks"][2]["segments"][0]["material_id"] = d5["materials"]["texts"][0]["id"]

# Update auxiliary material IDs and refs
# Regenerate all auxiliary materials with new IDs
for cat in ["canvases", "material_animations", "material_colors", "loudnesses"]:
    for item in d5["materials"][cat]:
        item["id"] = uid()
for cat in ["speeds", "sound_channel_mappings", "placeholder_infos", "vocal_separations"]:
    for item in d5["materials"][cat]:
        item["id"] = uid()

# Rebuild extra_material_refs with new IDs
def rebuild_refs(track_idx, seg_idx):
    ref_cats = ["speeds", "placeholder_infos", "canvases", "material_animations",
                "material_colors", "sound_channel_mappings", "loudnesses", "vocal_separations"]
    d5["tracks"][track_idx]["segments"][seg_idx]["extra_material_refs"] = [
        d5["materials"][c][seg_idx]["id"] if seg_idx < len(d5["materials"][c]) else d5["materials"][c][0]["id"]
        for c in ref_cats
    ]

rebuild_refs(0, 0)
rebuild_refs(0, 1)

d5["id"] = str(uuid.uuid4()).upper()
d5["duration"] = total_dur
build_and_register("TestS5_FullReplace", "TestS5-" + str(int(time.time())), d5, image_paths, audio_path, total_dur)
print("S5 done")

# ======== Test S6: S5 + modify draft_meta_info ========
print("=== S6: S5 + modify draft_meta_info ===")
d6 = copy.deepcopy(d5)
build_and_register("TestS6_WithMeta", "TestS6-" + str(int(time.time())), d6, image_paths, audio_path, total_dur, modify_meta=True)
print("S6 done")

# ======== Test S7: S5 + update attachment_id_mapping ========
print("=== S7: S5 + update id_mapping ===")
d7 = copy.deepcopy(d5)
build_and_register("TestS7_WithIdMap", "TestS7-" + str(int(time.time())), d7, image_paths, audio_path, total_dur, update_idmap=True)
print("S7 done")

# ======== Test S8: S5 + BOTH meta + idmap ========
print("=== S8: S5 + meta + idmap ===")
d8 = copy.deepcopy(d5)
build_and_register("TestS8_MetaAndMap", "TestS8-" + str(int(time.time())), d8, image_paths, audio_path, total_dur, modify_meta=True, update_idmap=True)
print("S8 done")

# ======== Test S9: S5 + draft_cover from our images ========
print("=== S9: S5 + our cover image ===")
d9 = copy.deepcopy(d5)
build_and_register("TestS9_OurCover", "TestS9-" + str(int(time.time())), d9, image_paths, audio_path, total_dur)
print("S9 done")

print(f"\n{'='*60}")
print("S1-S9 registered. Open 剪映 and test each.")
print("S1: video paths  S2: +text  S3: +audio  S4: +1 video seg")
print("S5: full material replace (same counts)  S6: +modify meta")
print("S7: +update idmap  S8: +meta+idmap  S9: our cover")
