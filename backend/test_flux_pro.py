"""Flux-pro 测试：前 5 段 8:9 bench card 配图，对比 flux-dev"""
import asyncio, os, sys, base64, io
sys.path.insert(0, '.')
from services.image_service import (
    plan_visual_arc, build_single_segment_prompt, _generate_fal_flux_pro,
)
from services.llm_service import split_into_short_sentences
from PIL import Image as PILImage

OUT = 'data/tasks/4/images'
with open('data/tasks/4/rewritten.txt', 'r', encoding='utf-8') as f:
    rewritten = f.read()

sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)
print(f'{len(rewritten)} chars, {len(sentences)} segments')

REQ_W, REQ_H = 1080, 1216
TGT_W, TGT_H = 1080, 1214


async def main():
    vp = await plan_visual_arc(
        rewritten_transcript=rewritten,
        book_title='', book_author='', visual_context='',
        style='documentary_realism', total_segments=len(sentences),
        sentences=sentences,
    )
    if not vp:
        print('plan_visual_arc FAILED')
        return

    print(f"Protagonist: {vp.get('protagonist','')[:120]}...")
    scenes = vp.get('scenes', [])
    for i in range(min(5, len(scenes))):
        entry = scenes[i]
        if isinstance(entry, dict):
            print(f"  [{i}] emotion={entry.get('emotion','?')} scene={entry.get('scene','')[:100]}...")
        else:
            print(f"  [{i}] {str(entry)[:100]}")

    for i in range(5):
        prompt = build_single_segment_prompt(
            text=sentences[i], segment_index=i, total_segments=len(sentences),
            style_bible='', aspect_ratio='8:9', visual_context='', visual_plan=vp,
        )
        print(f'\n=== seg_{i:03d}_fluxpro ({len(prompt)} chars) ===')
        print(prompt[:400])
        print()

        b64 = await _generate_fal_flux_pro(prompt, width=REQ_W, height=REQ_H)
        if b64:
            img_bytes = base64.b64decode(b64)
            pil_img = PILImage.open(io.BytesIO(img_bytes)).convert("RGB")
            actual_w, actual_h = pil_img.size
            print(f"Flux Pro 原始尺寸: {actual_w}x{actual_h}")

            if (actual_w, actual_h) != (TGT_W, TGT_H):
                pil_img = pil_img.resize((TGT_W, TGT_H), PILImage.LANCZOS)
                print(f"缩图: {actual_w}x{actual_h} → {TGT_W}x{TGT_H}")

            path = os.path.join(OUT, f'seg_{i:03d}_fluxpro.png')
            pil_img.save(path, "PNG", optimize=True)
            pil_img.close()
            print(f'OK: seg_{i:03d}_fluxpro.png ({os.path.getsize(path)} bytes)')
        else:
            print('FAILED')


asyncio.run(main())
