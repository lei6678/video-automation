"""
对比 service 生成的 Task6 和 Scale_N26 的 JSON 结构差异
两者都从同一模板出发, 用同样的 26-segment 数据
"""
import json, os, uuid, subprocess, shutil, time, copy, sys

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

# ======== 准备相同的 26-segment 数据 ========
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

print(f"Data: {len(sentences)} sentences, {len(image_paths)} images, {len(seg_durations_us)} durations")

# ======== 方法A: 用 service 生成 ========
print("\n=== Method A: Service ===")
from services.jianying_v11_service import export_jianying_draft_v11

svc_dir = export_jianying_draft_v11(
    sentences=sentences,
    image_paths=image_paths,
    audio_path=audio_path,
    seg_durations_us=seg_durations_us,
    draft_name="Diff_Service",
)

# Decrypt service output
svc_dc = os.path.join(svc_dir, "draft_content.json")
svc_dec = os.path.join(svc_dir, "draft_content.dec.json")
decrypt(svc_dc, svc_dec)
with open(svc_dec, "r", encoding="utf-8") as f:
    svc = json.load(f)

print(f"Service: {len(svc['tracks'][0]['segments'])}v, {len(svc['tracks'][2]['segments'])}t, {len(svc['tracks'][1]['segments'])}a")
print(f"  videos: {len(svc['materials']['videos'])}")
print(f"  texts: {len(svc['materials']['texts'])}")
print(f"  audios: {len(svc['materials']['audios'])}")
print(f"  speeds: {len(svc['materials']['speeds'])}")
print(f"  canvases: {len(svc['materials']['canvases'])}")

# ======== 方法B: 用 S20 手动模式 ========
print("\n=== Method B: Manual (S20 pattern) ===")
# Load template
tmpl_enc = os.path.join(TEMPLATE_DIR, "draft_content.json")
tmpl_dec = os.path.join(TEMPLATE_DIR, "draft_content.diff.json")
decrypt(tmpl_enc, tmpl_dec)
with open(tmpl_dec, "r", encoding="utf-8") as f:
    template = json.load(f)

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

# Build base
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

# Remap aux IDs
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

# Expand to 26
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

# Text segments
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

# Audio refs
manual["tracks"][1]["segments"][0]["extra_material_refs"] = [
    manual["materials"]["speeds"][26]["id"],
    manual["materials"]["placeholder_infos"][26]["id"],
    manual["materials"]["sound_channel_mappings"][26]["id"],
    manual["materials"]["vocal_separations"][26]["id"],
]
manual["duration"] = int(sum(seg_durations_us))

print(f"Manual: {len(manual['tracks'][0]['segments'])}v, {len(manual['tracks'][2]['segments'])}t, {len(manual['tracks'][1]['segments'])}a")
print(f"  videos: {len(manual['materials']['videos'])}")
print(f"  texts: {len(manual['materials']['texts'])}")
print(f"  audios: {len(manual['materials']['audios'])}")
print(f"  speeds: {len(manual['materials']['speeds'])}")
print(f"  canvases: {len(manual['materials']['canvases'])}")

# ======== 逐项比较 ========
print("\n" + "="*70)
print("STRUCTURAL DIFF")
print("="*70)

# 1. 顶层字段
top_keys_svc = set(svc.keys())
top_keys_manual = set(manual.keys())
only_svc = top_keys_svc - top_keys_manual
only_manual = top_keys_manual - top_keys_svc
if only_svc:
    print(f"\n[DIFF] Top-level keys only in service: {only_svc}")
if only_manual:
    print(f"[DIFF] Top-level keys only in manual: {only_manual}")

# 2. Materials counts
for cat in ["videos", "audios", "texts", "canvases", "speeds",
            "material_animations", "material_colors", "sound_channel_mappings",
            "loudnesses", "placeholder_infos", "vocal_separations"]:
    svc_count = len(svc["materials"].get(cat, []))
    man_count = len(manual["materials"].get(cat, []))
    if svc_count != man_count:
        print(f"[DIFF] materials.{cat}: service={svc_count}, manual={man_count}")

# 3. Track counts
for ti in range(len(svc["tracks"])):
    svc_segs = len(svc["tracks"][ti]["segments"])
    man_segs = len(manual["tracks"][ti]["segments"])
    if svc_segs != man_segs:
        print(f"[DIFF] tracks[{ti}] segments: service={svc_segs}, manual={man_segs}")

# 4. Video materials: check material_id field
print("\n--- Video material fields ---")
svc_v0 = svc["materials"]["videos"][0]
man_v0 = manual["materials"]["videos"][0]
for k in set(list(svc_v0.keys()) + list(man_v0.keys())):
    in_svc = k in svc_v0
    in_man = k in man_v0
    if in_svc != in_man:
        print(f"[DIFF] video[0].{k}: in service={in_svc}, in manual={in_man}")

# 5. Audio materials: check material_id field (should be absent!)
print("\n--- Audio material fields ---")
svc_a0 = svc["materials"]["audios"][0]
man_a0 = manual["materials"]["audios"][0]
for k in set(list(svc_a0.keys()) + list(man_a0.keys())):
    in_svc = k in svc_a0
    in_man = k in man_a0
    if in_svc != in_man:
        print(f"[DIFF] audio[0].{k}: in service={in_svc}, in manual={in_man}")
if "material_id" in svc_a0:
    print(f"[DIFF] Audio HAS material_id in service (BAD!): {svc_a0['material_id']}")
if "material_id" in man_a0:
    print(f"[DIFF] Audio HAS material_id in manual (BAD!): {man_a0['material_id']}")

# 6. Check first video segment's target_timerange
print("\n--- Video seg[0] target_timerange ---")
svc_vseg0 = svc["tracks"][0]["segments"][0]["target_timerange"]
man_vseg0 = manual["tracks"][0]["segments"][0]["target_timerange"]
print(f"Service: {svc_vseg0}")
print(f"Manual:  {man_vseg0}")
if svc_vseg0 != man_vseg0:
    print("[DIFF] Video seg[0] target_timerange differs!")

# 7. Check subsequent segments have "start"
print("\n--- Video seg target_timerange 'start' presence ---")
for i in range(min(5, len(svc["tracks"][0]["segments"]))):
    svc_tr = svc["tracks"][0]["segments"][i]["target_timerange"]
    man_tr = manual["tracks"][0]["segments"][i]["target_timerange"]
    svc_has_start = "start" in svc_tr
    man_has_start = "start" in man_tr
    if svc_has_start != man_has_start:
        print(f"[DIFF] Video seg[{i}]: service has_start={svc_has_start}, manual has_start={man_has_start}")
    elif not svc_has_start:
        print(f"  Video seg[{i}]: both omit start (correct for first)")

# 8. Check extra_material_refs order
print("\n--- Video seg[1] extra_material_refs categories ---")
# 通过检查 refs 指向的 ID 来确定类别
def cat_of_ref(draft, ref_id):
    for cat in ["speeds", "placeholder_infos", "canvases", "material_animations",
                "sound_channel_mappings", "material_colors", "loudnesses", "vocal_separations"]:
        for item in draft["materials"].get(cat, []):
            if item["id"] == ref_id:
                return cat
    return "UNKNOWN"

svc_refs = svc["tracks"][0]["segments"][1]["extra_material_refs"]
man_refs = manual["tracks"][0]["segments"][1]["extra_material_refs"]
svc_cats = [cat_of_ref(svc, r) for r in svc_refs]
man_cats = [cat_of_ref(manual, r) for r in man_refs]
print(f"Service: {svc_cats}")
print(f"Manual:  {man_cats}")
if svc_cats != man_cats:
    print("[DIFF] Ref order differs!")

# 9. Check audio segment refs
print("\n--- Audio seg extra_material_refs categories ---")
svc_arefs = svc["tracks"][1]["segments"][0]["extra_material_refs"]
man_arefs = manual["tracks"][1]["segments"][0]["extra_material_refs"]
svc_acats = [cat_of_ref(svc, r) for r in svc_arefs]
man_acats = [cat_of_ref(manual, r) for r in man_arefs]
print(f"Service: {svc_acats}")
print(f"Manual:  {man_acats}")
if svc_acats != man_acats:
    print("[DIFF] Audio ref order differs!")

# 10. Check audio refs point to correct indices (should be at video_count)
print("\n--- Audio refs index check ---")
n_vid_svc = len(svc["tracks"][0]["segments"])
n_vid_man = len(manual["tracks"][0]["segments"])
for ci, cat in enumerate(["speeds", "placeholder_infos", "sound_channel_mappings", "vocal_separations"]):
    svc_aref = svc_arefs[ci]
    man_aref = man_arefs[ci]
    # Find index of this ref in the material array
    svc_idx = None
    man_idx = None
    for idx, item in enumerate(svc["materials"][cat]):
        if item["id"] == svc_aref:
            svc_idx = idx
            break
    for idx, item in enumerate(manual["materials"][cat]):
        if item["id"] == man_aref:
            man_idx = idx
            break
    print(f"  {cat}: service idx={svc_idx}, manual idx={man_idx}")

# 11. Key: check target_timerange for text segments
print("\n--- Text seg target_timerange check ---")
svc_t0 = svc["tracks"][2]["segments"][0]["target_timerange"]
man_t0 = manual["tracks"][2]["segments"][0]["target_timerange"]
print(f"Text seg[0]: service={svc_t0}, manual={man_t0}")

# 12. Full top-level keys comparison
print("\n--- Top-level structure ---")
for k in sorted(top_keys_svc | top_keys_manual):
    svc_val = svc.get(k)
    man_val = manual.get(k)
    if k in ["tracks", "materials"]:
        continue
    if svc_val != man_val:
        print(f"[DIFF] {k}: service={svc_val}, manual={man_val}")

# 13. Check if any extra fields
print("\n--- Video material extra fields check ---")
for vi in range(min(3, len(svc["materials"]["videos"]))):
    svc_keys = set(svc["materials"]["videos"][vi].keys())
    man_keys = set(manual["materials"]["videos"][vi].keys())
    extra_in_svc = svc_keys - man_keys
    extra_in_man = man_keys - svc_keys
    if extra_in_svc or extra_in_man:
        print(f"  video[{vi}]: svc_extra={extra_in_svc}, man_extra={extra_in_man}")

# 14. Check text materials
print("\n--- Text material comparison ---")
svc_tm0 = svc["materials"]["texts"][0]
man_tm0 = manual["materials"]["texts"][0]
svc_tkeys = set(svc_tm0.keys())
man_tkeys = set(man_tm0.keys())
if svc_tkeys != man_tkeys:
    print(f"[DIFF] Text material keys: svc_only={svc_tkeys-man_tkeys}, man_only={man_tkeys-svc_tkeys}")

# 15. Check if service has "material_id" on text
if "material_id" in svc_tm0:
    print(f"[DIFF] Service text HAS material_id={svc_tm0['material_id']} (BAD!)")

# ======== Summary ========
print("\n" + "="*70)
print("KEY DIFFERENCES FOUND:")
print("(Review above output for [DIFF] markers)")
