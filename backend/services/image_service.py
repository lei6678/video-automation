"""
配图生成服务 — Fal.ai gpt-image-2 主 · 可灵备 — v3
================================================
1. 按句切片（每句 ~60 字 / 约 18 秒口播）
2. 每 9 句一组构建 3×3 九宫格 Prompt
3. 调用 Fal.ai gpt-image-2 生成九宫格总图（3840×2160, low quality）
4. PIL 裁切：16:9 格子 → 中心裁 9:16 → 1080×1920 竖屏
5. 写入 TaskImage 表

成本: 7 组九宫格 × $0.012 ≈ $0.084（约 0.6 元人民币）
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
FAL_QUALITY = os.getenv("FAL_QUALITY", "low")  # low | medium | high，默认 low

KELING_API_KEY = os.getenv("KELING_API_KEY", "")
KELING_BASE_URL = os.getenv("KELING_BASE_URL", "https://api.kuaishou.com/keling/v1")

# ============== 模型配置 ==============
FAL_MODEL = "openai/gpt-image-2"
KELING_IMAGE_MODEL = "keling-v1"


# ============== 样式圣经库（来自大佬白皮书）==============

STYLE_BIBLES = {
    "default": (
        "固定美术方向:明亮电影感真实摄影，安静、克制、有知识短视频质感。"
        "固定色彩:暖白、浅木色、柔和灰蓝、低饱和绿色，少量温暖阳光点缀。"
        "固定光线:窗边自然光、清晨或傍晚柔光，阴影干净，整体曝光偏明亮。"
        "固定镜头:35mm/50mm人文镜头语言，主体明确，背景简洁。"
        "人物气质:普通成年人，安静、理性、克制，优先背影、侧影、手部动作和生活场景。"
        "所有图片必须共享同一套色彩、光线、镜头、人物气质、材质和时代感。"
    ),
    "warm_book": (
        "温暖治愈书单风。暖黄光线，柔焦质感，仿佛午后窗边翻书的氛围。"
        "色调偏奶油色+琥珀色，画面像旧胶片相机拍摄。"
        "常见元素：书架一角、茶杯、绿植、阳光透过窗帘、手写字条。"
    ),
    "clean_health": (
        "明亮干净的健康生活方式风。清晨自然光，白色+浅木色为主调。"
        "场景：厨房备餐、晨跑背影、公园长椅、水杯特写、瑜伽垫一角。"
        "传达平静、自律、积极的生活态度，避免医疗感。"
    ),
    "philosophy": (
        "哲学思辨风。广角远景，人物渺小于自然或城市之中。"
        "冷暖对比色调，画面留白多，有呼吸感。"
        "场景：海边独行、山顶远眺、城市天台、空旷图书馆。"
        "传达人生感悟、认知成长的深邃感。"
    ),
    "documentary_realism": (
        "纪实摄影风，拒绝美化贫困与苦难。"
        "冷灰主色调，低饱和、低曝光、暗调阴影，硬侧光或阴天散射光。"
        "粗粝质感，不完美构图，允许破旧的墙壁、斑驳的地面、磨损的衣物、简陋的家具。"
        "场景真实破败但不过度渲染：老式平房、水泥地面铁管床、旧棉被堆叠、煤炉取暖、昏黄灯泡、开裂的木桌。"
        "拒绝暖色滤镜、拒绝日系小清新、拒绝温馨柔光——这不是向往的生活，这是需要逃离的处境。"
        "人物表情克制但疲惫，肢体语言传达压抑与坚韧并存。"
    ),
}

# ============== 风格后缀映射（注入 Fal.ai prompt 末端）==============

STYLE_PROMPT_MAP = {
    "default": ", cinematic lighting, photorealistic, 35mm lens, depth of field",
    "warm_book": ", warm pastel colors, soft morning sunlight, cozy atmosphere, studio Ghibli aesthetic style",
    "clean_health": ", bright natural lighting, clean minimalism, vibrant colors, commercial photography",
    "philosophy": ", moody dramatic lighting, melancholic low key tone, surrealism artistic texture",
    "documentary_realism": ", gritty documentary photography, desaturated cold tones, harsh shadows, unpolished realism, reportage style, no glamour no beauty filter",
}

# ============== 画面后置防线（防崩坏补丁）==============

SAFETY_SUFFIX = ", highly detailed faces, no duplicate characters, perfect anatomy, masterpiece"

# 句切分结果缓存：避免轮询期间每次请求都重新 split_into_short_sentences()
# key = (task_id, rewritten_mtime), value = list[str]
_SENTENCE_CACHE: dict[tuple[int, int], list[str]] = {}


# ============== Prompt 安全降级（Fal.ai 内容审查规避）==============

# 敏感词 → 中性替代词映射（按风险从高到低排列，长匹配优先）
_CONTENT_SANITIZE_MAP: list[tuple[str, str]] = [
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


async def _llm_sanitize_segment(
    sentence: str,
    book_title: str = "",
    book_author: str = "",
    segment_index: int = 0,
    total_segments: int = 1,
    visual_context: str = "",
) -> str:
    """用 DeepSeek 将原文的一句话改写为"画面安全但同情绪、同场景"的视觉描述。

    只用于生图 prompt 构建，不影响配音/字幕/rewritten.txt。
    触发条件：全文级 sanitize 无法匹配的关键词，但 Fal.ai 语义审查拒绝通过
    （如集中描写死亡、流血、极端贫困、儿童苦难等高度悲剧性段落）。

    改写约束：
    - 保留场景、人物关系、情绪基调（悲悯→克制伤感，苦难→坚韧）
    - 去掉具象的血腥/死亡/虐待描写，转为含蓄的肢体语言、环境氛围、象征意象
    - 仍然是一段约 18 秒口播对应的画面场次描述
    - 输出纯文本，不附带任何解释
    """

    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not deepseek_key:
        print("[image:llm-sanitize] DEEPSEEK_API_KEY 未设置，跳过")
        return sentence

    context_block = ""
    if visual_context.strip():
        context_block = f"\n故事全局视觉档案:\n{visual_context.strip()}"

    system_msg = (
        "你是一个影视分镜改写助手。你的任务是把原文中可能触发图像 AI 内容审查的"
        "具象负面描写（血腥、死亡、暴力、虐待、极端苦难等），改写成一段**含蓄但同情绪、"
        "同场景的视觉画面描述**。"
        "\n\n约束："
        "\n1. 保留原场景、人物位置关系、情绪基调（比如「压抑的悲伤」→「克制地低头沉默」）"
        "\n2. 用肢体语言、光影、环境氛围、象征意象来代替具象负面描写"
        "\n3. 输出长度应与原句接近（短句写短，长句可稍长），仅输出改写后的纯文本"
        "\n4. 不要添加「画面中」「场景：」「图中」等引导词，直接输出描述"
        "\n5. 不要输出解释或 markdown"
    )
    user_msg = (
        f"原句:\n{sentence}\n\n"
        f"背景: 全书「{book_title}」，作者 {book_author}，"
        f"第 {segment_index + 1}/{total_segments} 个分镜。{context_block}\n\n"
        f"请只输出改写后的画面描述（不含引导词、不含解释）："
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as http:
            resp = await http.post(
                "https://api.deepseek.com/v1/chat/completions",
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.6,
                    "max_tokens": 200,
                },
                headers={
                    "Authorization": f"Bearer {deepseek_key}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                rewritten = data["choices"][0]["message"]["content"].strip()
                if rewritten and rewritten != sentence:
                    print(
                        f"[image:llm-sanitize] 段 {segment_index + 1} LLM 安全改写成功 "
                        f"({len(sentence)}→{len(rewritten)} 字)"
                    )
                    return rewritten
                else:
                    print(f"[image:llm-sanitize] 段 {segment_index + 1} LLM 返回与原文相同，跳过")
                    return sentence
            else:
                print(f"[image:llm-sanitize] DeepSeek API 错误 {resp.status_code}: {resp.text[:150]}")
                return sentence
    except httpx.TimeoutException:
        print(f"[image:llm-sanitize] 段 {segment_index + 1} 超时 (15s)，跳过")
        return sentence
    except Exception as e:
        print(f"[image:llm-sanitize] 段 {segment_index + 1} 异常: {type(e).__name__}: {e}")
        return sentence


def _build_generic_prompt(
    book_title: str,
    book_author: str,
    segment_index: int,
    total_segments: int,
    style_bible: str,
    aspect_ratio: str,
    visual_context: str = "",
) -> str:
    """当原文内容被所有内容审查拒绝后，构建不引用原文的通用配图 prompt。

    按分镜序号轮换场景模板；若有 visual_context，从档案中提取情绪基调
    和典型环境来影响场景选择，避免兜底图与故事整体氛围割裂。
    """
    # 8 套场景模板
    scenes = [
        ("温暖阳光透过窗格洒在书页上",
         "暖金色光线，微尘在光束中漂浮，画面安静克制"),
        ("一条延伸向远方的林间小路",
         "晨雾弥漫，路旁野花星星点点，逆光拍摄，空气通透"),
        ("一张老式木桌上摊开的笔记本和一支钢笔",
         "侧光从左边打来，桌面纹理清晰，笔尖有墨迹，极简构图"),
        ("傍晚时分远处山顶的天空剪影",
         "橙蓝渐变天色，山脊线干净利落，长焦远景，心境辽阔"),
        ("雨后的老街石板路，积水倒映着路灯",
         "湿润的反光，两侧老墙青苔斑驳，纵深构图，宁静克制"),
        ("厨房窗台上的玻璃花瓶，插着几枝野花",
         "逆光透射花瓣纹理，背景虚化成柔光斑，生活感静谧"),
        ("一个人站在海边，面向无尽的大海",
         "背影构图，海浪轻拍脚边，灰蓝色调，极简留白"),
        ("旧书架上排列整齐的书脊",
         "低饱和色彩，侧光勾勒书脊边缘，浅景深，知识氛围"),
    ]
    scene_desc, scene_light = scenes[segment_index % len(scenes)]

    # 从视觉档案提取 context_boost 注入风格描述
    context_boost = ""
    if visual_context.strip():
        # 提取档案中的情绪基调关键词
        mood_match = re.search(r'情绪基调[：:]\s*(.*)', visual_context, re.IGNORECASE)
        env_match = re.search(r'典型环境[：:]\s*(.*)', visual_context, re.IGNORECASE)
        body_match = re.search(r'身体特征[（(]极度重要.*?[）)]\s*[：:]\s*(.*)', visual_context, re.IGNORECASE | re.DOTALL)
        mood = mood_match.group(1).strip() if mood_match else ""
        env = env_match.group(1).strip() if env_match else ""
        body = body_match.group(1).strip() if body_match else ""
        parts = []
        if body and body != "无":
            parts.append(f"主人公固定身体特征：{body}")
        if env:
            parts.append(f"故事环境：{env}")
        if mood:
            parts.append(f"画面情绪：{mood}")
        if parts:
            context_boost = "；".join(parts)

    # 8:9 近方形卡片版式：额外构图约束（对标满宽大图展示区）
    if aspect_ratio == "8:9":
        aspect_line = (
            "8:9 近正方形竖版构图，主体居中、略偏上，四周留出呼吸空间，"
            "关键元素不贴边（成片满宽出血展示，无裁切余量）"
        )
    else:
        aspect_line = f"{aspect_ratio}，主体放在中央安全区，方便后期排版。"

    prompt = f"""为中文短视频口播生成一张独立意境配图。

最终用途:
这张图作为短视频的连续分镜之一，对应一段约 18 秒的口播配音。

画幅要求:
{aspect_line}

主题方向:
图书启发、认知成长、人生感悟、关系洞察、命运转折。

统一视觉风格:
{style_bible}

风格要求:
明亮电影感，真实摄影或高级插画风
光线自然，画面干净，低信息密度
与同一条视频的其他配图保持相同视觉调性
"""
    if context_boost:
        prompt += f"故事全局信息:{context_boost}\n"
    prompt += f"""
整条视频主题:{book_title}
书籍作者:{book_author}
当前分镜序号:第 {segment_index + 1}/{total_segments} 镜

本次画面主题:{scene_desc}
光线要求:{scene_light}

请生成一张意境配图。不要加任何文字。"""
    return prompt


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


def build_single_segment_prompt(
    text: str,
    book_title: str = "",
    book_author: str = "",
    segment_index: int = 0,
    total_segments: int = 1,
    style_bible: str = "",
    aspect_ratio: str = "9:16",
    visual_context: str = "",
) -> str:
    """
    构建单句配图 User Prompt（v4：单图直生，无九宫格）。

    新增 visual_context 参数：LLM 从改写稿中提取的主人公视觉档案，
    注入到每张图的 prompt 中，确保人物一致性。
    """
    if not style_bible:
        style_bible = STYLE_BIBLES.get("default", "")

    # 构建视觉档案注入段落（如果有的话）
    visual_block = ""
    if visual_context.strip():
        # 检测视觉档案是否涉及年龄跨度
        import re as _re
        _has_age_span = bool(_re.search(r'\d+岁[→\-~至到]+\d+岁|年龄|年龄段|年轻时|年轻时|年老时|中年|老年|少年|青年|老去|变老',
                                        visual_context))
        _age_note = ""
        if _has_age_span:
            _age_note = (
                "\n⚠️ 年龄动态提示：视觉档案描述的是角色一生的外貌变化范围，"
                "不是所有镜头的统一模板。请根据【当前段落文案】的具体剧情阶段来推断角色"
                "此时此刻的实际年龄和形象（少年/青年/中年/老年），不要把所有镜头都画成同一个年龄。"
            )
        visual_block = f"""\n\n配图视觉档案（角色可变特征参考，根据当前段落时间点灵活调整）：
{visual_context.strip()}
{_age_note}
"""

    # 8:9 近方形卡片版式：额外构图约束（对标满宽大图展示区）
    if aspect_ratio == "8:9":
        aspect_line = (
            "8:9 近正方形竖版构图，主体居中、略偏上，四周留出呼吸空间，"
            "关键元素不贴边（成片满宽出血展示，无裁切余量）"
        )
    else:
        aspect_line = f"{aspect_ratio}，主体放在中央安全区，方便后期排版。"

    prompt = f"""为中文短视频口播生成一张独立意境配图。

最终用途:
这张图作为短视频的连续分镜之一，对应一段约 18 秒的口播配音。

画幅要求:
{aspect_line}

主题方向:
图书启发、认知成长、人生感悟、关系洞察、命运转折。

统一视觉风格:
{style_bible}

风格要求:
明亮电影感，真实摄影或高级插画风
光线自然，画面干净，低信息密度
与同一条视频的其他配图保持相同视觉调性
{visual_block}
内容来源限制:
只参考当前段落文案，不引用原视频标题、账号、作者或来源信息。

整条视频主题:{book_title}
书籍作者:{book_author}
当前分镜序号:第 {segment_index + 1}/{total_segments} 镜

当前段落文案:
{text.strip()}

请直接生成单张配图。
不要在图片里放任何文字。
不要输出解释。"""
    return prompt


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

async def _generate_keling(prompt: str, size: str = "1080x1920") -> Optional[str]:
    """调用快手可灵 API 生成图片（兜底通道）。"""
    if not KELING_API_KEY:
        print("[image:keling] KELING_API_KEY 未设置，跳过")
        return None

    url = f"{KELING_BASE_URL}/images/generations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {KELING_API_KEY}",
    }

    payload = {
        "model": KELING_IMAGE_MODEL,
        "prompt": prompt,
        "n": 1,
        "size": size,
    }

    print(f"[image:keling] 尝试可灵 API")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code == 200:
            data = resp.json()
            images = data.get("data", [])
            if images and len(images) > 0:
                b64 = images[0].get("b64_json", "") or images[0].get("image_base64", "")
                if b64:
                    return b64
                url_val = images[0].get("url", "")
                if url_val:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as dl:
                        img_resp = await dl.get(url_val)
                        if img_resp.status_code == 200:
                            return base64.b64encode(img_resp.content).decode("utf-8")
            return None
        else:
            print(f"[image:keling] API 错误 {resp.status_code}: {resp.text[:300]}")
            return None

    except Exception as e:
        print(f"[image:keling] 异常: {type(e).__name__}: {e}")
        return None


# ============== 主入口：按句批量生图（v4 单图直生）==============

async def generate_all_images(
    task_id: int,
    db,
    style: str = "default",
    book_title: str = "",
    book_author: str = "",
    aspect_ratio: str = "9:16",
) -> dict:
    """
    v4 单图直生：每个句段独立请求 Fal.ai 生成一张高精单图。

    彻底废弃 v3 九宫格模式，解决：
    - 人像重影、肢体多指、面部表情扭曲崩坏
    - 裁切导致构图失控、焦点失焦

    流程:
    0. 从改写稿提取视觉档案（LLM）→ 注入全局人物一致性上下文
    1. 读取 rewritten.txt → split_into_short_sentences() 切句
    2. for each sentence → build_single_segment_prompt + visual_context + STYLE_PROMPT_MAP + SAFETY_SUFFIX
    3. Fal.ai gpt-image-2 单图直生（按 aspect_ratio 决定尺寸）
    4. PIL resize 到精确目标分辨率 → 写入 TaskImage 表
    5. 异常兜底：单张失败不阻塞后续 → 降敏 → 通用 prompt → 占位图

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
    if not visual_context.strip():
        print(f"[image:v4] 视觉档案未缓存 → LLM 提取中...")
        try:
            visual_context = await extract_visual_context(rewritten)
            if visual_context.strip():
                task.visual_context = visual_context
                db.commit()
                print(f"[image:v4] 视觉档案已缓存到 task.visual_context")
        except Exception as e:
            print(f"[image:v4] 视觉档案提取失败: {e}，跳过")
            visual_context = ""
    else:
        print(f"[image:v4] 使用已缓存的视觉档案 ({len(visual_context)} 字)")

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
            if os.path.exists(target_path) and os.path.getsize(target_path) > 1000:
                print(f"[image:v4] 段 {seg_idx + 1}/{total_segments} 已存在（并发检测），跳过")
                return {"seg_idx": seg_idx, "status": "skipped", "target_path": target_path}

            text_len = len(sentence.strip())
            print(
                f"[image:v4] 段 {seg_idx + 1}/{total_segments}: "
                f"{text_len} 字, size={REQUEST_W}x{REQUEST_H}, aspect={aspect_ratio}"
            )

            # ★ 情绪检测：自动匹配最贴合文案氛围的 Style Bible
            sentence_style = _detect_sentence_mood(sentence, visual_context)
            if sentence_style != "default":
                actual_style_bible = STYLE_BIBLES.get(sentence_style, style_bible)
                actual_style_suffix = STYLE_PROMPT_MAP.get(sentence_style, STYLE_PROMPT_MAP["default"])
            else:
                actual_style_bible = style_bible
                actual_style_suffix = STYLE_PROMPT_MAP.get(style, STYLE_PROMPT_MAP["default"])

            # 构建 Prompt
            base_prompt = build_single_segment_prompt(
                text=sentence,
                book_title=book_title,
                book_author=book_author,
                segment_index=seg_idx,
                total_segments=total_segments,
                style_bible=actual_style_bible,
                aspect_ratio=aspect_ratio,
                visual_context=visual_context,
            )
            final_prompt = base_prompt + actual_style_suffix + SAFETY_SUFFIX

            # 保存 prompt 到文件
            prompt_path = os.path.join(images_dir, f"seg_{seg_idx:03d}_prompt.txt")
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(final_prompt)

            # 多通道生图（fal → sanitized → generic → keling → sanitized keling）
            img_bytes = None
            error_msg = ""
            try:
                b64 = await _generate_fal(final_prompt, width=REQUEST_W, height=REQUEST_H, quality=quality)
                if b64:
                    img_bytes = base64.b64decode(b64)
                else:
                    # fal 失败 → 降敏重试
                    sanitized = _sanitize_prompt(final_prompt)
                    if sanitized != final_prompt:
                        print(f"[image:v4] 段 {seg_idx + 1} fal 首次失败 → 降敏重试")
                        b64 = await _generate_fal(sanitized, width=REQUEST_W, height=REQUEST_H, quality=quality)
                        if b64:
                            img_bytes = base64.b64decode(b64)
                            final_prompt = sanitized

                    # sanitized 也失败 → LLM 语义安全改写（保留同场景同情绪，去掉触发审查的具象描写）
                    generic = None
                    if not img_bytes:
                        print(f"[image:v4] 段 {seg_idx + 1} 降敏仍失败 → LLM 安全改写")
                        safe_sentence = await _llm_sanitize_segment(
                            sentence=sentence,
                            book_title=book_title,
                            book_author=book_author,
                            segment_index=seg_idx,
                            total_segments=total_segments,
                            visual_context=visual_context,
                        )
                        if safe_sentence != sentence:
                            # 用 LLM 改写后的句子重建 prompt
                            llm_base = build_single_segment_prompt(
                                text=safe_sentence,
                                book_title=book_title,
                                book_author=book_author,
                                segment_index=seg_idx,
                                total_segments=total_segments,
                                style_bible=actual_style_bible,
                                aspect_ratio=aspect_ratio,
                                visual_context=visual_context,
                            )
                            llm_prompt = llm_base + actual_style_suffix + SAFETY_SUFFIX
                            print(f"[image:v4] 段 {seg_idx + 1} LLM 改写完成 → 重试 Fal.ai")
                            b64 = await _generate_fal(llm_prompt, width=REQUEST_W, height=REQUEST_H, quality=quality)
                            if b64:
                                img_bytes = base64.b64decode(b64)
                                final_prompt = llm_prompt
                                print(f"[image:v4] 段 {seg_idx + 1} LLM 改写后生图成功")

                    # LLM 改写也失败 → 通用 prompt 兜底
                    if not img_bytes:
                        generic = _build_generic_prompt(
                            book_title=book_title, book_author=book_author,
                            segment_index=seg_idx, total_segments=total_segments,
                            style_bible=actual_style_bible, aspect_ratio=aspect_ratio,
                            visual_context=visual_context,
                        )
                        generic += actual_style_suffix + SAFETY_SUFFIX
                        print(f"[image:v4] 段 {seg_idx + 1} 降敏仍失败 → 通用 prompt 兜底")
                        b64 = await _generate_fal(generic, width=REQUEST_W, height=REQUEST_H, quality=quality)
                        if b64:
                            img_bytes = base64.b64decode(b64)
                            final_prompt = generic

                    if not img_bytes:
                        # fal 全部失败 → 可灵
                        keling_size = f"{TARGET_W}x{TARGET_H}"
                        b64 = await _generate_keling(final_prompt, size=keling_size)
                        if b64:
                            img_bytes = base64.b64decode(b64)
                        elif sanitized != final_prompt:
                            b64 = await _generate_keling(sanitized, size=keling_size)
                            if b64:
                                img_bytes = base64.b64decode(b64)
                                final_prompt = sanitized
                            elif generic is not None:
                                b64 = await _generate_keling(generic, size=keling_size)
                                if b64:
                                    img_bytes = base64.b64decode(b64)
                                    final_prompt = generic
                                else:
                                    error_msg = "所有生图通道均失败"
                            else:
                                error_msg = "所有生图通道均失败"
                        else:
                            error_msg = "所有生图通道均失败"
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
) -> dict:
    """
    v4 单段配图重跑：单张独立生图（高精直出，不走九宫格）。
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
    sentence_style = _detect_sentence_mood(text, visual_context)
    if sentence_style != "default":
        actual_style_bible = STYLE_BIBLES.get(sentence_style, style_bible)
        actual_style_suffix = STYLE_PROMPT_MAP.get(sentence_style, STYLE_PROMPT_MAP["default"])
    else:
        actual_style_bible = style_bible
        actual_style_suffix = STYLE_PROMPT_MAP.get(style, STYLE_PROMPT_MAP["default"])

    # 构建 Prompt + 视觉档案 + 风格后缀 + 安全补丁
    base_prompt = build_single_segment_prompt(
        text=text,
        book_title=book_title,
        book_author=book_author,
        segment_index=segment_index,
        total_segments=len(sentences),
        style_bible=actual_style_bible,
        aspect_ratio=aspect_ratio,
        visual_context=visual_context,
    )
    prompt = base_prompt + actual_style_suffix + SAFETY_SUFFIX

    print(f"[image:single] 单句配图 task={task_id} sent={segment_index}, text_len={len(text)}, aspect={aspect_ratio}")

    b64 = await _generate_fal(prompt, width=REQUEST_W, height=REQUEST_H, quality=quality)
    if not b64:
        # fal 失败 → 降敏重试
        sanitized = _sanitize_prompt(prompt)
        if sanitized != prompt:
            print(f"[image:single] fal 首次失败 → 降敏重试")
            b64 = await _generate_fal(sanitized, width=REQUEST_W, height=REQUEST_H, quality=quality)
            if b64:
                prompt = sanitized
        # sanitized 也失败 → LLM 语义安全改写（保留同场景同情绪）
        generic = None
        if not b64:
            print(f"[image:single] 降敏仍失败 → LLM 安全改写")
            safe_text = await _llm_sanitize_segment(
                sentence=text,
                book_title=book_title,
                book_author=book_author,
                segment_index=segment_index,
                total_segments=len(sentences),
                visual_context=visual_context,
            )
            if safe_text != text:
                llm_base = build_single_segment_prompt(
                    text=safe_text,
                    book_title=book_title,
                    book_author=book_author,
                    segment_index=segment_index,
                    total_segments=len(sentences),
                    style_bible=actual_style_bible,
                    aspect_ratio=aspect_ratio,
                    visual_context=visual_context,
                )
                llm_prompt = llm_base + actual_style_suffix + SAFETY_SUFFIX
                print(f"[image:single] LLM 改写完成 → 重试 Fal.ai")
                b64 = await _generate_fal(llm_prompt, width=REQUEST_W, height=REQUEST_H, quality=quality)
                if b64:
                    prompt = llm_prompt
                    print(f"[image:single] LLM 改写后生图成功")

        # LLM 改写也失败 → 通用 prompt 兜底（完全去掉原文避免上下文级审查）
        if not b64:
            generic = _build_generic_prompt(
                book_title=book_title, book_author=book_author,
                segment_index=segment_index, total_segments=len(sentences),
                style_bible=actual_style_bible, aspect_ratio=aspect_ratio,
                visual_context=visual_context,
            )
            generic += actual_style_suffix + SAFETY_SUFFIX
            print(f"[image:single] 降敏仍失败 → 通用 prompt 兜底")
            b64 = await _generate_fal(generic, width=REQUEST_W, height=REQUEST_H, quality=quality)
            if b64:
                prompt = generic
        if not b64:
            # 尝试可灵
            keling_size = f"{TARGET_W}x{TARGET_H}"
            b64 = await _generate_keling(prompt, size=keling_size)
            if not b64 and sanitized != prompt:
                b64 = await _generate_keling(sanitized, size=keling_size)
                if b64:
                    prompt = sanitized
                elif generic is not None:
                    b64 = await _generate_keling(generic, size=keling_size)
                    if b64:
                        prompt = generic
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
