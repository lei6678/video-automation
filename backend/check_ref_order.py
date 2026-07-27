"""Check: what order does the template use for extra_material_refs?"""
import json, os, subprocess

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR

def decrypt(enc, out):
    subprocess.run(["jy-draftc", "-d", enc, out], env=env, capture_output=True, text=True)

tmpl_enc = r"E:/360Downloads/JianyingPro Drafts/TestReEncrypt/draft_content.json"
tmpl_dec = tmpl_enc.replace(".json", ".refs.json")
decrypt(tmpl_enc, tmpl_dec)
with open(tmpl_dec, "r", encoding="utf-8") as f:
    t = json.load(f)

# Build ID -> (category, index) map
id_to_cat = {}
for cat, items in t["materials"].items():
    if isinstance(items, list):
        for i, item in enumerate(items):
            if isinstance(item, dict) and "id" in item:
                id_to_cat[item["id"]] = (cat, i)

# Analyze extra_material_refs for each segment
print("=== Template extra_material_refs analysis ===")
for track_idx, track in enumerate(t["tracks"]):
    for seg_idx, seg in enumerate(track["segments"]):
        refs = seg.get("extra_material_refs", [])
        if not refs:
            continue
        print(f"\nTrack {track_idx} ({track['type']}) seg {seg_idx}:")
        for ri, ref_id in enumerate(refs):
            cat, idx = id_to_cat.get(ref_id, ("UNKNOWN", -1))
            print(f"  [{ri}] {cat}[{idx}] = {ref_id}")

# Also check: are there material types with index-based mapping?
# For video seg[0] vs seg[1], which specific indices are referenced?
print("\n=== Index mapping pattern ===")
for track_idx, track in enumerate(t["tracks"]):
    for seg_idx, seg in enumerate(track["segments"]):
        refs = seg.get("extra_material_refs", [])
        if not refs:
            continue
        cats_order = []
        for ri, ref_id in enumerate(refs):
            cat, idx = id_to_cat.get(ref_id, ("?", -1))
            cats_order.append(cat)
        print(f"Track {track_idx} seg {seg_idx}: {cats_order}")

# Check if the order is the same for all video segments
print("\n=== Order consistency check ===")
all_orders = []
for track_idx, track in enumerate(t["tracks"]):
    for seg_idx, seg in enumerate(track["segments"]):
        refs = seg.get("extra_material_refs", [])
        if refs:
            order = tuple(id_to_cat.get(r, ("?", -1))[0] for r in refs)
            all_orders.append((track_idx, seg_idx, order))
            print(f"  T{track_idx}S{seg_idx}: {order}")

print(f"\n=== All unique orders: {len(set(o for _,_,o in all_orders))} ===")
for o in set(o for _,_,o in all_orders):
    print(f"  {o}")

# What does our code use?
our_order = ("speeds", "placeholder_infos", "canvases", "material_animations",
             "material_colors", "sound_channel_mappings", "loudnesses", "vocal_separations")
print(f"\n=== Our ref order: {our_order} ===")

