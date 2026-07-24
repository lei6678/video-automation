"""
用 volcengine 标准 AK/SK 签名调用 TTS
"""
import base64, json, httpx, asyncio, uuid, hashlib, hmac, time, urllib.parse
from datetime import datetime, timezone

AK_RAW = 'AKLT_PLACEHOLDER'
SK_RAW = 'WVdVM05ERTVZMkl6TnpSa05HRm1NbUV4TW1Wak9XTXhZbVk0WVRobE56aw=='

# 解码真实 AK/SK
AK = base64.b64decode(AK_RAW[4:] + '==').decode('utf-8')
SK_STAGE1 = base64.b64decode(SK_RAW).decode('latin-1')
SK = base64.b64decode(SK_STAGE1 + '==').decode('latin-1')
print(f"真实 AK: {AK}")
print(f"真实 SK: {SK}")

def sign_v4(ak, sk, method, host, path, params):
    """火山引擎 V4 签名"""
    now = datetime.fromtimestamp(int(time.time()), tz=timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Canonical request
    hashed = hashlib.sha256(f"{method}\n{path}\n{urllib.parse.urlencode(sorted(params.items()))}\n{host}\n\napplication/json".encode()).hexdigest()

    # String to sign
    sts = f"HMAC-SHA256\n{now_iso}\n{hashed}"

    # Signature
    sig = hmac.new(sk.encode(), sts.encode(), hashlib.sha256).digest()

    return now_iso, base64.b64encode(sig).decode()

async def call_tts():
    """调用 volcengine TTS API"""
    reqid = str(uuid.uuid4())
    now_iso, signature = sign_v4(AK, SK, "POST", "openspeech.bytedance.com", "/api/v1/tts", {
        "AccessKeyId": AK,
        "SignatureVersion": "1.0",
        "SignatureMethod": "HMAC-SHA256",
    })

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'HMAC-SHA256 Credential={AK}, SignedHeaders=content-type;host, Signature={signature}',
        'X-Date': now_iso,
    }

    payload = {
        'reqid': reqid,
        'app': {'appid': '5373024197', 'cluster': 'volc_tts_production'},
        'user': {'uid': '2104534266'},
        'text': '今天天气真好。',
        'voice_id': 'zh_female_shangning',
        'encoding': 'mp3',
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            'https://openspeech.bytedance.com/api/v1/tts',
            json=payload,
            headers=headers
        )
        print(f"\n签名认证结果: {resp.status_code}")
        print(f"响应: {resp.text[:300]}")
        if resp.status_code == 200:
            with open('E:/video-automation/test_volc_signed.mp3', 'wb') as f:
                f.write(resp.content)
            print(f"成功! {len(resp.content)} bytes")

async def call_volcengine_api():
    """调用标准 volcengine API (非 openspeech)"""
    # volcengine 通用 API
    urls_to_try = [
        'https://visual.volcengine.com/api/tts/v1',
        'https://cv.volcengine.com/api/tts/v1',
    ]

    reqid = str(uuid.uuid4())
    now_iso, signature = sign_v4(AK, SK, "POST", "visual.volcengine.com", "/api/tts/v1", {
        "AccessKeyId": AK,
        "SignatureVersion": "1.0",
        "SignatureMethod": "HMAC-SHA256",
    })

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'HMAC-SHA256 Credential={AK}, SignedHeaders=content-type;host, Signature={signature}',
        'X-Date': now_iso,
    }

    payload = {
        'text': '今天天气真好',
        'voice_id': 'zh_female_shangning',
        'encoding': 'mp3',
    }

    for url in urls_to_try:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                print(f"URL {url.split('/')[2]}: {resp.status_code} | {resp.text[:100]}")
        except Exception as e:
            print(f"URL {url}: ERROR {e}")

if __name__ == '__main__':
    print("=== 1. 签名认证 TTS ===")
    asyncio.run(call_tts())
    print("\n=== 2. 标准 volc API ===")
    asyncio.run(call_volcengine_api())
