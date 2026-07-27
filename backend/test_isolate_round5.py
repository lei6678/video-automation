"""
第五轮：精准修复测试
1. Test Q: 同 TestP 但不设 audio material_id
2. Test N2 验证 project.json fix
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
tmpl_dec = os.path.join(TEMPLATE_DIR, "draft_content.iso5.json")
decrypt(tmpl_enc, tmpl_dec)
with open(tmpl_dec, "r", encoding="utf-8") as f:
    template = json.load(f)

tl_src = os.path.join(TEMPLATE_DIR, "Timelines")

# Check exactly what fields each material type has
print("=== Template material field analysis ===")
for cat in ["videos", "audios", "texts", "canvases", "speeds", "material_animations",
            "material_colors", "sound_channel_mappings", "loudnesses", "placeholder_infos",
            "vocal_separations"]:
    mats = template["materials"].get(cat, [])
    if mats:
        m0 = mats[0]
        print(f"  {cat}: keys={sorted(m0.keys())}")
        # Check for 'material_id' specifically
        if "material_id" in m0:
            print(f"    HAS material_id = {m0['material_id'][:12] if isinstance(m0['material_id'], str) else m0['material_id']}...")
        else:
            print(f"    NO material_id")

# Check which material has id != material_id pattern
print("\n=== ID vs material_id check ===")
for cat in ["videos", "audios", "texts"]:
    mats = template["materials"].get(cat, [])
    if mats:
        m0 = mats[0]
        mid = m0.get("material_id")
        iid = m0.get("id")
        if mid:
            print(f"  {cat}: id={iid[:12]}..., material_id={mid[:12]}..., same={mid==iid}")
        else:
            print(f"  {cat}: id={iid[:12]}..., material_id=MISSING")

# ======== Test Q: Same as TestP but FIX audio material_id ========
print("\n=== Test Q: Fix audio material_id ===")
from services.llm_service import split_into_short_sentences
from services.video_service import get_audio_duration, split_into_word_groups

# Build minimal draft like TestP
images_dir = os.path.join(TASK_DIR, "images")
img_files = sorted([f for f in os.listdir(images_dir) if f.endswith(".png") and f.startswith("seg_")])[:5]
img_map = {}
for f in img_files:
    seg_idx = int(f.replace("seg_", "").replace(".png", ""))
    img_map[seg_idx] = os.path.join(images_dir, f).replace("\\", "/")

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
image_paths = [img_map.get(i, img_map.get(0, "")) for i in range(5)]
audio_path = os.path.join(TASK_DIR, "final_audio.mp3")
if not os.path.exists(audio_path):
    audio_path = os.path.join(TASK_DIR, "final_tts.mp3")
audio_path = audio_path.replace("\\", "/")

# Prototypes
proto_video_seg = copy.deepcopy(template["tracks"][0]["segments"][0])
proto_video_mat = copy.deepcopy(template["materials"]["videos"][0])
proto_audio_mat = copy.deepcopy(template["materials"]["audios"][0])
proto_audio_seg = copy.deepcopy(template["tracks"][1]["segments"][0])
proto_text_mat = copy.deepcopy(template["materials"]["texts"][0])
proto_text_seg = copy.deepcopy(template["tracks"][2]["segments"][0])
proto_speed = copy.deepcopy(template["materials"]["speeds"][0])
proto_canvas = copy.deepcopy(template["materials"]["canvases"][0])
proto_anim = copy.deepcopy(template["materials"]["material_animations"][0])
proto_color = copy.deepcopy(template["materials"]["material_colors"][0])
proto_sound = copy.deepcopy(template["materials"]["sound_channel_mappings"][0])
proto_loud = copy.deepcopy(template["materials"]["loudnesses"][0])
proto_ph = copy.deepcopy(template["materials"]["placeholder_infos"][0])
proto_vocal = copy.deepcopy(template["materials"]["vocal_separations"][0])

# Generate materials
video_mat_ids, video_mats = [], []
for i, img_path in enumerate(image_paths):
    mid = uid(); video_mat_ids.append(mid)
    m = copy.deepcopy(proto_video_mat); m["id"] = mid; m["material_id"] = mid
    m["path"] = img_path; m["material_name"] = os.path.basename(img_path)
    video_mats.append(m)

text_mat_ids, text_mats = [], []
for i, text in enumerate(sentences):
    dur = seg_durations[i]
    if dur <= 0: continue
    groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
    for group in groups:
        tid = uid(); text_mat_ids.append(tid)
        m = copy.deepcopy(proto_text_mat); m["id"] = tid
        style_json = json.dumps({
            "styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}},
                        "range": [0, len(group["text"])], "size": 5.0, "bold": True, "italic": False, "underline": False, "strokes": []}],
            "text": group["text"]
        }, ensure_ascii=False)
        m["content"] = style_json; m["font_path"] = FONT_PATH
        text_mats.append(m)

# FIX: Don't set material_id on audio (template audio doesn't have it)
audio_mat_id = uid()
audio_mat = copy.deepcopy(proto_audio_mat)
audio_mat["id"] = audio_mat_id
# REMOVED: audio_mat["material_id"] = audio_mat_id  <-- THIS WAS THE BUG
audio_mat["music_id"] = audio_mat_id
audio_mat["local_material_id"] = audio_mat_id
audio_mat["path"] = audio_path
audio_mat["name"] = os.path.basename(audio_path)
audio_mat["duration"] = total_dur

canvases, speeds, anims, colors, sounds, louds, phs, vocals = [], [], [], [], [], [], [], []
for i in range(len(sentences)):
    c = copy.deepcopy(proto_canvas); c["id"] = uid(); canvases.append(c)
    s = copy.deepcopy(proto_speed); s["id"] = uid(); speeds.append(s)
    a = copy.deepcopy(proto_anim); a["id"] = uid(); anims.append(a)
    co = copy.deepcopy(proto_color); co["id"] = uid(); colors.append(co)
    so = copy.deepcopy(proto_sound); so["id"] = uid(); sounds.append(so)
    l = copy.deepcopy(proto_loud); l["id"] = uid(); louds.append(l)
    p = copy.deepcopy(proto_ph); p["id"] = uid(); phs.append(p)
    v = copy.deepcopy(proto_vocal); v["id"] = uid(); vocals.append(v)

# Generate segments
video_segs = []
time_cursor = 0.0
for i in range(len(sentences)):
    dur = seg_durations[i]
    if dur <= 0: continue
    sid = uid()
    seg = copy.deepcopy(proto_video_seg); seg["id"] = sid
    seg["material_id"] = video_mat_ids[i]
    seg["source_timerange"]["duration"] = int(dur)
    seg["target_timerange"] = {"start": int(time_cursor), "duration": int(dur)}
    seg["extra_material_refs"] = [speeds[i]["id"], phs[i]["id"], canvases[i]["id"],
                                   anims[i]["id"], colors[i]["id"], sounds[i]["id"],
                                   louds[i]["id"], vocals[i]["id"]]
    video_segs.append(seg); time_cursor += dur

audio_seg = copy.deepcopy(proto_audio_seg); audio_seg["id"] = uid()
audio_seg["material_id"] = audio_mat_id
audio_seg["source_timerange"]["duration"] = total_dur
audio_seg["target_timerange"] = {"start": 0, "duration": total_dur}

text_segs = []
stime_cursor, ti = 0.0, 0
for i, text in enumerate(sentences):
    dur = seg_durations[i]
    if dur <= 0: continue
    groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
    for group in groups:
        gdur = int((group["end"] - group["start"]) * 1_000_000)
        gstart = int((stime_cursor + group["start"]) * 1_000_000)
        sid = uid()
        seg = copy.deepcopy(proto_text_seg); seg["id"] = sid
        seg["material_id"] = text_mat_ids[ti]
        seg["target_timerange"] = {"start": gstart, "duration": gdur}
        text_segs.append(seg); ti += 1
    stime_cursor += dur

# Assemble
draft_q = copy.deepcopy(template)
draft_q["id"] = str(uuid.uuid4()).upper()
draft_q["duration"] = total_dur
draft_q["materials"]["videos"] = video_mats
draft_q["materials"]["audios"] = [audio_mat]
draft_q["materials"]["texts"] = text_mats
draft_q["materials"]["canvases"] = canvases
draft_q["materials"]["speeds"] = speeds
draft_q["materials"]["material_animations"] = anims
draft_q["materials"]["material_colors"] = colors
draft_q["materials"]["sound_channel_mappings"] = sounds
draft_q["materials"]["loudnesses"] = louds
draft_q["materials"]["placeholder_infos"] = phs
draft_q["materials"]["vocal_separations"] = vocals
draft_q["tracks"][0]["id"] = uid(); draft_q["tracks"][0]["segments"] = video_segs
draft_q["tracks"][1]["id"] = uid(); draft_q["tracks"][1]["segments"] = [audio_seg]
draft_q["tracks"][2]["id"] = uid(); draft_q["tracks"][2]["segments"] = text_segs

all_seg_ids = []
for track in draft_q["tracks"]:
    for seg in track["segments"]:
        all_seg_ids.append(seg["id"])

dir_q = make_dir("TestQ_FixAudio")
dc_q = os.path.join(dir_q, "draft_content.json")
with open(dc_q, "w", encoding="utf-8") as f:
    json.dump(draft_q, f, ensure_ascii=False, indent=2)

# draft_meta_info
tmpl_meta_enc = os.path.join(TEMPLATE_DIR, "draft_meta_info.json")
tmpl_meta_dec = os.path.join(TEMPLATE_DIR, "draft_meta_info.q.json")
decrypt(tmpl_meta_enc, tmpl_meta_dec)
with open(tmpl_meta_dec, "r", encoding="utf-8") as f:
    draft_meta = json.load(f)
draft_meta["draft_id"] = "TestQ-" + str(int(time.time()))
draft_meta["draft_name"] = "TestQ_FixAudio"
draft_meta["draft_fold_path"] = dir_q.replace("\\", "/")
draft_meta["draft_root_path"] = DRAFT_ROOT.replace("\\", "/")
draft_meta["tm_draft_create"] = NOW_US
draft_meta["tm_draft_modified"] = NOW_US
draft_meta["tm_duration"] = total_dur
total_mat_size = sum(os.path.getsize(p) for p in image_paths if os.path.exists(p)) + os.path.getsize(audio_path)
draft_meta["draft_timeline_materials_size_"] = total_mat_size
if draft_meta.get("draft_materials"):
    for grp in draft_meta["draft_materials"]:
        if grp.get("type") == 0 and grp.get("value"):
            grp["value"][0]["id"] = audio_mat_id
            grp["value"][0]["duration"] = total_dur
            grp["value"][0]["extra_info"] = os.path.basename(audio_path)
            grp["value"][0]["file_Path"] = "./" + os.path.basename(audio_path)
            if "roughcut_time_range" in grp["value"][0]:
                grp["value"][0]["roughcut_time_range"]["duration"] = total_dur
dm_path = os.path.join(dir_q, "draft_meta_info.json")
with open(dm_path, "w", encoding="utf-8") as f:
    json.dump(draft_meta, f, ensure_ascii=False, indent=2)

# draft_settings
with open(os.path.join(dir_q, "draft_settings"), "w", encoding="utf-8") as f:
    f.write(f"[General]\ncloud_last_modify_platform=windows\ndraft_create_time={NOW_S}\ndraft_last_edit_time={NOW_S}\nreal_edit_seconds=0\nreal_edit_keys=0\n")

# Cover
if image_paths:
    shutil.copy2(image_paths[0], os.path.join(dir_q, "draft_cover.jpg"))

# Timelines (keep project.json UNCHANGED from template)
shutil.copytree(os.path.join(TEMPLATE_DIR, "Timelines"), os.path.join(dir_q, "Timelines"))
for d in os.listdir(os.path.join(dir_q, "Timelines")):
    dp = os.path.join(dir_q, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        shutil.copy2(dc_q, os.path.join(dp, "draft_content.json"))
        # Update id_mapping
        id_map_path = os.path.join(dp, "common_attachment", "attachment_id_mapping.json")
        if os.path.exists(id_map_path):
            with open(id_map_path, "r", encoding="utf-8") as f:
                id_map = json.load(f)
            id_map["id_mapping"]["mapping"] = [{"short_id": str(1000 + i), "uuid": sid} for i, sid in enumerate(all_seg_ids)]
            with open(id_map_path, "w", encoding="utf-8") as f:
                json.dump(id_map, f, ensure_ascii=False, indent=2)
        break

encrypt(dc_q)
encrypt(dm_path)
for d in os.listdir(os.path.join(dir_q, "Timelines")):
    dp = os.path.join(dir_q, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        encrypt(os.path.join(dp, "draft_content.json"), dp)

register("TestQ_FixAudio", dir_q, "TestQ-" + str(int(time.time())))
print(f"Test Q registered: {len(video_segs)}v {len(text_segs)}t {total_dur/1e6:.1f}s")

# ======== Verify: check if audio_mat still has no material_id ========
print(f"\nVerification - audio_mat keys: {sorted(audio_mat.keys())}")
print(f"  has material_id: {'material_id' in audio_mat}")

print(f"\n{'='*60}")
print("Tests to check:")
print("  N2: project.json fully fixed (proj.id + main_timeline_id + no .bak)")
print("  Q: audio material_id removed (same as TestP otherwise)")
