"""
测试火山引擎认证并列出可用音色
"""
import base64, json
from volcenginesdkspeechsaasprod.api import SPEECHSAASPRODApi
from volcenginesdkspeechsaasprod.models import ListSpeakersRequest, ListBigModelTTSTimbresRequest
from volcenginesdkcore import ApiClient, Configuration

AK_RAW = 'AKLT_PLACEHOLDER'
SK_RAW = 'WVdVM05ERTVZMkl6TnpSa05HRm1NbUV4TW1Wak9XTXhZbVk0WVRobE56aw=='

def decode_ak(ak_raw):
    """AK 格式: AKLT + base64(hex_ak)"""
    content = ak_raw[4:]
    decoded = base64.b64decode(content + '==').decode('utf-8')
    return decoded

def decode_sk(sk_raw):
    """SK 是双重 base64 编码"""
    s1 = base64.b64decode(sk_raw).decode('latin-1')  # 第一层解码
    s2 = base64.b64decode(s1 + '==').decode('latin-1')  # 第二层解码
    return s2

print("=== 凭证解码 ===")
ak = decode_ak(AK_RAW)
sk = decode_sk(SK_RAW)
print(f"AK: {ak} (len={len(ak)})")
print(f"SK: {sk} (len={len(sk)})")

print("\n=== 测试认证 & 列出音色 ===")
conf = Configuration()
conf.ak = ak
conf.sk = sk
conf.host = 'open.volcengineapi.com'

client = ApiClient(conf)
api = SPEECHSAASPRODApi(client)

# 尝试列出音色
req = ListSpeakersRequest()
try:
    resp = api.list_speakers(req)
    print("ListSpeakers SUCCESS:", resp)
    data = resp.to_dict() if hasattr(resp, 'to_dict') else vars(resp)
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str)[:2000])
except Exception as e:
    if hasattr(e, 'body'):
        body = json.loads(e.body) if isinstance(e.body, str) else e.body
        print("Error:", json.dumps(body, indent=2, ensure_ascii=False))
    else:
        print("ERROR:", e)

# 尝试音色克隆列表
print("\n=== 尝试音色克隆音色列表 ===")
req2 = ListBigModelTTSTimbresRequest()
try:
    resp2 = api.list_big_model_tts_timbres(req2)
    print("ListBigModelTTSTimbres SUCCESS")
    data2 = resp2.to_dict() if hasattr(resp2, 'to_dict') else vars(resp2)
    print(json.dumps(data2, indent=2, ensure_ascii=False, default=str)[:2000])
except Exception as e:
    if hasattr(e, 'body'):
        body = json.loads(e.body) if isinstance(e.body, str) else e.body
        print("Error:", json.dumps(body, indent=2, ensure_ascii=False))
    else:
        print("ERROR:", e)
