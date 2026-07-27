"""最终测试：用service JSON + quick_build写文件 = ComboA同款"""
import sys, os, time, json, shutil, subprocess, copy

sys.path.insert(0, os.path.dirname(__file__))

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
TEMPLATE_DIR = r"E:/360Downloads/JianyingPro Drafts/TestReEncrypt"
REG_PATH = r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json"
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR

# Import service helpers
from services.jianying_v11_service import (
    _load_template, _deep_clone_prototypes, _uid, _mk_target_timerange,
    _remap_aux_ids, _build_video_refs, _build_audio_refs, _append_aux_for_video,
    _decrypt_file, _encrypt_file, SYSTEM_FONT_PATH
)
from services.llm_service import split_into_short_sentences
from services.video_service import get_audio_duration, split_into_word_groups

# ======== Load data ========
TASK_DIR = os.path.join(os.path.dirname(__file__), "data", "tasks", "6")

with open(os.path.join(TASK_DIR, "rewritten.txt"), "r", encoding="utf-8") as f:
    raw = f.read()
full_text = ""
for line in raw.strip().split("\n"):
    if not line.strip():
        continue
    parts = line.split("\t", 1)
    full_text += parts[1] if len(parts) > 1 else parts[0]
sentences = split_into_short_sentences(full_text, max_chars=80, min_chars=30)

images_dir = os.path.join(TASK_DIR, "images")
img_files = sorted([f for f in os.listdir(images_dir) if f.endswith(".png") and f.startswith("seg_")])
img_map = {}
for f in img_files:
    seg_idx = int(f.replace("seg_", "").replace(".png", ""))
    img_map[seg_idx] = os.path.join(images_dir, f).replace("\\", "/")
image_paths = [img_map.get(i, img_map.get(0, "")) for i in range(len(sentences))]

segments_dir = os.path.join(TASK_DIR, "segments")
seg_files = sorted([f for f in os.listdir(segments_dir) if f.endswith(".mp3") and f.startswith("seg_")])
tts_durs = [get_audio_duration(os.path.join(segments_dir, sf)) for sf in seg_files]
seg_durations_us = [d * 1_000_000 for d in tts_durs]

audio_path = os.path.join(TASK_DIR, "final_audio.mp3")
if not os.path.exists(audio_path):
    audio_path = os.path.join(TASK_DIR, "final_tts.mp3")
audio_path = audio_path.replace("\\", "/")

# ======== Build JSON using service functions ========
n = 26
total_dur = int(sum(seg_durations_us[:n]))

template = _load_template()
proto = _deep_clone_prototypes(template)
draft = copy.deepcopy(template)

tmpl_vid_count = len(draft["materials"]["videos"])
for i in range(min(tmpl_vid_count, n)):
    draft["materials"]["videos"][i]["id"] = _uid()
    draft["materials"]["videos"][i]["material_id"] = draft["materials"]["videos"][i]["id"]
    draft["materials"]["videos"][i]["path"] = image_paths[i]
    draft["materials"]["videos"][i]["material_name"] = os.path.basename(image_paths[i])
for i in range(tmpl_vid_count, n):
    vm = copy.deepcopy(proto["video_mat"]); vm["id"] = _uid(); vm["material_id"] = vm["id"]
    vm["path"] = image_paths[i]; vm["material_name"] = os.path.basename(image_paths[i])
    draft["materials"]["videos"].append(vm)

tmpl_text_count = len(draft["materials"]["texts"])
all_text_groups = []; text_idx = 0
for i, text in enumerate(sentences[:n]):
    dur = seg_durations_us[i]
    if dur <= 0: continue
    groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
    for group in groups:
        all_text_groups.append((text_idx, group, i)); text_idx += 1
for gi, (ti, group, si) in enumerate(all_text_groups):
    content_json = json.dumps({"styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
        "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}}, "range": [0, len(group["text"])],
        "size": 5.0, "bold": True, "italic": False, "underline": False, "strokes": []}],
        "text": group["text"]}, ensure_ascii=False)
    if gi < tmpl_text_count:
        draft["materials"]["texts"][gi]["id"] = _uid()
        draft["materials"]["texts"][gi]["content"] = content_json
        draft["materials"]["texts"][gi]["font_path"] = SYSTEM_FONT_PATH
    else:
        tm = copy.deepcopy(proto["text_mat"]); tm["id"] = _uid()
        tm["content"] = content_json; tm["font_path"] = SYSTEM_FONT_PATH
        draft["materials"]["texts"].append(tm)

draft["materials"]["audios"][0]["id"] = _uid()
draft["materials"]["audios"][0]["music_id"] = draft["materials"]["audios"][0]["id"]
draft["materials"]["audios"][0]["local_material_id"] = draft["materials"]["audios"][0]["id"]
draft["materials"]["audios"][0]["path"] = audio_path
draft["materials"]["audios"][0]["name"] = os.path.basename(audio_path)
draft["materials"]["audios"][0]["duration"] = total_dur

_remap_aux_ids(draft)
for i in range(tmpl_vid_count, n):
    _append_aux_for_video(draft, proto)

tmpl_vid_segs = len(draft["tracks"][0]["segments"])
time_cursor = 0.0
for i in range(min(tmpl_vid_segs, n)):
    seg = draft["tracks"][0]["segments"][i]; dur = seg_durations_us[i]
    seg["id"] = _uid(); seg["material_id"] = draft["materials"]["videos"][i]["id"]
    seg["source_timerange"]["duration"] = int(dur)
    seg["target_timerange"] = _mk_target_timerange(time_cursor, dur)
    seg["extra_material_refs"] = _build_video_refs(draft, i)
    time_cursor += dur
for i in range(tmpl_vid_segs, n):
    dur = seg_durations_us[i]
    seg = copy.deepcopy(proto["video_seg"]); seg["id"] = _uid()
    seg["material_id"] = draft["materials"]["videos"][i]["id"]
    seg["source_timerange"]["duration"] = int(dur)
    seg["target_timerange"] = {"start": int(time_cursor), "duration": int(dur)}
    seg["extra_material_refs"] = _build_video_refs(draft, i)
    draft["tracks"][0]["segments"].append(seg)
    time_cursor += dur

audio_seg = draft["tracks"][1]["segments"][0]; audio_seg["id"] = _uid()
audio_seg["material_id"] = draft["materials"]["audios"][0]["id"]
audio_seg["source_timerange"]["duration"] = total_dur
audio_seg["target_timerange"] = _mk_target_timerange(0, total_dur)
audio_seg["extra_material_refs"] = _build_audio_refs(draft, n)

tmpl_text_segs = len(draft["tracks"][2]["segments"])
stime_cursor = 0.0; gi = 0
for i, text in enumerate(sentences[:n]):
    dur = seg_durations_us[i]
    if dur <= 0: continue
    groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
    for group in groups:
        gdur = int((group["end"] - group["start"]) * 1_000_000)
        gstart = stime_cursor + group["start"] * 1_000_000
        if gi < tmpl_text_segs:
            seg = draft["tracks"][2]["segments"][gi]; seg["id"] = _uid()
            seg["material_id"] = draft["materials"]["texts"][gi]["id"]
            seg["target_timerange"] = _mk_target_timerange(gstart, gdur)
        else:
            seg = copy.deepcopy(proto["text_seg"]); seg["id"] = _uid()
            seg["material_id"] = draft["materials"]["texts"][gi]["id"]
            seg["target_timerange"] = _mk_target_timerange(gstart, gdur)
            draft["tracks"][2]["segments"].append(seg)
        gi += 1
    stime_cursor += dur

# 不修改 draft["id"] — 必须与 project.json UUID 和 Timelines/ 目录名一致
draft["duration"] = total_dur

# ======== Write with quick_build ========
name = "FinalTest"
draft_dir = os.path.join(DRAFT_ROOT, name)
if os.path.exists(draft_dir):
    shutil.rmtree(draft_dir)
os.makedirs(draft_dir)

dc_path = os.path.join(draft_dir, "draft_content.json")
with open(dc_path, "w", encoding="utf-8") as f:
    json.dump(draft, f, ensure_ascii=False, indent=2)

# Copy template encrypted files
for fn in ["draft_meta_info.json", "draft_settings"]:
    sf = os.path.join(TEMPLATE_DIR, fn)
    if os.path.exists(sf):
        shutil.copy2(sf, os.path.join(draft_dir, fn))

if image_paths and os.path.exists(image_paths[0]):
    shutil.copy2(image_paths[0], os.path.join(draft_dir, "draft_cover.jpg"))

# Copy Timelines
tl_src = os.path.join(TEMPLATE_DIR, "Timelines")
tl_dst = os.path.join(draft_dir, "Timelines")
shutil.copytree(tl_src, tl_dst)
for d in os.listdir(tl_dst):
    dp = os.path.join(tl_dst, d)
    if os.path.isdir(dp) and d != "common_attachment":
        shutil.copy2(dc_path, os.path.join(dp, "draft_content.json"))
        for f in os.listdir(dp):
            if f.endswith(".tmp") or f.endswith(".bak"):
                os.remove(os.path.join(dp, f))
        break

# Fix draft_meta_info.json: decrypt -> edit -> re-encrypt
dm_path = os.path.join(draft_dir, "draft_meta_info.json")
dm = _decrypt_file(dm_path)
dm["draft_id"] = draft["id"]
dm["draft_name"] = name
dm["draft_fold_path"] = draft_dir.replace("\\", "/")
dm["draft_root_path"] = DRAFT_ROOT.replace("\\", "/")
dm["tm_draft_create"] = int(time.time() * 1000000)
dm["tm_draft_modified"] = int(time.time() * 1000000)
dm["tm_duration"] = total_dur
dm["draft_new_version"] = "164.0.0"
with open(dm_path, "w", encoding="utf-8") as f:
    json.dump(dm, f, ensure_ascii=False, indent=2)
_encrypt_file(dm_path)
print(f"Meta edit: OK")

# Encrypt draft_content.json
_encrypt_file(dc_path)
for d in os.listdir(tl_dst):
    dp = os.path.join(tl_dst, d)
    if os.path.isdir(dp) and d != "common_attachment":
        _encrypt_file(os.path.join(dp, "draft_content.json"))

# Register
with open(REG_PATH, "r", encoding="utf-8") as f:
    reg = json.load(f)
now = int(time.time() * 1000000)
dfold = draft_dir.replace("\\", "/")
reg["all_draft_store"].insert(0, {
    "cloud_draft_cover": False, "cloud_draft_sync": False,
    "draft_cloud_last_action_download": False,
    "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
    "draft_cloud_tutorial_info": "", "draft_cloud_videocut_purchase_info": "",
    "draft_cover": dfold + "/draft_cover.jpg",
    "draft_fold_path": dfold, "draft_id": "FINAL-" + str(int(time.time())),
    "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
    "draft_is_invisible": False, "draft_is_web_article_video": False,
    "draft_json_file": dfold + "/draft_content.json",
    "draft_name": name, "draft_new_version": "164.0.0",
    "draft_root_path": DRAFT_ROOT.replace("\\", "/"),
    "draft_timeline_materials_size": 0, "draft_type": "",
    "draft_web_article_video_enter_from": "",
    "streaming_edit_draft_ready": True,
    "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1,
    "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
    "tm_draft_cloud_space_id": -1, "tm_draft_cloud_user_id": -1,
    "tm_draft_create": now, "tm_draft_modified": now, "tm_draft_removed": 0,
})
with open(REG_PATH, "w", encoding="utf-8") as f:
    json.dump(reg, f, ensure_ascii=False, indent=2)

print(f"Done: {draft_dir}")
print(f"Segments: {len(draft['tracks'][0]['segments'])}v, {gi}t, 1a")
