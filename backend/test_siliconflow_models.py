"""
Test SiliconFlow TTS with different models
"""
import httpx, asyncio, base64

SILICONFLOW_KEY = 'sk-qjwhbrusppisdhixooiabnstihxbfuxgwionjqdndncmsijv'
BASE_URL = 'https://api.siliconflow.cn'
VOICE_URI = 'speech:test_voice_001:d8uv3ftsssvc73almr4g:cwqvwkzhilbjwwqqrzfw'

async def test_models():
    """测试不同模型"""
    models_to_try = [
        'FunAudioLLM/CosyVoice2-0.5B',
    ]

    url = f'{BASE_URL}/v1/audio/speech'
    text = 'Today the weather is great, let us go for a walk.'

    async with httpx.AsyncClient(timeout=60.0) as client:
        for model in models_to_try:
            payload = {
                'model': model,
                'input': text,
                'voice': VOICE_URI,
            }
            resp = await client.post(url, json=payload, headers={
                'Authorization': f'Bearer {SILICONFLOW_KEY}'
            })
            print(f'Model={model:40s}: {resp.status_code} | {resp.text[:100]}')
            if resp.status_code == 200:
                out_path = f'E:/video-automation/test_{model.split("/")[-1]}.mp3'
                with open(out_path, 'wb') as f:
                    f.write(resp.content)
                print(f'  SUCCESS! {len(resp.content)} bytes -> {out_path}')
                return True
    return False

async def test_tts_no_voice():
    """测试不用 reference voice 的普通 TTS"""
    url = f'{BASE_URL}/v1/audio/speech'

    # 先列出可用的标准音色（不用 reference 的）
    models = [
        'FunAudioLLM/CosyVoice2-0.5B',
    ]

    async with httpx.AsyncClient(timeout=60.0) as client:
        for model in models:
            payload = {
                'model': model,
                'input': 'Today the weather is great.',
            }
            resp = await client.post(url, json=payload, headers={
                'Authorization': f'Bearer {SILICONFLOW_KEY}'
            })
            print(f'Model={model:40s}: {resp.status_code} | {resp.text[:100]}')
            if resp.status_code == 200:
                out_path = f'E:/video-automation/test_{model.split("/")[-1]}_normal.mp3'
                with open(out_path, 'wb') as f:
                    f.write(resp.content)
                print(f'  SUCCESS! {len(resp.content)} bytes')

async def main():
    print('=== Test TTS with reference voice ===')
    await test_models()
    print('\n=== Test TTS without reference voice ===')
    await test_tts_no_voice()

if __name__ == '__main__':
    asyncio.run(main())
