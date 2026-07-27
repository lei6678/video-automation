"""从 S18 (works) 逐步改造成 S10 的形态"""
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

def quick_build(name, draft_id, draft):
    dir_path = make_dir(name)
    dc_path = os.path.join(dir_path, "draft_content.json")
    with open(dc_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
    for fn in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
        sf = os.path.join(TEMPLATE_DIR, fn)
        if os.path.exists(sf): shutil.copy2(sf, os.path.join(dir_path, fn))
    shutil.copytree(os.path.join(TEMPLATE_DIR, "Timelines"), os.path.join(dir_path, "Timelines"))
    for d in os.listdir(os.path.join(dir_path, "Timelines")):
        dp = os.path.join(dir_path, "Timelines", d)
        if os.path.isdir(dp) and d != "common_attachment":
            shutil.copy2(dc_path, os.path.join(dp, "draft_content.json"))
            break
    encrypt(dc_path)
    for d in os.listdir(os.path.join(dir_path, "Timelines")):
        dp = os.path.join(dir_path, "Timelines", d)
        if os.path.isdir(dp) and d != "common_attachment":
            encrypt(os.path.join(dp, "draft_content.json"), dp)
    register(name, dir_path, draft_id)
    return True

# Load template
tmpl_enc = os.path.join(TEMPLATE_DIR, "draft_content.json")
tmpl_dec = os.path.join(TEMPLATE_DIR, "draft_content.s20.json")
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

audio_path = os.path.join(TASK_DIR, "final_audio.mp3")
if not os.path.exists(audio_path):
    audio_path = os.path.join(TASK_DIR, "final_tts.mp3")
audio_path = audio_path.replace("\\", "/")

with open(os.path.join(TASK_DIR, "rewritten.txt"), "r", encoding="utf-8") as f:
    raw = f.read()
full_text = ""
for line in raw.strip().split("\n")[:3]:
    if not line.strip(): continue
    parts = line.split("\t", 1)
    full_text += parts[1] if len(parts) > 1 else parts[0]
sentences = split_into_short_sentences(full_text, max_chars=80, min_chars=30)[:5]

# Prototypes
proto_vseg = copy.deepcopy(template["tracks"][0]["segments"][0])
proto_vmat = copy.deepcopy(template["materials"]["videos"][0])
proto_tseg = copy.deepcopy(template["tracks"][2]["segments"][0])
proto_tmat = copy.deepcopy(template["materials"]["texts"][0])
proto_canvas = copy.deepcopy(template["materials"]["canvases"][0])
proto_speed = copy.deepcopy(template["materials"]["speeds"][0])
proto_anim = copy.deepcopy(template["materials"]["material_animations"][0])
proto_color = copy.deepcopy(template["materials"]["material_colors"][0])
proto_sound = copy.deepcopy(template["materials"]["sound_channel_mappings"][0])
proto_loud = copy.deepcopy(template["materials"]["loudnesses"][0])
proto_ph = copy.deepcopy(template["materials"]["placeholder_infos"][0])
proto_vocal = copy.deepcopy(template["materials"]["vocal_separations"][0])

# Build S18 baseline first (S17 + aux remap)
d_base = copy.deepcopy(template)
# Replace video/text/audio (same counts)
proto_vm = copy.deepcopy(d_base["materials"]["videos"][0])
new_vids = []
for i in range(2):
    m = copy.deepcopy(proto_vm); m["id"] = uid(); m["material_id"] = m["id"]
    m["path"] = image_paths[i]; m["material_name"] = os.path.basename(image_paths[i])
    new_vids.append(m)
d_base["materials"]["videos"] = new_vids
d_base["tracks"][0]["segments"][0]["material_id"] = new_vids[0]["id"]
d_base["tracks"][0]["segments"][1]["material_id"] = new_vids[1]["id"]

proto_tm = copy.deepcopy(d_base["materials"]["texts"][0])
m = copy.deepcopy(proto_tm); m["id"] = uid()
m["content"] = json.dumps({"styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
    "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}}, "range": [0, len(sentences[0])],
    "size": 5.0, "bold": True, "italic": False, "underline": False, "strokes": []}],
    "text": sentences[0]}, ensure_ascii=False)
d_base["materials"]["texts"] = [m]
d_base["tracks"][2]["segments"][0]["material_id"] = m["id"]

proto_am = copy.deepcopy(d_base["materials"]["audios"][0])
m = copy.deepcopy(proto_am); m["id"] = uid()
m["music_id"] = m["id"]; m["local_material_id"] = m["id"]
m["path"] = audio_path; m["name"] = os.path.basename(audio_path)
d_base["materials"]["audios"] = [m]
d_base["tracks"][1]["segments"][0]["material_id"] = m["id"]

# Aux remap (id_map approach)
id_map = {}
for cat in ["canvases", "speeds", "material_animations", "material_colors",
            "sound_channel_mappings", "loudnesses", "placeholder_infos", "vocal_separations"]:
    for item in d_base["materials"].get(cat, []):
        old_id = item["id"]
        new_id = uid()
        id_map[old_id] = new_id
        item["id"] = new_id
for track in d_base["tracks"]:
    for seg in track["segments"]:
        if "extra_material_refs" in seg:
            seg["extra_material_refs"] = [id_map.get(r, r) for r in seg["extra_material_refs"]]

CORRECT_ORDER = ["speeds", "placeholder_infos", "canvases", "material_animations",
                 "sound_channel_mappings", "material_colors", "loudnesses", "vocal_separations"]

# ======== S20: d_base + add video seg 2->5 + add text seg 1->5 ========
print("=== S20: Transform S18 into 5v + 5t + 1a ===")
d20 = copy.deepcopy(d_base)

# Track current indices
n_vid = 2  # current video count
n_txt = 1  # current text count
total_vid_dur = d20["tracks"][0]["segments"][0]["target_timerange"]["duration"] + \
                d20["tracks"][0]["segments"][1]["target_timerange"]["start"] + \
                d20["tracks"][0]["segments"][1]["target_timerange"]["duration"]

# Add video segments (2->5)
for i in range(2, 5):
    # New video material
    vm = copy.deepcopy(proto_vmat); vm["id"] = uid(); vm["material_id"] = vm["id"]
    vm["path"] = image_paths[i]; vm["material_name"] = os.path.basename(image_paths[i])
    d20["materials"]["videos"].append(vm)

    # New auxiliary materials for video
    c = copy.deepcopy(proto_canvas); c["id"] = uid(); d20["materials"]["canvases"].append(c)
    a = copy.deepcopy(proto_anim); a["id"] = uid(); d20["materials"]["material_animations"].append(a)
    co = copy.deepcopy(proto_color); co["id"] = uid(); d20["materials"]["material_colors"].append(co)
    l = copy.deepcopy(proto_loud); l["id"] = uid(); d20["materials"]["loudnesses"].append(l)

    # Types that also need audio entry
    s = copy.deepcopy(proto_speed); s["id"] = uid(); d20["materials"]["speeds"].append(s)
    so = copy.deepcopy(proto_sound); so["id"] = uid(); d20["materials"]["sound_channel_mappings"].append(so)
    p = copy.deepcopy(proto_ph); p["id"] = uid(); d20["materials"]["placeholder_infos"].append(p)
    v = copy.deepcopy(proto_vocal); v["id"] = uid(); d20["materials"]["vocal_separations"].append(v)

    # New video segment
    seg = copy.deepcopy(proto_vseg); seg["id"] = uid()
    seg["material_id"] = vm["id"]
    dur = seg_durations[i]
    seg["source_timerange"]["duration"] = int(dur)
    seg["target_timerange"] = {"start": int(total_vid_dur), "duration": int(dur)}
    seg["extra_material_refs"] = [
        d20["materials"]["speeds"][i]["id"],
        d20["materials"]["placeholder_infos"][i]["id"],
        d20["materials"]["canvases"][i]["id"],
        d20["materials"]["material_animations"][i]["id"],
        d20["materials"]["sound_channel_mappings"][i]["id"],
        d20["materials"]["material_colors"][i]["id"],
        d20["materials"]["loudnesses"][i]["id"],
        d20["materials"]["vocal_separations"][i]["id"],
    ]
    d20["tracks"][0]["segments"].append(seg)
    total_vid_dur += dur

n_vid = 5

# Add text segments (1->5)
text_cursor = d20["tracks"][2]["segments"][0]["target_timerange"]["duration"]
for i in range(1, 5):
    dur = seg_durations[i]
    groups = split_into_word_groups(sentences[i], duration_sec=dur / 1_000_000)
    for group in groups:
        tm = copy.deepcopy(proto_tmat); tm["id"] = uid()
        tm["content"] = json.dumps({"styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
            "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}}, "range": [0, len(group["text"])],
            "size": 5.0, "bold": True, "italic": False, "underline": False, "strokes": []}],
            "text": group["text"]}, ensure_ascii=False)
        tm["font_path"] = FONT_PATH
        d20["materials"]["texts"].append(tm)

        gdur = int((group["end"] - group["start"]) * 1_000_000)
        gstart = text_cursor + int(group["start"] * 1_000_000)
        seg = copy.deepcopy(proto_tseg); seg["id"] = uid()
        seg["material_id"] = tm["id"]
        seg["target_timerange"] = {"start": gstart, "duration": gdur}
        d20["tracks"][2]["segments"].append(seg)
    text_cursor += dur

# Fix audio segment refs (now needs index n_vid=5)
d20["tracks"][1]["segments"][0]["extra_material_refs"] = [
    d20["materials"]["speeds"][n_vid]["id"],
    d20["materials"]["placeholder_infos"][n_vid]["id"],
    d20["materials"]["sound_channel_mappings"][n_vid]["id"],
    d20["materials"]["vocal_separations"][n_vid]["id"],
]

# Fix duration
d20["duration"] = total_dur

quick_build("TestS20_Transform", "TestS20-" + str(int(time.time())), d20)

n_text = len(d20["tracks"][2]["segments"])
print(f"S20 done: {len(d20['tracks'][0]['segments'])}v {n_text}t 1a")
print("Open 剪映 and test TestS20_Transform")
