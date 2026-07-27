"""S18: S17 + aux ID remap (TestD style, keeps refs intact)
   S19: S5 with correct ref order + audio ref fix"""
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
tmpl_dec = os.path.join(TEMPLATE_DIR, "draft_content.s18.json")
decrypt(tmpl_enc, tmpl_dec)
with open(tmpl_dec, "r", encoding="utf-8") as f:
    template = json.load(f)

from services.llm_service import split_into_short_sentences

images_dir = os.path.join(TASK_DIR, "images")
img_files = sorted([f for f in os.listdir(images_dir) if f.endswith(".png") and f.startswith("seg_")])[:5]
img_map = {}
for f in img_files:
    seg_idx = int(f.replace("seg_", "").replace(".png", ""))
    img_map[seg_idx] = os.path.join(images_dir, f).replace("\\", "/")
image_paths = [img_map.get(i, img_map.get(0, "")) for i in range(5)]

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

# Build S17 baseline (video+text+audio replace, aux unchanged)
d17 = copy.deepcopy(template)
proto_vm = copy.deepcopy(d17["materials"]["videos"][0])
new_vids = []
for i in range(2):
    m = copy.deepcopy(proto_vm); m["id"] = uid(); m["material_id"] = m["id"]
    m["path"] = image_paths[i]; m["material_name"] = os.path.basename(image_paths[i])
    new_vids.append(m)
d17["materials"]["videos"] = new_vids
d17["tracks"][0]["segments"][0]["material_id"] = new_vids[0]["id"]
d17["tracks"][0]["segments"][1]["material_id"] = new_vids[1]["id"]

proto_tm = copy.deepcopy(d17["materials"]["texts"][0])
m = copy.deepcopy(proto_tm); m["id"] = uid()
m["content"] = json.dumps({
    "styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
        "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}},
        "range": [0, len(sentences[0])], "size": 5.0,
        "bold": True, "italic": False, "underline": False, "strokes": []}],
    "text": sentences[0]
}, ensure_ascii=False)
d17["materials"]["texts"] = [m]
d17["tracks"][2]["segments"][0]["material_id"] = m["id"]

proto_am = copy.deepcopy(d17["materials"]["audios"][0])
m = copy.deepcopy(proto_am); m["id"] = uid()
m["music_id"] = m["id"]; m["local_material_id"] = m["id"]
m["path"] = audio_path; m["name"] = os.path.basename(audio_path)
d17["materials"]["audios"] = [m]
d17["tracks"][1]["segments"][0]["material_id"] = m["id"]

# ======== S18: S17 + aux ID remap (TestD style) ========
print("=== S18: S17 + aux ID remap (id_map approach, preserves all refs) ===")
d18 = copy.deepcopy(d17)
id_map = {}
for cat in ["canvases", "speeds", "material_animations", "material_colors",
            "sound_channel_mappings", "loudnesses", "placeholder_infos", "vocal_separations"]:
    for item in d18["materials"].get(cat, []):
        old_id = item["id"]
        new_id = uid()
        id_map[old_id] = new_id
        item["id"] = new_id

# Remap ALL segment refs using id_map
for track in d18["tracks"]:
    for seg in track["segments"]:
        if "extra_material_refs" in seg:
            seg["extra_material_refs"] = [id_map.get(r, r) for r in seg["extra_material_refs"]]

quick_build("TestS18_AuxRemap", "TestS18-" + str(int(time.time())), d18)
print("S18 done")

# ======== S19: S5 rebuilt with correct order + audio fix ========
print("=== S19: S5 rebuilt — correct ref order + audio refs ===")
d19 = copy.deepcopy(d17)  # Start from S17 baseline

# Regenerate aux IDs
for cat in ["canvases", "material_animations", "material_colors", "loudnesses"]:
    for item in d19["materials"][cat]:
        item["id"] = uid()
for cat in ["speeds", "sound_channel_mappings", "placeholder_infos", "vocal_separations"]:
    for item in d19["materials"][cat]:
        item["id"] = uid()

# CORRECT ref order: speeds, ph, canvases, anims, sounds, colors, louds, vocals
CORRECT_ORDER = ["speeds", "placeholder_infos", "canvases", "material_animations",
                 "sound_channel_mappings", "material_colors", "loudnesses", "vocal_separations"]

# Rebuild video segment refs
for seg_idx in range(len(d19["tracks"][0]["segments"])):
    refs = []
    for cat in CORRECT_ORDER:
        items = d19["materials"][cat]
        refs.append(items[seg_idx]["id"] if seg_idx < len(items) else items[0]["id"])
    d19["tracks"][0]["segments"][seg_idx]["extra_material_refs"] = refs

# Rebuild audio segment refs (speeds, ph, sounds, vocals at index N)
n_video = len(d19["tracks"][0]["segments"])
audio_refs = []
for cat in ["speeds", "placeholder_infos", "sound_channel_mappings", "vocal_separations"]:
    items = d19["materials"][cat]
    audio_refs.append(items[n_video]["id"] if n_video < len(items) else items[0]["id"])
d19["tracks"][1]["segments"][0]["extra_material_refs"] = audio_refs

quick_build("TestS19_S5Fixed", "TestS19-" + str(int(time.time())), d19)
print("S19 done")

# Verify
print("\nVerification:")
print("S18: TestD-style id_map remap on all aux materials")
print("S19: Rebuild refs with correct order + audio fix")
print(f"\nS18 video seg[0] refs: {len(d18['tracks'][0]['segments'][0]['extra_material_refs'])}")
print(f"S19 video seg[0] refs: {len(d19['tracks'][0]['segments'][0]['extra_material_refs'])}")
print(f"S19 audio seg refs: {len(d19['tracks'][1]['segments'][0]['extra_material_refs'])}")
