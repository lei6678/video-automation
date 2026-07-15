"""
完整 TTS 测试脚本 - 带详细调试信息
"""
import sys
import os
import asyncio

sys.path.insert(0, 'e:/video-automation/backend')
os.chdir('e:/video-automation/backend')

print("=" * 60)
print("Step 1: Apply patches")
print("=" * 60)

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
print("Patches applied")

print()
print("=" * 60)
print("Step 2: Build SSML")
print("=" * 60)

from services.tts_service import build_ssml
ssml = build_ssml("test <break time='300ms'/> hello")
print(f"SSML:\n{ssml}")

print()
print("=" * 60)
print("Step 3: Create Communicate and inspect texts")
print("=" * 60)

c = edge_tts.Communicate(ssml, 'zh-CN-XiaoxiaoNeural')

# texts is a generator - consume it into a list
texts_list = list(c.texts)
print(f"texts count: {len(texts_list)}")
text0_bytes = texts_list[0]
print(f"texts[0] first 100 bytes: {text0_bytes[:100]}")
text0_str = text0_bytes.decode('utf-8')
has_break = '<break' in text0_str
print(f"texts[0] contains <break: {has_break}")
print(f"texts[0] content:\n{text0_str}")

print()
print("=" * 60)
print("Step 4: Verify mkssml output")
print("=" * 60)

tc = TTSConfig('zh-CN-XiaoxiaoNeural', '+0%', '+0%', '+0Hz', 'SentenceBoundary')
final = edge_tts.communicate.mkssml(tc, texts_list[0])
print(f"mkssml output (first 300 chars):\n{final[:300]}")
has_break_final = '<break' in final
print(f"mkssml output contains <break: {has_break_final}")

print()
print("=" * 60)
print("Step 5: TTS request")
print("=" * 60)

async def run_tts():
    output = "e:/video-automation/backend/test_break.mp3"
    try:
        await c.save(output)
        size = os.path.getsize(output)
        print(f"SUCCESS! File size: {size} bytes")
        return True
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return False

result = asyncio.run(run_tts())
print(f"Final result: {'PASS' if result else 'FAIL'}")
