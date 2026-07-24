"""
直接用原始二进制测试 protobuf 格式
"""
import httpx, asyncio, uuid, json

async def test_raw_protobuf():
    """直接发送二进制 protobuf，看是否成功"""
    reqid = str(uuid.uuid4())

    # 构建一个最小的 protobuf message 二进制
    # 用简单的方式：构建 JSON bytes，然后看服务器反应
    test_payloads = [
        # A: 极简 JSON
        json.dumps({'reqid': reqid, 'app': {'appid': '5373024197', 'cluster': 'tts'}, 'text': 'hi'}).encode(),
        # B: 嵌套 request
        json.dumps({'request': {'reqid': reqid, 'app': {'appid': '5373024197', 'cluster': 'tts'}, 'text': 'hi'}}).encode(),
    ]

    for i, body in enumerate(test_payloads):
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                'https://openspeech.bytedance.com/api/v1/tts',
                content=body,
                headers={
                    'Content-Type': 'application/x-protobuf',
                    'X-Api-Key': '5373024197',
                }
            )
            print(f'Raw T{i+1}: {resp.status_code} | {resp.text[:100]}')

    # 测试不同的 protobuf variant
    for i, ct in enumerate([
        'application/x-google-protobuf',
        'application/x-protobuf; charset=utf-8',
    ]):
        body = json.dumps({'request': {'reqid': reqid, 'app': {'appid': '5373024197', 'cluster': 'tts'}, 'text': 'hi'}}).encode()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                'https://openspeech.bytedance.com/api/v1/tts',
                content=body,
                headers={'Content-Type': ct}
            )
            print(f'ProtoCT T{i+1}: {resp.status_code} | {resp.text[:100]}')

async def test_query_params():
    """测试 query string 参数方式"""
    reqid = str(uuid.uuid4())

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f'https://openspeech.bytedance.com/api/v1/tts?reqid={reqid}&appid=5373024197&text=hello',
            headers={'Content-Type': 'application/json'}
        )
        print(f'GET: {resp.status_code} | {resp.text[:100]}')

async def main():
    print("=== Raw protobuf 测试 ===")
    await test_raw_protobuf()
    print("\n=== Query params 测试 ===")
    await test_query_params()

if __name__ == '__main__':
    asyncio.run(main())
