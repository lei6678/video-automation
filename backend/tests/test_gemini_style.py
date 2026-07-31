"""
Gemini 版 chinese_docu 对比测试 — 正向摄影术语 + 胶片/镜头/画质锚点
与 test_chinese_docu.py 的区别：去掉负面禁令，改用 Gemini 分析报告验证过的 prompt 策略
"""
import asyncio
import base64
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from services.image_service import _generate_fal

# ── Gemini 风格定义（精简/正向/摄影术语） ──

GEMINI_STYLE_BIBLE = (
    "Chinese neorealism documentary photography, "
    "Kodak Portra 400 film stock, 35mm f/2 lens, natural available light, "
    "photorealistic, masterpiece, ultra-high definition, "
    "highly detailed skin texture and fabric weave, "
    "rich environmental detail, subtle authentic film grain, "
    "Magnum Photos aesthetic, genuine unposed documentary moment"
)

GEMINI_STYLE_SUFFIX = (
    ", Chinese documentary neorealism, Kodak Portra 400, 35mm, "
    "natural light, photorealistic, highly detailed skin texture, "
    "masterpiece, Magnum style, authentic moment"
)

GEMINI_PREFIX = "A Magnum-style documentary photograph"

OUTPUT_DIR = Path("D:/gemini_style_test")


async def main():
    # 复用 test_chinese_docu 的输出目录中的 prompt 文件提取场景描述
    chinese_docu_dir = Path("D:/chinese_docu_test")

    sentences = [
        (
            "今年高考，湖北有这么一对双胞胎姐妹，把不少人都看愣了。"
            "清华和北大的招生老师都亲自找上门来了。"
        ),
        (
            "你听清楚了，是清华北大主动来的，多少孩子做梦都想够着的那扇门，"
            "人家把门推开，请她们进去，可这姐妹俩问清楚情况以后，几乎没怎么犹豫，"
            "就把这两所学校给推了。"
        ),
        (
            "我头一回听说这事儿，心里咯噔一下，这得是多大的定力，"
            "才敢在18岁这个年纪，跟清华北大说一声\"不用了\"。"
        ),
    ]

    # 场景描述与分镜数据（来自上次 chinese_docu 测试的 storyboard 输出）
    shots = [
        {
            "visual_subject": "Recruitment teachers",
            "shot_type": "wide",
            "composition": (
                "Exterior of modern apartment building; two teachers in navy suit "
                "and gray blazer approach door with briefcase and brochures; "
                "soft afternoon sun casts long shadows."
            ),
            "emotion": "daily",
        },
        {
            "visual_subject": "Qiu Aoyu and Qiu Aojie, twin sisters",
            "shot_type": "medium",
            "composition": (
                "Living room with wooden bookshelf; two 18-year-old twin sisters "
                "sit on sofa exchanging a knowing glance, sunlight through curtains; "
                "teachers silhouetted in foreground."
            ),
            "emotion": "daily",
        },
        {
            "visual_subject": "object detail — college brochure pushed away",
            "shot_type": "detail",
            "composition": (
                "Extreme close-up: a young woman's hand with simple bracelet gently "
                "pushes a Tsinghua University brochure across a wooden coffee table; "
                "soft light filters through lace curtains."
            ),
            "emotion": "transition",
        },
    ]

    shot_hints = {
        "wide": "wide establishing shot, small figures in context, environmental storytelling",
        "medium": "medium shot, waist-up framing, natural body language, candid interaction",
        "detail": "extreme close-up detail shot, no face, texture focus, hands and objects",
    }

    emotion_light = {
        "daily": (
            "Soft natural daylight, diffuse window light, neutral warm tones, "
            "gentle shadows, quiet afternoon atmosphere"
        ),
        "transition": (
            "Late afternoon golden hour, warm rim light through curtains, "
            "dusty air, contemplative mood, nostalgic atmosphere"
        ),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    test_count = 3

    print("=" * 60)
    print("[Gemini Style] 对比测试 — 正向摄影术语策略")
    print("=" * 60)
    print()
    print("核心改动:")
    print("  [x] 删除所有负面禁令 (no CGI, no 3D, no plastic skin...)")
    print("  [+] Kodak Portra 400 + 35mm f/2 镜头锚点")
    print("  [+] photorealistic, masterpiece, highly detailed")
    print("  [+] Magnum Photos 风格引用")
    print("  [-] 精简 style bible 从 80 词 -> 40 词")
    print()

    results = []
    for i in range(test_count):
        shot = shots[i]
        hint = shot_hints.get(shot["shot_type"], shot_hints["medium"])
        light = emotion_light.get(shot["emotion"], emotion_light["daily"])

        # ── Gemini 式 prompt 结构：简洁/正向/摄影术语 ──
        prompt = (
            f"{GEMINI_PREFIX}, 8:9 vertical, {hint}. "
            f"Subject: {shot['visual_subject']}. "
            f"Scene: {shot['composition']} "
            f"Lighting: {light}. "
            f"Style: {GEMINI_STYLE_BIBLE}"
            f"{GEMINI_STYLE_SUFFIX}"
            f". single image, no text, no watermark"
        )

        print(f"[{i+1}/{test_count}] {shot['visual_subject']} | {shot['shot_type']} | {shot['emotion']}")
        print(f"          Prompt: {len(prompt)} 字符 (旧版 897-896 字符)")
        print(f"          原文: {sentences[i][:60]}...")

        # 保存 prompt 到文件
        prompt_path = OUTPUT_DIR / f"gemini_{i+1:02d}_prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")

        # 调用 Fal.ai
        b64 = await _generate_fal(
            prompt=prompt,
            width=2160,
            height=3840,
            quality="low",
        )

        if b64:
            img_path = OUTPUT_DIR / f"gemini_{i+1:02d}.png"
            img_path.write_bytes(base64.b64decode(b64))
            size_kb = img_path.stat().st_size / 1024
            print(f"          [OK] -> {img_path.name} ({size_kb:.0f} KB)")
            results.append({"index": i + 1, "status": "ok", "path": str(img_path)})
        else:
            print(f"          [FAIL]")
            results.append({"index": i + 1, "status": "failed", "path": None})
        print()

    # ── 对比路径 ──
    print("=" * 60)
    print("对比目录:")
    print(f"  旧版 (负面禁令):  D:\\chinese_docu_test\\")
    print(f"  新版 (Gemini正向): D:\\gemini_style_test\\")
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"\n[OK] {ok}/{test_count} 张成功")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
