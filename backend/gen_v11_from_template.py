"""
从工作草稿模板生成 Task6 v11 草稿 — 只替换内容，保留结构
"""
import json, os, uuid, subprocess, shutil, time, copy

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
FONT_PATH = JY_DIR + "/Resources/Font/SystemFont/zh-hans.ttf"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
FOLDER_NAME = "Task6_v11_final"
DRAFT_DIR = os.path.join(DRAFT_ROOT, FOLDER_NAME)
TASK_DIR = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6"
DRAFT_ID = "Task6-v11f-" + str(int(time.time()))
NOW_US = int(time.time() * 1000000)
NOW_S = int(time.time())

def uid():
    return uuid.uuid4().hex

# ======== 加载模板和工作草稿 ========
# 解密 TestReEncrypt 的 draft_content.json
TEMPLATE_DIR = r"E:/360Downloads/JianyingPro Drafts/TestReEncrypt"
tmpl_enc = os.path.join(TEMPLATE_DIR, "draft_content.json")
tmpl_dec = os.path.join(TEMPLATE_DIR, "draft_content.tmpl.json")
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR
subprocess.run(["jy-draftc", "-d", tmpl_enc, tmpl_dec], env=env,
               capture_output=True, text=True, cwd=TEMPLATE_DIR)

with open(tmpl_dec, "r", encoding="utf-8") as f:
    template = json.load(f)
print(f"Template loaded: {len(template['materials']['videos'])} vids, {len(template['materials']['texts'])} texts")

# ======== 数据准备 ========
from services.llm_service import split_into_short_sentences
from services.video_service import get_audio_duration, split_into_word_groups

with open(os.path.join(TASK_DIR, "rewritten.txt"), "r", encoding="utf-8") as f:
    raw = f.read()
full_text = ""
for line in raw.strip().split("\n"):
    if not line.strip():
        continue
    parts = line.split("\t", 1)
    full_text += parts[1] if len(parts) > 1 else parts[0]
sentences = split_into_short_sentences(full_text, max_chars=80, min_chars=30)

segments_dir = os.path.join(TASK_DIR, "segments")
seg_files = sorted([f for f in os.listdir(segments_dir)
                    if f.endswith(".mp3") and f.startswith("seg_")])
tts_durs = [get_audio_duration(os.path.join(segments_dir, sf)) for sf in seg_files]
seg_durations = [d * 1_000_000 for d in tts_durs]
total_duration_us = int(sum(seg_durations))

images_dir = os.path.join(TASK_DIR, "images")
img_files = sorted([f for f in os.listdir(images_dir)
                    if f.endswith(".png") and f.startswith("seg_")])
img_map = {}
for f in img_files:
    seg_idx = int(f.replace("seg_", "").replace(".png", ""))
    img_map[seg_idx] = os.path.join(images_dir, f).replace("\\", "/")

image_paths = []
for i in range(len(sentences)):
    if i in img_map:
        image_paths.append(img_map[i])
    else:
        image_paths.append(image_paths[-1] if image_paths else None)

audio_path = os.path.join(TASK_DIR, "final_audio.mp3")
if not os.path.exists(audio_path):
    audio_path = os.path.join(TASK_DIR, "final_tts.mp3")
audio_path = audio_path.replace("\\", "/")

print(f"Data: {len(sentences)} sentences, {total_duration_us/1e6:.1f}s")

# ======== 基于模板克隆结构 ========
# 取模板的第一个视频/文本 segment 作为原型
proto_video_seg = copy.deepcopy(template["tracks"][0]["segments"][0])
proto_video_mat = copy.deepcopy(template["materials"]["videos"][0])
proto_text_seg = copy.deepcopy(template["tracks"][2]["segments"][0])
proto_text_mat = copy.deepcopy(template["materials"]["texts"][0])

# 辅助素材原型
proto_speed = copy.deepcopy(template["materials"]["speeds"][0])
proto_canvas = copy.deepcopy(template["materials"]["canvases"][0])
proto_anim = copy.deepcopy(template["materials"]["material_animations"][0])
proto_color = copy.deepcopy(template["materials"]["material_colors"][0])
proto_sound = copy.deepcopy(template["materials"]["sound_channel_mappings"][0])
proto_loud = copy.deepcopy(template["materials"]["loudnesses"][0])
proto_ph = copy.deepcopy(template["materials"]["placeholder_infos"][0])
proto_vocal = copy.deepcopy(template["materials"]["vocal_separations"][0])
proto_audio_mat = copy.deepcopy(template["materials"]["audios"][0])
proto_audio_seg = copy.deepcopy(template["tracks"][1]["segments"][0])

# ======== 生成材枴 ========
video_mat_ids = []
video_mats = []
for i, img_path in enumerate(image_paths):
    mid = uid()
    video_mat_ids.append(mid)
    m = copy.deepcopy(proto_video_mat)
    m["id"] = mid
    m["material_id"] = mid
    m["path"] = img_path
    m["material_name"] = os.path.basename(img_path)
    video_mats.append(m)

# 字幕素材
text_mat_ids = []
text_mats = []
stime_cursor = 0.0
for i, text in enumerate(sentences):
    dur = seg_durations[i]
    if dur <= 0:
        continue
    groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
    for group in groups:
        tid = uid()
        text_mat_ids.append(tid)
        m = copy.deepcopy(proto_text_mat)
        m["id"] = tid
        # Build proper style JSON
        style_json = json.dumps({
            "styles": [{
                "fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}},
                "range": [0, len(group["text"])],
                "size": 5.0, "bold": True, "italic": False, "underline": False, "strokes": []
            }],
            "text": group["text"]
        }, ensure_ascii=False)
        m["content"] = style_json
        m["font_path"] = FONT_PATH
        text_mats.append(m)

# 音频素材
audio_mat_id = uid()
audio_mat = copy.deepcopy(proto_audio_mat)
audio_mat["id"] = audio_mat_id
audio_mat["material_id"] = audio_mat_id
audio_mat["music_id"] = audio_mat_id
audio_mat["local_material_id"] = audio_mat_id
audio_mat["path"] = audio_path
audio_mat["name"] = os.path.basename(audio_path)
audio_mat["duration"] = total_duration_us

# 辅助素材（按视频段数生成）
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

# ======== 生成轨道 segments ========
video_segs = []
time_cursor = 0.0
for i in range(len(sentences)):
    dur = seg_durations[i]
    if dur <= 0:
        continue
    seg = copy.deepcopy(proto_video_seg)
    seg["id"] = uid()
    seg["material_id"] = video_mat_ids[i]
    seg["source_timerange"]["duration"] = int(dur)
    seg["target_timerange"] = {"start": int(time_cursor), "duration": int(dur)}
    seg["extra_material_refs"] = [speeds[i]["id"], phs[i]["id"], canvases[i]["id"],
                                   anims[i]["id"], colors[i]["id"], sounds[i]["id"],
                                   louds[i]["id"], vocals[i]["id"]]
    video_segs.append(seg)
    time_cursor += dur

# 音频 segment
audio_seg = copy.deepcopy(proto_audio_seg)
audio_seg["id"] = uid()
audio_seg["material_id"] = audio_mat_id
audio_seg["source_timerange"]["duration"] = total_duration_us
audio_seg["target_timerange"] = {"start": 0, "duration": total_duration_us}

# 字幕 segments
text_segs = []
stime_cursor = 0.0
ti = 0
for i, text in enumerate(sentences):
    dur = seg_durations[i]
    if dur <= 0:
        continue
    groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
    for group in groups:
        gdur = int((group["end"] - group["start"]) * 1_000_000)
        gstart = int((stime_cursor + group["start"]) * 1_000_000)
        seg = copy.deepcopy(proto_text_seg)
        seg["id"] = uid()
        seg["material_id"] = text_mat_ids[ti]
        seg["target_timerange"] = {"start": gstart, "duration": gdur}
        text_segs.append(seg)
        ti += 1
    stime_cursor += dur

# ======== 组装完整草稿 ========
draft = copy.deepcopy(template)
draft["id"] = str(uuid.uuid4()).upper()
draft["duration"] = total_duration_us
draft["new_version"] = "177.0.0"

draft["materials"]["videos"] = video_mats
draft["materials"]["audios"] = [audio_mat]
draft["materials"]["texts"] = text_mats
draft["materials"]["canvases"] = canvases
draft["materials"]["speeds"] = speeds
draft["materials"]["material_animations"] = anims
draft["materials"]["material_colors"] = colors
draft["materials"]["sound_channel_mappings"] = sounds
draft["materials"]["loudnesses"] = louds
draft["materials"]["placeholder_infos"] = phs
draft["materials"]["vocal_separations"] = vocals

draft["tracks"][0]["id"] = uid()
draft["tracks"][0]["segments"] = video_segs
draft["tracks"][1]["id"] = uid()
draft["tracks"][1]["segments"] = [audio_seg]
draft["tracks"][2]["id"] = uid()
draft["tracks"][2]["segments"] = text_segs

# ======== 写入文件 ========
os.makedirs(DRAFT_DIR, exist_ok=True)

# draft_content.json
dc_path = os.path.join(DRAFT_DIR, "draft_content.json")
with open(dc_path, "w", encoding="utf-8") as f:
    json.dump(draft, f, ensure_ascii=False, indent=2)

# draft_meta_info.json: 复制模板 + 改字段
# Decrypt template meta
tmpl_meta_enc = os.path.join(TEMPLATE_DIR, "draft_meta_info.json")
tmpl_meta_dec = os.path.join(TEMPLATE_DIR, "draft_meta_info.tmpl.json")
subprocess.run(["jy-draftc", "-d", tmpl_meta_enc, tmpl_meta_dec], env=env,
               capture_output=True, text=True, cwd=TEMPLATE_DIR)

with open(tmpl_meta_dec, "r", encoding="utf-8") as f:
    draft_meta = json.load(f)

draft_meta["draft_id"] = DRAFT_ID
draft_meta["draft_name"] = FOLDER_NAME
draft_meta["draft_fold_path"] = DRAFT_DIR.replace("\\", "/")
draft_meta["draft_root_path"] = DRAFT_ROOT.replace("\\", "/")
draft_meta["draft_removable_storage_device"] = "E:"
draft_meta["tm_draft_create"] = NOW_US
draft_meta["tm_draft_modified"] = NOW_US
draft_meta["tm_duration"] = total_duration_us
draft_meta["draft_timeline_materials_size_"] = sum(
    os.path.getsize(p) for p in image_paths if os.path.exists(p)) + os.path.getsize(audio_path)
draft_meta["draft_materials"][0]["value"][0]["id"] = audio_mat_id
draft_meta["draft_materials"][0]["value"][0]["duration"] = total_duration_us
draft_meta["draft_materials"][0]["value"][0]["extra_info"] = os.path.basename(audio_path)
draft_meta["draft_materials"][0]["value"][0]["file_Path"] = "./" + os.path.basename(audio_path)
draft_meta["draft_materials"][0]["value"][0]["roughcut_time_range"]["duration"] = total_duration_us

dm_path = os.path.join(DRAFT_DIR, "draft_meta_info.json")
with open(dm_path, "w", encoding="utf-8") as f:
    json.dump(draft_meta, f, ensure_ascii=False, indent=2)

# draft_settings
ds_path = os.path.join(DRAFT_DIR, "draft_settings")
with open(ds_path, "w", encoding="utf-8") as f:
    f.write(f"""[General]
cloud_last_modify_platform=windows
draft_create_time={NOW_S}
draft_last_edit_time={NOW_S}
real_edit_seconds=0
real_edit_keys=0
""")

# draft_cover.jpg
if image_paths:
    shutil.copy2(image_paths[0], os.path.join(DRAFT_DIR, "draft_cover.jpg"))

# Timelines/ — 完整复制
tl_src = os.path.join(TEMPLATE_DIR, "Timelines")
tl_dst = os.path.join(DRAFT_DIR, "Timelines")
if os.path.exists(tl_dst):
    shutil.rmtree(tl_dst)
shutil.copytree(tl_src, tl_dst)

# 更新 Timelines/project.json
proj_path = os.path.join(tl_dst, "project.json")
with open(proj_path, "r", encoding="utf-8") as f:
    proj = json.load(f)
new_tl_id = str(uuid.uuid4()).upper()
proj["id"] = new_tl_id
proj["main_timeline_id"] = new_tl_id
proj["create_time"] = NOW_US
proj["update_time"] = NOW_US
proj["timelines"][0]["id"] = new_tl_id
proj["timelines"][0]["create_time"] = NOW_US
proj["timelines"][0]["update_time"] = NOW_US
with open(proj_path, "w", encoding="utf-8") as f:
    json.dump(proj, f, ensure_ascii=False, indent=2)

# 更新 Timelines/<id>/draft_content.json (复制主草稿)
tl_sub = os.path.join(tl_dst, os.listdir(tl_dst)[0])
if os.path.isdir(tl_sub):
    shutil.copy2(dc_path, os.path.join(tl_sub, "draft_content.json"))

# ======== 加密 ========
for fname in ["draft_content.json", "draft_meta_info.json"]:
    fpath = os.path.join(DRAFT_DIR, fname)
    subprocess.run(["jy-draftc", "-e", fpath], cwd=DRAFT_DIR, env=env,
                   capture_output=True, text=True)
    enc_path = fpath + ".enc.json"
    if os.path.exists(enc_path):
        os.remove(fpath)
        os.rename(enc_path, fpath)
        print(f"{fname}: encrypted ({os.path.getsize(fpath)} bytes)")
    else:
        print(f"{fname}: FAILED")

# Timelines version
tl_dc = None
for item in os.listdir(tl_dst):
    item_path = os.path.join(tl_dst, item)
    if os.path.isdir(item_path):
        tl_dc = os.path.join(item_path, "draft_content.json")
        break
if tl_dc and os.path.exists(tl_dc):
    subprocess.run(["jy-draftc", "-e", tl_dc], cwd=os.path.dirname(tl_dc), env=env,
                   capture_output=True, text=True)
    enc_out = tl_dc + ".enc.json"
    if os.path.exists(enc_out):
        os.remove(tl_dc)
        os.rename(enc_out, tl_dc)
        print("Timelines/draft_content.json: encrypted")

# ======== 注册 ========
meta_path = r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json"
with open(meta_path, "r", encoding="utf-8") as f:
    meta = json.load(f)

all_drafts = meta.get("all_draft_store", [])
all_drafts = [d for d in all_drafts if DRAFT_ID not in str(d.get("draft_id", ""))]
all_drafts = [d for d in all_drafts if "Task6_v11_final" not in str(d.get("draft_name", ""))]

total_mat_size = draft_meta["draft_timeline_materials_size_"]
dfold = DRAFT_DIR.replace("\\", "/")
all_drafts.insert(0, {
    "cloud_draft_cover": False, "cloud_draft_sync": False,
    "draft_cloud_last_action_download": False,
    "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
    "draft_cloud_tutorial_info": "", "draft_cloud_videocut_purchase_info": "",
    "draft_cover": dfold + "/draft_cover.jpg",
    "draft_fold_path": dfold,
    "draft_id": DRAFT_ID,
    "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
    "draft_is_invisible": False, "draft_is_web_article_video": False,
    "draft_json_file": dfold + "/draft_content.json",
    "draft_name": FOLDER_NAME,
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

print(f"\nDONE: {FOLDER_NAME}")
print(f"  Video: {len(video_segs)} segments")
print(f"  Text: {len(text_segs)} segments")
print(f"  Duration: {total_duration_us/1e6:.1f}s")
print(f"\nClose + reopen 剪映 to test.")
