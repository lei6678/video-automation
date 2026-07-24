import sys
import os
import asyncio

sys.path.insert(0, 'e:/video-automation/backend')
os.chdir('e:/video-automation/backend')

import edge_tts
from edge_tts.communicate import mkssml as _orig_mkssml, TTSConfig

def _patched_escape(s):
    return s.replace("&", "&amp;")

def _patched_mkssml(tc, text):
    if isinstance(text, bytes):
        text = text.decode('utf-8')
    if text.strip().startswith('<speak'):
        return text
    return _orig_mkssml(tc, text)

edge_tts.communicate.escape = _patched_escape
edge_tts.communicate.mkssml = _patched_mkssml

from services.tts_service import build_ssml

ssml = build_ssml('test <break time="300ms"/> hello')
print('SSML:', ssml)

tc = TTSConfig('zh-CN-XiaoxiaoNeural', '+0%', '+0%', '+0Hz', 'SentenceBoundary')
final = edge_tts.communicate.mkssml(tc, ssml.encode())
print('mkssml output:', final[:300])
print('Has <break:', '<break' in final)

async def t():
    c = edge_tts.Communicate(ssml, 'zh-CN-XiaoxiaoNeural')
    await c.save('test_break2.mp3')
    size = os.path.getsize('test_break2.mp3')
    print('SUCCESS, size:', size, 'bytes')

asyncio.run(t())
