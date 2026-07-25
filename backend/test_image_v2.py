import asyncio, os, sys, base64
sys.path.insert(0, '.')
from services.image_service import (
    plan_visual_arc, build_single_segment_prompt,
    STYLE_BIBLES, STYLE_PROMPT_MAP, SAFETY_SUFFIX, _generate_fal, FAL_QUALITY,
)
from services.llm_service import split_into_short_sentences

OUT_DIR = 'data/tasks/4/images'
with open('data/tasks/4/rewritten.txt', 'r', encoding='utf-8') as f:
    rewritten = f.read()

sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)
print(f'文案: {len(rewritten)} 字, {len(sentences)} 分镜')

async def main():
    vp = await plan_visual_arc(
        rewritten_transcript=rewritten,
        book_title='', book_author='', visual_context='',
        style='documentary_realism', total_segments=len(sentences),
    )
    if not vp:
        print('FAILED')
        return

    for k, v in vp.items():
        print(f'{k}: {len(v)} chars → {v[:120]}...')

    for seg_idx in [4, 10]:
        text = sentences[seg_idx]
        prompt = build_single_segment_prompt(
            text=text, segment_index=seg_idx, total_segments=len(sentences),
            style_bible=STYLE_BIBLES.get('documentary_realism', ''),
            aspect_ratio='8:9', visual_context='', visual_plan=vp,
        )
        full = prompt + STYLE_PROMPT_MAP.get('documentary_realism', '') + SAFETY_SUFFIX
        print(f'\n=== seg_{seg_idx} ({len(full)} chars) ===')
        print(full[:600])

        # Generate
        print(f'Generating seg_{seg_idx}...')
        b64 = await _generate_fal(full, width=1080, height=1214, quality='low')
        if b64:
            path = os.path.join(OUT_DIR, f'seg_{seg_idx:03d}_v5_fix2.png')
            with open(path, 'wb') as f:
                f.write(base64.b64decode(b64))
            print(f'Saved: {path}')
        else:
            print('FAILED')

    print('\nDone!')

asyncio.run(main())
