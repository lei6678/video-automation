import asyncio

async def test():
    ssml = '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN"><voice name="zh-CN-XiaoxiaoNeural">你好，<break time="300ms"/>世界！</voice></speak>'
    print('1. 开始测试...')

    from services.tts_service import CommunicateSSML
    print('2. 导入成功，创建对象...')

    c = CommunicateSSML(ssml, 'zh-CN-XiaoxiaoNeural')
    print('3. 开始连接微软服务器...')

    count = 0
    async for chunk in c.stream():
        count += 1
        print(f'4. 收到数据: {chunk["type"]}')

    print(f'5. 完成！共收到 {count} 个数据块')

asyncio.run(test())
print('脚本执行完毕')
