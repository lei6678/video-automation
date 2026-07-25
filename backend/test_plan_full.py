import asyncio, sys, json
sys.path.insert(0, '.')
from services.image_service import plan_visual_arc, build_single_segment_prompt, STYLE_BIBLES
from services.llm_service import split_into_short_sentences

with open('data/tasks/4/rewritten.txt', 'r', encoding='utf-8') as f:
    rewritten = f.read()

sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)
print(f'文案: {len(rewritten)} 字, {len(sentences)} 分镜')
print()

async def main():
    vp = await plan_visual_arc(
        rewritten_transcript=rewritten,
        book_title='', book_author='', visual_context='',
        style='documentary_realism', total_segments=len(sentences),
    )
    if not vp:
        print('FAILED')
        return

    gs = vp.get('global_style', '')
    ca = vp.get('color_arc', '')
    en = vp.get('era_notes', '')
    print(f'global_style: {len(gs)} chars / {len(gs.split())} words')
    print(f'color_arc:   {len(ca)} chars / {len(ca.split())} words')
    print(f'era_notes:   {len(en)} chars')
    print()
    print('--- global_style ---')
    print(gs)
    print()
    print('--- color_arc ---')
    print(ca)
    print()
    print('--- era_notes ---')
    print(en)
    print()

    # 前 3 段 prompt
    for i in range(min(3, len(sentences))):
        p = build_single_segment_prompt(
            text=sentences[i], segment_index=i, total_segments=len(sentences),
            style_bible=STYLE_BIBLES.get('documentary_realism', ''),
            aspect_ratio='8:9', visual_context='', visual_plan=vp,
        )
        print(f'=== seg_{i:03d} (len={len(p)}) ===')
        print(p[:500])
        print()

asyncio.run(main())
