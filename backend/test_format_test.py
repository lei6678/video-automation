"""测试: jy-draftc 加密时是否对 JSON 格式敏感"""
import json, os, subprocess, shutil

JY_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
TASK_DIR = r"D:/VideoWorkstation_Deploy/backend/data/tasks/6"
env = os.environ.copy()
env["JY_INSTALL_DIR"] = JY_DIR

# ======== Step 1: Take the Task6 JSON and re-save compact ========
# Decrypt current Task6 to get the JSON content
dec_path = os.path.join(DRAFT_ROOT, "Task6", "_task6_dec.json")
with open(dec_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# ======== Step 2: Write both versions ========
test_dir = os.path.join(DRAFT_ROOT, "Test_Format")
if os.path.exists(test_dir):
    shutil.rmtree(test_dir)
os.makedirs(test_dir)

# Pretty version (matching what service writes)
pretty_path = os.path.join(test_dir, "pretty.json")
with open(pretty_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
pretty_size = os.path.getsize(pretty_path)

# Compact version
compact_path = os.path.join(test_dir, "compact.json")
with open(compact_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
compact_size = os.path.getsize(compact_path)

print(f"Pretty JSON: {pretty_size} bytes")
print(f"Compact JSON: {compact_size} bytes")

# ======== Step 3: Encrypt both ========
def jy_encrypt(filepath):
    cwd = os.path.dirname(filepath)
    result = subprocess.run(["jy-draftc", "-e", filepath], cwd=cwd, env=env,
                           capture_output=True, text=True)
    print(f"  stdout: {result.stdout.strip()}")
    print(f"  stderr: {result.stderr.strip()}")
    enc_out = filepath + ".enc.json"
    if os.path.exists(enc_out):
        return enc_out
    return None

pretty_enc = jy_encrypt(pretty_path)
compact_enc = jy_encrypt(compact_path)

if pretty_enc:
    print(f"Pretty encrypted: {os.path.getsize(pretty_enc)} bytes")
if compact_enc:
    print(f"Compact encrypted: {os.path.getsize(compact_enc)} bytes")

# ======== Step 4: Decrypt both ========
def jy_decrypt(enc_path, out_path):
    subprocess.run(["jy-draftc", "-d", enc_path, out_path], env=env,
                   capture_output=True, text=True)
    return out_path

if pretty_enc:
    pretty_dec = os.path.join(test_dir, "pretty_dec.json")
    jy_decrypt(pretty_enc, pretty_dec)
    with open(pretty_dec, "rb") as f:
        raw = f.read()
    print(f"Pretty decrypted: {len(raw)} bytes")
    print(f"  First 40 bytes: {raw[:40]}")
    print(f"  Lines: {raw.decode('utf-8').count(chr(10))}")

if compact_enc:
    compact_dec = os.path.join(test_dir, "compact_dec.json")
    jy_decrypt(compact_enc, compact_dec)
    with open(compact_dec, "rb") as f:
        raw = f.read()
    print(f"Compact decrypted: {len(raw)} bytes")
    print(f"  First 40 bytes: {raw[:40]}")
    print(f"  Lines: {raw.decode('utf-8').count(chr(10))}")

# ======== Step 5: Make a full draft with compact JSON ========
print("\n=== Building test draft with compact JSON ===")
dc_path = os.path.join(test_dir, "draft_content.json")
# Use compact format
with open(dc_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

# Encrypt it
dc_enc = jy_encrypt(dc_path)
if dc_enc:
    os.remove(dc_path)
    os.rename(dc_enc, dc_path)
    print(f"Encrypted draft_content.json: {os.path.getsize(dc_path)} bytes")

# Verify roundtrip
verify_path = os.path.join(test_dir, "verify_dec.json")
jy_decrypt(dc_path, verify_path)
with open(verify_path, "rb") as f:
    raw = f.read()
print(f"Decrypted roundtrip: {len(raw)} bytes, lines: {raw.decode('utf-8').count(chr(10))}")
print(f"  First 50 bytes: {raw[:50]}")
