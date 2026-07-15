"""Debug list_voices"""
import asyncio, sys, os
sys.path.insert(0, '.')
os.chdir('E:/video-automation/backend')

from dotenv import load_dotenv
load_dotenv()

key = os.getenv('SILICONFLOW_API_KEY', '')
print('Key loaded:', key[:15], '...' if len(key) > 15 else '')
print('Key length:', len(key))

from services.siliconflow_tts_service import list_voices
import httpx

async def test():
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            'https://api.siliconflow.cn/v1/audio/voice/list',
            headers={'Authorization': f'Bearer {key}'}
        )
        print('Status:', resp.status_code)
        print('Response:', resp.text[:500])

asyncio.run(test())
