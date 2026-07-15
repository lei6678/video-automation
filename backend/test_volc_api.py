"""
测试火山引擎 TTS API - 完整版
"""
import base64, json, httpx, asyncio, uuid

# AK/SK 需要先 base64 解码，得到真实凭证
AK_RAW = 'AKLT_PLACEHOLDER'
SK_RAW = 'WVdVM05ERTVZMkl6TnpSa05HRm1NbUV4TW1Wak9XTXhZbVk0WVRobE56aw=='

# SK 是双重 base64 编码
sk_stage1 = base64.b64decode(SK_RAW).decode('latin-1')
sk_final = base64.b64decode(sk_stage1 + '==').decode('latin-1')
print(f"SK: {sk_final} (len={len(sk_final)})")

# AK: AKLT 前缀 + base64(hex)
AK_CONTENT = AK_RAW[4:]
ak_bytes = AK_CONTENT.encode('latin-1')
padding = (4 - len(ak_bytes) % 4) % 4
ak_padded = ak_bytes + b'=' * padding
ak_final = base64.b64decode(ak_padded).decode('utf-8')
print(f"AK: {ak_final} (len={len(ak_final)})")

async def test_tts_api():
    """测试 openspeech TTS API"""
    reqid = str(uuid.uuid4())

    # 测试: audio 字段用正确格式
    with open('E:/video-automation/test_edge_direct.mp3', 'rb') as f:
        audio_b64 = base64.b64encode(f.read()).decode('utf-8')

    audio_obj = {
        'audio_data': audio_b64,
        'audio_type': 'mp3',
        'sample_rate': 24000
    }

    payload = {
        'request': {
            'reqid': reqid,
            'app': {'appid': '5373024197', 'cluster': 'volc_tts_production'},
            'user': {'uid': '2104534266'},
            'text': '今天天气真好。',
            'voice_id': 'zh_female_shangning',
            'encoding': 'mp3',
            'speed_ratio': 1.0,
            'pitch_ratio': 1.0,
            'volume_ratio': 1.0,
            'audio': audio_obj,
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            'https://openspeech.bytedance.com/api/v1/tts',
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        print(f"TTS API 状态: {resp.status_code}")
        print(f"响应: {resp.text[:500]}")
        if resp.status_code == 200:
            with open('E:/video-automation/test_volc_clone.mp3', 'wb') as f:
                f.write(resp.content)
            print(f"✅ 成功! {len(resp.content)} bytes")

async def test_sdk_list_speakers():
    """用真实 AK/SK 测试 SDK"""
    from volcenginesdkspeechsaasprod.api import SPEECHSAASPRODApi
    from volcenginesdkspeechsaasprod.models import ListSpeakersRequest
    from volcenginesdkcore import ApiClient, Configuration

    AK = ak_final
    SK = sk_final

    conf = Configuration()
    conf.ak = AK
    conf.sk = SK
    conf.host = 'open.volcengineapi.com'

    client = ApiClient(conf)
    api = SPEECHSAASPRODApi(client)

    req = ListSpeakersRequest()
    try:
        resp = api.list_speakers(req)
        print("ListSpeakers SUCCESS")
        print(json.dumps(resp.to_dict(), indent=2, ensure_ascii=False, default=str)[:2000])
    except Exception as e:
        if hasattr(e, 'body'):
            body = json.loads(e.body) if isinstance(e.body, str) else e.body
            print("ListSpeakers Error:", json.dumps(body, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    print("=== 1. 测试 openspeech TTS API ===")
    asyncio.run(test_tts_api())
    print("\n=== 2. 测试 SDK list_speakers ===")
    asyncio.run(test_sdk_list_speakers())
