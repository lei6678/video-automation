"""
测试脚本：chinese_docu 风格生图验证（前 3 张）
完整链路：视觉档案 → 剧本 → 分镜 → 生图（与生产环境一致）
用法：python backend/tests/test_chinese_docu.py <文案文件路径>
"""
import asyncio
import os
import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from services.llm_service import split_into_short_sentences, extract_visual_context
from services.image_service import (
    generate_screenplay, generate_storyboard, build_single_segment_prompt,
    _generate_fal, STYLE_BIBLES, STYLE_PROMPT_MAP, _sanitize_prompt,
)

STYLE_KEY = "chinese_docu"
OUTPUT_DIR = Path("D:/chinese_docu_test")


async def main():
    print("=" * 60)
    print(f"[{STYLE_KEY}] 风格生图测试（完整链路）")
    print("=" * 60)
    print()

    # ── 读取文案 ──
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        text = Path(file_path).read_text(encoding="utf-8").strip()
        print(f"[file] 从文件读取: {file_path}")
    else:
        print("用法: python test_chinese_docu.py <文案文件路径>")
        return

    if not text:
        print("[FAIL] 文件为空，退出。")
        return

    print(f"[text] 文案 {len(text)} 字\n")

    # ── 切句 ──
    sentences = split_into_short_sentences(text, max_chars=80, min_chars=30)
    total = len(sentences)
    print(f"[cut] 切分为 {total} 句\n")

    style_bible = STYLE_BIBLES[STYLE_KEY]

    # ── Pass 0: 视觉档案提取 ──
    print("─" * 40)
    print("[search] Step 1/4: 提取视觉档案（DeepSeek）...")
    try:
        visual_context = await extract_visual_context(text)
        if visual_context.strip():
            print(f"   [OK] 视觉档案 ({len(visual_context)} 字)")
            print(f"   {visual_context[:200]}...")
        else:
            print("   [WARN] 视觉档案为空，继续")
    except Exception as e:
        print(f"   [FAIL] 失败: {e}")
        visual_context = ""
    print()

    # ── Pass 0.5a: 剧本生成 ──
    print("─" * 40)
    print("[screenplay] Step 2/4: 剧本生成（DeepSeek）...")
    screenplay = await generate_screenplay(
        rewritten_transcript=text,
        visual_context=visual_context,
        style=STYLE_KEY,
        total_segments=total,
        sentences=sentences,
    )
    if not screenplay:
        print("   [FAIL] 剧本生成失败，退出。")
        return
    cast_count = len(screenplay.get("character_cast", []))
    scene_count = len(screenplay.get("scenes", []))
    # 兜底：DeepSeek 偶尔丢角色表，从 visual_context 解析补上
    if cast_count == 0 and visual_context.strip():
        from services.image_service import _parse_visual_context_fallback
        fallback_cast = _parse_visual_context_fallback(visual_context)
        if fallback_cast:
            screenplay["character_cast"] = fallback_cast
            cast_count = len(fallback_cast)
            print(f"   [WARN] 剧本角色表为空 → 已用 visual_context 兜底: {cast_count} 角色")
    print(f"   [OK] {cast_count} 角色, {scene_count} 场景")
    print()

    # ── Pass 0.5b: 分镜脚本 ──
    print("─" * 40)
    print("[storyboard] Step 3/4: 分镜脚本（DeepSeek）...")
    storyboard = await generate_storyboard(
        screenplay=screenplay,
        sentences=sentences,
        visual_context=visual_context,
        total_segments=total,
    )
    if not storyboard:
        print("   [FAIL] 分镜脚本生成失败，退出。")
        return
    storyboard["face_policy"] = screenplay.get("face_policy", "show")
    storyboard["character_cast"] = screenplay.get("character_cast", [])
    shot_count = len(storyboard.get("shots", []))
    print(f"   [OK] {shot_count} 镜")
    print()

    # ── 生图：仅前 3 张 ──
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    test_count = min(3, total)
    print("─" * 40)
    print(f"[images]  Step 4/4: 生图（Fal.ai，前 {test_count} 张，预计 ~${test_count * 0.012:.3f}）\n")

    results = []
    for seg_idx in range(test_count):
        sentence = sentences[seg_idx]

        # 构建 prompt（完整生产路径）
        prompt = build_single_segment_prompt(
            text=sentence,
            book_title="",
            book_author="",
            segment_index=seg_idx,
            total_segments=total,
            style_bible=style_bible,
            style_key=STYLE_KEY,
            aspect_ratio="9:16",
            visual_context=visual_context,
            storyboard=storyboard,
        )

        if not prompt:
            print(f"   [{seg_idx + 1}/{test_count}] [WARN] 分镜数据不足，跳过")
            results.append({"index": seg_idx + 1, "status": "skipped", "path": None})
            continue

        # 保存 prompt
        prompt_path = OUTPUT_DIR / f"test_{seg_idx + 1:02d}_prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")

        # 打印分镜信息
        shot = storyboard["shots"][seg_idx] if seg_idx < shot_count else {}
        print(f"[{seg_idx + 1}/{test_count}] 原文: {sentence[:60]}...")
        print(f"           主体: {shot.get('visual_subject', '?')}")
        print(f"           景别: {shot.get('shot_type', '?')}")
        print(f"           情绪: {shot.get('emotion', '?')}")
        print(f"           Prompt ({len(prompt)} 字符) → {prompt_path.name}")

        # 调用 Fal.ai
        b64 = await _generate_fal(
            prompt=prompt,
            width=2160,
            height=3840,
            quality="low",
        )

        if b64:
            img_path = OUTPUT_DIR / f"test_{seg_idx + 1:02d}.png"
            img_path.write_bytes(base64.b64decode(b64))
            size_kb = img_path.stat().st_size / 1024
            print(f"           [OK] 成功 → {img_path.name} ({size_kb:.0f} KB)")
            results.append({"index": seg_idx + 1, "status": "ok", "path": str(img_path)})
        else:
            print(f"           [FAIL] 失败")
            results.append({"index": seg_idx + 1, "status": "failed", "path": None})
        print()

    # ── 汇总 ──
    print("=" * 60)
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"[OK] {ok}/{test_count} 张成功")
    for r in results:
        icon = {"ok": "[OK]", "failed": "[FAIL]", "skipped": "[WARN]"}.get(r["status"], "?")
        print(f"  {icon} 第{r['index']}张: {r['path'] or 'N/A'}")
    print(f"\n[dir] 所有文件: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
