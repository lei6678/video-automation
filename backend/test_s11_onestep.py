"""从 S3 出发，每次只改一个辅助材料 ID + 更新对应的 ref"""
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

def quick_build(name, draft_id, draft, copy_timelines=True):
    """Minimal build: write dc, copy companions, encrypt, register"""
    dir_path = make_dir(name)
    dc_path = os.path.join(dir_path, "draft_content.json")
    with open(dc_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    for fn in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
        sf = os.path.join(TEMPLATE_DIR, fn)
        if os.path.exists(sf): shutil.copy2(sf, os.path.join(dir_path, fn))

    if copy_timelines:
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

# ======== Load template & build baseline S3 ========
tmpl_enc = os.path.join(TEMPLATE_DIR, "draft_content.json")
tmpl_dec = os.path.join(TEMPLATE_DIR, "draft_content.s11.json")
decrypt(tmpl_enc, tmpl_dec)
with open(tmpl_dec, "r", encoding="utf-8") as f:
    template = json.load(f)

from services.llm_service import split_into_short_sentences
from services.video_service import get_audio_duration

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

# Build S3 baseline
d3 = copy.deepcopy(template)
for i in range(min(2, len(image_paths))):
    d3["materials"]["videos"][i]["path"] = image_paths[i]
    d3["materials"]["videos"][i]["material_name"] = os.path.basename(image_paths[i])
if sentences:
    new_content = json.dumps({
        "styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
            "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}},
            "range": [0, len(sentences[0])], "size": 5.0,
            "bold": True, "italic": False, "underline": False, "strokes": []}],
        "text": sentences[0]
    }, ensure_ascii=False)
    d3["materials"]["texts"][0]["content"] = new_content
d3["materials"]["audios"][0]["path"] = audio_path
d3["materials"]["audios"][0]["name"] = os.path.basename(audio_path)

# ======== S11: S3 + change ONE speed[0] ID + update video seg[0] ref ========
print("=== S11: Change 1 speed ID ===")
d11 = copy.deepcopy(d3)
old_speed_id = d11["materials"]["speeds"][0]["id"]
new_speed_id = uid()
d11["materials"]["speeds"][0]["id"] = new_speed_id
# Update ref in video seg[0]
refs = d11["tracks"][0]["segments"][0]["extra_material_refs"]
for i, r in enumerate(refs):
    if r == old_speed_id:
        refs[i] = new_speed_id
        break
quick_build("TestS11_OneSpeed", "TestS11-" + str(int(time.time())), d11)
print("S11 done")

# ======== S12: S3 + change ONE canvas[0] ID + update ref ========
print("=== S12: Change 1 canvas ID ===")
d12 = copy.deepcopy(d3)
old_id = d12["materials"]["canvases"][0]["id"]
new_id = uid()
d12["materials"]["canvases"][0]["id"] = new_id
refs = d12["tracks"][0]["segments"][0]["extra_material_refs"]
for i, r in enumerate(refs):
    if r == old_id:
        refs[i] = new_id
        break
quick_build("TestS12_OneCanvas", "TestS12-" + str(int(time.time())), d12)
print("S12 done")

# ======== S13: S3 + replace ALL video materials by rebuilding from prototype ========
print("=== S13: Replace video materials (2) using prototype ===")
d13 = copy.deepcopy(d3)
proto_vm = copy.deepcopy(d13["materials"]["videos"][0])
new_vids = []
for i in range(2):
    m = copy.deepcopy(proto_vm)
    m["id"] = uid()
    m["material_id"] = m["id"]
    m["path"] = image_paths[i]
    m["material_name"] = os.path.basename(image_paths[i])
    new_vids.append(m)
d13["materials"]["videos"] = new_vids
# Update segment refs
d13["tracks"][0]["segments"][0]["material_id"] = new_vids[0]["id"]
d13["tracks"][0]["segments"][1]["material_id"] = new_vids[1]["id"]
quick_build("TestS13_NewVidMats", "TestS13-" + str(int(time.time())), d13)
print("S13 done")

# ======== S14: S3 + replace ALL text material ========
print("=== S14: Replace text material ===")
d14 = copy.deepcopy(d3)
proto_tm = copy.deepcopy(d14["materials"]["texts"][0])
m = copy.deepcopy(proto_tm)
m["id"] = uid()
m["content"] = json.dumps({
    "styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
        "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}},
        "range": [0, len(sentences[0])], "size": 5.0,
        "bold": True, "italic": False, "underline": False, "strokes": []}],
    "text": sentences[0]
}, ensure_ascii=False)
d14["materials"]["texts"] = [m]
d14["tracks"][2]["segments"][0]["material_id"] = m["id"]
quick_build("TestS14_NewTextMat", "TestS14-" + str(int(time.time())), d14)
print("S14 done")

# ======== S15: S3 + replace ALL audio material ========
print("=== S15: Replace audio material ===")
d15 = copy.deepcopy(d3)
proto_am = copy.deepcopy(d15["materials"]["audios"][0])
m = copy.deepcopy(proto_am)
m["id"] = uid()
m["music_id"] = m["id"]
m["local_material_id"] = m["id"]
m["path"] = audio_path
m["name"] = os.path.basename(audio_path)
d15["materials"]["audios"] = [m]
d15["tracks"][1]["segments"][0]["material_id"] = m["id"]
quick_build("TestS15_NewAudioMat", "TestS15-" + str(int(time.time())), d15)
print("S15 done")

# ======== S16: S13 + S14 (new video + text materials) ========
print("=== S16: New video + text materials ===")
d16 = copy.deepcopy(d13)
proto_tm = copy.deepcopy(d16["materials"]["texts"][0])
m = copy.deepcopy(proto_tm)
m["id"] = uid()
m["content"] = json.dumps({
    "styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
        "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}},
        "range": [0, len(sentences[0])], "size": 5.0,
        "bold": True, "italic": False, "underline": False, "strokes": []}],
    "text": sentences[0]
}, ensure_ascii=False)
d16["materials"]["texts"] = [m]
d16["tracks"][2]["segments"][0]["material_id"] = m["id"]
quick_build("TestS16_VidText", "TestS16-" + str(int(time.time())), d16)
print("S16 done")

# ======== S17: S16 + new audio material ========
print("=== S17: New video + text + audio materials ===")
d17 = copy.deepcopy(d16)
proto_am = copy.deepcopy(d17["materials"]["audios"][0])
m = copy.deepcopy(proto_am)
m["id"] = uid()
m["music_id"] = m["id"]
m["local_material_id"] = m["id"]
m["path"] = audio_path
m["name"] = os.path.basename(audio_path)
d17["materials"]["audios"] = [m]
d17["tracks"][1]["segments"][0]["material_id"] = m["id"]
quick_build("TestS17_All3Mats", "TestS17-" + str(int(time.time())), d17)
print("S17 done")

print(f"\n{'='*60}")
print("S11-S17 registered. Open 剪映 and check each.")
print("S11: 1 speed ID change   S12: 1 canvas ID change")
print("S13: new video mats   S14: new text mat   S15: new audio mat")
print("S16: video+text mats   S17: video+text+audio mats")
