"""探测其他 API 端点"""
import httpx, asyncio, base64, hashlib, hmac, time, urllib.parse, uuid, json
from datetime import datetime, timezone

AK = 'd8e605ca9e104521baeb5630c580d4bf'
SK = 'ae7419cb374d4af2a12ec9c1bf8a8e79'

def sign_v4(sk, method, host, path, params):
    now = datetime.fromtimestamp(int(time.time()), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    canonical = f'{method}\n{path}\n{urllib.parse.urlencode(sorted(params.items()))}\n{host}\n\napplication/json'
    hashed = hashlib.sha256(canonical.encode()).hexdigest()
    sts = f'HMAC-SHA256\n{now}\n{hashed}'
    sig = base64.b64encode(hmac.new(sk.encode(), sts.encode(), hashlib.sha256).digest()).decode()
    return now, sig

async def test():
    now_iso, sig = sign_v4(SK, 'POST', 'openspeech.bytedance.com', '/api/v1/tts', {
        'AccessKeyId': AK, 'SignatureVersion': '1.0', 'SignatureMethod': 'HMAC-SHA256'
    })
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'HMAC-SHA256 Credential={AK}, SignedHeaders=content-type;host, Signature={sig}',
        'X-Date': now_iso,
    }

    endpoints = [
        '/api/v1/audio/upload',
        '/api/v1/audio/submit',
        '/api/v1/ref_audio',
        '/api/v1/voice/clone',
        '/api/v1/mega_tts/submit',
        '/api/v1/mega_tts/audio',
        '/api/v1/tts/voice_clone',
        '/api/v1/tts/audio',
        '/api/v1/tts/async_submit',
    ]

    reqid = str(uuid.uuid4())
    body = json.dumps({'request': {'reqid': reqid, 'app': {'appid': '5373024197', 'cluster': 'volc_tts_production'}, 'text': 'hello'}}).encode()

    for ep in endpoints:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f'https://openspeech.bytedance.com{ep}',
                    content=body,
                    headers=headers
                )
                print(f'{ep:40s}: {resp.status_code} | {resp.text[:80]}')
        except Exception as e:
            print(f'{ep:40s}: ERROR {e}')

if __name__ == '__main__':
    asyncio.run(test())
