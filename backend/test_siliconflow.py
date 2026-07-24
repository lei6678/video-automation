"""
Test SiliconFlow voice cloning API
"""
import httpx, asyncio, base64, json, os, sys

SILICONFLOW_KEY = 'sk-qjwhbrusppisdhixooiabnstihxbfuxgwionjqdndncmsijv'
BASE_URL = 'https://api.siliconflow.cn'

async def test_upload():
    test_files = [
        'E:/video-automation/test_edge_direct.mp3',
        'E:/video-automation/backend/data/tasks/25/segments/seg_000.mp3',
    ]
    audio_path = next((f for f in test_files if os.path.exists(f)), None)
    if not audio_path:
        print('No test audio file found')
        return None

    with open(audio_path, 'rb') as f:
        audio_bytes = f.read()
    print(f'Audio: {audio_path}, size: {len(audio_bytes)} bytes')

    url = f'{BASE_URL}/v1/uploads/audio/voice'

    # Method 1: multipart file upload
    async with httpx.AsyncClient(timeout=60.0) as client:
        with open(audio_path, 'rb') as f:
            files = {'file': ('reference.mp3', f, 'audio/mpeg')}
            data = {
                'model': 'FunAudioLLM/CosyVoice2-0.5B',
                'customName': 'test_voice_001',
                'text': 'This is a test audio for voice cloning.',
            }
            resp = await client.post(url, files=files, data=data, headers={
                'Authorization': f'Bearer {SILICONFLOW_KEY}'
            })
        print(f'Method 1 (file upload): {resp.status_code}')
        print(f'ReSponse: {resp.text[:300]}')
        if resp.status_code == 200:
            result = resp.json()
            uri = result.get('uri')
            print(f'SUCCESS! uri={uri}')
            return uri

        # Method 2: base64 upload
        audio_b64 = base64.b64encode(audio_bytes).decode()
        data_uri = f'data:audio/mpeg;base64,{audio_b64}'
        payload = {
            'model': 'FunAudioLLM/CosyVoice2-0.5B',
            'customName': 'test_voice_002',
            'text': 'This is a test audio for voice cloning.',
            'audio': data_uri,
        }
        resp = await client.post(url, json=payload, headers={
            'Authorization': f'Bearer {SILICONFLOW_KEY}'
        })
        print(f'Method 2 (base64): {resp.status_code}')
        print(f'ReSponse: {resp.text[:300]}')
        if resp.status_code == 200:
            result = resp.json()
            uri = result.get('uri')
            print(f'SUCCESS! uri={uri}')
            return uri

    return None

async def test_list_voices():
    url = f'{BASE_URL}/v1/audio/voice/list'
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers={
            'Authorization': f'Bearer {SILICONFLOW_KEY}'
        })
        print(f'List voices: {resp.status_code}')
        print(f'ReSponse: {resp.text[:500]}')
        if resp.status_code == 200:
            return resp.json().get('results', [])
    return []

async def test_tts(voice_uri, text='Today the weather is great, let us go for a walk.'):
    url = f'{BASE_URL}/v1/audio/speech'
    payload = {
        'model': 'FunAudioLLM/CosyVoice2-0.5B',
        'input': text,
        'voice': voice_uri,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers={
            'Authorization': f'Bearer {SILICONFLOW_KEY}'
        })
        print(f'TTS request: {resp.status_code}')
        if resp.status_code == 200:
            out_path = 'E:/video-automation/test_siliconflow_clone.mp3'
            with open(out_path, 'wb') as f:
                f.write(resp.content)
            print(f'SUCCESS! Audio saved: {len(resp.content)} bytes -> {out_path}')
            return True
        else:
            print(f'ReSponse: {resp.text[:300]}')
            return False

async def main():
    print('=== Step 1: Upload reference audio ===')
    uri = await test_upload()

    print('\n=== Step 2: List voices ===')
    voices = await test_list_voices()

    if voices:
        print(f'\n=== Step 3: TTS with first voice ===')
        await test_tts(voices[0]['uri'])
    elif uri:
        print(f'\n=== Step 3: TTS with uploaded voice ===')
        await test_tts(uri)

if __name__ == '__main__':
    asyncio.run(main())
