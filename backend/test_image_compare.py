"""
新旧 Prompt 生图对比测试
- Seg 4: 王人美被改名（1930年代上海美美女校场景）
- Seg 10: 被诬陷进疯人院（1952年精神崩溃场景）
"""
import asyncio, os, sys, json, base64
sys.path.insert(0, '.')
from services.image_service import (
    plan_visual_arc, build_single_segment_prompt,
    STYLE_BIBLES, STYLE_PROMPT_MAP, SAFETY_SUFFIX,
    _generate_fal, FAL_QUALITY,
)
from services.llm_service import split_into_short_sentences

OUT_DIR = 'data/tasks/4/images'
os.makedirs(OUT_DIR, exist_ok=True)

with open('data/tasks/4/rewritten.txt', 'r', encoding='utf-8') as f:
    rewritten = f.read()

sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)
print(f'文案: {len(rewritten)} 字, {len(sentences)} 分镜')

# 选 2 个代表性段落对比
TEST_SEGMENTS = [4, 10]  # 4=改名场景, 10=疯人院段落

async def main():
    # Step 1: 获取全局视觉规划
    vp = await plan_visual_arc(
        rewritten_transcript=rewritten,
        book_title='', book_author='', visual_context='',
        style='documentary_realism', total_segments=len(sentences),
    )
    if not vp:
        print('plan_visual_arc FAILED')
        return

    # Step 2: 对每个测试段，分别构建新旧 prompt 并生图
    for seg_idx in TEST_SEGMENTS:
        text = sentences[seg_idx]
        print(f'\n{"="*60}')
        print(f'Segment {seg_idx}: {text[:80]}...')
        print(f'{"="*60}')

        # --- New prompt (v5) ---
        new_prompt = build_single_segment_prompt(
            text=text, segment_index=seg_idx, total_segments=len(sentences),
            style_bible=STYLE_BIBLES.get('documentary_realism', ''),
            aspect_ratio='8:9', visual_context='', visual_plan=vp,
        )
        # Append safety + style suffix
        style_suffix = STYLE_PROMPT_MAP.get('documentary_realism', '')
        new_prompt_full = new_prompt + style_suffix + SAFETY_SUFFIX
        print(f'\n[NEW prompt] ({len(new_prompt_full)} chars):')
        print(new_prompt_full[:300] + '...')

        # --- Old prompt (v4 template, no visual_plan) ---
        old_prompt = build_single_segment_prompt(
            text=text, segment_index=seg_idx, total_segments=len(sentences),
            style_bible=STYLE_BIBLES.get('documentary_realism', ''),
            aspect_ratio='8:9', visual_context='', visual_plan=None,
        )
        old_prompt_full = old_prompt + style_suffix + SAFETY_SUFFIX
        print(f'\n[OLD prompt] ({len(old_prompt_full)} chars):')
        print(old_prompt_full[:300] + '...')

        # --- Generate with Fal.ai ---
        # 8:9 bench card at 4x oversampling: 2160x2432 → 1080x1214
        W, H = 1080, 1214
        print(f'\n--- Generating NEW image {W}x{H} quality={FAL_QUALITY} ---')
        new_img_b64 = await _generate_fal(new_prompt_full, width=W, height=H, quality=FAL_QUALITY)

        print(f'\n--- Generating OLD image {W}x{H} quality={FAL_QUALITY} ---')
        old_img_b64 = await _generate_fal(old_prompt_full, width=W, height=H, quality=FAL_QUALITY)

        # Save
        if new_img_b64:
            new_path = os.path.join(OUT_DIR, f'seg_{seg_idx:03d}_v5_new.png')
            with open(new_path, 'wb') as f:
                f.write(base64.b64decode(new_img_b64))
            print(f'NEW saved: {new_path}')
        else:
            print('NEW generation FAILED')

        if old_img_b64:
            old_path = os.path.join(OUT_DIR, f'seg_{seg_idx:03d}_v4_old.png')
            with open(old_path, 'wb') as f:
                f.write(base64.b64decode(old_img_b64))
            print(f'OLD saved: {old_path}')
        else:
            print('OLD generation FAILED')

        # Save prompts for reference
        with open(os.path.join(OUT_DIR, f'seg_{seg_idx:03d}_v5_new_prompt.txt'), 'w', encoding='utf-8') as f:
            f.write(new_prompt_full)
        with open(os.path.join(OUT_DIR, f'seg_{seg_idx:03d}_v4_old_prompt.txt'), 'w', encoding='utf-8') as f:
            f.write(old_prompt_full)

    print('\nDone!')

asyncio.run(main())
