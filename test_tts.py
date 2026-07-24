import sys
sys.path.insert(0, 'e:/video-automation/backend')

import asyncio
import os

async def test():
    ssml = '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN"><voice name="zh-CN-XiaoxiaoNeural">你好，<break time="300ms"/>世界！</voice></speak>'
    print('SSML 内容:')
    print(ssml)
    print()

    from services.tts_service import generate_audio
    output = 'e:/video-automation/test_output.mp3'
    print('开始合成...')
    await generate_audio(ssml, 'zh-CN-XiaoxiaoNeural', output)
    print(f'成功！文件: {output}')
    print(f'大小: {os.path.getsize(output)} bytes')

try:
    asyncio.run(test())
except Exception as e:
    print(f'错误: {type(e).__name__}: {e}')
