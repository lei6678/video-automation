"""Test S10: Fix ref order to match template exactly"""
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

# Load template
tmpl_enc = os.path.join(TEMPLATE_DIR, "draft_content.json")
tmpl_dec = os.path.join(TEMPLATE_DIR, "draft_content.s10.json")
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

audio_path = os.path.join(TASK_DIR, "final_audio.mp3")
if not os.path.exists(audio_path):
    audio_path = os.path.join(TASK_DIR, "final_tts.mp3")
audio_path = audio_path.replace("\\", "/")

# ========== CORRECT ref order matching template ==========
# Template video: speeds, placeholder_infos, canvases, material_animations,
#                 sound_channel_mappings, material_colors, loudnesses, vocal_separations
# Template audio: speeds, placeholder_infos, sound_channel_mappings, vocal_separations

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
        m["content"] = json.dumps({
            "styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
                "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}},
                "range": [0, len(group["text"])], "size": 5.0,
                "bold": True, "italic": False, "underline": False, "strokes": []}],
            "text": group["text"]
        }, ensure_ascii=False)
        m["font_path"] = FONT_PATH
        text_mats.append(m)

audio_mat_id = uid()
audio_mat = copy.deepcopy(proto_audio_mat)
audio_mat["id"] = audio_mat_id
audio_mat["music_id"] = audio_mat_id
audio_mat["local_material_id"] = audio_mat_id
audio_mat["path"] = audio_path
audio_mat["name"] = os.path.basename(audio_path)
audio_mat["duration"] = total_dur

# Generate auxiliary materials for video segments
canvases, speeds, anims, colors, sounds, louds, phs, vocals_list = [], [], [], [], [], [], [], []
for i in range(len(sentences)):
    c = copy.deepcopy(proto_canvas); c["id"] = uid(); canvases.append(c)
    s = copy.deepcopy(proto_speed); s["id"] = uid(); speeds.append(s)
    a = copy.deepcopy(proto_anim); a["id"] = uid(); anims.append(a)
    co = copy.deepcopy(proto_color); co["id"] = uid(); colors.append(co)
    so = copy.deepcopy(proto_sound); so["id"] = uid(); sounds.append(so)
    l = copy.deepcopy(proto_loud); l["id"] = uid(); louds.append(l)
    p = copy.deepcopy(proto_ph); p["id"] = uid(); phs.append(p)
    v = copy.deepcopy(proto_vocal); v["id"] = uid(); vocals_list.append(v)

# Extra auxiliary for audio segment (speeds, phs, sounds, vocals)
extra_speed = copy.deepcopy(proto_speed); extra_speed["id"] = uid(); speeds.append(extra_speed)
extra_ph = copy.deepcopy(proto_ph); extra_ph["id"] = uid(); phs.append(extra_ph)
extra_sound = copy.deepcopy(proto_sound); extra_sound["id"] = uid(); sounds.append(extra_sound)
extra_vocal = copy.deepcopy(proto_vocal); extra_vocal["id"] = uid(); vocals_list.append(extra_vocal)

# Build video refs in CORRECT template order
def build_video_refs(i):
    return [
        speeds[i]["id"], phs[i]["id"], canvases[i]["id"], anims[i]["id"],
        sounds[i]["id"], colors[i]["id"],  # sound before color (FIXED)
        louds[i]["id"], vocals_list[i]["id"]
    ]

# Generate video segments
video_segs = []
time_cursor = 0.0
for i in range(len(sentences)):
    dur = seg_durations[i]
    if dur <= 0: continue
    seg = copy.deepcopy(proto_video_seg)
    seg["id"] = uid()
    seg["material_id"] = video_mat_ids[i]
    seg["source_timerange"]["duration"] = int(dur)
    seg["target_timerange"] = mk_tr(time_cursor, dur)
    seg["extra_material_refs"] = build_video_refs(i)
    video_segs.append(seg)
    time_cursor += dur

# Audio segment with correct refs
audio_seg = copy.deepcopy(proto_audio_seg)
audio_seg["id"] = uid()
audio_seg["material_id"] = audio_mat_id
audio_seg["source_timerange"]["duration"] = total_dur
audio_seg["target_timerange"] = mk_tr(0, total_dur)
audio_ref_idx = len(video_segs)  # audio uses index after all video segments
audio_seg["extra_material_refs"] = [
    speeds[audio_ref_idx]["id"], phs[audio_ref_idx]["id"],
    sounds[audio_ref_idx]["id"], vocals_list[audio_ref_idx]["id"]
]

# Text segments - no extra_material_refs
text_segs = []
stime_cursor, ti = 0.0, 0
for i, text in enumerate(sentences):
    dur = seg_durations[i]
    if dur <= 0: continue
    groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
    for group in groups:
        gdur = int((group["end"] - group["start"]) * 1_000_000)
        gstart = stime_cursor + group["start"] * 1_000_000
        seg = copy.deepcopy(proto_text_seg)
        seg["id"] = uid()
        seg["material_id"] = text_mat_ids[ti]
        seg["target_timerange"] = mk_tr(gstart, gdur)
        text_segs.append(seg)
        ti += 1
    stime_cursor += dur

# Assemble draft
draft_s10 = copy.deepcopy(template)
draft_s10["id"] = str(uuid.uuid4()).upper()
draft_s10["duration"] = total_dur
draft_s10["materials"]["videos"] = video_mats
draft_s10["materials"]["audios"] = [audio_mat]
draft_s10["materials"]["texts"] = text_mats
draft_s10["materials"]["canvases"] = canvases
draft_s10["materials"]["speeds"] = speeds
draft_s10["materials"]["material_animations"] = anims
draft_s10["materials"]["material_colors"] = colors
draft_s10["materials"]["sound_channel_mappings"] = sounds
draft_s10["materials"]["loudnesses"] = louds
draft_s10["materials"]["placeholder_infos"] = phs
draft_s10["materials"]["vocal_separations"] = vocals_list
draft_s10["tracks"][0]["id"] = uid()
draft_s10["tracks"][0]["segments"] = video_segs
draft_s10["tracks"][1]["id"] = uid()
draft_s10["tracks"][1]["segments"] = [audio_seg]
draft_s10["tracks"][2]["id"] = uid()
draft_s10["tracks"][2]["segments"] = text_segs

# Write and register
dir_s10 = make_dir("TestS10_FixOrder")
dc_s10 = os.path.join(dir_s10, "draft_content.json")
with open(dc_s10, "w", encoding="utf-8") as f:
    json.dump(draft_s10, f, ensure_ascii=False, indent=2)

for fn in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
    sf = os.path.join(TEMPLATE_DIR, fn)
    if os.path.exists(sf):
        shutil.copy2(sf, os.path.join(dir_s10, fn))

shutil.copytree(os.path.join(TEMPLATE_DIR, "Timelines"), os.path.join(dir_s10, "Timelines"))
for d in os.listdir(os.path.join(dir_s10, "Timelines")):
    dp = os.path.join(dir_s10, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        shutil.copy2(dc_s10, os.path.join(dp, "draft_content.json"))
        break

encrypt(dc_s10)
for d in os.listdir(os.path.join(dir_s10, "Timelines")):
    dp = os.path.join(dir_s10, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        encrypt(os.path.join(dp, "draft_content.json"), dp)

register("TestS10_FixOrder", dir_s10, "TestS10-" + str(int(time.time())))

# Verify
print(f"Test S10: {len(video_segs)}v {len(text_segs)}t {len(audio_seg['extra_material_refs'])} audio refs, {total_dur/1e6:.1f}s")
for i, seg in enumerate(video_segs[:2]):
    refs = seg["extra_material_refs"]
    cats = []
    for rid in refs:
        for cat in ["speeds", "placeholder_infos", "canvases", "material_animations",
                     "sound_channel_mappings", "material_colors", "loudnesses", "vocal_separations"]:
            if any(m["id"] == rid for m in draft_s10["materials"][cat]):
                cats.append(cat)
                break
    expected = ["speeds", "placeholder_infos", "canvases", "material_animations",
                "sound_channel_mappings", "material_colors", "loudnesses", "vocal_separations"]
    match = "OK" if cats == expected else f"WRONG! Got: {cats}"
    print(f"  Video seg {i}: {match}")

arefs = audio_seg["extra_material_refs"]
acats = []
for rid in arefs:
    for cat in ["speeds", "placeholder_infos", "sound_channel_mappings", "vocal_separations"]:
        if any(m["id"] == rid for m in draft_s10["materials"][cat]):
            acats.append(cat)
            break
expected_audio = ["speeds", "placeholder_infos", "sound_channel_mappings", "vocal_separations"]
amatch = "OK" if acats == expected_audio else f"WRONG! Got: {acats}"
print(f"  Audio seg: {amatch}")
