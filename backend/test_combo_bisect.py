"""
关键测试: service 的 JSON 生成逻辑 + quick_build 写文件
如果这能打开, bug 就在 service 的文件写入环节
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

def decrypt_file(enc_path):
    import tempfile
    tmp = tempfile.mktemp(suffix=".json")
    subprocess.run(["jy-draftc", "-d", enc_path, tmp], env=env, capture_output=True, text=True)
    if not os.path.exists(tmp):
        raise FileNotFoundError(f"Decrypt failed: {enc_path}")
    with open(tmp, "r", encoding="utf-8") as f:
        data = json.load(f)
    os.remove(tmp)
    return data

from services.llm_service import split_into_short_sentences
from services.video_service import get_audio_duration, split_into_word_groups
from services.jianying_v11_service import (
    _deep_clone_prototypes, _remap_aux_ids, _build_video_refs,
    _build_audio_refs, _append_aux_for_video, _mk_target_timerange, _uid,
)

# ======== 共享数据 ========
images_dir = os.path.join(TASK_DIR, "images")
img_files = sorted([f for f in os.listdir(images_dir) if f.endswith(".png") and f.startswith("seg_")])
img_map = {}
for f in img_files:
    seg_idx = int(f.replace("seg_", "").replace(".png", ""))
    img_map[seg_idx] = os.path.join(images_dir, f).replace("\\", "/")
image_paths = [img_map.get(i, img_map.get(0, "")) for i in range(26)]

segments_dir = os.path.join(TASK_DIR, "segments")
seg_files = sorted([f for f in os.listdir(segments_dir) if f.endswith(".mp3") and f.startswith("seg_")])
tts_durs = [get_audio_duration(os.path.join(segments_dir, sf)) for sf in seg_files]
seg_durations_us = [d * 1_000_000 for d in tts_durs[:26]]

audio_path = os.path.join(TASK_DIR, "final_audio.mp3")
if not os.path.exists(audio_path):
    audio_path = os.path.join(TASK_DIR, "final_tts.mp3")
audio_path = audio_path.replace("\\", "/")

with open(os.path.join(TASK_DIR, "rewritten.txt"), "r", encoding="utf-8") as f:
    raw = f.read()
full_text = ""
for line in raw.strip().split("\n"):
    if not line.strip(): continue
    parts = line.split("\t", 1)
    full_text += parts[1] if len(parts) > 1 else parts[0]
sentences = split_into_short_sentences(full_text, max_chars=80, min_chars=30)[:26]

n_sentences = 26
total_dur = int(sum(seg_durations_us))

# ======== 准备 4 种不同组合来二分 ========

# --- 组合 A: service JSON + quick_build (最可能 work) ---
print("=== Combo A: Service JSON + quick_build (min files) ===")
template = decrypt_file(os.path.join(TEMPLATE_DIR, "draft_content.json"))
proto = _deep_clone_prototypes(template)
draft = copy.deepcopy(template)
tmpl_vid_count = len(draft["materials"]["videos"])

# --- 使用 service 的 JSON 生成逻辑 ---
for i in range(min(tmpl_vid_count, n_sentences)):
    draft["materials"]["videos"][i]["id"] = _uid()
    draft["materials"]["videos"][i]["material_id"] = draft["materials"]["videos"][i]["id"]
    draft["materials"]["videos"][i]["path"] = image_paths[i]
    draft["materials"]["videos"][i]["material_name"] = os.path.basename(image_paths[i])
for i in range(tmpl_vid_count, n_sentences):
    vm = copy.deepcopy(proto["video_mat"]); vm["id"] = _uid(); vm["material_id"] = vm["id"]
    vm["path"] = image_paths[i]; vm["material_name"] = os.path.basename(image_paths[i])
    draft["materials"]["videos"].append(vm)

tmpl_text_count = len(draft["materials"]["texts"])
all_text_groups = []; text_idx = 0
for i, text in enumerate(sentences):
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
        draft["materials"]["texts"][gi]["font_path"] = FONT_PATH
    else:
        tm = copy.deepcopy(proto["text_mat"]); tm["id"] = _uid()
        tm["content"] = content_json; tm["font_path"] = FONT_PATH
        draft["materials"]["texts"].append(tm)

draft["materials"]["audios"][0]["id"] = _uid()
draft["materials"]["audios"][0]["music_id"] = draft["materials"]["audios"][0]["id"]
draft["materials"]["audios"][0]["local_material_id"] = draft["materials"]["audios"][0]["id"]
draft["materials"]["audios"][0]["path"] = audio_path
draft["materials"]["audios"][0]["name"] = os.path.basename(audio_path)
draft["materials"]["audios"][0]["duration"] = total_dur

_remap_aux_ids(draft)
for i in range(tmpl_vid_count, n_sentences):
    _append_aux_for_video(draft, proto)

tmpl_vid_segs = len(draft["tracks"][0]["segments"])
time_cursor = 0.0
for i in range(min(tmpl_vid_segs, n_sentences)):
    seg = draft["tracks"][0]["segments"][i]; dur = seg_durations_us[i]
    seg["id"] = _uid(); seg["material_id"] = draft["materials"]["videos"][i]["id"]
    seg["source_timerange"]["duration"] = int(dur)
    seg["target_timerange"] = _mk_target_timerange(time_cursor, dur)
    seg["extra_material_refs"] = _build_video_refs(draft, i)
    time_cursor += dur
for i in range(tmpl_vid_segs, n_sentences):
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
audio_seg["extra_material_refs"] = _build_audio_refs(draft, n_sentences)

tmpl_text_segs = len(draft["tracks"][2]["segments"])
stime_cursor = 0.0; gi = 0
for i, text in enumerate(sentences):
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

draft["duration"] = total_dur

# ======== quick_build (S20/Scaletest 同款) ========
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
        "draft_fold_path": dfold, "draft_id": draft_id,
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
        "tm_draft_create": NOW_US, "tm_draft_modified": NOW_US, "tm_draft_removed": 0,
    })
    meta["all_draft_store"] = all_drafts
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

def quick_build(name, draft_id, draft_obj):
    dir_path = make_dir(name)
    dc_path = os.path.join(dir_path, "draft_content.json")
    with open(dc_path, "w", encoding="utf-8") as f:
        json.dump(draft_obj, f, ensure_ascii=False, indent=2)
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

name_a = "ComboA_SvcJSON_QuickBuild"
draft_id_a = f"ComboA-{int(time.time())}"
quick_build(name_a, draft_id_a, draft)
print(f"  [OK] {name_a} ({len(draft['tracks'][0]['segments'])}v, {len(draft['tracks'][2]['segments'])}t)")

# --- 组合 B: service JSON + 完整模板文件 (模拟 service write，但不改 draft_meta_info) ---
print("\n=== Combo B: Service JSON + Full template files (no meta edit) ===")
dir_b = make_dir("ComboB_SvcJSON_FullFiles")
dc_b = os.path.join(dir_b, "draft_content.json")
with open(dc_b, "w", encoding="utf-8") as f:
    json.dump(draft, f, ensure_ascii=False, indent=2)

# Copy ALL template files (same as service)
OVERWRITE_FILES = {"draft_content.json", "draft_meta_info.json", "draft_settings", "draft_cover.jpg"}
for fn in os.listdir(TEMPLATE_DIR):
    if fn.startswith(".") or fn == "Timelines" or fn in OVERWRITE_FILES:
        continue
    if fn.endswith(".json") and any(x in fn for x in [".debug", ".dec", ".iso", ".tmpl", ".bs", ".chk", ".refs", ".deep", ".s10", ".s11", ".s18", ".s20", ".mod", ".reenc", ".scale", ".diff"]):
        continue
    sf = os.path.join(TEMPLATE_DIR, fn)
    df = os.path.join(dir_b, fn)
    if os.path.isdir(sf):
        if os.path.exists(df): shutil.rmtree(df)
        shutil.copytree(sf, df)
    else:
        shutil.copy2(sf, df)

# Copy core 3 from template (encrypted)
for fn in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
    sf = os.path.join(TEMPLATE_DIR, fn)
    if os.path.exists(sf): shutil.copy2(sf, os.path.join(dir_b, fn))

# Copy Timelines
tl_src = os.path.join(TEMPLATE_DIR, "Timelines")
tl_dst = os.path.join(dir_b, "Timelines")
shutil.copytree(tl_src, tl_dst)
for d in os.listdir(tl_dst):
    dp = os.path.join(tl_dst, d)
    if os.path.isdir(dp) and d != "common_attachment":
        shutil.copy2(dc_b, os.path.join(dp, "draft_content.json"))
        for f in os.listdir(dp):
            if f.endswith(".tmp") or f.endswith(".bak"):
                os.remove(os.path.join(dp, f))
        break

# Encrypt
encrypt(dc_b)
for d in os.listdir(tl_dst):
    dp = os.path.join(tl_dst, d)
    if os.path.isdir(dp) and d != "common_attachment":
        encrypt(os.path.join(dp, "draft_content.json"), dp)

register("ComboB_SvcJSON_FullFiles", dir_b, f"ComboB-{int(time.time())}")
print(f"  [OK] ComboB_SvcJSON_FullFiles")

# --- 组合 C: service JSON + full files + MODIFY draft_meta_info (完整模拟 service) ---
print("\n=== Combo C: Service JSON + Full files + Meta edit (full service mimic) ===")
dir_c = make_dir("ComboC_FullService")
dc_c = os.path.join(dir_c, "draft_content.json")
with open(dc_c, "w", encoding="utf-8") as f:
    json.dump(draft, f, ensure_ascii=False, indent=2)

# Same full copy as Combo B
for fn in os.listdir(TEMPLATE_DIR):
    if fn.startswith(".") or fn == "Timelines" or fn in OVERWRITE_FILES:
        continue
    if fn.endswith(".json") and any(x in fn for x in [".debug", ".dec", ".iso", ".tmpl", ".bs", ".chk", ".refs", ".deep", ".s10", ".s11", ".s18", ".s20", ".mod", ".reenc", ".scale", ".diff"]):
        continue
    sf = os.path.join(TEMPLATE_DIR, fn)
    df = os.path.join(dir_c, fn)
    if os.path.isdir(sf):
        if os.path.exists(df): shutil.rmtree(df)
        shutil.copytree(sf, df)
    else:
        shutil.copy2(sf, df)

for fn in ["draft_meta_info.json", "draft_settings", "draft_cover.jpg"]:
    sf = os.path.join(TEMPLATE_DIR, fn)
    if os.path.exists(sf): shutil.copy2(sf, os.path.join(dir_c, fn))

# MODIFY draft_meta_info.json (decrypt + edit + re-encrypt)
dm_path = os.path.join(dir_c, "draft_meta_info.json")
dm = decrypt_file(dm_path)
dm["draft_id"] = f"ComboC-{int(time.time())}"
dm["draft_name"] = "ComboC_FullService"
dm["draft_fold_path"] = dir_c.replace("\\", "/")
dm["draft_root_path"] = DRAFT_ROOT.replace("\\", "/")
dm["tm_draft_create"] = NOW_US
dm["tm_draft_modified"] = NOW_US
dm["tm_duration"] = total_dur
with open(dm_path, "w", encoding="utf-8") as f:
    json.dump(dm, f, ensure_ascii=False, indent=2)

# Copy Timelines
shutil.copytree(tl_src, os.path.join(dir_c, "Timelines"))
for d in os.listdir(os.path.join(dir_c, "Timelines")):
    dp = os.path.join(dir_c, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        shutil.copy2(dc_c, os.path.join(dp, "draft_content.json"))
        for f in os.listdir(dp):
            if f.endswith(".tmp") or f.endswith(".bak"):
                os.remove(os.path.join(dp, f))
        break

# Encrypt all
encrypt(dc_c)
encrypt(dm_path)
for d in os.listdir(os.path.join(dir_c, "Timelines")):
    dp = os.path.join(dir_c, "Timelines", d)
    if os.path.isdir(dp) and d != "common_attachment":
        encrypt(os.path.join(dp, "draft_content.json"), dp)

register("ComboC_FullService", dir_c, f"ComboC-{int(time.time())}")
print(f"  [OK] ComboC_FullService")

print("\n" + "="*70)
print("3 combos built:")
print("  ComboA: Service JSON + quick_build (min files, no meta edit)")
print("  ComboB: Service JSON + full template files, encrypted meta from template")
print("  ComboC: Service JSON + full files + meta decrypt/edit/re-encrypt")
print("\nTest order: A -> B -> C (stop at first failure)")
