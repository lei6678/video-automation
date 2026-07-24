"""
测试火山引擎 TTS API 连通性
"""
import base64, httpx, asyncio, json

AK_ENC = 'AKLT_PLACEHOLDER'
SK_ENC = 'WVdVM05ERTVZMkl6TnpSa05HRm1NbUV4TW1Wak9XTXhZbVk0WVRobE56aw=='

# 尝试解码 SK
try:
    SK_DEC = base64.b64decode(SK_ENC + '==').decode('utf-8')
    print(f'SK 解码结果: {repr(SK_DEC)}')
except Exception as e:
    print(f'SK 解码失败: {e}')
    SK_DEC = None

print(f'AK 原始值: {AK_ENC[:30]}...')


async def test():
    # 测试 TTS API 端点
    tests = [
        ('无认证', {}),
        ('AK作Bearer', {'Authorization': f'Bearer {AK_ENC}'}),
    ]
    payload = {
        'appid': 'test_appid',
        'text': '你好，这是测试。',
        'voice_id': 'zh_female_shangning',
        'encoding': 'mp3',
    }

    for name, extra_headers in tests:
        headers = {'Content-Type': 'application/json', **extra_headers}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    'https://openspeech.bytedance.com/api/v1/tts',
                    json=payload,
                    headers=headers
                )
                print(f'\n{name}: {resp.status_code}')
                print(f'  响应: {resp.text[:300]}')
        except Exception as e:
            print(f'\n{name}: ERROR {e}')

    # 测试 STS 端点
    print('\n--- 测试 STS AssumeRole ---')
    if SK_DEC:
        import hashlib, hmac, time, urllib.parse
        from datetime import datetime, timezone

        now_iso = datetime.fromtimestamp(int(time.time()), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        def sign(secret, string_to_sign):
            return base64.b64encode(
                hmac.new(secret.encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha256).digest()
            ).decode('utf-8')

        # 用解码后的 SK 做签名测试
        string_to_sign = f"GET\n/api/v1/sts/AssumeRole\nAccessKeyId={AK_ENC}&SignatureMethod=HMAC-SHA256&SignatureVersion=1.0&Timestamp={urllib.parse.quote(now_iso)}"
        hashed = hashlib.sha256(string_to_sign.encode('utf-8')).hexdigest()
        sts_string = f"HMAC-SHA256\n{now_iso}\n{hashed}"
        signature = sign(SK_DEC, sts_string)

        params = {
            'AccessKeyId': AK_ENC,
            'SignatureMethod': 'HMAC-SHA256',
            'SignatureVersion': '1.0',
            'Timestamp': now_iso,
            'Signature': signature,
            'RoleArn': 'acs:ram::123456789:role/ttsrole',  # 占位
            'RoleSessionName': 'tts_session',
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get('https://open.volcengineapi.com/api/v1/sts/AssumeRole', params=params)
                print(f'STS: {resp.status_code} | {resp.text[:300]}')
        except Exception as e:
            print(f'STS ERROR: {e}')

if __name__ == '__main__':
    asyncio.run(test())
