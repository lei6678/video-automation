"""Deep dive: compare template text material vs our generated one"""
import json, os, subprocess

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR

def decrypt(enc_path, out_path):
    subprocess.run(["jy-draftc", "-d", enc_path, out_path], env=env, capture_output=True, text=True)

# Decrypt template
tmpl_enc = r"E:/360Downloads/JianyingPro Drafts/TestReEncrypt/draft_content.json"
tmpl_dec = tmpl_enc.replace(".json", ".deep.json")
decrypt(tmpl_enc, tmpl_dec)
with open(tmpl_dec, "r", encoding="utf-8") as f:
    template = json.load(f)

# Decrypt TestQ (our latest attempt)
testq_enc = r"E:/360Downloads/JianyingPro Drafts/TestQ_FixAudio/draft_content.json"
testq_dec = testq_enc.replace(".json", ".deep.json")
decrypt(testq_enc, testq_dec)
with open(testq_dec, "r", encoding="utf-8") as f:
    testq = json.load(f)

# Compare template text material FULLY
print("=" * 60)
print("TEMPLATE TEXT MATERIAL (full)")
print("=" * 60)
tm = template["materials"]["texts"][0]
for k, v in tm.items():
    val_str = str(v)
    if len(val_str) > 500:
        val_str = val_str[:500] + f"... [{len(val_str)} total]"
    print(f"  {k}: {val_str}")

print("\n" + "=" * 60)
print("OUR TEXT MATERIAL (first, from TestQ)")
print("=" * 60)
gm = testq["materials"]["texts"][0]
for k, v in gm.items():
    val_str = str(v)
    if len(val_str) > 500:
        val_str = val_str[:500] + f"... [{len(val_str)} total]"
    print(f"  {k}: {val_str}")

# Compare KEYS
print("\n" + "=" * 60)
print("TEXT MATERIAL KEYS DIFF")
print("=" * 60)
t_keys = set(tm.keys())
g_keys = set(gm.keys())
print(f"  Template keys: {sorted(t_keys)}")
print(f"  Our keys: {sorted(g_keys)}")
print(f"  Missing: {t_keys - g_keys}")
print(f"  Extra: {g_keys - t_keys}")

# Parse and compare content JSON
print("\n" + "=" * 60)
print("CONTENT JSON COMPARISON")
print("=" * 60)
t_content = json.loads(tm["content"])
g_content = json.loads(gm["content"])
print(f"  Template text: {t_content.get('text', 'N/A')[:100]}")
print(f"  Our text: {g_content.get('text', 'N/A')[:100]}")
print(f"  Template styles count: {len(t_content.get('styles', []))}")
print(f"  Our styles count: {len(g_content.get('styles', []))}")

# Compare first style
if t_content.get("styles") and g_content.get("styles"):
    ts = t_content["styles"][0]
    gs = g_content["styles"][0]
    print(f"\n  Template style keys: {sorted(ts.keys())}")
    print(f"  Our style keys: {sorted(gs.keys())}")
    for k in sorted(set(list(ts.keys()) + list(gs.keys()))):
        tv = ts.get(k, "<MISSING>")
        gv = gs.get(k, "<MISSING>")
        if tv != gv:
            print(f"    {k}: T={tv} vs G={gv}")

# Check words/current_words fields
print("\n" + "=" * 60)
print("WORDS / CURRENT_WORDS")
print("=" * 60)
print(f"  Template words: {json.dumps(tm.get('words', 'N/A'), ensure_ascii=False)[:200]}")
print(f"  Our words: {json.dumps(gm.get('words', 'N/A'), ensure_ascii=False)[:200]}")
print(f"  Template current_words: {json.dumps(tm.get('current_words', 'N/A'), ensure_ascii=False)[:200]}")
print(f"  Our current_words: {json.dumps(gm.get('current_words', 'N/A'), ensure_ascii=False)[:200]}")

# Check combo_info
print(f"\n  Template combo_info: {json.dumps(tm.get('combo_info', 'N/A'), ensure_ascii=False)[:200]}")
print(f"  Our combo_info: {json.dumps(gm.get('combo_info', 'N/A'), ensure_ascii=False)[:200]}")

# Check caption_template_info
print(f"\n  Template caption_template_info: {json.dumps(tm.get('caption_template_info', 'N/A'), ensure_ascii=False)[:200]}")
print(f"  Our caption_template_info: {json.dumps(gm.get('caption_template_info', 'N/A'), ensure_ascii=False)[:200]}")

# Check lyrics_template
print(f"\n  Template lyrics_template: {json.dumps(tm.get('lyrics_template', 'N/A'), ensure_ascii=False)[:200]}")
print(f"  Our lyrics_template: {json.dumps(gm.get('lyrics_template', 'N/A'), ensure_ascii=False)[:200]}")

# Now compare video segment target_timerange structure  
print("\n" + "=" * 60)
print("VIDEO SEGMENT target_timerange")
print("=" * 60)
tv_seg = template["tracks"][0]["segments"][0]
gv_seg = testq["tracks"][0]["segments"][0]
print(f"  Template: {tv_seg['target_timerange']}")
print(f"  Ours: {gv_seg['target_timerange']}")

# Check if first segment start=0 should be OMITTED
print("\n  Template has 'start' in first video seg: {'start' in tv_seg['target_timerange']}")
print(f"  Template keys: {sorted(tv_seg['target_timerange'].keys())}")

# Check if start:0 should be OMITTED (not just different)
print("\n" + "=" * 60)
print("target_timerange 'start' FIELD ANALYSIS")
print("=" * 60)
for i, seg in enumerate(template["tracks"][0]["segments"]):
    tr = seg["target_timerange"]
    has_start = "start" in tr
    start_val = tr.get("start", "N/A")
    print(f"  Template video seg[{i}]: has_start={has_start}, start={start_val}, duration={tr['duration']}")

# Check ALL segments for the pattern
for track_idx, track in enumerate(template["tracks"]):
    for i, seg in enumerate(track["segments"]):
        tr = seg["target_timerange"]
        has_start = "start" in tr
        print(f"  Template track[{track_idx}]({track['type']}) seg[{i}]: has_start={has_start}, keys={sorted(tr.keys())}")

# Now check: does our generated version have start in the right places?
print("\n--- Our segments ---")
for track_idx, track in enumerate(testq["tracks"]):
    for i, seg in enumerate(track["segments"][:3]):
        tr = seg["target_timerange"]
        has_start = "start" in tr
        print(f"  Our track[{track_idx}]({track['type']}) seg[{i}]: has_start={has_start}, keys={sorted(tr.keys())}")

