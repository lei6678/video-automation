"""
测试不同 Content-Type 和认证方式
"""
import httpx, asyncio, uuid, base64, json
from google.protobuf import json_format, descriptor_pb2
from google.protobuf.struct_pb2 import Struct, Value
from google.protobuf.message import Message

async def test_content_types():
    reqid = str(uuid.uuid4())

    # 测试不同 Content-Type
    content_types = [
        'application/json',
        'application/x-protobuf',
        'application/octet-stream',
        'text/plain',
    ]

    base_payload = {
        'request': {
            'reqid': reqid,
            'app': {'appid': '5373024197', 'cluster': 'volc_tts_production'},
            'text': 'hello',
            'voice_id': 'zh_female_shangning',
        }
    }

    for ct in content_types:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if ct == 'application/json':
                resp = await client.post(
                    'https://openspeech.bytedance.com/api/v1/tts',
                    json=base_payload,
                    headers={'Content-Type': ct}
                )
            else:
                # 非 JSON 的用 json bytes
                resp = await client.post(
                    'https://openspeech.bytedance.com/api/v1/tts',
                    content=json.dumps(base_payload).encode(),
                    headers={'Content-Type': ct}
                )
            print(f'CT={ct:30s}: {resp.status_code} | {resp.text[:100]}')

async def test_proto_binary():
    """用 protobuf 二进制格式发送"""
    reqid = str(uuid.uuid4())

    # 尝试用 Struct 来构建 audio 字段
    s = Struct()
    s['audio_data'] = 'test'
    s['audio_type'] = 'mp3'

    payload = {
        'request': {
            'reqid': reqid,
            'app': {'appid': '5373024197', 'cluster': 'volc_tts_production'},
            'text': 'hello',
            'voice_id': 'zh_female_shangning',
            'audio': s
        }
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            'https://openspeech.bytedance.com/api/v1/tts',
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        print(f'Struct audio: {resp.status_code} | {resp.text[:150]}')

async def test_auth_variants():
    """测试不同的认证方式"""
    reqid = str(uuid.uuid4())
    ak_raw = 'AKLT_PLACEHOLDER'
    sk_raw = 'WVdVM05ERTVZMkl6TnpSa05HRm1NbUV4TW1Wak9XTXhZbVk0WVRobE56aw=='

    # AK: AKLT开头，是字节系特殊格式
    # 试试直接把原始字符串当作 token
    auth_headers = [
        {},
        {'Authorization': f'Bearer {ak_raw}'},
        {'Authorization': f'Token {ak_raw}'},
        {'X-Api-Key': ak_raw},
        {'ApiKey': ak_raw},
    ]

    payload = {
        'request': {
            'reqid': reqid,
            'app': {'appid': '5373024197', 'cluster': 'volc_tts_production'},
            'text': 'hello',
            'voice_id': 'zh_female_shangning',
        }
    }

    for auth in auth_headers:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                'https://openspeech.bytedance.com/api/v1/tts',
                json=payload,
                headers={'Content-Type': 'application/json', **auth}
            )
            auth_name = list(auth.keys())[0] if auth else 'no-auth'
            print(f'Auth={auth_name:20s}: {resp.status_code} | {resp.text[:80]}')

async def main():
    print("=== 1. Content-Type 测试 ===")
    await test_content_types()
    print("\n=== 2. Struct audio 测试 ===")
    await test_proto_binary()
    print("\n=== 3. 认证变体测试 ===")
    await test_auth_variants()

if __name__ == '__main__':
    asyncio.run(main())
