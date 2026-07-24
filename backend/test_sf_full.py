"""Full SiliconFlow TTS service test"""
import asyncio, sys, os
sys.path.insert(0, '.')
os.chdir('E:/video-automation/backend')

from dotenv import load_dotenv
load_dotenv()

from services.siliconflow_tts_service import upload_reference_audio, synthesize, list_voices

async def main():
    # 1. 列出已有音色
    voices = await list_voices()
    print(f'Step 1 - 已有 {len(voices)} 个音色')

    # 2. 用已有音色合成
    if not voices:
        print('No voices found')
        return

    voice_uri = voices[0]['uri']
    print(f'Step 2 - 使用音色: {voice_uri}')

    result = await synthesize(
        text='Today the weather is great, let us go for a walk.',
        voice_uri=voice_uri,
        output_path='E:/video-automation/test_clone_final.mp3'
    )

    if result:
        size = os.path.getsize(result)
        print(f'SUCCESS! File: {result}, size: {size} bytes')
    else:
        print('Synthesis failed')

if __name__ == '__main__':
    asyncio.run(main())
