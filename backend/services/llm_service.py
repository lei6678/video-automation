"""
大模型清洗服务 - DeepSeek API
"""
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv
from sqlalchemy.orm import Session

# 加载环境变量
load_dotenv()

# 初始化 DeepSeek 客户端
client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

SYSTEM_PROMPT = """你是逐字稿修复清洗助手。你需要在保留事实和原文顺序的前提下，删除非正文噪声，修复乱码和明显ASR同音错词。你必须同时遵守视频号内容安全要求，避免输出任何低俗、暴力、虚假夸大、医疗承诺、导流诱导或误导性表达。输出必须是清洗后的纯正文。"""


def build_user_prompt(transcript: str, keyword: str = "", title: str = "", author: str = "") -> str:
    """构建用户 Prompt"""
    return f"""请对下面的逐字稿做修复型清洗。
  你可以做的事:
  1. 删除明显属于原博主的栏目口号、作者自称、互动引导、导流主页、平台水印、往期节目提示等非正文钩子。
  2.删除跨平台搬运水印，例如'优优独播剧场一YoYo Television Series Exclusive'、'谢谢观看'。
  3.删除明显重复拼接的段落，只保留一次。
  4.对乱码符号和明显ASR同音错词做上下文推测修复，例如"轻运"应结合语境修成"清运"，"飘铃/飘龄"应结合语境修成"嘌呤"，"这不手几"应结合语境修成"这部手机"。
  5.适度补充必要标点，让正文可读。
  6.进一步删除或改写视频号高风险表达:低俗擦边、血腥暴力、虚假夸大、医疗承诺、诱导互动、导流私信/评论区/主页、恐吓式逼单、伪装权威结论。
  严禁做的事:
  1.不要改写观点、人物、时间、数字、案例和核心事实。
  2.不要概括、扩写、重排正文结构。
  3.不要输出标题、解释、Markdown、修改说明。
  如果不确定某个词该怎么修，就保留原词，不要编造新信息。
  主题关键词:{keyword}
  原视频标题:{title}
  原作者标识:{author}
  请基于下面的原始逐字稿，返回修复清洗后的正文:{transcript}"""


async def clean_asr_text(
    transcript: str,
    keyword: str = "",
    title: str = "",
    author: str = ""
) -> str:
    """
    调用 DeepSeek API 清洗 ASR 逐字稿

    Args:
        transcript: 原始逐字稿
        keyword: 主题关键词
        title: 原视频标题
        author: 作者标识

    Returns:
        清洗后的文本
    """
    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(transcript, keyword, title, author)}
        ],
        temperature=0.3,
        max_tokens=4096
    )

    return response.choices[0].message.content or ""


# ============== 脚本改写函数 =============

SYSTEM_PROMPT_REWRITE = """# Role: 短视频（抖音/快手/视频号）爆款故事文案改写大师

## Profile
你是一个部署在自动化生产线 API 环境中的顶级故事文案洗稿过审专家。你极其擅长用【最接地气的民间拉家常口吻】讲故事，同时能巧妙避开平台的文案查重机制。你的改写兼具"市井烟火气"与"高光时刻直击人心的力量"。

## 核心死律（任何情况下违背均会导致系统级崩溃）

1. 绝对格式死律 (Anti-Markdown & Zero-Noise)：
   - 严禁输出任何 Markdown 标签（严禁出现 #, *, -, >, _, ` 等符号），严禁包含任何小标题。
   - 严禁输出任何引言、结束语、客套话、括号备注（例如严禁输出"为您改写如下："或"（此处语气加重）"或"[背景音乐]"）。
   - 严禁一句一换行！必须按照正常的叙事逻辑划分自然段落，呈现出自然的段落块状。

2. 极端数字汉化与格式死律 (Total Number Sinicization)：
   - 最终输出的文案中，绝对不允许出现任何一个阿拉伯数字（0-9）或百分号（%）。
   - 必须将所有数字、年份、百分比、金额全部转换为对应的【简体中文纯汉字】读法。
   - 规范：[1924年] 变 [一九二四年]；[120斤] 变 [一百二十斤]；[20%] 变 [百分之二十]。

3. 骨架与爆点铁壁 (Skeleton Preservation)：
   - 首尾雷打不动：原文的第一句（前3-5秒爆款引子）必须【逐字保留，100%原封不动】，严禁修改任何一个字！结尾的升华和点赞引导也必须保持原有逻辑。
   - 核心资产留存：故事的时空线、关键数字、人物姓名、人物对话的原始意思必须 100% 完整保留，严禁删减核心情节。

4. 爆款标题生成规则 (Viral Title Generation)：
   你必须基于故事内容设计【1个】极具情绪张力、方便做视频封面的爆款标题。
   - 字数限制：严格控制在 15-25 字以内。
   - 公式二选一，必须严格符合且仅符合以下爆款公式之一：
     公式一（极限反差法）：[极弱/极惨的主角人设] + [极强/极高光的逆袭/坚守结果]（如：10岁失去双臂的男孩，用脚弹上金色大厅）
     公式二（数字具象化）：用最极端的对比数字，将主角的苦难或执念放大到极致（如：一根扁担挑大7个弟妹的山西大哥）
   - 【数字表现红线】：标题内所有涉及的数字，在标题里必须严格使用"阿拉伯数字"（如：10岁、7个、6000公里）。改写后的文案正文主体内，所有涉及的数字必须全部使用"中文汉字"（如：十岁、七个、六千公里）。两者在代码输出前必须做好分流过滤！
   - 输出格式：必须输出严格的 JSON，不带任何 Markdown 代码块或解释文字。格式为：
     {"title": "生成的爆款标题", "rewritten_transcript": "改写后的口播纯正文"}"""

SYSTEM_PROMPT_LIGHT_DEDUP = SYSTEM_PROMPT_REWRITE

USER_PROMPT_REWRITE = """请使用以下【市井烟火气对抗型洗稿技术】对目标原文进行改写。

## 强控级改写业务指令：

1. 【彻底去掉AI味，主打民间口播口吻】：
   - 拒绝翻译感、拒绝车轱辘话和机械因果关系。说话要像一个活生生的、有血有肉的人在聊天，多用老百姓听得懂、感觉亲切的市井大白话。
   - 句式要极短，多用逗号。改写的手段是"换大白话和画面感的说法"，而不是生硬找同义词，必须保证AI配音读起来顺口、有呼吸感。
   - 示例：将"成婚数载"改为"结婚几年"；将"潜回上海"改为"偷偷回到上海"。

2. 【保留适度词汇，让文案有深度质感】：
   - 虽然主打民间口语，但不需要死板地避免所有庄重或文艺词汇。
   - 在故事的【高光时刻、转折点、或情感爆发处】，要正常保留或适当加入一些有分量、有深度的词（如：命里的刀锋、傲骨嶙峋、死不瞑目、撒手人寰等），用这些词来给故事定调，让文案显得有质感，不廉价。

3. 【自然融入三大爆款去重逻辑（切忌用力过猛，要自然过渡）】：
   - 【第二人称代入法】：在需要引起共鸣的过渡段，适度用"如果你"、"换作是你"拉近与观众的距离，打破原有句式。
   - 【细节具象化法】：把原视频中抽象、概括的词，翻译成大白话的生活细节或画面（例如：把"不开心"改写为"天天看着围墙里的四角天空，心里直发堵"），为后续AI配图留出空间。
   - 【旁观者冷眼对比法】：如果故事涉及冲突或逆袭，适度放大"周围看热闹、嚼舌根的人"的冷言冷语，再用主角的行动狠狠打脸，拉满情绪张力。

4. 【破除连续七字死律】：
   - 除原封不动保留的第一句、汉化数字和人名外，文中严禁连续出现 7 个以上与原文完全相同的汉字。一旦超过，必须通过上述动作、画面、口语垫字进行像素级打碎。

5. 【字数控制】：
   - 改写后的文案总字数与原文案总字数的差异必须控制在增减 10% 到 15% 的范围内，不得大幅缩水或膨胀。

## 输出格式
你的输出必须是纯 JSON，不带任何 Markdown 代码块（严禁 ```json 或 ``` 围栏），不带任何解释或废话。
格式示例：{"title":"爆款标题(15-25字，阿拉伯数字)","rewritten_transcript":"口播纯正文(全部中文汉字)"}

## 目标原文（由下游脚本动态传入）：
\"\"\"
{cleaned_text}
\"\"\""""

USER_PROMPT_LIGHT_DEDUP = USER_PROMPT_REWRITE


async def rewrite_script(task_id: int, cleaned_text: str, mode: str, db: Session) -> dict:
    """
    调用 DeepSeek API 对清洗后的正文进行改写，同时生成爆款标题。

    Args:
        task_id: 任务 ID
        cleaned_text: 清洗后的正文
        mode: 改写模式，"rewrite"（深度改写）或 "light_dedupe"（轻量去重）
        db: 数据库会话

    Returns:
        {"rewritten_transcript": str, "video_title": str}
    """
    import json as _json

    # 验证 Task 存在
    from models import Task
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise ValueError(f"[llm_service] 任务 {task_id} 不存在")

    # 两个模式共用同一套洗稿过审专家提示词
    if mode not in ("rewrite", "light_dedupe"):
        raise ValueError(f"[llm_service] 未知改写模式: {mode}，请使用 'rewrite' 或 'light_dedupe'")

    user_prompt = USER_PROMPT_REWRITE.format(cleaned_text=cleaned_text)

    print(f"[llm_service] rewrite_script 模式: {mode}, task_id: {task_id}")

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_REWRITE},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    print(f"[llm_service] rewrite_script 原始返回前 200 字符: {raw[:200]}")

    # 清理可能的 markdown 代码块围栏
    raw_clean = raw.strip()
    if raw_clean.startswith("```"):
        # 去掉 ```json 或 ``` 围栏
        raw_clean = raw_clean.split("\n", 1)[-1] if "\n" in raw_clean else raw_clean[3:]
        if raw_clean.endswith("```"):
            raw_clean = raw_clean[:-3]
        raw_clean = raw_clean.strip()

    try:
        parsed = _json.loads(raw_clean)
        rewritten = parsed.get("rewritten_transcript", "")
        video_title = parsed.get("title", "")
    except _json.JSONDecodeError:
        # 解析失败：全文当作正文，标题留空
        print(f"[llm_service] JSON 解析失败，回退为纯文本")
        rewritten = raw
        video_title = ""

    if not rewritten.strip():
        rewritten = raw  # 极端兜底

    # 存入数据库
    task.rewritten_transcript = rewritten
    if video_title:
        task.video_title = video_title
    db.commit()

    print(f"[llm_service] rewrite_script 完成: 正文 {len(rewritten)} 字, 标题: {video_title[:30] if video_title else '(无)'}")
    return {"rewritten_transcript": rewritten, "video_title": video_title}


# ============== 书籍信息反推函数 =============

SYSTEM_PROMPT_BOOK_INFO = """你是中文图书短视频的信息抽取助手。你的任务是从原视频标题、描述、逐字稿或清洗文案中识别被讲解/带货的书籍名和作者名。只抽取文本中能支持的信息，不能根据主题猜书，不能编造作者。书籍名只保留书名本体，不带书名号《》，不带'经典解读'等营销词。作者名保留国别或地区前缀和中文译名，格式优先使用全角方括号，例如[美]彼得·阿提亚。如果无法可靠识别某字段，输出空字符串。严格输出 JSON: {"book_title":"","book_author":"","confidence":0.0, "evidence":""}。confidence是0到1的数字；evidence用一句中文说明依据。禁止markdown、解释、代码围栏。"""


async def extract_book_info(task_id: int, db: Session) -> dict:
    """
    从任务的 douyin_meta 和文案中反推书籍信息

    Args:
        task_id: 任务 ID
        db: 数据库会话

    Returns:
        包含 book_title, book_author, confidence, evidence 的字典
    """
    from models import Task
    import json

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise ValueError(f"[llm_service] 任务 {task_id} 不存在")

    douyin_meta = task.douyin_meta or {}
    title = douyin_meta.get("title", "") or ""
    desc = douyin_meta.get("desc", "") or ""

    # 优先使用改写稿，其次清洗稿，最后原始稿
    text = task.rewritten_transcript or task.raw_transcript or ""

    user_prompt = f"原视频标题:{title}\n原视频描述:{desc}\n文案:\n{text}\n请识别书籍名和作者名并输出纯 JSON。"

    print(f"[llm_service] extract_book_info task_id: {task_id}")

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_BOOK_INFO},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.05,
        max_tokens=512,
        response_format={"type": "json_object"}
    )

    raw = response.choices[0].message.content or "{}"
    print(f"[llm_service] extract_book_info 原始返回: {raw[:200]}")

    try:
        result = json.loads(raw)
    except Exception:
        result = {"book_title": "", "book_author": "", "confidence": 0.0, "evidence": "JSON解析失败"}

    return {
        "book_title": result.get("book_title", ""),
        "book_author": result.get("book_author", ""),
        "confidence": float(result.get("confidence", 0.0)),
        "evidence": result.get("evidence", ""),
    }


# ============== 智能配音拆段（LLM 语义切段）==============

SYSTEM_PROMPT_SEGMENT = """你是中文短视频口播的配音拆段助手。你的任务是把改写后的完整口播稿拆成适合 TTS 配音的自然段落。

硬性要求:
- 必须在语义自然、语气停顿的地方切分，绝对不能机械硬切
- 单段口播时长控制在 24~28 秒内（按中文口播 ~3.5 字/秒估算，即 84~98 字/段）
- 每个段落必须是完整独立的语义单元（一段话把一个小观点讲完，不截断因果链）
- 段落之间在逻辑上是连续递进的，保持原文叙事节奏
- 保留原文所有内容，不增不减不改，不调整顺序
- 如果原文最后一段不足 24 秒口播量，也要单独成段，不要强行合并

输出格式: 纯 JSON
{"segments": ["段落1全文", "段落2全文", ...]}
不要输出 markdown、代码围栏、解释或任何非 JSON 内容。"""


async def segment_for_tts(text: str) -> list[str]:
    """
    调用 DeepSeek API 把口播稿智能拆成 TTS 配音段落（每段 24-28 秒口播时长）

    Args:
        text: 改写后的完整口播稿

    Returns:
        段落文本列表
    """
    import json as _json

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_SEGMENT},
            {"role": "user", "content": f"请将以下口播稿拆成适合配音的自然段落（每段 84~98 字，即约 24~28 秒口播时长）：\n\n{text}"}
        ],
        temperature=0.3,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    print(f"[llm:segment] 原始返回前 200 字符: {raw[:200]}")

    try:
        result = _json.loads(raw)
        segments = result.get("segments", [])
        if not segments:
            print("[llm:segment] LLM 返回空 segments，回退到原文")
            return [text]
        # 校验：确保拼接后原文不丢失（允许标点和空白差异）
        joined = "".join(segments)
        if len(joined.replace(" ", "").replace("\n", "")) < len(text.replace(" ", "").replace("\n", "")) * 0.9:
            print(f"[llm:segment] WARNING: 拼接后长度 ({len(joined)}) 明显短于原文 ({len(text)})，可能有截断")
        print(f"[llm:segment] 智能拆段完成: {len(text)} 字 → {len(segments)} 段")
        return segments
    except _json.JSONDecodeError as e:
        print(f"[llm:segment] JSON 解析失败: {e}，回退到原文")
        return [text]


# ============== 短句切分（用于配图 — v3: 强标点 + 长句适配）==============

def split_into_short_sentences(text: str, max_chars: int = 80, min_chars: int = 30) -> list[str]:
    """
    把口播稿按其标点切分为短句，用于配图分镜。

    大佬经验: 只按强标点（。！？）切分，不按逗号切。
    ~4000 字 → ~63 句 → 7 组九宫格 → 63 张分镜图。
    每句约 60~65 字，对应约 18 秒口播——刚好是一张 Ken Burns 图的自然展示时长。

    Args:
        text: 改写后的完整口播稿
        max_chars: 单句最大字数（默认 80，只对特别长的句子进一步断句）
        min_chars: 单句最小字数（低于此值则与前句合并）

    Returns:
        短句列表
    """
    import re as _re

    # 第一步：只按强标点切分（。！？ + 换行）
    raw = _re.split(r'(?<=[。！？\n])', text)
    sentences = []

    for chunk in raw:
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) <= max_chars:
            sentences.append(chunk)
        else:
            # 第二步：超长句才进一步按分号/冒号切分（不按逗号切）
            sub = _re.split(r'(?<=[；;：:])', chunk)
            cur = ""
            for part in sub:
                part = part.strip()
                if not part:
                    continue
                if len(cur) + len(part) <= max_chars:
                    cur += part
                else:
                    if cur.strip():
                        sentences.append(cur.strip())
                    # 如果还超长，按 max_chars 硬切（极少见）
                    if len(part) > max_chars:
                        for k in range(0, len(part), max_chars):
                            sentences.append(part[k:k + max_chars].strip())
                        cur = ""
                    else:
                        cur = part
            if cur.strip():
                sentences.append(cur.strip())

    # 第三步：合并过短的句子（min_chars 以下）
    merged = []
    buffer = ""
    for s in sentences:
        if not buffer:
            buffer = s
        elif len(buffer) < min_chars or len(buffer) + len(s) <= max_chars:
            buffer += s
        else:
            merged.append(buffer)
            buffer = s
    if buffer:
        if merged and len(buffer) < min_chars:
            merged[-1] += buffer
        else:
            merged.append(buffer)

    avg = len(text) / max(1, len(merged))
    print(f"[llm:split-sent] 全文 {len(text)} 字 → {len(merged)} 句, 平均 {avg:.0f} 字/句 (max={max_chars})")
    return merged