"""
v4 测试：纯英文 prompt + medium quality
"""
import asyncio, os, sys, base64
sys.path.insert(0, '.')
from services.image_service import (
    plan_visual_arc, build_single_segment_prompt,
    STYLE_BIBLES, STYLE_PROMPT_MAP, SAFETY_SUFFIX, _generate_fal,
)
from services.llm_service import split_into_short_sentences

OUT = 'data/tasks/4/images'
with open('data/tasks/4/rewritten.txt', 'r', encoding='utf-8') as f:
    rewritten = f.read()

sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)

async def main():
    vp = await plan_visual_arc(
        rewritten_transcript=rewritten,
        book_title='', book_author='', visual_context='',
        style='documentary_realism', total_segments=len(sentences),
    )
    if not vp: print('FAILED'); return
    print(f"global_style={vp.get('global_style','')[:150]}...")
    print(f"color_arc={vp.get('color_arc','')}")

    for i in range(5):
        text = sentences[i]
        prompt = build_single_segment_prompt(
            text=text, segment_index=i, total_segments=len(sentences),
            style_bible=STYLE_BIBLES.get('documentary_realism', ''),
            aspect_ratio='8:9', visual_context='', visual_plan=vp,
        )
        full = prompt + STYLE_PROMPT_MAP.get('documentary_realism', '') + SAFETY_SUFFIX
        print(f'\nseg_{i:03d} ({len(full)} chars):')
        print(full)
        print()

        b64 = await _generate_fal(full, width=1080, height=1214, quality='medium')
        if b64:
            path = os.path.join(OUT, f'seg_{i:03d}_v5_en.png')
            with open(path, 'wb') as f:
                f.write(base64.b64decode(b64))
            print(f'OK: seg_{i:03d}_v5_en.png')
        else:
            print('FAILED')

asyncio.run(main())
