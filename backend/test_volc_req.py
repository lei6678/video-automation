"""测试 encoding 值"""
import httpx, asyncio, uuid

async def test():
    reqid = str(uuid.uuid4())
    enc_tests = ['mp3', 'wav', 'pcm', 'opus']

    for enc in enc_tests:
        payload = {
            'request': {
                'reqid': reqid,
                'app': {'appid': '5373024197', 'cluster': 'test'},
                'text': 'hello',
                'voice_id': 'zh_female_shangning',
                'encoding': enc
            }
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                'https://openspeech.bytedance.com/api/v1/tts',
                json=payload,
                headers={'Content-Type': 'application/json'}
            )
            print(f'enc={enc:6s}: {resp.status_code} | {resp.text[:80]}')

    # 无 encoding
    payload = {
        'request': {
            'reqid': reqid,
            'app': {'appid': '5373024197', 'cluster': 'test'},
            'text': 'hello',
            'voice_id': 'zh_female_shangning'
        }
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            'https://openspeech.bytedance.com/api/v1/tts',
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        print(f'enc=None  : {resp.status_code} | {resp.text[:80]}')

if __name__ == '__main__':
    asyncio.run(test())
