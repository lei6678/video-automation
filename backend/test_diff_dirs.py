"""Binary diff every file between Task6 and ComboC"""
import os, hashlib

DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
TASK6 = os.path.join(DRAFT_ROOT, "Task6")
COMBOC = os.path.join(DRAFT_ROOT, "ComboC_FullService")

def hash_file(path):
    if not os.path.isfile(path): return "NONEXISTENT"
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except:
        return "ERROR"

def list_all_files(d):
    result = set()
    for root, dirs, files in os.walk(d):
        for f in files:
            if f.startswith("_") or f.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(root, f), d).replace("\\", "/")
            result.add(rel)
    return result

t6_files = list_all_files(TASK6)
cb_files = list_all_files(COMBOC)

all_files = sorted(t6_files | cb_files)
print(f"Task6 has {len(t6_files)} files, ComboC has {len(cb_files)} files")
print(f"Total unique paths: {len(all_files)}")

for f in all_files:
    t6_p = os.path.join(TASK6, f)
    cb_p = os.path.join(COMBOC, f)
    t6_h = hash_file(t6_p)
    cb_h = hash_file(cb_p)
    t6_s = os.path.getsize(t6_p) if os.path.isfile(t6_p) else -1
    cb_s = os.path.getsize(cb_p) if os.path.isfile(cb_p) else -1

    if t6_h == cb_h:
        continue  # identical, skip

    # Determine category
    if t6_h == "NONEXISTENT":
        cat = "T6_MISSING"
    elif cb_h == "NONEXISTENT":
        cat = "C_MISSING"
    else:
        cat = "DIFFERENT"

    print(f"[{cat}] {f}")
    print(f"  Task6: {t6_s}B md5={t6_h[:12]}")
    print(f"  ComboC: {cb_s}B md5={cb_h[:12]}")
