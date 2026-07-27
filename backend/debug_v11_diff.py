"""调试：对比模板和生成的draft_content.json，找出差异"""
import json, os, subprocess, shutil

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"

def decrypt(path, out):
    env = os.environ.copy()
    env["JY_INSTALL_DIR"] = JY_DIR
    subprocess.run(["jy-draftc", "-d", path, out], env=env, capture_output=True, text=True)

# Decrypt template
tmpl_enc = os.path.join(DRAFT_ROOT, "TestReEncrypt", "draft_content.json")
tmpl_dec = os.path.join(DRAFT_ROOT, "TestReEncrypt", "draft_content.debug.json")
decrypt(tmpl_enc, tmpl_dec)
with open(tmpl_dec, "r", encoding="utf-8") as f:
    template = json.load(f)

# Decrypt our generated
gen_enc = os.path.join(DRAFT_ROOT, "Task6_v11_final", "draft_content.json")
gen_dec = os.path.join(DRAFT_ROOT, "Task6_v11_final", "draft_content.debug.json")
decrypt(gen_enc, gen_dec)
with open(gen_dec, "r", encoding="utf-8") as f:
    generated = json.load(f)

def deep_compare(a, b, path=""):
    """Recursively compare two structures, print differences"""
    diffs = []
    if type(a) != type(b):
        diffs.append(f"{path}: TYPE {type(a).__name__} vs {type(b).__name__}")
        return diffs
    if isinstance(a, dict):
        a_keys = set(a.keys())
        b_keys = set(b.keys())
        for k in a_keys - b_keys:
            diffs.append(f"{path}.{k}: MISSING in generated")
        for k in b_keys - a_keys:
            diffs.append(f"{path}.{k}: EXTRA in generated")
        for k in a_keys & b_keys:
            diffs.extend(deep_compare(a[k], b[k], f"{path}.{k}"))
    elif isinstance(a, list):
        if len(a) != len(b):
            diffs.append(f"{path}: LENGTH {len(a)} vs {len(b)}")
        for i in range(min(len(a), len(b))):
            diffs.extend(deep_compare(a[i], b[i], f"{path}[{i}]"))
    else:
        if a != b:
            diffs.append(f"{path}: '{a}' vs '{b}'")
    return diffs

# Compare top-level keys
print("=" * 60)
print("TOP-LEVEL KEY DIFFS")
print("=" * 60)
tmpl_keys = set(template.keys())
gen_keys = set(generated.keys())
for k in sorted(tmpl_keys - gen_keys):
    print(f"  MISSING: {k}")
for k in sorted(gen_keys - tmpl_keys):
    print(f"  EXTRA: {k}")

# Compare tracks structure
print("\n" + "=" * 60)
print("TRACKS STRUCTURE")
print("=" * 60)
for i, (tt, gt) in enumerate(zip(template["tracks"], generated["tracks"])):
    print(f"\nTrack {i}:")
    print(f"  Template: type={tt['type']}, id={tt['id'][:8]}..., segments={len(tt['segments'])}")
    print(f"  Generated: type={gt['type']}, id={gt['id'][:8]}..., segments={len(gt['segments'])}")
    if tt['type'] != gt['type']:
        print(f"  *** TYPE MISMATCH ***")

# Compare first video segment field-by-field
print("\n" + "=" * 60)
print("FIRST VIDEO SEGMENT COMPARISON")
print("=" * 60)
tv = template["tracks"][0]["segments"][0]
gv = generated["tracks"][0]["segments"][0]
for k in sorted(set(list(tv.keys()) + list(gv.keys()))):
    tv_val = tv.get(k, "<MISSING>")
    gv_val = gv.get(k, "<MISSING>")
    if tv_val != gv_val:
        print(f"  {k}:")
        print(f"    T: {str(tv_val)[:120]}")
        print(f"    G: {str(gv_val)[:120]}")

# Compare first video material
print("\n" + "=" * 60)
print("FIRST VIDEO MATERIAL COMPARISON")
print("=" * 60)
tm = template["materials"]["videos"][0]
gm = generated["materials"]["videos"][0]
for k in sorted(set(list(tm.keys()) + list(gm.keys()))):
    tm_val = tm.get(k, "<MISSING>")
    gm_val = gm.get(k, "<MISSING>")
    if tm_val != gm_val:
        print(f"  {k}:")
        print(f"    T: {str(tm_val)[:120]}")
        print(f"    G: {str(gm_val)[:120]}")

# Check total structure: materials dict keys
print("\n" + "=" * 60)
print("MATERIALS CATEGORIES")
print("=" * 60)
tm_mat_keys = set(template["materials"].keys())
gm_mat_keys = set(generated["materials"].keys())
for k in sorted(tm_mat_keys - gm_mat_keys):
    print(f"  MISSING: {k}")
for k in sorted(gm_mat_keys - tm_mat_keys):
    print(f"  EXTRA: {k}")
for k in sorted(tm_mat_keys & gm_mat_keys):
    tc = len(template["materials"][k])
    gc = len(generated["materials"][k])
    flag = " ***" if tc != gc else ""
    print(f"  {k}: T={tc}, G={gc}{flag}")

# Check extra_material_refs
print("\n" + "=" * 60)
print("EXTRA MATERIAL REFS")
print("=" * 60)
tv_refs = tv.get("extra_material_refs", [])
gv_refs = gv.get("extra_material_refs", [])
print(f"  Template: {len(tv_refs)} refs: {tv_refs}")
print(f"  Generated: {len(gv_refs)} refs: {gv_refs}")

# Check if refs point to valid materials
print("\n" + "=" * 60)
print("REF VALIDATION")
print("=" * 60)
all_mat_ids = set()
for cat, items in generated["materials"].items():
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and "id" in item:
                all_mat_ids.add(item["id"])
for i, seg in enumerate(generated["tracks"][0]["segments"]):
    refs = seg.get("extra_material_refs", [])
    for r in refs:
        if r not in all_mat_ids:
            print(f"  BROKEN REF in video seg {i}: {r} not found")

# Check image paths
print("\n" + "=" * 60)
print("IMAGE PATH CHECK")
print("=" * 60)
for i, mat in enumerate(generated["materials"]["videos"][:3]):
    p = mat.get("path", "")
    exists = os.path.exists(p) if p else False
    print(f"  [{i}] {p}")
    print(f"       exists={exists}")

# Check audio path
print("\n" + "=" * 60)
print("AUDIO PATH CHECK")
print("=" * 60)
if generated["materials"]["audios"]:
    ap = generated["materials"]["audios"][0].get("path", "")
    print(f"  {ap}")
    print(f"  exists={os.path.exists(ap)}")

# Check timelines directory structure
print("\n" + "=" * 60)
print("TIMELINES STRUCTURE")
print("=" * 60)
tl_dir = os.path.join(DRAFT_ROOT, "Task6_v11_final", "Timelines")
for root, dirs, files in os.walk(tl_dir):
    level = root.replace(tl_dir, "").count(os.sep)
    indent = "  " * level
    print(f"{indent}{os.path.basename(root)}/")
    subindent = "  " * (level + 1)
    for f in files:
        size = os.path.getsize(os.path.join(root, f))
        print(f"{subindent}{f} ({size} bytes)")

