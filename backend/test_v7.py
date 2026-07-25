"""v7: Gemini情绪光影框架 — 主角+情绪光影+具象场景+风格锁"""
import asyncio, os, sys, base64, json
sys.path.insert(0, '.')
from services.image_service import (
    plan_visual_arc, build_single_segment_prompt, _generate_fal,
)
from services.llm_service import split_into_short_sentences

OUT = 'data/tasks/4/images'
with open('data/tasks/4/rewritten.txt', 'r', encoding='utf-8') as f:
    rewritten = f.read()

sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)
print(f'{len(rewritten)} chars, {len(sentences)} segments')

async def main():
    vp = await plan_visual_arc(
        rewritten_transcript=rewritten,
        book_title='', book_author='', visual_context='',
        style='documentary_realism', total_segments=len(sentences),
        sentences=sentences,
    )
    if not vp: print('FAILED'); return

    print(f"protagonist: {vp.get('protagonist','')[:100]}...")
    scenes = vp.get('scenes', [])
    for i in range(min(5, len(scenes))):
        entry = scenes[i]
        if isinstance(entry, dict):
            print(f"  [{i}] emotion={entry.get('emotion','?')} scene={entry.get('scene','')[:80]}...")
        else:
            print(f"  [{i}] {str(entry)[:80]}")

    for i in range(5):
        prompt = build_single_segment_prompt(
            text=sentences[i], segment_index=i, total_segments=len(sentences),
            style_bible='', aspect_ratio='8:9', visual_context='', visual_plan=vp,
        )
        print(f'\n=== seg_{i:03d} ({len(prompt)} chars) ===')
        print(prompt[:400])
        print()

        b64 = await _generate_fal(prompt, width=1080, height=1214, quality='medium')
        if b64:
            path = os.path.join(OUT, f'seg_{i:03d}_v7.png')
            with open(path, 'wb') as f:
                f.write(base64.b64decode(b64))
            print(f'OK: seg_{i:03d}_v7.png')
        else:
            print('FAILED')

asyncio.run(main())
