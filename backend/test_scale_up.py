"""
S20 增量扩展测试: 5→10→15→20→26 段, 逐步验证剪映 v11 上限
使用 S20 完全相同的模式 (手动增量追加), 不做抽象
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
    """S20 同款 quick_build: 最小文件集 + 加密"""
    dir_path = make_dir(name)
    dc_path = os.path.join(dir_path, "draft_content.json")
    with open(dc_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    # 只复制核心文件 + Timelines (与 S20 完全一致)
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

# ======== 加载数据 ========
from services.llm_service import split_into_short_sentences
from services.video_service import get_audio_duration, split_into_word_groups

images_dir = os.path.join(TASK_DIR, "images")
img_files = sorted([f for f in os.listdir(images_dir) if f.endswith(".png") and f.startswith("seg_")])
img_map = {}
for f in img_files:
    seg_idx = int(f.replace("seg_", "").replace(".png", ""))
    img_map[seg_idx] = os.path.join(images_dir, f).replace("\\", "/")

segments_dir = os.path.join(TASK_DIR, "segments")
seg_files = sorted([f for f in os.listdir(segments_dir) if f.endswith(".mp3") and f.startswith("seg_")])
tts_durs = [get_audio_duration(os.path.join(segments_dir, sf)) for sf in seg_files]
seg_durations = [d * 1_000_000 for d in tts_durs]

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
sentences = split_into_short_sentences(full_text, max_chars=80, min_chars=30)

print(f"Total sentences: {len(sentences)}")
print(f"Total segments: {len(seg_files)}")
print(f"Total images: {len(img_files)}")

# Cap at what we actually have
N_MAX = min(len(sentences), len(seg_files), len(img_files))
print(f"Usable: {N_MAX}")

# ======== 加载模板 + 准备原型 ========
tmpl_enc = os.path.join(TEMPLATE_DIR, "draft_content.json")
tmpl_dec = os.path.join(TEMPLATE_DIR, "draft_content.scale.json")
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

# ======== 构建 baseline (d_base: 2v + 1t + 1a, aux remapped) ========
def build_base(sentence_subset, image_subset, dur_subset):
    """构建 S18-style baseline, 与 S20 的 d_base 完全一致"""
    d = copy.deepcopy(template)

    # Replace videos (2 items)
    proto_vm = copy.deepcopy(d["materials"]["videos"][0])
    new_vids = []
    for i in range(2):
        m = copy.deepcopy(proto_vm); m["id"] = uid(); m["material_id"] = m["id"]
        m["path"] = image_subset[i]; m["material_name"] = os.path.basename(image_subset[i])
        new_vids.append(m)
    d["materials"]["videos"] = new_vids
    d["tracks"][0]["segments"][0]["material_id"] = new_vids[0]["id"]
    d["tracks"][0]["segments"][1]["material_id"] = new_vids[1]["id"]

    # Replace text (1 item)
    proto_tm = copy.deepcopy(d["materials"]["texts"][0])
    m = copy.deepcopy(proto_tm); m["id"] = uid()
    m["content"] = json.dumps({"styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
        "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}}, "range": [0, len(sentence_subset[0])],
        "size": 5.0, "bold": True, "italic": False, "underline": False, "strokes": []}],
        "text": sentence_subset[0]}, ensure_ascii=False)
    d["materials"]["texts"] = [m]
    d["tracks"][2]["segments"][0]["material_id"] = m["id"]

    # Replace audio (1 item)
    proto_am = copy.deepcopy(d["materials"]["audios"][0])
    m = copy.deepcopy(proto_am); m["id"] = uid()
    m["music_id"] = m["id"]; m["local_material_id"] = m["id"]
    m["path"] = audio_path; m["name"] = os.path.basename(audio_path)
    d["materials"]["audios"] = [m]
    d["tracks"][1]["segments"][0]["material_id"] = m["id"]

    # Remap aux IDs (id_map approach)
    id_map = {}
    for cat in ["canvases", "speeds", "material_animations", "material_colors",
                "sound_channel_mappings", "loudnesses", "placeholder_infos", "vocal_separations"]:
        for item in d["materials"].get(cat, []):
            old_id = item["id"]
            new_id = uid()
            id_map[old_id] = new_id
            item["id"] = new_id
    for track in d["tracks"]:
        for seg in track["segments"]:
            if "extra_material_refs" in seg:
                seg["extra_material_refs"] = [id_map.get(r, r) for r in seg["extra_material_refs"]]

    return d

# ======== 从 d_base 扩展到 N 段 ========
def expand_to_n(d_base, N, sentences_subset, image_subset, dur_subset):
    """S20 同款扩展: 从 2v+1t 扩展到 N v + M t"""
    d = copy.deepcopy(d_base)

    n_vid = 2  # current video count in d_base

    # Get template first video seg duration for cursor start
    total_vid_dur = d["tracks"][0]["segments"][0]["target_timerange"]["duration"] + \
                    d["tracks"][0]["segments"][1]["target_timerange"]["start"] + \
                    d["tracks"][0]["segments"][1]["target_timerange"]["duration"]

    # Add video segments (2 -> N)
    for i in range(2, N):
        # New video material
        vm = copy.deepcopy(proto_vmat); vm["id"] = uid(); vm["material_id"] = vm["id"]
        vm["path"] = image_subset[i]; vm["material_name"] = os.path.basename(image_subset[i])
        d["materials"]["videos"].append(vm)

        # New auxiliary materials for this video
        c = copy.deepcopy(proto_canvas); c["id"] = uid(); d["materials"]["canvases"].append(c)
        a = copy.deepcopy(proto_anim); a["id"] = uid(); d["materials"]["material_animations"].append(a)
        co = copy.deepcopy(proto_color); co["id"] = uid(); d["materials"]["material_colors"].append(co)
        lo = copy.deepcopy(proto_loud); lo["id"] = uid(); d["materials"]["loudnesses"].append(lo)
        s = copy.deepcopy(proto_speed); s["id"] = uid(); d["materials"]["speeds"].append(s)
        so = copy.deepcopy(proto_sound); so["id"] = uid(); d["materials"]["sound_channel_mappings"].append(so)
        p = copy.deepcopy(proto_ph); p["id"] = uid(); d["materials"]["placeholder_infos"].append(p)
        v = copy.deepcopy(proto_vocal); v["id"] = uid(); d["materials"]["vocal_separations"].append(v)

        # New video segment
        seg = copy.deepcopy(proto_vseg); seg["id"] = uid()
        seg["material_id"] = vm["id"]
        dur = dur_subset[i]
        seg["source_timerange"]["duration"] = int(dur)
        seg["target_timerange"] = {"start": int(total_vid_dur), "duration": int(dur)}
        seg["extra_material_refs"] = [
            d["materials"]["speeds"][i]["id"],
            d["materials"]["placeholder_infos"][i]["id"],
            d["materials"]["canvases"][i]["id"],
            d["materials"]["material_animations"][i]["id"],
            d["materials"]["sound_channel_mappings"][i]["id"],
            d["materials"]["material_colors"][i]["id"],
            d["materials"]["loudnesses"][i]["id"],
            d["materials"]["vocal_separations"][i]["id"],
        ]
        d["tracks"][0]["segments"].append(seg)
        total_vid_dur += dur

    n_vid = N

    # Add text segments (1 -> N)
    # First, fix the existing text segment's target_timerange
    text_cursor = d["tracks"][2]["segments"][0]["target_timerange"]["duration"]
    for i in range(1, N):
        dur = dur_subset[i]
        groups = split_into_word_groups(sentences_subset[i], duration_sec=dur / 1_000_000)
        for group in groups:
            tm = copy.deepcopy(proto_tmat); tm["id"] = uid()
            tm["content"] = json.dumps({"styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
                "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}}, "range": [0, len(group["text"])],
                "size": 5.0, "bold": True, "italic": False, "underline": False, "strokes": []}],
                "text": group["text"]}, ensure_ascii=False)
            tm["font_path"] = FONT_PATH
            d["materials"]["texts"].append(tm)

            gdur = int((group["end"] - group["start"]) * 1_000_000)
            gstart = text_cursor + int(group["start"] * 1_000_000)
            seg = copy.deepcopy(proto_tseg); seg["id"] = uid()
            seg["material_id"] = tm["id"]
            seg["target_timerange"] = {"start": gstart, "duration": gdur}
            d["tracks"][2]["segments"].append(seg)
        text_cursor += dur

    # Fix audio segment refs (index = n_vid)
    d["tracks"][1]["segments"][0]["extra_material_refs"] = [
        d["materials"]["speeds"][n_vid]["id"],
        d["materials"]["placeholder_infos"][n_vid]["id"],
        d["materials"]["sound_channel_mappings"][n_vid]["id"],
        d["materials"]["vocal_separations"][n_vid]["id"],
    ]

    # Fix total duration
    total_dur = int(sum(dur_subset[:N]))
    d["duration"] = total_dur

    return d, len(d["tracks"][2]["segments"])

# ======== 为每个 checkpoint 生成草稿 ========
CHECKPOINTS = [5, 10, 15, 20, 26]
CHECKPOINTS = [c for c in CHECKPOINTS if c <= N_MAX]

for cp in CHECKPOINTS:
    print(f"\n{'='*60}")
    print(f"Building checkpoint N={cp}...")

    s_sub = sentences[:cp]
    i_sub = [img_map.get(i, img_map.get(0, "")) for i in range(cp)]
    d_sub = seg_durations[:cp]

    # Build base (2v + 1t + 1a)
    base = build_base(s_sub, i_sub, d_sub)

    # Expand to N
    draft, n_text = expand_to_n(base, cp, s_sub, i_sub, d_sub)

    n_vid_final = len(draft["tracks"][0]["segments"])
    n_aud_final = len(draft["tracks"][1]["segments"])

    # Quick stats
    n_speeds = len(draft["materials"]["speeds"])
    n_canvases = len(draft["materials"]["canvases"])
    n_anims = len(draft["materials"]["material_animations"])

    print(f"  Videos: {n_vid_final}, Texts: {n_text}, Audios: {n_aud_final}")
    print(f"  Aux: speeds={n_speeds}, canvases={n_canvases}, anims={n_anims}")
    print(f"  Duration: {draft['duration']/1_000_000:.1f}s")

    # Verify refs
    for vi in range(n_vid_final):
        refs = draft["tracks"][0]["segments"][vi]["extra_material_refs"]
        assert len(refs) == 8, f"Video {vi}: expected 8 refs, got {len(refs)}"
    aud_refs = draft["tracks"][1]["segments"][0]["extra_material_refs"]
    assert len(aud_refs) == 4, f"Audio: expected 4 refs, got {len(aud_refs)}"

    # Verify audio refs point to valid aux indices
    # speeds index = n_vid_final should exist
    assert n_vid_final < n_speeds, f"Audio speed ref {n_vid_final} >= speeds count {n_speeds}"

    # Build draft
    name = f"Scale_N{cp:02d}"
    draft_id = f"ScaleN{cp:02d}-{int(time.time())}"
    quick_build(name, draft_id, draft)
    print(f"  [OK] Draft '{name}' built successfully")

print(f"\n{'='*60}")
print(f"All {len(CHECKPOINTS)} checkpoints built: {', '.join(f'N{c}' for c in CHECKPOINTS)}")
print("Kill 剪映, reopen, and test each Scale_N* draft.")
