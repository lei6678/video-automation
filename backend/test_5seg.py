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
print(f'{len(rewritten)} 字, {len(sentences)} 分镜')

async def main():
    # 获取全局视觉规划
    vp = await plan_visual_arc(
        rewritten_transcript=rewritten,
        book_title='', book_author='', visual_context='',
        style='documentary_realism', total_segments=len(sentences),
    )
    if not vp:
        print('plan_visual_arc FAILED'); return

    print(f"global_style={len(vp.get('global_style',''))}chars")
    print(f"era_notes={vp.get('era_notes','')[:100]}...")

    # 前5段: seg 0-4
    for i in range(5):
        text = sentences[i]
        prompt = build_single_segment_prompt(
            text=text, segment_index=i, total_segments=len(sentences),
            style_bible=STYLE_BIBLES.get('documentary_realism', ''),
            aspect_ratio='8:9', visual_context='', visual_plan=vp,
        )
        style_suffix = STYLE_PROMPT_MAP.get('documentary_realism', '')
        full = prompt + style_suffix + SAFETY_SUFFIX
        print(f'\n--- seg_{i:03d} ({len(full)} chars) ---')
        print(full[:300])

        print(f'Generating...')
        b64 = await _generate_fal(full, width=1080, height=1214, quality='low')
        if b64:
            path = os.path.join(OUT, f'seg_{i:03d}_v5_final.png')
            with open(path, 'wb') as f:
                f.write(base64.b64decode(b64))
            print(f'Saved: {path}')
        else:
            print('FAILED')

    print('\nDone! 5 images generated.')

asyncio.run(main())
