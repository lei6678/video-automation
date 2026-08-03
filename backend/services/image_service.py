"""
配图生成服务 — Fal.ai gpt-image-2 主 · 可灵备 — v5
================================================
1. LLM 通读全文 → 规划全局视觉弧线 + 逐段画面 Prompt（plan_visual_arc）
2. 混合 Prompt：中文文化场景 + 英文视觉词汇 → Fal.ai 单图直生
3. 4x 超采样（2160×2432 → 1080×1214 LANCZOS），quality="medium"
4. 多通道降级：Fal → 降敏 Fal → Keling → 通用兜底
5. 写入 TaskImage 表

成本: 1 次 DeepSeek（~1美分） + N×Fal.ai（~0.5美分/张）
"""

import asyncio
import base64
import json
import os
import re
import time
from typing import Optional
from _resource import get_data_dir

import httpx
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

# ============== 凭证 ==============
FAL_KEY = os.getenv("FAL_KEY", "")
FAL_QUALITY = os.getenv("FAL_QUALITY", "low")  # low | medium | high，默认 low（成本控制）
FAL_MODEL = "openai/gpt-image-2"


# ============== 样式圣经库（来自大佬白皮书）==============

# ============== 视觉风格配方（v5：中文文化场景 + 英文视觉词汇）==============

STYLE_BIBLES = {
    "default": (
        "cinematic realism, natural window lighting, soft diffused shadows, "
        "warm whites + muted wood tones + dusty blues, 35mm/50mm prime lens, "
        "shallow depth of field, clean composition, editorial photography, "
        "ordinary people in quiet moments, backs and profiles preferred, "
        "film grain subtle, Kodak Portra color palette"
    ),
    "warm_book": (
        "warm golden hour sunlight through windows, cream + amber tones, "
        "soft focus, cozy reading nook atmosphere, vintage film camera aesthetic, "
        "bookshelf corner, teacup, green plants, handwritten notes, "
        "afternoon stillness, gentle bokeh, 85mm portrait lens"
    ),
    "clean_health": (
        "bright morning daylight, white + light wood dominant, "
        "clean minimal composition, positive calm energy, "
        "kitchen prep, morning jog silhouette, park bench, water glass close-up, "
        "commercial lifestyle photography, airy spacious feel, no medical aesthetic"
    ),
    "philosophy": (
        "wide angle distant view, small figure in vast landscape or city, "
        "cool-warm color contrast, generous negative space, breathing room, "
        "solitary walk on coastline, mountain summit vista, rooftop at dusk, empty library, "
        "contemplative depth, Terrence Malick golden hour, anamorphic lens feel"
    ),
    "documentary_realism": (
        "cinematic neorealism, atmospheric natural light through windows and doorways, "
        "warm earth tones + faded sage greens + dusty rose, "
        "intimate handheld composition, shallow depth of field on faces and hands, "
        "aged textures — weathered wood, peeling paint, worn fabric — beautiful in their decay, "
        "ordinary people in quiet moments of dignity, "
        "inspired by Wong Kar-wai and Zhang Yimou's early works"
    ),
    "wong_kar_wai": (
        "Wong Kar-wai cinematic aesthetic, rain-soaked neon streets, saturated reds and greens, "
        "slow shutter drag with motion blur, step-printing rhythm, "
        "intimate close-ups, shallow focus, 85mm portrait lens, "
        "nostalgic 1960s Hong Kong atmosphere, rich film grain, "
        "high contrast chiaroscuro, dreamlike color wash, "
        "solitary figures in crowded spaces, emotional texture over plot"
    ),
    "warm_docu": (
        "warm natural tones throughout, consistent cohesive color palette, "
        "soft daylight, gentle shadows, no dramatic color shifts, "
        "documentary photography, editorial magazine composition, "
        "ordinary people in authentic unposed moments, clean composition, "
        "warm browns + muted amber + soft cream, natural textures, "
        "medium format film look, honest and grounded aesthetic"
    ),
    "chinese_docu": (
        "Steve McCurry photographic style, cinematic sharpness, ultra-high definition, "
        "full-frame DSLR photography, Canon EOS 5D Mark IV, 35mm f/1.4 prime lens, "
        "shallow depth of field, natural window light, soft ambient shadows, "
        "neutral white balance, true-to-life colors, "
        "highly detailed, photorealistic, masterpiece, "
        "ordinary Chinese people in everyday unposed moments, "
        "real environments: homes, streets, schools, markets, workplaces"
    ),
}

# ============== 风格后缀（v5：英文视觉修饰词，注入 Fal.ai prompt）==============

STYLE_PROMPT_MAP = {
    "default": (
        ", cinematic lighting, photorealistic, 35mm prime lens, "
        "shallow depth of field, Kodak Portra 400 color, film grain subtle"
    ),
    "warm_book": (
        ", warm pastel colors, soft morning sunlight, cozy atmosphere, "
        "golden hour glow, cream and amber palette, vintage film aesthetic"
    ),
    "clean_health": (
        ", bright natural daylight, clean minimal composition, "
        "vibrant yet natural colors, commercial lifestyle photography, airy spacious"
    ),
    "philosophy": (
        ", moody dramatic lighting, melancholic low key, surrealism texture, "
        "wide landscape scale, anamorphic lens feel, contemplative atmosphere"
    ),
    "documentary_realism": (
        ", cinematic photography, atmospheric lighting, rich textures, "
        "award-winning composition, elegant, timeless"
    ),
    "wong_kar_wai": (
        ", Wong Kar-wai film aesthetic, 85mm lens, shallow depth of field, "
        "beautiful bokeh, photorealistic, ultra-high definition, masterpiece, "
        "highly detailed skin texture, rich cinematic contrast, "
        "nostalgic retro film aesthetic"
    ),
    "warm_docu": (
        ", warm natural tones, consistent cohesive color palette, "
        "soft daylight, gentle shadows, documentary photography style, "
        "editorial composition, authentic unposed feel, "
        "medium format film, honest and grounded aesthetic"
    ),
    "chinese_docu": (
        ", Steve McCurry portrait style, Canon 5D Mark IV, 35mm f/1.4, "
        "natural window light, neutral colors, shallow depth of field, "
        "ultra-high definition, cinematic sharpness, photorealistic, highly detailed"
    ),
}

# ============== 画面后置防线 ==============

SAFETY_SUFFIX = (
    ", single image, no collage, no multi-panel, no grid, "
    "highly detailed, natural skin texture, no duplicate faces, "
    "masterpiece composition, no text, no watermark, no graphic overlay"
)

# ============== 王家卫电影感（v10：从全局锁改为可选风格）==============

# ============== v7 情绪光影字典（对标题 Gemini 分析报告3）==============

EMOTION_LIGHTING = {
    "glory": (
        "natural daylight, soft directional light, bright even exposure, "
        "realistic colors, natural shallow depth of field, unposed genuine atmosphere"
    ),
    "tragedy": (
        "natural daylight, soft directional light, bright even exposure, "
        "realistic colors, natural shallow depth of field, unposed genuine atmosphere"
    ),
    "transition": (
        "natural daylight, soft directional light, bright even exposure, "
        "realistic colors, natural shallow depth of field, unposed genuine atmosphere"
    ),
    "daily": (
        "natural daylight, soft directional light, bright even exposure, "
        "realistic colors, natural shallow depth of field, unposed genuine atmosphere"
    ),
}

def get_emotion_lighting(emotion: str) -> str:
    """根据情绪标签返回对应的光影描述。"""
    return EMOTION_LIGHTING.get(emotion, EMOTION_LIGHTING["daily"])

async def plan_visual_arc(
    rewritten_transcript: str,
    book_title: str = "",
    book_author: str = "",
    visual_context: str = "",
    style: str = "default",
    total_segments: int = 1,
    sentences: list = None,
    gender: str = "auto",
) -> dict:
    """
    [DEPRECATED v8] Use generate_screenplay() + generate_storyboard() instead.

    v5 核心：LLM 通读全文 → 输出全局视觉方向（单次 API，短平快）。
    sentences: 预切分好的文案列表，用于生成带编号的分段提示。

    保留此函数仅作为 v8 screenplay/storyboard pipeline 的降级回退。
    """
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not deepseek_key:
        print("[image:plan] DEEPSEEK_API_KEY not set, skip")
        return {}

    system_prompt = (
        "You are a cinematographer directing a BIOGRAPHY film. "
        "Determine the protagonist's gender STRICTLY from the text (look for 他/她/he/she/man/woman/boy/girl). "
        "Never default to any gender. The examples in this prompt are format references ONLY — "
        "always extract the ACTUAL gender from the story. "
        + (f"OVERRIDE: protagonist gender is {gender}. Ignore text cues, use this gender for all outputs. " if gender in ("male", "female") else "") +
        "The story has {total} numbered segments. Output JSON. ALL text in ENGLISH.\n\n"
        "=== FACE POLICY (IMPORTANT — classify by public recognizability) ===\n"
        "The ONLY question: does the audience KNOW what this person looks like?\n"
        '- "show": protagonist is NOT a publicly-recognized figure. '
        "No famous portrait exists in the public mind. This includes:\n"
        "  · Ordinary people, unknown individuals, private citizens\n"
        "  · Fictional characters from novels/stories\n"
        "  · Ancient/historical figures with no widely-known portraits\n"
        "  · Anyone the audience has no pre-existing mental image of\n"
        "  → Normal portraiture, facial features, expressions, eye contact all OK.\n"
        '- "avoid": protagonist IS a publicly-recognized figure whose face the '
        "audience KNOWS. AI CANNOT replicate this face accurately. This includes:\n"
        "  · Celebrities, public figures, politicians, national leaders\n"
        "  · Famous historical figures with widely-known photographs/portraits\n"
        "  · Anyone whose face would trigger 'that doesn't look like them'\n"
        "  → NEVER show a clear frontal face. Face <15% of frame. Use instead:\n"
        "  · Back view (seen from behind, facing away)\n"
        "  · Side profile with face turned away or obscured\n"
        "  · Silhouette against window/light/sunset\n"
        "  · Hands, gestures, body language close-ups (face out of frame)\n"
        "  · Environmental wide shots where figure is small and distant\n"
        "  · Over-the-shoulder or partial frame (only back of head visible)\n"
        "Rule of thumb: if you had to Google this person's face, "
        "they're 'show'. If their face is on magazine covers, they're 'avoid'.\n\n"
        "=== EMOTION LIGHTING DICTIONARY (match each scene to one) ===\n"
        "1. glory (peak fame, success, joy): warm amber gold, bright marquee lights, high contrast\n"
        "2. tragedy (death, betrayal, persecution, asylum): cold cyan grey, desaturated, overcast, deep shadows\n"
        "3. transition (fleeing, journey, uncertainty): golden hour, sunset silhouette, rim light\n"
        "4. daily (learning, ordinary life): soft natural light, diffuse, neutral palette\n\n"
        "=== OUTPUT KEYS ===\n"
        '- "face_policy": "show" or "avoid" — see FACE POLICY above.\n'
        '- "protagonist": fixed character reference for EVERY image. '
        "Describe gender, age range, key physical traits (hairstyle, typical clothing, body type). "
        "20-30 words. Example (gender from text, NOT a default): "
        "'a person in their 20s, short hair, simple cotton shirt, lean build'.\n"
        '- "scenes": array of {total} objects, each with:\n'
        '   - "emotion": one of [glory, tragedy, transition, daily]\n'
        '   - "scene": DETAILED English visual description, 15-30 words. '
        "MUST include: specific costume, specific prop or setting detail, "
        "specific lighting source. Be VIVID — NOT 'person in room' but "
        "'a figure in a worn denim jacket, leaning against a graffiti-covered wall, "
        "golden hour light slicing through a narrow alley in Shenzhen'. "
        "IMPORTANT: describe the SCENE and ACTION, never describe the face.\n"
        '- "era_notes": atmosphere in Chinese, 20-40 words (for reference only)\n'
        "SAFETY: no deathbeds, no graves, no blood, no crying faces. "
        "Use poetic distance: an empty chair, light through a window, a silhouette.\n"
        "Output pure JSON, no markdown."
    ).replace("{total}", str(total_segments))

    context_block = ""
    if visual_context.strip():
        context_block = (
            f"\nCHARACTER PROFILE (use this for the 'protagonist' key):\n"
            f"{visual_context.strip()}\n"
        )

    # 构建带编号的分段列表，确保 scenes[i] 对应 segment[i]
    if sentences and len(sentences) == total_segments:
        numbered = "\n".join(
            f"[{i}] {s}" for i, s in enumerate(sentences)
        )
        story_block = (
            f"=== SEGMENTED STORY ({total_segments} segments) ===\n"
            f"Each [N] below corresponds to scenes[N] in your output.\n"
            f"scenes[i] MUST visually reflect the content of segment [i].\n\n"
            f"{numbered}\n=== END ==="
        )
    else:
        story_block = (
            f"=== STORY ===\n{rewritten_transcript.strip()}\n=== END ==="
        )

    user_prompt = (
        f"Title: {book_title or 'N/A'}\nAuthor: {book_author or 'N/A'}\n"
        f"Style: {style}\nSegments: {total_segments}\n"
        f"{context_block}\n"
        f"{story_block}\n"
        f"Output the JSON now."
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as http:
            resp = await http.post(
                "https://api.deepseek.com/v1/chat/completions",
                json={
                    "model": "deepseek-v4-pro",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 16384,
                    "response_format": {"type": "json_object"},
                },
                headers={
                    "Authorization": f"Bearer {deepseek_key}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                finish_reason = data["choices"][0].get("finish_reason", "unknown")
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rstrip("```").strip()
                plan = json.loads(content)
                gs = plan.get("global_style", "")
                print(f"[image:plan] OK — style={len(gs)}chars, keys={list(plan.keys())}")
                return plan
            else:
                print(f"[image:plan] API error {resp.status_code}: {resp.text[:200]}")
                return {}
    except Exception as e:
        print(f"[image:plan] Failed: {type(e).__name__}: {e}")
        finish_info = ""
        try:
            finish_info = f"finish_reason={finish_reason}"
        except Exception:
            finish_info = "finish_reason=N/A"
        content_info = ""
        try:
            content_info = f"len={len(content)}, tail={content[-200:]}"
        except Exception:
            content_info = "content=N/A"
        print(f"[image:plan] {finish_info}, {content_info}")
        return {}


def _repair_json(text: str) -> str:
    """修复 LLM 输出的常见 JSON 格式错误（缺逗号、尾逗号）。"""
    import re as _re
    # 1. 去除尾逗号：",}" → "}", ",]" → "]"
    text = _re.sub(r',\s*}', '}', text)
    text = _re.sub(r',\s*]', ']', text)
    # 2. 补缺逗号："}\n{" → "},\n{"（数组中对象之间）
    text = _re.sub(r'\}\s*\n\s*\{', '},\n{', text)
    # 3. 补缺逗号："]\n{" → "],\n{"
    text = _re.sub(r'\]\s*\n\s*\{', '],\n{', text)
    # 4. 补缺逗号：'"\n"key" → '",\n"key"（对象属性之间）
    text = _re.sub(r'"\s*\n\s*"', '",\n"', text)
    # 5. 补缺逗号：数字/true/false/null 后缺逗号接下一行 "
    text = _re.sub(r'(\d)\s*\n\s*"', r'\1,\n"', text)
    text = _re.sub(r'(true|false|null)\s*\n\s*"', r'\1,\n"', text)
    return text


async def generate_screenplay(
    rewritten_transcript: str,
    book_title: str = "",
    book_author: str = "",
    visual_context: str = "",
    style: str = "default",
    total_segments: int = 1,
    sentences: list = None,
    gender: str = "auto",
) -> dict:
    """
    v8 Step 0: 剧本生成 — LLM 通读全文 → 全角色档案 + 场景列表。

    替代旧版 plan_visual_arc 的单 protagonist 模式。
    输出 character_cast（所有角色）+ scenes（每段场景描述+在场角色）。
    """
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not deepseek_key:
        print("[image:screenplay] DEEPSEEK_API_KEY not set, skip")
        return {}

    system_prompt = (
        "You are a screenwriter and casting director adapting a story for film. "
        "Your job: read the full script, identify ALL characters, and break it into scenes.\n\n"
        + (f"OVERRIDE: protagonist gender is {gender}. Use this for the main character. " if gender in ("male", "female") else "") +
        "The story has {total} numbered segments. Output JSON. ALL text in ENGLISH.\n\n"
        "=== FACE POLICY (same as before) ===\n"
        "Classify by public recognizability:\n"
        '- "show": protagonist is NOT a publicly-recognized figure (ordinary person, fictional character, '
        "historical figure with no widely-known portrait). Normal portraiture OK.\n"
        '- "avoid": protagonist IS a publicly-recognized figure (celebrity, politician, famous face). '
        "NEVER show a clear frontal face. Use back view, silhouette, hands, environmental wide shots.\n\n"
        "=== DIRECTOR'S MANDATE (4 principles — EVERY scene MUST follow) ===\n"
        "1. AGE TIMELINE: If a character appears at multiple ages (young → old, or via flashback),\n"
        "   create SEPARATE cast entries: 'young Li Dacheng (age 27)' and 'older Li Dacheng (age 42)'.\n"
        "   Each version gets its OWN appearance/clothing/body_type. Never describe both ages in one entry.\n"
        "   scenes[i] MUST reference the CORRECT version based on the segment's time period.\n\n"
        "2. ERA MARKERS: Every scene MUST include era-specific visual anchors in scene_desc.\n"
        "   Flashback to 1985 rural China → mud-brick houses,自行车 (bicycles), blue Mao suits, kerosene lamps.\n"
        "   Present day 2024 city → glass buildings, smartphones, casual modern clothing.\n"
        "   Without era markers, ALL images look like 'present day'. Make time VISIBLE.\n\n"
        "3. SIGNATURE PROPS: Identify 1-2 objects that can appear across multiple scenes\n"
        "   (a crumpled letter, an old palm-leaf fan, a worn fountain pen, a jade bracelet).\n"
        "   When the same prop reappears, describe it with the SAME visual details.\n"
        "   Props externalize emotion — use them intentionally.\n\n"
        "4. LOCATION CONTINUITY: If the same place appears in multiple scenes (e.g. 'the old house'),\n"
        "   anchor it with FIXED visual elements EVERY time: 'the red-painted wooden door',\n"
        "   'the jujube tree in the courtyard', 'the crack running down the south wall'.\n"
        "   The viewer must recognize it as the SAME place across shots.\n\n"
        "=== CHARACTER CAST ===\n"
        "List EVERY named or recurring character. For each:\n"
        "- name: character name with age version if applicable (e.g. 'young Li Dacheng' vs 'older Li Dacheng')\n"
        "- gender: 'male' | 'female'\n"
        "- age: specific age or range (e.g. '27', '65-70', '8-10')\n"
        "- appearance: key physical traits — hairstyle, facial features, skin tone, distinguishing marks (15-25 words). "
        "NEVER write 'unknown' — INFER from role, era, and context. A 70-year-old rural man has gray hair and wrinkles. "
        "A 42-year-old businessman has a crisp haircut and a slight belly. If the text doesn't say, USE COMMON SENSE.\n"
        "- clothing: typical outfit, fabric, colors (10-15 words). Infer from identity: worker→rough overalls, "
        "official→dark Zhongshan suit, businessman→tailored suit. NEVER 'unknown'.\n"
        "- body_type: build, posture, height, any disability (5-10 words). Infer from age and lifestyle. NEVER 'unknown'.\n"
        "- role: 'protagonist' | 'supporting' | 'minor'\n"
        "IMPORTANT: extract characters from BOTH the provided CHARACTER PROFILES and the story text. "
        "If the character profiles already describe someone, use those details faithfully. "
        "If the story mentions a character NOT in the profiles, create a profile from text clues + reasonable inference.\n"
        "CRITICAL: character_cast MUST NOT be empty if the story contains ANY human characters. "
        "An empty array `[]` is NEVER correct for stories about real people. "
        "If characters_present in scenes references a name, that name MUST have a cast entry. "
        "Every named person in the story = one cast entry. No exceptions.\n\n"
        "=== SCENES ===\n"
        "For each of the {total} segments, describe:\n"
        "- emotion: one of [glory, tragedy, transition, daily]\n"
        "- scene_desc: DETAILED English visual description, 15-30 words. MUST include: specific costume, "
        "era marker (time-appropriate object/technology), lighting source. Be VIVID.\n"
        "- characters_present: list of character names (use EXACT age-version name from cast) who appear. "
        "Can be empty for environment-only scenes.\n"
        "- location: where this scene takes place. If recurring location, use SAME location name + SAME anchor elements.\n"
        "- time: time of day / season / specific year or era cue (e.g. 'summer 1985, dusk', 'present day, morning')\n\n"
        "=== EMOTION LIGHTING DICTIONARY ===\n"
        "1. glory (peak fame, success, joy): warm amber gold, bright marquee lights, high contrast\n"
        "2. tragedy (death, betrayal, persecution): cold cyan grey, desaturated, overcast, deep shadows\n"
        "3. transition (journey, uncertainty, fleeing): golden hour, sunset silhouette, rim light\n"
        "4. daily (learning, ordinary life): soft natural light, diffuse, neutral palette\n\n"
        "SAFETY: no deathbeds, no graves, no blood, no crying faces. "
        "Use poetic distance: an empty chair, light through a window, a silhouette.\n"
        "REMINDER: character_cast array must not be empty. Minimum 1 entry for any story with human subjects. "
        "Output pure JSON, no markdown."
    ).replace("{total}", str(total_segments))

    context_block = ""
    if visual_context.strip():
        context_block = (
            f"\nCHARACTER PROFILES (extracted from text — use these details faithfully):\n"
            f"{visual_context.strip()}\n"
        )

    if sentences and len(sentences) == total_segments:
        numbered = "\n".join(
            f"[{i}] {s}" for i, s in enumerate(sentences)
        )
        story_block = (
            f"=== SEGMENTED STORY ({total_segments} segments) ===\n"
            f"Each [N] below corresponds to scenes[N] in your output.\n"
            f"scenes[i] MUST visually reflect the content of segment [i].\n\n"
            f"{numbered}\n=== END ==="
        )
    else:
        story_block = (
            f"=== STORY ===\n{rewritten_transcript.strip()}\n=== END ==="
        )

    user_prompt = (
        f"Title: {book_title or 'N/A'}\nAuthor: {book_author or 'N/A'}\n"
        f"Style: {style}\nSegments: {total_segments}\n"
        f"{context_block}\n"
        f"{story_block}\n"
        f"Output the JSON now."
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as http:
            resp = await http.post(
                "https://api.deepseek.com/v1/chat/completions",
                json={
                    "model": "deepseek-v4-pro",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 32768,
                    "response_format": {"type": "json_object"},
                },
                headers={
                    "Authorization": f"Bearer {deepseek_key}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                finish_reason = data["choices"][0].get("finish_reason", "unknown")
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rstrip("```").strip()
                try:
                    screenplay = json.loads(content)
                except json.JSONDecodeError:
                    repaired = _repair_json(content)
                    screenplay = json.loads(repaired)
                    print("[image:screenplay] JSON repaired successfully")
                cast_count = len(screenplay.get("character_cast", []))
                scene_count = len(screenplay.get("scenes", []))
                print(f"[image:screenplay] OK — {cast_count} characters, {scene_count} scenes")
                return screenplay
            else:
                print(f"[image:screenplay] API error {resp.status_code}: {resp.text[:200]}")
                return {}
    except Exception as e:
        print(f"[image:screenplay] Failed: {type(e).__name__}: {e}")
        finish_info = ""
        try:
            finish_info = f"finish_reason={finish_reason}"
        except Exception:
            finish_info = "finish_reason=N/A"
        content_info = ""
        try:
            content_info = f"len={len(content)}, tail={content[-200:]}"
        except Exception:
            content_info = "content=N/A"
        print(f"[image:screenplay] {finish_info}, {content_info}")
        return {}


async def generate_storyboard(
    screenplay: dict,
    sentences: list,
    visual_context: str = "",
    total_segments: int = 1,
) -> dict:
    """
    v8 Step 1: 分镜脚本 — 基于剧本生成逐镜拍摄方案。

    输入 screenplay（角色表+场景列表），输出每镜的 visual_subject、
    shot_type、composition、emotion、character_ref。
    核心变化：visual_subject 不再总是主角，而是根据每段内容灵活选择。
    """
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not deepseek_key:
        print("[image:storyboard] DEEPSEEK_API_KEY not set, skip")
        return {}

    character_cast = screenplay.get("character_cast", [])
    scenes = screenplay.get("scenes", [])
    face_policy = screenplay.get("face_policy", "show")

    # 构建角色速查表
    cast_summary = ""
    for c in character_cast:
        cast_summary += (
            f"- {c.get('name', '?')}: {c.get('gender', '?')}, {c.get('age', '?')}, "
            f"{c.get('appearance', '?')}. Clothing: {c.get('clothing', '?')}. "
            f"Body: {c.get('body_type', '?')}. Role: {c.get('role', '?')}\n"
        )

    _face_rules = {
        "show": "",
        "avoid": "FACE RULE: NEVER show a clear frontal face of the protagonist. "
                 "Use back view, side profile with face turned away, silhouette, "
                 "hands/body close-ups (face out of frame), environmental wide shots "
                 "where figure is small and distant, or over-the-shoulder (only back of head visible). ",
    }
    face_rule = _face_rules.get(face_policy, "")

    system_prompt = (
        "You are a director of photography creating a shot-by-shot storyboard. "
        "Given a screenplay with character profiles and scene descriptions, "
        "decide the VISUAL APPROACH for each segment.\n\n"
        "=== YOUR TASK ===\n"
        "For each of the {total} segments, specify WHO or WHAT is on screen, "
        "the camera distance, and the exact visual composition.\n\n"
        "=== SHOT TYPE GUIDE ===\n"
        '- "wide": environmental establishing shot, figure is small in frame, emphasis on place/atmosphere\n'
        '- "medium": waist-up or full-body, balanced figure-environment relationship, most common for dialogue\n'
        '- "close-up": face or upper body dominates, emotional intensity, facial expression (unless face_policy=avoid)\n'
        '- "detail": extreme close-up on hands, objects, textures, food, props — NO face at all\n\n'
        "=== VISUAL SUBJECT RULES ===\n"
        "- The visual_subject should VARY across segments. NOT every shot features the protagonist.\n"
        "- Supporting characters get their OWN shots when the segment is about them.\n"
        "- Use 'environment' when the segment describes a place or atmosphere, not a person.\n"
        "- Use 'object detail' for close-ups of significant props (letters, food, tools, etc.).\n"
        "- Use 'group' when multiple characters share the frame equally.\n"
        "- A character can appear via: full figure, back view, hands only, silhouette, reflection.\n"
        f"{face_rule}\n"
        "=== EMOTION LIGHTING ===\n"
        "1. glory: warm amber gold, bright marquee lights, high contrast\n"
        "2. tragedy: cold cyan grey, desaturated, overcast, deep shadows\n"
        "3. transition: golden hour, sunset silhouette, rim light\n"
        "4. daily: soft natural light, diffuse, neutral palette\n\n"
        "=== OUTPUT FORMAT ===\n"
        '{{"shots": [{{"visual_subject": "...", "shot_type": "wide|medium|close-up|detail", '
        '"composition": "DETAILED English visual description 15-30 words with costume/prop/lighting", '
        '"emotion": "glory|tragedy|transition|daily", '
        '"character_ref": "name from cast or empty string"}}]}}\n\n'
        "IMPORTANT: composition MUST include specific visual details — clothing colors, "
        "lighting source, camera angle hint, prop or setting detail. "
        "Make every shot visually DISTINCT from the others.\n"
        "Output pure JSON, no markdown."
    ).replace("{total}", str(total_segments))

    # 构建场景摘要
    scene_summary = ""
    for i, sc in enumerate(scenes):
        if isinstance(sc, dict):
            scene_summary += (
                f"[{i}] emotion={sc.get('emotion', 'daily')}, "
                f"chars={sc.get('characters_present', [])}, "
                f"loc={sc.get('location', '?')}, time={sc.get('time', '?')}\n"
                f"    desc: {sc.get('scene_desc', '')}\n"
            )
        else:
            scene_summary += f"[{i}] {sc}\n"

    user_prompt = (
        f"=== CHARACTER CAST ===\n{cast_summary}\n"
        f"=== SCENE BREAKDOWN ===\n{scene_summary}\n"
        f"=== SEGMENT TEXT (for precise shot matching) ===\n"
        + "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences))
        + f"\n\nOutput {total_segments} shots as JSON array. Vary visual_subject and shot_type across segments."
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as http:
            resp = await http.post(
                "https://api.deepseek.com/v1/chat/completions",
                json={
                    "model": "deepseek-v4-pro",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 32768,
                    "response_format": {"type": "json_object"},
                },
                headers={
                    "Authorization": f"Bearer {deepseek_key}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                finish_reason = data["choices"][0].get("finish_reason", "unknown")
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rstrip("```").strip()
                storyboard = json.loads(content)
                shot_count = len(storyboard.get("shots", []))
                print(f"[image:storyboard] OK — {shot_count} shots")
                return storyboard
            else:
                print(f"[image:storyboard] API error {resp.status_code}: {resp.text[:200]}")
                return {}
    except Exception as e:
        print(f"[image:storyboard] Failed: {type(e).__name__}: {e}")
        # 诊断：打印原始响应长度和finish_reason，区分截断 vs 模型输出坏JSON
        finish_info = ""
        try:
            finish_info = f"finish_reason={finish_reason}"
        except Exception:
            finish_info = "finish_reason=N/A"
        content_info = ""
        try:
            content_info = f"len={len(content)}, tail={content[-200:]}"
        except Exception:
            content_info = "content=N/A"
        print(f"[image:storyboard] {finish_info}, {content_info}")
        return {}


# 句切分结果缓存：避免轮询期间每次请求都重新 split_into_short_sentences()
# key = (task_id, rewritten_mtime), value = list[str]
_SENTENCE_CACHE: dict[tuple[int, int], list[str]] = {}


# ============== Prompt 安全降级（Fal.ai 内容审查规避）==============

# 敏感词 → 中性替代词映射（按风险从高到低排列，长匹配优先）
_CONTENT_SANITIZE_MAP: list[tuple[str, str]] = [
    # 死亡/疾病/葬礼类（先匹配长的，用于 scenes 过滤）
    ("kneeling", "sitting"),
    ("somber", "quiet"),
    ("mourning", "quiet"),
    ("deathbed", "bedside in dim light"),
    ("mother's deathbed", "quiet bedside vigil"),
    ("funeral", "memorial gathering"),
    ("dying", "resting"),
    ("death", "loss"),
    ("coffin", "wooden bed"),
    ("grave", "quiet hill"),
    ("tomb", "quiet place"),
    ("blood", "water"),
    ("wound", "scar"),
    ("crying", "gazing"),
    ("tear-streaked", "quiet"),
    ("tears", "quiet gaze"),
    ("tear", "quiet"),
    ("hornet sting", "childhood memory"),
    (" sting ", " brief pain "),
    (" stung ", " touched "),
    ("hospital", "quiet room"),
    ("mental ward", "quiet corridor"),
    ("asylum", "old building"),
    ("fleeing", "traveling"),
    ("fled", "traveled"),
    ("flee", "depart"),
    ("deathbed", "bedside"),
    ("mother's deathbed", "mother's bedside"),
    ("funeral", "memorial"),
    ("death", "loss"),
    # 暴力/伤害类（长匹配优先）
    ("碰高压电", "遭遇意外"),
    ("高压电", "意外事故"),
    ("触电身亡", "遭遇不幸"),
    ("触电", "受伤"),
    ("双手没了", "受了重伤"),
    ("手没了", "受了伤"),
    ("腿没了", "受了伤"),
    ("双臂没了", "受了重伤"),
    ("失去双手", "受了重伤"),
    ("失去双腿", "受了重伤"),
    ("失去手臂", "受了重伤"),
    ("截肢", ""),
    ("打死", "教训"),
    ("耳光", "回应"),
    ("血淋淋", "沉重"),
    ("血流", ""),
    ("鲜血", ""),
    ("自杀", "想不开"),
    ("杀死", ""),
    ("掐死", ""),
    ("勒死", ""),
    ("捅死", "伤害"),
    ("捅了", "伤了"),
    ("捅", "伤"),
    ("砍死", "伤害"),
    ("砍伤", "受伤"),
    ("砍", "打"),
    ("开枪", ""),
    ("枪杀", ""),
    ("枪", ""),
    ("炸弹", ""),
    ("丧命", "离世"),
    ("惨死", "离世"),
    ("毙命", ""),
    ("活埋", ""),
    # 性/裸露
    ("裸体", ""),
    ("强奸", "侵害"),
    ("性侵", "侵害"),
    ("猥亵", "欺负"),
    ("色情", ""),
    # 少儿安全
    ("虐待儿童", ""),
    ("小丫头", "孩子"),
    ("六岁的", "年幼的"),
    ("五岁的", "年幼的"),
    ("七岁的", "年幼的"),
    ("八岁的", "年幼的"),
    ("抱着门框哭", "站在门口"),
    ("哭得嗓子都哑了", "安静地站在那里"),
    ("嫌闺女是个累赘", "觉得孩子需要更多照顾"),
    ("累赘", "负担"),
    ("没人要的孩子", "需要关爱的孩子"),
    ("弃婴", "新生儿"),
    ("被抛弃", "被托付给家人"),
    ("抛弃", "送走"),
    ("虐童", ""),
    ("拐卖", "带走了"),
    # 自残类
    ("割腕", "伤害自己"),
    ("跳楼", "轻生"),
    ("上吊", "轻生"),
]


def _sanitize_prompt(prompt: str) -> str:
    """替换 prompt 中可能触发内容审查的敏感短语。"""
    result = prompt
    for bad, replacement in _CONTENT_SANITIZE_MAP:
        if bad in result:
            result = result.replace(bad, replacement)
            print(f"[image:sanitize] 替换敏感词: '{bad}' → '{replacement}'")
    return result


# ============== 情绪检测 → 自动匹配风格 ==============

# 情绪关键词 → 最适合的 Style Bible
_MOOD_STYLE_MAP: dict[str, str] = {
    "documentary_realism": "documentary_realism",
    "warm_book": "warm_book",
    "philosophy": "philosophy",
    "default": "default",
}

# 负面/苦难情绪关键词（触发纪实风）
_TRAGIC_KEYWORDS = [
    "贫困", "贫穷", "穷困", "苦难", "悲惨", "凄惨", "惨烈",
    "绝望", "压抑", "沉重", "悲痛", "悲恸", "哀伤", "哭泣",
    "饥饿", "流浪", "逃荒", "乞讨", "捡破烂",
    "家徒四壁", "一贫如洗", "揭不开锅", "饿死", "冻死",
    "虐待", "抛弃", "遗弃", "父亲疯了", "母亲跑了",
    "孤儿", "无家可归", "流浪儿", "留守儿童",
    "阴暗", "灰暗", "昏暗", "破败", "残破", "破旧不堪",
    "挣扎", "煎熬", "苟活", "活不下去", "生不如死",
    "患病", "病重", "绝症", "临终",
]

# 温暖/治愈情绪关键词（触发书单风）
_WARM_KEYWORDS = [
    "温暖", "治愈", "幸福", "美好", "甜蜜", "温馨",
    "阳光", "明媚", "欢快", "轻松", "悠闲",
    "田园", "花海", "森林", "海边漫步", "落日",
    "团圆", "和睦", "和谐", "宁静", "安详",
]

# 哲思/深沉情绪关键词（触发哲学风）
_PHILOSOPHY_KEYWORDS = [
    "哲学", "思辨", "孤独", "深邃", "广阔", "渺小",
    "人生", "命运", "时间", "永恒", "反思", "冥想",
    "宇宙", "星空", "山川", "大海", "荒原",
]


def _detect_sentence_mood(
    sentence: str,
    visual_context: str = "",
) -> str:
    """
    根据句子文本和视觉档案的情绪基调，自动选择最匹配的 Style Bible。
    返回风格 key: "documentary_realism" | "warm_book" | "philosophy" | "default"
    """
    combined = f"{visual_context}\n{sentence}"

    tragic_score = sum(1 for kw in _TRAGIC_KEYWORDS if kw in combined)
    warm_score = sum(1 for kw in _WARM_KEYWORDS if kw in combined)
    philo_score = sum(1 for kw in _PHILOSOPHY_KEYWORDS if kw in combined)

    # 优先匹配最强的情绪信号
    if tragic_score >= warm_score and tragic_score >= philo_score and tragic_score > 0:
        return "documentary_realism"
    if warm_score >= tragic_score and warm_score >= philo_score and warm_score > 0:
        return "warm_book"
    if philo_score >= tragic_score and philo_score >= warm_score and philo_score > 0:
        return "philosophy"

    # 无强信号 → 从 visual_context 提取情绪基调
    if visual_context:
        mood_match = re.search(r'情绪基调[：:]\s*(.*)', visual_context, re.IGNORECASE)
        if mood_match:
            mood_text = mood_match.group(1).strip()
            # 解析情绪基调中的关键词
            tragic_in_context = any(kw in mood_text for kw in _TRAGIC_KEYWORDS)
            warm_in_context = any(kw in mood_text for kw in _WARM_KEYWORDS)
            if tragic_in_context:
                return "documentary_realism"
            if warm_in_context:
                return "warm_book"

    return "default"


# ============== 单图直生 Prompt（v4：单句独立生图，彻底废弃九宫格）==============


# ============== 风格前缀（根据风格类型选择 prompt 开头，纪实=documentary / 电影=cinematic）==============

STYLE_PREFIX = {
    "chinese_docu": "A cinematic photograph",
    "documentary_realism": "A neorealist photograph",
    "warm_docu": "A documentary photograph",
    "default": "A cinematic photograph",
    "wong_kar_wai": "A cinematic film still",
    "warm_book": "A cinematic photograph",
    "clean_health": "A lifestyle photograph",
    "philosophy": "A contemplative photograph",
}


def build_single_segment_prompt(
    text: str,
    book_title: str = "",
    book_author: str = "",
    segment_index: int = 0,
    total_segments: int = 1,
    style_bible: str = "",
    style_key: str = "default",
    aspect_ratio: str = "9:16",
    visual_context: str = "",
    visual_plan: Optional[dict] = None,
    storyboard: Optional[dict] = None,
) -> str:
    """
    v8 构建单句配图 Prompt（仅 storyboard 分镜，无降级）。
    """
    _face_rules = {
        "show": "",
        "avoid": "FACE RULE: never show a clear frontal face — "
                 "use back view, side profile, silhouette, or environmental wide shot. ",
    }

    # === v8 分镜脚本（storyboard 必须存在且数据完整，否则跳过该段，不降级不浪费API）===
    if not storyboard:
        print(f"[image:prompt] seg {segment_index} 无 storyboard → 跳过, 不浪费API")
        return ""

    shots = storyboard.get("shots", [])
    character_cast = storyboard.get("character_cast", [])
    face_policy = storyboard.get("face_policy", "show")
    face_rule = _face_rules.get(face_policy, "")

    if segment_index >= len(shots):
        print(f"[image:prompt] seg {segment_index} 分镜数据不足 (shots={len(shots)}) → 跳过, 不浪费API")
        return ""

    shot = shots[segment_index]
    if not isinstance(shot, dict):
        print(f"[image:prompt] seg {segment_index} shot 格式异常 → 跳过, 不浪费API")
        return ""

    visual_subject = shot.get("visual_subject", "")
    shot_type = shot.get("shot_type", "medium")
    composition = _sanitize_prompt(shot.get("composition", shot.get("scene_desc", "")))
    emotion = shot.get("emotion", "daily")
    character_ref = shot.get("character_ref", "")

    if not composition:
        print(f"[image:prompt] seg {segment_index} composition 为空 → 跳过, 不浪费API")
        return ""

    if not visual_subject:
        visual_subject = "a figure"

    # 查找角色档案
    char_profile = ""
    if character_ref and character_cast:
        for c in character_cast:
            if c.get("name", "") == character_ref:
                char_profile = (
                    f"Character: {c.get('name', '')}, {c.get('gender', '')}, "
                    f"age {c.get('age', '')}, {c.get('appearance', '')}. "
                    f"Clothing: {c.get('clothing', '')}. "
                    f"Body: {c.get('body_type', '')}. "
                )
                break

    emotion_light = get_emotion_lighting(emotion)
    shot_hint = {
        "wide": "wide establishing shot, small figure in a large space",
        "medium": "medium shot, waist-up or full body",
        "close-up": "close-up shot, face or upper body dominates",
        "detail": "extreme close-up detail shot, no face, texture focus",
    }.get(shot_type, "medium shot")

    prompt_prefix = STYLE_PREFIX.get(style_key, STYLE_PREFIX["default"])

    # v9: 自然段落格式，去掉 Subject:/Scene:/Lighting:/Style: 标签体
    # 接近手写英文 prompt 的流畅描述，对 gpt-image-2 友好
    char_part = f" {char_profile.strip()}" if char_profile.strip() else ""
    face_part = f" {face_rule.strip()}" if face_rule.strip() else ""

    prompt = (
        f"{prompt_prefix} in {aspect_ratio} format. "
        f"{shot_hint} of {visual_subject}. "
        f"{composition} "
        f"{emotion_light}.{char_part}{face_part}"
        f" The overall aesthetic is {style_bible}. "
        f"single image, no text, no watermark"
    )
    print(
        f"[image:prompt] seg {segment_index} v8分镜, "
        f"subject={visual_subject}, shot={shot_type}, emotion={emotion}, len={len(prompt)}"
    )
    return prompt


# ============== 通道 A2：Fal.ai flux-dev（备选，人物一致性更强）==============

# ============== 通道 A：Fal.ai gpt-image-2（主力）==============

async def _generate_fal(
    prompt: str,
    width: int = 3840,
    height: int = 2160,
    quality: str = "low",
) -> Optional[str]:
    """
    调用 Fal.ai gpt-image-2 生成图片。

    Args:
        prompt: 生图 prompt
        width, height: 画布尺寸（必须 16 的倍数，最大 3840px，总像素 ≤ 8,294,400）
        quality: "low" | "medium" | "high"

    Returns:
        base64 图片字符串，失败返回 None
    """
    if not FAL_KEY:
        print("[image:fal] FAL_KEY 未设置")
        return None

    url = "https://fal.run/openai/gpt-image-2"
    headers = {
        "Authorization": f"Key {FAL_KEY}",
        "Content-Type": "application/json",
    }

    # ★ gpt-image-2 要求宽高均为 16 的倍数，否则自动向下取整导致尺寸偏差
    # 例如 1080 会被取整为 1072（1080/16=67.5, 67*16=1072）
    original_w, original_h = width, height
    width = (width // 16) * 16
    height = (height // 16) * 16
    if (width, height) != (original_w, original_h):
        print(f"[image:fal] 尺寸对齐 16 倍数: {original_w}x{original_h} → {width}x{height}")

    payload = {
        "prompt": prompt,
        "image_size": {"width": width, "height": height},
        "quality": quality,
        "num_images": 1,
        "output_format": "png",
        "sync_mode": True,  # 同步返回 base64 data URI，跳过队列轮询
    }

    total_pixels = width * height
    print(
        f"[image:fal] 请求 {FAL_MODEL}, "
        f"size={width}x{height} ({total_pixels / 1e6:.1f}MP), "
        f"quality={quality}, prompt_len={len(prompt)}"
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code == 200:
            data = resp.json()
            images = data.get("images", [])
            if images and len(images) > 0:
                img = images[0]
                img_url = img.get("url", "")

                # sync_mode=True 可能返回 data URI 或 HTTP URL
                if img_url.startswith("data:"):
                    # data:image/png;base64,xxxx
                    b64 = img_url.split(",", 1)[1] if "," in img_url else img_url
                    print(f"[image:fal] 生图成功 (data URI), base64_len={len(b64)}")
                    return b64
                elif img_url.startswith("http"):
                    print(f"[image:fal] 生图成功, 从 URL 下载: {img_url[:80]}...")
                    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as dl:
                        img_resp = await dl.get(img_url)
                        if img_resp.status_code == 200:
                            b64 = base64.b64encode(img_resp.content).decode("utf-8")
                            print(f"[image:fal] 下载完成, base64_len={len(b64)}")
                            return b64
                else:
                    print(f"[image:fal] 未知 URL 格式: {img_url[:100]}")
                    return None
            print(f"[image:fal] 返回数据无 images: {json.dumps(data, ensure_ascii=False)[:300]}")
            return None
        else:
            err = resp.text[:500]
            print(f"[image:fal] API 错误 {resp.status_code}: {err}")
            return None

    except httpx.TimeoutException:
        print("[image:fal] 请求超时 (300s)")
        return None
    except Exception as e:
        print(f"[image:fal] 异常: {type(e).__name__}: {e}")
        return None


# ============== 通道 B：可灵（备）==============

# ============== 视觉档案合法性校验 ==============

def _is_valid_visual_profile(text: str) -> bool:
    """校验 LLM 返回的视觉档案是否合法，过滤客套话/幻觉/空模板。

    正常档案至少包含 "主人公视觉档案" 或 "性别" 关键词，且有实际内容。
    拦截以下情况：
    - LLM 客套话（"好的"、"明白了"、"请提供"）
    - 空填表模板（字段名存在但字段值全为空）
    - 纯 markdown 格式模板（LLM 自作主张画表格）
    """
    if not text or not text.strip():
        return False
    t = text.strip()

    # 1. 客套话检测
    platitudes = ["好的", "明白了", "请提供", "以下是", "根据您", "收到"]
    first_line = t.split("\n")[0].strip()
    for p in platitudes:
        if first_line.startswith(p):
            return False

    # 2. Markdown 模板检测（LLM 自作主张画**加粗**或#标题的表格框架）
    if first_line.startswith("**") or first_line.startswith("#"):
        return False

    # 3. 必须有档案特征关键词
    has_profile_header = ("角色档案" in t or "主人公视觉档案" in t or "视觉档案" in t)
    has_gender = "性别" in t or "男" in first_line or "女" in first_line
    has_body = "身体特征" in t
    if not (has_profile_header or (has_gender and has_body)):
        return False

    # 4. 空模板检测：字段行数很多但几乎都为空值
    #    统计 "字段名：X" 模式中 X 非空的行占比
    lines = t.split("\n")
    field_lines = 0
    filled_lines = 0
    for line in lines:
        if "：" in line or ":" in line:
            field_lines += 1
            # 冒号后有超过2个非空白字符才算是有效填充
            for sep in ("：", ":"):
                if sep in line:
                    val = line.split(sep, 1)[1].strip()
                    if len(val) >= 2:
                        filled_lines += 1
                    break
    # 字段行超过3行但填充行不到一半 → 空模板
    if field_lines >= 4 and filled_lines < field_lines * 0.5:
        print(f"[image:v4] 视觉档案疑似空模板: {field_lines}字段行, 仅{filled_lines}行有内容")
        return False

    return True


def _parse_visual_context_fallback(visual_context: str) -> list[dict]:
    """
    当 screenplay 返回空 character_cast 时，从 visual_context 解析角色档案作为兜底。
    兼容两种格式：
      F1（deepseek-chat 旧格式）：
        角色1：邱傲玉|女|18岁|中等偏瘦|齐耳短发|五官清秀，眉眼坚定|白色T恤/运动校服|无
      F2（deepseek-v4-pro 可能变体）：
        **角色1**：邱傲玉|女|18岁|...   （markdown bold）
        - 角色1：邱傲玉|女|18岁|...      （bullet list）
        1. 角色1：邱傲玉|女|18岁|...     （numbered list）
    映射：姓名→name, 性别→gender, 年龄→age, 体型→body_type,
         发型+面部→appearance, 服装→clothing
    """
    import re as _re
    cast = []
    seen_names = set()

    # 多模式正则：逐行匹配 "角色N：..." 的各种变体
    # 组1 = 名字后的整行 pipe 数据
    patterns = [
        # F1: 角色1：邱傲玉|女|18岁|...
        _re.compile(r'^角色(\d+)[：:]\s*(.+)$'),
        # F2a: **角色1**：邱傲玉|女|18岁|...
        _re.compile(r'^\*\*角色(\d+)\*\*\s*[：:]\s*(.+)$'),
        # F2b: - 角色1：邱傲玉|女|18岁|... 或 * 角色1：...
        _re.compile(r'^[-*]\s*角色(\d+)\s*[：:]\s*(.+)$'),
        # F2c: 1. 角色1：... 或 1) 角色1：...
        _re.compile(r'^\d+[.)]\s*角色(\d+)\s*[：:]\s*(.+)$'),
    ]

    lines = visual_context.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        matched_data = None
        for pat in patterns:
            m = pat.match(stripped)
            if m:
                matched_data = m.group(2)
                break

        if not matched_data:
            continue

        parts = [p.strip() for p in matched_data.split("|")]
        if len(parts) < 5:
            # 字段数不够 → 可能不是标准格式，跳过
            continue

        name = parts[0] if len(parts) > 0 else "?"
        if name in seen_names:
            continue  # 去重（如"年轻时/老年时"拆成两行，保留第一个）
        seen_names.add(name)

        gender_raw = parts[1] if len(parts) > 1 else ""
        if "女" in gender_raw:
            gender_en = "female"
        elif "男" in gender_raw:
            gender_en = "male"
        else:
            gender_en = "unknown"

        age = parts[2] if len(parts) > 2 else "?"
        body_type = parts[3] if len(parts) > 3 else ""
        appearance = parts[4] if len(parts) > 4 else ""
        clothing = parts[5] if len(parts) > 5 else ""
        special = parts[6] if len(parts) > 6 else ""
        if special and special != "无":
            body_type = f"{body_type}, {special}" if body_type else special

        cast.append({
            "name": name,
            "gender": gender_en,
            "age": age,
            "appearance": appearance,
            "clothing": clothing,
            "body_type": body_type,
            "role": "protagonist" if len(cast) == 0 else "supporting",
        })

    if cast:
        print(f"[image:fallback] 从 visual_context 解析到 {len(cast)} 个角色: "
              f"{[c['name'] for c in cast]}")
    else:
        print(f"[image:fallback] visual_context 解析结果为 0（visual_context 前200字: {visual_context[:200]}）")
    return cast


# ============== 主入口：按句批量生图（v4 单图直生）==============

async def generate_all_images(
    task_id: int,
    db,
    style: str = "default",
    book_title: str = "",
    book_author: str = "",
    aspect_ratio: str = "9:16",
    force: bool = False,
    gender: str = "auto",
) -> dict:
    """
    v8 分镜架构：剧本 → 分镜 → 逐镜生图 + 多通道降级。

    流程:
    0. extract_visual_context → 提取全体角色档案（v8: 含配角）
    0.5a generate_screenplay → LLM 剧本生成 → 角色表 + 场景列表
    0.5b generate_storyboard → LLM 分镜脚本 → per-shot visual_subject + shot_type
    1. 读取 rewritten.txt → split_into_short_sentences() 切句
    2. for each sentence → build_single_segment_prompt(storyboard)
    3. Fal.ai gpt-image-2 单图直生（quality="medium", 4x 超采样）
    4. PIL resize 到精确目标分辨率 → 写入 TaskImage 表
    5. 异常兜底：单张失败不阻塞后续 → 降敏 → LLM 改写 → 通用 prompt → 占位图

    v8 vs v7: visual_subject 不再总是主角，配角/环境/物品都有独立镜头。
    screenplay / storyboard 任一失败 → 中止生图，不浪费 API 费用。
    Returns:
        {"total_segments": N, "total_images": N, "success": N, "failed": N}
    """
    from models import TaskImage, Task
    from services.llm_service import split_into_short_sentences, extract_visual_context

    # 1. 读取改写稿
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return {"error": f"任务 {task_id} 不存在", "total_segments": 0}

    # ★ 防并发栅栏：如果已有生图正在执行，直接拒绝
    if task.images_generating:
        # 安全检查：如果标记为 generating 但 DB 里一张图都没有 → 上次启动后立即崩溃，
        # 允许本次请求继续（否则任务永久卡死）
        img_count = db.query(TaskImage).filter(TaskImage.task_id == task_id).count()
        if img_count == 0:
            print(f"[image:v4] 检测到僵尸 generating 标记（0 张已存图），自动解除并允许重试")
        else:
            return {"error": "配图正在生成中，请勿重复操作。刷新页面即可看到最新进度。", "total_segments": 0}
    task.images_generating = True
    task.images_complete = False
    db.commit()

    rewritten = task.rewritten_transcript or ""
    if not rewritten.strip():
        tasks_dir = os.path.join(get_data_dir(), "tasks")
        task_dir = os.path.join(os.path.abspath(tasks_dir), str(task_id))
        rewritten_file = os.path.join(task_dir, "rewritten.txt")
        if os.path.exists(rewritten_file):
            with open(rewritten_file, "r", encoding="utf-8") as f:
                rewritten = f.read()

    if not rewritten.strip():
        task.images_generating = False
        db.commit()
        return {"error": "没有改写稿，请先完成文本改写", "total_segments": 0}

    # 2. 按强标点切句（与视频合成阶段参数完全一致）
    sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)
    total_segments = len(sentences)

    avg_chars = len(rewritten) / max(1, total_segments)
    print(
        f"[image:v4] 任务 {task_id}: "
        f"全文 {len(rewritten)} 字 → {total_segments} 句 "
        f"(平均 {avg_chars:.0f} 字/句) → {total_segments} 张单图直生"
    )

    book_title = book_title or task.book_title or ""
    book_author = book_author or task.book_author or ""
    style_bible = STYLE_BIBLES.get(style, STYLE_BIBLES["default"])
    quality = os.getenv("FAL_QUALITY", "low")

    # ── Pass 0: 提取视觉档案 ──
    visual_context = task.visual_context or ""
    if force and visual_context.strip():
        print(f"[image:v4] force=true → 清除已缓存的视觉档案，重新提取")
        task.visual_context = ""
        db.commit()
        visual_context = ""
    if not visual_context.strip():
        print(f"[image:v4] 视觉档案未缓存 → LLM 提取中...")
        try:
            visual_context = await extract_visual_context(rewritten)
            if visual_context.strip():
                if _is_valid_visual_profile(visual_context):
                    task.visual_context = visual_context
                    db.commit()
                    print(f"[image:v4] 视觉档案已缓存到 task.visual_context")
                else:
                    print(f"[image:v4] 视觉档案校验不通过（疑似客套话），丢弃。内容前80字: {visual_context[:80]}")
                    visual_context = ""
        except Exception as e:
            print(f"[image:v4] 视觉档案提取失败: {e}，跳过")
            visual_context = ""
    else:
        print(f"[image:v4] 使用已缓存的视觉档案 ({len(visual_context)} 字)")

    # ── Pass 0.5a: v8 剧本生成（LLM 通读全文 → 全角色档案 + 场景列表）──
    print(f"[image:v8] 启动剧本生成 (全文 {len(rewritten)} 字, {total_segments} 段)...")
    screenplay = await generate_screenplay(
        rewritten_transcript=rewritten,
        book_title=book_title,
        book_author=book_author,
        visual_context=visual_context,
        style=style,
        total_segments=total_segments,
        sentences=sentences,
        gender=gender,
    )

    # ── Pass 0.5b: v8 分镜脚本（剧本 → 逐镜 visual_subject + shot_type）──
    storyboard = None
    if screenplay:
        cast_count = len(screenplay.get("character_cast", []))
        scene_count = len(screenplay.get("scenes", []))
        # 兜底：DeepSeek 偶尔丢角色表，从 visual_context 解析补上
        if cast_count == 0 and visual_context.strip():
            fallback_cast = _parse_visual_context_fallback(visual_context)
            if fallback_cast:
                screenplay["character_cast"] = fallback_cast
                cast_count = len(fallback_cast)
                print(f"[image:v8] 剧本角色表为空 → 已用 visual_context 兜底: {cast_count} 角色")
        print(f"[image:v8] 剧本生成成功: {cast_count} 角色, {scene_count} 场景 → 启动分镜脚本...")
        storyboard = await generate_storyboard(
            screenplay=screenplay,
            sentences=sentences,
            visual_context=visual_context,
            total_segments=total_segments,
        )
        if storyboard:
            storyboard["face_policy"] = screenplay.get("face_policy", "show")
            storyboard["character_cast"] = screenplay.get("character_cast", [])
            shot_count = len(storyboard.get("shots", []))
            print(f"[image:v8] 分镜脚本成功: {shot_count} 镜")
        else:
            msg = "[image:v8] 分镜脚本生成失败，已中止生图，避免浪费 API 费用。请检查日志后重试。"
            print(msg)
            return {"error": msg}
    else:
        msg = "[image:v8] 剧本生成失败，已中止生图，避免浪费 API 费用。请检查日志后重试。"
        print(msg)
        return {"error": msg}

    # v8 storyboard 已就绪，直接进入生图阶段
    # （storyboard 失败已在上方 return error，不会执行到这里）
    visual_plan = None
    shot_count = len(storyboard.get("shots", [])) if storyboard else 0
    print(f"[image:v8] 分镜就绪: {shot_count} 镜 → 开始生图")

    # 3. 根据画幅比确定请求尺寸与目标尺寸
    if aspect_ratio == "16:9":
        REQUEST_W, REQUEST_H = 3840, 2160
        TARGET_W, TARGET_H = 1280, 720
    elif aspect_ratio == "3:4":
        REQUEST_W, REQUEST_H = 768, 1024
        TARGET_W, TARGET_H = 768, 1024
    elif aspect_ratio == "8:9":
        REQUEST_W, REQUEST_H = 2160, 2432  # 8:9 超采样（近方形卡片版式，对标满宽展示区 1080×1214）
        TARGET_W, TARGET_H = 1080, 1214
    else:
        REQUEST_W, REQUEST_H = 2160, 3840  # 9:16 超采样
        TARGET_W, TARGET_H = 1080, 1920

    # 4. 数据目录
    tasks_dir = os.path.join(get_data_dir(), "tasks")
    task_dir = os.path.join(os.path.abspath(tasks_dir), str(task_id))
    images_dir = os.path.join(task_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # 5. 不再无脑清空旧记录 → 改为逐段 upsert + 末尾清理多余（防并发竞态）
    # 旧记录在每个 segment 循环中按 seg_idx 覆盖写入

    # 6. 并行单图直生（v5：4 路并发 + 两阶段架构，DB session 安全）
    # 阶段 1：全部 API 调用并发执行（纯网络 I/O，不碰 DB）
    # 阶段 2：串行落盘 + DB upsert（保证 SQLAlchemy session 单线程安全）
    import asyncio as _asyncio
    MAX_CONCURRENT = 4
    sem = _asyncio.Semaphore(MAX_CONCURRENT)

    async def _generate_one(seg_idx: int, sentence: str) -> dict:
        """生成单张配图（纯 API 调用 + prompt 文件写入，不碰 DB）。"""
        async with sem:
            target_path = os.path.join(images_dir, f"seg_{seg_idx:03d}.png")

            # 跳过已存在的成功图片（支持断点续跑）
            if not force and os.path.exists(target_path) and os.path.getsize(target_path) > 1000:
                print(f"[image:v4] 段 {seg_idx + 1}/{total_segments} 已存在（并发检测），跳过")
                return {"seg_idx": seg_idx, "status": "skipped", "target_path": target_path}
            if force and os.path.exists(target_path):
                print(f"[image:v4] force=true → 删除旧图 seg_{seg_idx:03d}.png")
                os.remove(target_path)

            text_len = len(sentence.strip())
            print(
                f"[image:v4] 段 {seg_idx + 1}/{total_segments}: "
                f"{text_len} 字, size={REQUEST_W}x{REQUEST_H}, aspect={aspect_ratio}"
            )

            # 始终使用用户选择的风格，不随情绪检测变化
            # 情绪（glory/tragedy/transition/daily）已通过 screenplay → EMOTION_LIGHTING 注入 prompt
            actual_style_bible = style_bible
            actual_style_suffix = STYLE_PROMPT_MAP.get(style, STYLE_PROMPT_MAP["default"])

            # 构建 Prompt（v8 storyboard）
            # ★ style_key 始终用用户选择的风格，不随情绪检测变化
            # 情绪检测只影响 style_bible + emotion_lighting，不影响 prompt 风格前缀
            base_prompt = build_single_segment_prompt(
                text=sentence,
                book_title=book_title,
                book_author=book_author,
                segment_index=seg_idx,
                total_segments=total_segments,
                style_bible=actual_style_bible,
                style_key=style,
                aspect_ratio=aspect_ratio,
                visual_context=visual_context,
                visual_plan=visual_plan,
                storyboard=storyboard,
            )
            if not base_prompt:
                # 分镜数据不完整 → 跳过此段，不调用任何 API
                print(f"[image:v4] 段 {seg_idx + 1} prompt 为空 → 跳过, 不消耗API")
                return {"seg_idx": seg_idx, "status": "skipped_no_data", "target_path": target_path}
            final_prompt = base_prompt  # v8: 已包含所有风格元素

            # 保存 prompt 到文件
            prompt_path = os.path.join(images_dir, f"seg_{seg_idx:03d}_prompt.txt")
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(final_prompt)

            # Fal.ai 生图（仅一次降敏重试，不跨平台、不降级质量、不浪费其他API）
            img_bytes = None
            error_msg = ""
            try:
                b64 = await _generate_fal(final_prompt, width=REQUEST_W, height=REQUEST_H, quality=quality)
                if b64:
                    img_bytes = base64.b64decode(b64)
                else:
                    # 降敏重试（同平台、同模型、仅 prompt 微调）
                    sanitized = _sanitize_prompt(final_prompt)
                    if sanitized != final_prompt:
                        print(f"[image:v4] 段 {seg_idx + 1} fal 首次失败 → 降敏重试")
                        b64 = await _generate_fal(sanitized, width=REQUEST_W, height=REQUEST_H, quality=quality)
                        if b64:
                            img_bytes = base64.b64decode(b64)
                            final_prompt = sanitized
                    if not img_bytes:
                        # 预备方案：降级到简洁 prompt（原句先过 _sanitize_prompt 过滤敏感词）
                        safe_sentence = _sanitize_prompt(sentence.strip())
                        fallback_prompt = (
                            f"A cinematic vertical composition, 8:9 near-square vertical composition. "
                            f"Scene inspired by: {safe_sentence}. "
                        ) + actual_style_suffix + " " + SAFETY_SUFFIX
                        print(f"[image:v4] 段 {seg_idx + 1} 降敏重试也失败 → 尝试简洁 prompt 备选")
                        b64 = await _generate_fal(fallback_prompt, width=REQUEST_W, height=REQUEST_H, quality=quality)
                        if b64:
                            img_bytes = base64.b64decode(b64)
                            final_prompt = fallback_prompt
                            # 也更新保存的 prompt 文件
                            with open(prompt_path, "w", encoding="utf-8") as f:
                                f.write(final_prompt)
                        else:
                            error_msg = "Fal.ai 生图失败（含降敏重试 + 简洁prompt备选），已中止（不跨平台）"
            except Exception as e:
                error_msg = f"生图异常: {type(e).__name__}: {e}"
                print(f"[image:v4] 段 {seg_idx + 1} 异常: {error_msg}")

            return {
                "seg_idx": seg_idx,
                "status": "success" if img_bytes else "failed",
                "target_path": target_path,
                "img_bytes": img_bytes,
                "final_prompt": final_prompt,
                "error_msg": error_msg,
            }

    # 并发启动全部生图任务
    start_time = time.time()
    gen_results = await _asyncio.gather(*[
        _generate_one(i, s) for i, s in enumerate(sentences)
    ])
    elapsed = time.time() - start_time
    print(f"[image:v4] 全部 {total_segments} 张图 API 调用完成，耗时 {elapsed:.0f}s（并发数={MAX_CONCURRENT}）")

    # ===== 阶段 2：串行落盘 + DB upsert（保证 SQLAlchemy session 安全） =====
    total_success = 0
    total_failed = 0

    for result in gen_results:
        seg_idx = result["seg_idx"]
        target_path = result["target_path"]
        final_prompt = result.get("final_prompt", "")
        error_msg = result.get("error_msg", "")
        img_bytes = result.get("img_bytes")

        if result["status"] == "skipped":
            # ★ 补 DB 记录（断点续跑的场景：文件存在但 DB 可能缺记录）
            existing = db.query(TaskImage).filter(
                TaskImage.task_id == task_id, TaskImage.segment_index == seg_idx
            ).first()
            if not existing:
                db.add(TaskImage(
                    task_id=task_id, segment_index=seg_idx, grid_index=-1, cell_position=1,
                    image_path=target_path, status="success",
                ))
                db.commit()
            elif existing.status != "success":
                existing.status = "success"
                existing.image_path = target_path
                db.commit()
            total_success += 1
            continue

        # 落盘 + resize
        if img_bytes:
            tmp_path = target_path + ".tmp"
            try:
                with open(tmp_path, "wb") as f:
                    f.write(img_bytes)
                from PIL import Image as PILImage
                pil_img = PILImage.open(tmp_path).convert("RGB")
                actual_w, actual_h = pil_img.size
                if (actual_w, actual_h) != (TARGET_W, TARGET_H):
                    print(f"[image:v4] 缩图: {actual_w}x{actual_h} → {TARGET_W}x{TARGET_H}")
                    pil_img = pil_img.resize((TARGET_W, TARGET_H), PILImage.LANCZOS)
                pil_img.save(target_path, "PNG", optimize=True)
                pil_img.close()
                os.remove(tmp_path)
                print(f"[image:v4] 段 {seg_idx + 1} 落盘: {target_path} ({os.path.getsize(target_path)} bytes)")
                total_success += 1
            except Exception as e:
                print(f"[image:v4] 段 {seg_idx + 1} 写盘失败: {e}")
                img_bytes = None
                error_msg = f"写盘失败: {e}"
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        # 失败兜底：生成占位图
        if not img_bytes:
            print(f"[image:v4] 段 {seg_idx + 1} 失败 → 占位图: {error_msg}")
            try:
                from PIL import Image as PILImage
                ph = PILImage.new("RGB", (TARGET_W, TARGET_H), (30, 30, 35))
                ph.save(target_path, "PNG", optimize=True)
                ph.close()
            except Exception:
                pass
            total_failed += 1

        # DB upsert
        existing = db.query(TaskImage).filter(
            TaskImage.task_id == task_id, TaskImage.segment_index == seg_idx
        ).first()
        image_ok = os.path.exists(target_path) and os.path.getsize(target_path) > 1000
        if existing:
            existing.image_path = target_path if image_ok else existing.image_path
            existing.prompt_used = final_prompt
            existing.status = "success" if img_bytes else "failed"
            existing.error_msg = error_msg if error_msg else None
            existing.grid_index = -1
            existing.cell_position = 1
        else:
            ti = TaskImage(
                task_id=task_id,
                segment_index=seg_idx,
                grid_index=-1,
                cell_position=1,
                image_path=target_path if image_ok else None,
                prompt_used=final_prompt,
                status="success" if img_bytes else "failed",
                error_msg=error_msg if error_msg else None,
            )
            db.add(ti)
        db.commit()

    # 7. 收尾：清理多余旧记录 + 写入完成标记
    # 删除超出当前 total_segments 范围的残留记录（旧版留下的）
    extra = db.query(TaskImage).filter(
        TaskImage.task_id == task_id, TaskImage.segment_index >= total_segments
    ).delete()
    if extra > 0:
        print(f"[image:v4] 清理 {extra} 条多余旧配图记录")

    task.current_step = max(task.current_step, 4)
    task.images_generating = False
    task.images_complete = True
    task.total_images = total_segments
    db.commit()

    print(
        f"[image:v4] all done: {total_success} ok, {total_failed} fail | "
        f"style={style}, aspect={aspect_ratio}"
    )
    return {
        "total_segments": total_segments,
        "total_images": total_success,
        "success": total_success,
        "failed": total_failed,
    }


async def regenerate_single_image(
    task_id: int,
    segment_index: int,
    db,
    style: str = "default",
    book_title: str = "",
    book_author: str = "",
    aspect_ratio: str = "9:16",
    custom_prompt: str | None = None,
) -> dict:
    """
    v4 单段配图重跑：单张独立生图。
    如果 custom_prompt 非空，直接用自定义 prompt，跳过自动构建。
    """
    from models import TaskImage, Task
    from services.llm_service import split_into_short_sentences

    task = db.query(Task).filter(Task.id == task_id).first()
    book_title = book_title or (task.book_title if task else "") or ""
    book_author = book_author or (task.book_author if task else "") or ""
    style_bible = STYLE_BIBLES.get(style, STYLE_BIBLES["default"])
    quality = os.getenv("FAL_QUALITY", "low")
    visual_context = task.visual_context or "" if task else ""

    tasks_dir = os.path.join(get_data_dir(), "tasks")
    task_dir = os.path.join(os.path.abspath(tasks_dir), str(task_id))

    rewritten = task.rewritten_transcript or ""
    rewritten_file = os.path.join(task_dir, "rewritten.txt")
    if not rewritten and os.path.exists(rewritten_file):
        with open(rewritten_file, "r", encoding="utf-8") as f:
            rewritten = f.read()

    sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)

    if segment_index < 0 or segment_index >= len(sentences):
        return {"error": f"句子索引 {segment_index} 越界 (共 {len(sentences)} 句)"}

    text = sentences[segment_index]
    images_dir = os.path.join(task_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # v4: 尺寸由 aspect_ratio 决定
    if aspect_ratio == "16:9":
        REQUEST_W, REQUEST_H = 3840, 2160
        TARGET_W, TARGET_H = 1280, 720
    elif aspect_ratio == "3:4":
        REQUEST_W, REQUEST_H = 768, 1024
        TARGET_W, TARGET_H = 768, 1024
    elif aspect_ratio == "8:9":
        REQUEST_W, REQUEST_H = 2160, 2432  # 8:9 超采样（近方形卡片版式）
        TARGET_W, TARGET_H = 1080, 1214
    else:
        REQUEST_W, REQUEST_H = 2160, 3840
        TARGET_W, TARGET_H = 1080, 1920

    # ★ 情绪检测：自动匹配最贴合文案氛围的 Style Bible
    # 始终使用用户选择的风格，不随情绪检测变化
    actual_style_bible = style_bible
    actual_style_suffix = STYLE_PROMPT_MAP.get(style, STYLE_PROMPT_MAP["default"])

    # 用户自定义 prompt 优先，否则自动构建简单 prompt
    if custom_prompt and custom_prompt.strip():
        prompt = custom_prompt.strip() + " " + actual_style_suffix + " " + SAFETY_SUFFIX
        print(f"[image:single] 使用自定义 prompt task={task_id} sent={segment_index}, len={len(prompt)}")
    else:
        aspect_hint = "8:9 near-square vertical composition" if aspect_ratio == "8:9" else f"{aspect_ratio} vertical"
        prompt_prefix = STYLE_PREFIX.get(sentence_style if sentence_style != "default" else style, STYLE_PREFIX["default"])
        safe_text = _sanitize_prompt(text.strip())
        base_prompt = (
            f"{prompt_prefix}, {aspect_hint}. "
            f"Scene inspired by: {safe_text}. "
            f"single image, no text, no watermark"
        )
        prompt = base_prompt + actual_style_suffix + SAFETY_SUFFIX
        print(f"[image:single] 单句配图 task={task_id} sent={segment_index}, text_len={len(text)}, aspect={aspect_ratio}")

    b64 = await _generate_fal(prompt, width=REQUEST_W, height=REQUEST_H, quality=quality)
    if not b64:
        # 降敏重试（同平台、仅 prompt 微调）
        sanitized = _sanitize_prompt(prompt)
        if sanitized != prompt:
            print(f"[image:single] fal 首次失败 → 降敏重试")
            b64 = await _generate_fal(sanitized, width=REQUEST_W, height=REQUEST_H, quality=quality)
            if b64:
                prompt = sanitized
        if not b64:
            # 第三级：全通用兜底（完全剥离原文，仅保留风格氛围）
            fallback_prompt = (
                f"{prompt_prefix}, {aspect_hint}. "
                f"A quiet emotional scene in an everyday Chinese setting, "
                f"soft natural light, gentle atmosphere. "
                f"single image, no text, no watermark"
            ) + actual_style_suffix + " " + SAFETY_SUFFIX
            print(f"[image:single] 降敏重试也失败 → 通用兜底")
            b64 = await _generate_fal(fallback_prompt, width=REQUEST_W, height=REQUEST_H, quality=quality)
            if b64:
                prompt = fallback_prompt
    img_bytes = base64.b64decode(b64) if b64 else None

    target_path = os.path.join(images_dir, f"seg_{segment_index:03d}.png")

    if not img_bytes:
        existing = db.query(TaskImage).filter(
            TaskImage.task_id == task_id, TaskImage.segment_index == segment_index
        ).first()
        if existing:
            existing.status = "failed"
            existing.error_msg = "单图生图失败：所有通道均失败"
            existing.prompt_used = prompt
        else:
            db.add(TaskImage(
                task_id=task_id,
                segment_index=segment_index,
                grid_index=-1,
                cell_position=1,
                image_path=None,
                prompt_used=prompt,
                status="failed",
                error_msg="单图生图失败：所有通道均失败",
            ))
        db.commit()
        return {"error": "所有生图通道均失败", "segment_index": segment_index}

    # --- 写入临时文件 → PIL 校验尺寸 → resize 到精确 TARGET_W×TARGET_H ---
    tmp_path = target_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(img_bytes)

    try:
        from PIL import Image as PILImage
        pil_img = PILImage.open(tmp_path).convert("RGB")
        actual_w, actual_h = pil_img.size
        if (actual_w, actual_h) != (TARGET_W, TARGET_H):
            print(f"[image:single] 超采样缩图: {actual_w}x{actual_h} → {TARGET_W}x{TARGET_H}")
            pil_img = pil_img.resize((TARGET_W, TARGET_H), PILImage.LANCZOS)
        else:
            print(f"[image:single] 尺寸已正确: {actual_w}x{actual_h}，无需缩放")
        pil_img.save(target_path, "PNG", optimize=True)
        print(f"[image:single] 单图已保存: {target_path} ({os.path.getsize(target_path)} bytes, {TARGET_W}x{TARGET_H})")
    except Exception as e:
        print(f"[image:single] PIL 校验/缩放失败: {e}，直接使用原始数据")
        with open(target_path, "wb") as f:
            f.write(img_bytes)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    existing = db.query(TaskImage).filter(
        TaskImage.task_id == task_id, TaskImage.segment_index == segment_index
    ).first()
    if existing:
        existing.image_path = target_path
        existing.grid_index = -1
        existing.cell_position = 1
        existing.prompt_used = prompt
        existing.status = "success"
        existing.error_msg = None
    else:
        db.add(TaskImage(
            task_id=task_id,
            segment_index=segment_index,
            grid_index=-1,
            cell_position=1,
            image_path=target_path,
            prompt_used=prompt,
            status="success",
        ))
    db.commit()

    return {
        "segment_index": segment_index,
        "image_url": f"/images/{task_id}/images/seg_{segment_index:03d}.png",
        "status": "success",
        "message": f"句子 {segment_index + 1} 配图已重新生成",
    }


def get_images_for_task(task_id: int, db) -> list[dict]:
    """查询任务的所有配图记录（v4：按 segment_index 排序，无九宫格）"""
    from models import TaskImage
    from services.llm_service import split_into_short_sentences

    records = (
        db.query(TaskImage)
        .filter(TaskImage.task_id == task_id)
        .order_by(TaskImage.segment_index)
        .all()
    )

    # 读取句子文本用于前端展示（带缓存：same rewritten.txt → same result）
    tasks_dir = os.path.join(get_data_dir(), "tasks")
    task_dir = os.path.join(os.path.abspath(tasks_dir), str(task_id))
    rewritten_file = os.path.join(task_dir, "rewritten.txt")
    sentences: list[str] = []
    if os.path.exists(rewritten_file):
        # 以文件 mtime 作为缓存键：只有 rewritten.txt 被重写时才重新切句
        _file_key = (
            task_id,
            int(os.path.getmtime(rewritten_file)) if os.path.exists(rewritten_file) else 0,
        )
        if _file_key not in _SENTENCE_CACHE:
            with open(rewritten_file, "r", encoding="utf-8") as f:
                rewritten = f.read()
            _SENTENCE_CACHE[_file_key] = split_into_short_sentences(
                rewritten, max_chars=80, min_chars=30
            )
        sentences = _SENTENCE_CACHE[_file_key]

    # ★ 稳定缓存破壁：每张图用自己文件的 mtime 做 ?t=
    # 生图期间文件 mtime 不变 → 浏览器复用本地缓存 → 零重复下载
    # 配图重新生成后 mtime 更新 → 浏览器自动刷新单张

    return [
        {
            "id": r.id,
            "task_id": r.task_id,
            "segment_index": r.segment_index,
            "grid_index": -1,  # v4: 单图直生，无九宫格
            "cell_position": 1,
            "image_url": (
                f"/images/{task_id}/images/seg_{r.segment_index:03d}.png"
                f"?t={int(os.path.getmtime(r.image_path))}"
                if r.image_path and os.path.exists(r.image_path)
                else None
            ),
            "image_exists": bool(r.image_path and os.path.exists(r.image_path)),
            "status": r.status,
            "error_msg": r.error_msg,
            "sentence_text": sentences[r.segment_index] if r.segment_index < len(sentences) else "",
        }
        for r in records
    ]
