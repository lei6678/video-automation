"""
直接对比 service 和 manual 的 JSON 生成结果 (不写文件)
"""
import json, os, uuid, copy, sys

# Patch _decrypt_file to avoid file issues
import services.jianying_v11_service as svc_mod

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
FONT_PATH = JY_DIR + "/Resources/Font/SystemFont/zh-hans.ttf"
TEMPLATE_DIR = r"E:/360Downloads/JianyingPro Drafts/TestReEncrypt"
TASK_DIR = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6"
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR

def uid():
    return uuid.uuid4().hex

def decrypt_file(enc_path):
    """直接解密返回 dict"""
    import subprocess, tempfile
    tmp = tempfile.mktemp(suffix=".json")
    subprocess.run(["jy-draftc", "-d", enc_path, tmp], env=env, capture_output=True, text=True)
    if not os.path.exists(tmp):
        raise FileNotFoundError(f"Decrypt failed: {enc_path} -> {tmp}")
    with open(tmp, "r", encoding="utf-8") as f:
        data = json.load(f)
    os.remove(tmp)
    return data

# ======== 相同数据 ========
from services.llm_service import split_into_short_sentences
from services.video_service import get_audio_duration, split_into_word_groups

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

# ======== 加载模板 ========
template = decrypt_file(os.path.join(TEMPLATE_DIR, "draft_content.json"))

# ======== Service 方法: 复用 service 核心逻辑 ========
from services.jianying_v11_service import (
    _deep_clone_prototypes, _remap_aux_ids, _build_video_refs,
    _build_audio_refs, _append_aux_for_video, _mk_target_timerange,
    _uid, SYSTEM_FONT_PATH
)

n_sentences = 26
total_dur = int(sum(seg_durations_us))

svc = copy.deepcopy(template)
proto = _deep_clone_prototypes(template)
tmpl_vid_count = len(svc["materials"]["videos"])

# Video materials
for i in range(min(tmpl_vid_count, n_sentences)):
    svc["materials"]["videos"][i]["id"] = _uid()
    svc["materials"]["videos"][i]["material_id"] = svc["materials"]["videos"][i]["id"]
    svc["materials"]["videos"][i]["path"] = image_paths[i]
    svc["materials"]["videos"][i]["material_name"] = os.path.basename(image_paths[i])

for i in range(tmpl_vid_count, n_sentences):
    vm = copy.deepcopy(proto["video_mat"])
    vm["id"] = _uid()
    vm["material_id"] = vm["id"]
    vm["path"] = image_paths[i]
    vm["material_name"] = os.path.basename(image_paths[i])
    svc["materials"]["videos"].append(vm)

# Text materials
tmpl_text_count = len(svc["materials"]["texts"])
all_text_groups = []
text_idx = 0
for i, text in enumerate(sentences):
    dur = seg_durations_us[i]
    if dur <= 0: continue
    groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
    for group in groups:
        all_text_groups.append((text_idx, group, i))
        text_idx += 1

for gi, (ti, group, si) in enumerate(all_text_groups):
    content_json = json.dumps({
        "styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
            "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}},
            "range": [0, len(group["text"])],
            "size": 5.0, "bold": True, "italic": False, "underline": False, "strokes": []}],
        "text": group["text"]
    }, ensure_ascii=False)
    if gi < tmpl_text_count:
        svc["materials"]["texts"][gi]["id"] = _uid()
        svc["materials"]["texts"][gi]["content"] = content_json
        svc["materials"]["texts"][gi]["font_path"] = SYSTEM_FONT_PATH
    else:
        tm = copy.deepcopy(proto["text_mat"])
        tm["id"] = _uid()
        tm["content"] = content_json
        tm["font_path"] = SYSTEM_FONT_PATH
        svc["materials"]["texts"].append(tm)

# Audio material
svc["materials"]["audios"][0]["id"] = _uid()
svc["materials"]["audios"][0]["music_id"] = svc["materials"]["audios"][0]["id"]
svc["materials"]["audios"][0]["local_material_id"] = svc["materials"]["audios"][0]["id"]
svc["materials"]["audios"][0]["path"] = audio_path
svc["materials"]["audios"][0]["name"] = os.path.basename(audio_path)
svc["materials"]["audios"][0]["duration"] = total_dur

# Aux remap + append
_remap_aux_ids(svc)
for i in range(tmpl_vid_count, n_sentences):
    _append_aux_for_video(svc, proto)

# Video segments
tmpl_vid_segs = len(svc["tracks"][0]["segments"])
time_cursor = 0.0
for i in range(min(tmpl_vid_segs, n_sentences)):
    seg = svc["tracks"][0]["segments"][i]
    dur = seg_durations_us[i]
    seg["id"] = _uid()
    seg["material_id"] = svc["materials"]["videos"][i]["id"]
    seg["source_timerange"]["duration"] = int(dur)
    seg["target_timerange"] = _mk_target_timerange(time_cursor, dur)
    seg["extra_material_refs"] = _build_video_refs(svc, i)
    time_cursor += dur

for i in range(tmpl_vid_segs, n_sentences):
    dur = seg_durations_us[i]
    seg = copy.deepcopy(proto["video_seg"])
    seg["id"] = _uid()
    seg["material_id"] = svc["materials"]["videos"][i]["id"]
    seg["source_timerange"]["duration"] = int(dur)
    seg["target_timerange"] = {"start": int(time_cursor), "duration": int(dur)}
    seg["extra_material_refs"] = _build_video_refs(svc, i)
    svc["tracks"][0]["segments"].append(seg)
    time_cursor += dur

# Audio segment
audio_seg = svc["tracks"][1]["segments"][0]
audio_seg["id"] = _uid()
audio_seg["material_id"] = svc["materials"]["audios"][0]["id"]
audio_seg["source_timerange"]["duration"] = total_dur
audio_seg["target_timerange"] = _mk_target_timerange(0, total_dur)
audio_seg["extra_material_refs"] = _build_audio_refs(svc, n_sentences)

# Text segments
tmpl_text_segs = len(svc["tracks"][2]["segments"])
stime_cursor = 0.0
gi = 0
for i, text in enumerate(sentences):
    dur = seg_durations_us[i]
    if dur <= 0: continue
    groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
    for group in groups:
        gdur = int((group["end"] - group["start"]) * 1_000_000)
        gstart = stime_cursor + group["start"] * 1_000_000
        if gi < tmpl_text_segs:
            seg = svc["tracks"][2]["segments"][gi]
            seg["id"] = _uid()
            seg["material_id"] = svc["materials"]["texts"][gi]["id"]
            seg["target_timerange"] = _mk_target_timerange(gstart, gdur)
        else:
            seg = copy.deepcopy(proto["text_seg"])
            seg["id"] = _uid()
            seg["material_id"] = svc["materials"]["texts"][gi]["id"]
            seg["target_timerange"] = _mk_target_timerange(gstart, gdur)
            svc["tracks"][2]["segments"].append(seg)
        gi += 1
    stime_cursor += dur

svc["duration"] = total_dur

# ======== Manual 方法 ========
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

manual = copy.deepcopy(template)
proto_vm = copy.deepcopy(manual["materials"]["videos"][0])
new_vids = []
for i in range(2):
    m = copy.deepcopy(proto_vm); m["id"] = uid(); m["material_id"] = m["id"]
    m["path"] = image_paths[i]; m["material_name"] = os.path.basename(image_paths[i])
    new_vids.append(m)
manual["materials"]["videos"] = new_vids
manual["tracks"][0]["segments"][0]["material_id"] = new_vids[0]["id"]
manual["tracks"][0]["segments"][1]["material_id"] = new_vids[1]["id"]

proto_tm = copy.deepcopy(manual["materials"]["texts"][0])
m = copy.deepcopy(proto_tm); m["id"] = uid()
m["content"] = json.dumps({"styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
    "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}}, "range": [0, len(sentences[0])],
    "size": 5.0, "bold": True, "italic": False, "underline": False, "strokes": []}],
    "text": sentences[0]}, ensure_ascii=False)
manual["materials"]["texts"] = [m]
manual["tracks"][2]["segments"][0]["material_id"] = m["id"]

proto_am = copy.deepcopy(manual["materials"]["audios"][0])
m = copy.deepcopy(proto_am); m["id"] = uid()
m["music_id"] = m["id"]; m["local_material_id"] = m["id"]
m["path"] = audio_path; m["name"] = os.path.basename(audio_path)
manual["materials"]["audios"] = [m]
manual["tracks"][1]["segments"][0]["material_id"] = m["id"]

id_map = {}
for cat in ["canvases", "speeds", "material_animations", "material_colors",
            "sound_channel_mappings", "loudnesses", "placeholder_infos", "vocal_separations"]:
    for item in manual["materials"].get(cat, []):
        old_id = item["id"]
        new_id = uid()
        id_map[old_id] = new_id
        item["id"] = new_id
for track in manual["tracks"]:
    for seg in track["segments"]:
        if "extra_material_refs" in seg:
            seg["extra_material_refs"] = [id_map.get(r, r) for r in seg["extra_material_refs"]]

total_vid_dur = manual["tracks"][0]["segments"][0]["target_timerange"]["duration"] + \
                manual["tracks"][0]["segments"][1]["target_timerange"]["start"] + \
                manual["tracks"][0]["segments"][1]["target_timerange"]["duration"]
for i in range(2, 26):
    vm = copy.deepcopy(proto_vmat); vm["id"] = uid(); vm["material_id"] = vm["id"]
    vm["path"] = image_paths[i]; vm["material_name"] = os.path.basename(image_paths[i])
    manual["materials"]["videos"].append(vm)
    c = copy.deepcopy(proto_canvas); c["id"] = uid(); manual["materials"]["canvases"].append(c)
    a = copy.deepcopy(proto_anim); a["id"] = uid(); manual["materials"]["material_animations"].append(a)
    co = copy.deepcopy(proto_color); co["id"] = uid(); manual["materials"]["material_colors"].append(co)
    lo = copy.deepcopy(proto_loud); lo["id"] = uid(); manual["materials"]["loudnesses"].append(lo)
    s = copy.deepcopy(proto_speed); s["id"] = uid(); manual["materials"]["speeds"].append(s)
    so = copy.deepcopy(proto_sound); so["id"] = uid(); manual["materials"]["sound_channel_mappings"].append(so)
    p = copy.deepcopy(proto_ph); p["id"] = uid(); manual["materials"]["placeholder_infos"].append(p)
    v = copy.deepcopy(proto_vocal); v["id"] = uid(); manual["materials"]["vocal_separations"].append(v)
    seg = copy.deepcopy(proto_vseg); seg["id"] = uid()
    seg["material_id"] = vm["id"]
    dur = seg_durations_us[i]
    seg["source_timerange"]["duration"] = int(dur)
    seg["target_timerange"] = {"start": int(total_vid_dur), "duration": int(dur)}
    seg["extra_material_refs"] = [
        manual["materials"]["speeds"][i]["id"],
        manual["materials"]["placeholder_infos"][i]["id"],
        manual["materials"]["canvases"][i]["id"],
        manual["materials"]["material_animations"][i]["id"],
        manual["materials"]["sound_channel_mappings"][i]["id"],
        manual["materials"]["material_colors"][i]["id"],
        manual["materials"]["loudnesses"][i]["id"],
        manual["materials"]["vocal_separations"][i]["id"],
    ]
    manual["tracks"][0]["segments"].append(seg)
    total_vid_dur += dur

text_cursor = manual["tracks"][2]["segments"][0]["target_timerange"]["duration"]
for i in range(1, 26):
    dur = seg_durations_us[i]
    groups = split_into_word_groups(sentences[i], duration_sec=dur / 1_000_000)
    for group in groups:
        tm = copy.deepcopy(proto_tmat); tm["id"] = uid()
        tm["content"] = json.dumps({"styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
            "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}}, "range": [0, len(group["text"])],
            "size": 5.0, "bold": True, "italic": False, "underline": False, "strokes": []}],
            "text": group["text"]}, ensure_ascii=False)
        tm["font_path"] = FONT_PATH
        manual["materials"]["texts"].append(tm)
        gdur = int((group["end"] - group["start"]) * 1_000_000)
        gstart = text_cursor + int(group["start"] * 1_000_000)
        seg = copy.deepcopy(proto_tseg); seg["id"] = uid()
        seg["material_id"] = tm["id"]
        seg["target_timerange"] = {"start": gstart, "duration": gdur}
        manual["tracks"][2]["segments"].append(seg)
    text_cursor += dur

manual["tracks"][1]["segments"][0]["extra_material_refs"] = [
    manual["materials"]["speeds"][26]["id"],
    manual["materials"]["placeholder_infos"][26]["id"],
    manual["materials"]["sound_channel_mappings"][26]["id"],
    manual["materials"]["vocal_separations"][26]["id"],
]
manual["duration"] = int(sum(seg_durations_us))

# ======== COMPARISON ========
print("="*70)
print("STRUCTURAL COMPARISON: Service vs Manual (26 segments)")
print("="*70)

print(f"\nService: {len(svc['tracks'][0]['segments'])}v, {len(svc['tracks'][2]['segments'])}t")
print(f"Manual:  {len(manual['tracks'][0]['segments'])}v, {len(manual['tracks'][2]['segments'])}t")

# 1. Material counts
print("\n--- Material counts ---")
diffs = []
for cat in ["videos", "audios", "texts", "canvases", "speeds",
            "material_animations", "material_colors", "sound_channel_mappings",
            "loudnesses", "placeholder_infos", "vocal_separations"]:
    sc = len(svc["materials"].get(cat, []))
    mc = len(manual["materials"].get(cat, []))
    flag = " [DIFF!]" if sc != mc else ""
    print(f"  {cat}: service={sc}, manual={mc}{flag}")
    if sc != mc:
        diffs.append(f"Count mismatch: {cat}")

# 2. Target timerange comparison
print("\n--- Video target_timerange ---")
for i in range(min(5, len(svc["tracks"][0]["segments"]))):
    st = svc["tracks"][0]["segments"][i]["target_timerange"]
    mt = manual["tracks"][0]["segments"][i]["target_timerange"]
    s_has = "start" in st
    m_has = "start" in mt
    if st != mt:
        print(f"  seg[{i}]: SVC={st} MAN={mt} [DIFF!]")
        diffs.append(f"Video seg[{i}] target_timerange differs")
    elif s_has != m_has:
        print(f"  seg[{i}]: start presence differs! SVC={s_has} MAN={m_has} [DIFF!]")
        diffs.append(f"Video seg[{i}] start field presence differs")
    else:
        print(f"  seg[{i}]: OK (start={'present' if s_has else 'absent'})")

# 3. Video refs order
def cat_of_ref(draft, ref_id):
    for cat in ["speeds", "placeholder_infos", "canvases", "material_animations",
                "sound_channel_mappings", "material_colors", "loudnesses", "vocal_separations"]:
        for item in draft["materials"].get(cat, []):
            if item["id"] == ref_id:
                return cat
    return "UNKNOWN"

print("\n--- Video seg[2] ref categories ---")
svc_r = svc["tracks"][0]["segments"][2]["extra_material_refs"]
man_r = manual["tracks"][0]["segments"][2]["extra_material_refs"]
svc_cats = [cat_of_ref(svc, r) for r in svc_r]
man_cats = [cat_of_ref(manual, r) for r in man_r]
print(f"  Service: {svc_cats}")
print(f"  Manual:  {man_cats}")
if svc_cats != man_cats:
    print("  [DIFF!] Ref category order differs!")
    diffs.append("Video ref category order differs")

# 4. Audio refs
print("\n--- Audio segment refs ---")
svc_arefs = svc["tracks"][1]["segments"][0]["extra_material_refs"]
man_arefs = manual["tracks"][1]["segments"][0]["extra_material_refs"]
svc_acats = [cat_of_ref(svc, r) for r in svc_arefs]
man_acats = [cat_of_ref(manual, r) for r in man_arefs]
print(f"  Service: {svc_acats}")
print(f"  Manual:  {man_acats}")

# 5. Check which INDICES audio refs point to
print("\n--- Audio refs -> array indices ---")
n_vid = len(manual["tracks"][0]["segments"])
for ci, cat in enumerate(["speeds", "placeholder_infos", "sound_channel_mappings", "vocal_separations"]):
    for idx, item in enumerate(svc["materials"][cat]):
        if item["id"] == svc_arefs[ci]:
            svc_idx = idx
            break
    for idx, item in enumerate(manual["materials"][cat]):
        if item["id"] == man_arefs[ci]:
            man_idx = idx
            break
    flag = " [DIFF!]" if svc_idx != man_idx else ""
    print(f"  {cat}: service[{svc_idx}] vs manual[{man_idx}]{flag}")
    if svc_idx != man_idx:
        diffs.append(f"Audio ref index differs for {cat}")

# 6. Check if the template's original aux entries are still in the right positions
print("\n--- Template aux positions (speeds array structure) ---")
# In service: speeds = [remapped_v0, remapped_v1, remapped_a0, v2, v3, ..., v25]
# In manual: speeds = [remapped_v0', remapped_v1', remapped_a0', v2, v3, ..., v25]
# Audio refs in service point to speeds[N_video] = speeds[26]
# Audio refs in manual point to speeds[26]
# BUT: manual has 27 entries (indices 0-26), service also has 27 entries

svc_spd_count = len(svc["materials"]["speeds"])
man_spd_count = len(manual["materials"]["speeds"])
print(f"  Speeds count: service={svc_spd_count}, manual={man_spd_count}")

# Check if audio refs in service point to the right entry
# The template had speeds[0]=v0, speeds[1]=v1, speeds[2]=a0
# After remap + 24 appends: [v0', v1', a0', v2, ..., v25] = 27 entries
# Audio should reference the entry that WAS a0 (now a0')
# But service uses _build_audio_refs(svc, 26) which uses index 26 (last entry = v25)
# While the actual audio aux entry is at index 2

# Let's verify this theory:
svc_audio_speed_id = svc_arefs[0]
svc_audio_speed_idx = None
for idx, item in enumerate(svc["materials"]["speeds"]):
    if item["id"] == svc_audio_speed_id:
        svc_audio_speed_idx = idx
        break
print(f"  Service audio speed ref -> speeds[{svc_audio_speed_idx}]")

man_audio_speed_id = man_arefs[0]
man_audio_speed_idx = None
for idx, item in enumerate(manual["materials"]["speeds"]):
    if item["id"] == man_audio_speed_id:
        man_audio_speed_idx = idx
        break
print(f"  Manual audio speed ref -> speeds[{man_audio_speed_idx}]")

# KEY: In the template, the audio aux materials were at specific positions
# Let's check what the original template audio speed ID was
# Template speeds: [v0, v1, a0]
# After svc remap: same positions, new IDs
# After svc append 24: [v0', v1', a0', v2, v3, ..., v25]
# svc audio refs point to index 26 (LAST entry)
#
# AFTER manual: speeds = [v0', v1', a0', v2, v3, ..., v25]
# manual audio refs ALSO point to index 26
#
# BUT: maybe they point to different positions?
print(f"\n  Service audio speed ref id: {svc_audio_speed_id}")
print(f"  Manual audio speed ref id:  {man_audio_speed_id}")

# 7. AUDIO MATERIAL fields check
print("\n--- Audio material fields ---")
svc_audio = svc["materials"]["audios"][0]
man_audio = manual["materials"]["audios"][0]
for k in sorted(set(list(svc_audio.keys()) + list(man_audio.keys()))):
    if k == "id" or k == "music_id" or k == "local_material_id":
        continue
    sv = svc_audio.get(k, "<MISSING>")
    mv = man_audio.get(k, "<MISSING>")
    if sv != mv:
        print(f"  {k}: SVC={sv!r:.80} MAN={mv!r:.80} [DIFF!]")
        diffs.append(f"Audio material.{k} differs")

if "material_id" in svc_audio:
    print("  [CRITICAL] Service audio HAS material_id field!")
    diffs.append("Audio has material_id in service")
if "material_id" in man_audio:
    print("  [CRITICAL] Manual audio HAS material_id field!")

# 8. Check if video[1] material_id matches video_seg[1].material_id
print("\n--- Video material_id consistency ---")
for i in range(min(5, len(svc["tracks"][0]["segments"]))):
    seg_mid = svc["tracks"][0]["segments"][i]["material_id"]
    mat_mid = svc["materials"]["videos"][i].get("material_id")
    ok = seg_mid == mat_mid
    if not ok:
        print(f"  seg[{i}].material_id={seg_mid[:16]}... != video[{i}].material_id={mat_mid[:16]}... [DIFF!]")
        diffs.append(f"Video material_id mismatch at index {i}")

# 9. Check text material_ids
print("\n--- Text material_id check ---")
svc_tm0 = svc["materials"]["texts"][0]
man_tm0 = manual["materials"]["texts"][0]
if "material_id" in svc_tm0:
    print(f"  Service text[0] HAS material_id={svc_tm0['material_id'][:20]}... [DIFF!]")
    diffs.append("Text has material_id in service")
else:
    print("  Service text[0]: no material_id (correct)")

# ======== SUMMARY ========
print("\n" + "="*70)
if diffs:
    print(f"FOUND {len(diffs)} DIFFERENCES:")
    for d in diffs:
        print(f"  - {d}")
else:
    print("No structural differences found!")

# Even if no diffs found, check the file-writing step
print("\n--- Post-generation check ---")
print(f"Service draft_content.json size (estimated): ~{len(json.dumps(svc, ensure_ascii=False))} bytes")
print(f"Manual draft_content.json size (estimated): ~{len(json.dumps(manual, ensure_ascii=False))} bytes")
