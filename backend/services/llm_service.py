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

# 提示词文件目录
import os as _os
_PROMPTS_DIR = _os.path.join(_os.path.dirname(__file__), "..", "prompts")

# 提示词缓存（文件内容只在模块首次使用时加载一次）
_PROMPT_CACHE: dict[str, str] = {}

def _load_prompt(filename: str) -> str:
    """从 prompts/ 目录加载提示词文件，带内存缓存"""
    if filename not in _PROMPT_CACHE:
        filepath = _os.path.join(_PROMPTS_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                _PROMPT_CACHE[filename] = f.read()
            print(f"[llm_service] 加载提示词文件: {filename}")
        except FileNotFoundError:
            print(f"[llm_service] WARNING: 提示词文件缺失 {filepath}，请创建该文件")
            _PROMPT_CACHE[filename] = ""
    return _PROMPT_CACHE[filename]


async def extract_visual_context(rewritten_text: str) -> str:
    """从改写稿中提取主人公视觉档案，用于配图人物一致性。

    调用 DeepSeek API 分析文案，返回一份包含角色外貌、身体特征、
    时代背景、典型环境、情绪基调的文本档案。每次配图时会注入此档案。

    成本: ~1000 token 输入 + ~200 token 输出，约 ¥0.002
    """
    if not rewritten_text.strip():
        return ""

    context_template = _load_prompt("image_context.txt")
    user_prompt = context_template.replace("{rewritten_text}", rewritten_text)

    print(f"[llm_service] 提取视觉档案, 文案长度: {len(rewritten_text)} 字")

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是一个严谨的视觉档案提取助手。只提取文案中明确提到的信息，不要编造任何细节。"},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1,
        max_tokens=1024,
    )

    result = response.choices[0].message.content or ""
    print(f"[llm_service] 视觉档案提取完成: {len(result)} 字")
    print(f"[llm_service] 视觉档案内容:\n{result[:300]}")
    return result.strip()


async def rewrite_script(task_id: int, cleaned_text: str, db: Session, mode: str = "rewrite") -> dict:
    """
    双 pass 架构：Pass 1 检索人物背景知识 → Pass 2 基于知识改写。
    解决 API 模式下 deepseek-chat 不会主动"回忆"预训练知识的问题。
    """
    import json as _json
    import re as _re

    # 验证 Task 存在
    from models import Task
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise ValueError(f"[llm_service] 任务 {task_id} 不存在")

    # ── Pass 1: 人物背景知识检索 ──
    print(f"[llm_service] Pass 1: 人物背景知识检索, task_id: {task_id}")
    research_template = _load_prompt("rewrite_research.txt")
    research_prompt = research_template.replace("{cleaned_text}", cleaned_text)

    research_response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是一个人物背景知识检索助手。你的唯一任务是从文本中识别主角，列出你预训练记忆中关于他们的所有已知信息。不要改写，不要评价，只输出事实。"},
            {"role": "user", "content": research_prompt}
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    background_knowledge = research_response.choices[0].message.content or ""
    print(f"[llm_service] Pass 1 完成: 检索到 {len(background_knowledge)} 字背景知识")
    print(f"[llm_service] Pass 1 前 150 字符: {background_knowledge[:150]}")

    # ── Pass 2: 基于背景知识改写 ──
    print(f"[llm_service] Pass 2: 融合背景知识改写, task_id: {task_id}")
    system_prompt = _load_prompt("rewrite_system.txt")
    user_template = _load_prompt("rewrite_user.txt")
    user_prompt = user_template.replace("{background_knowledge}", background_knowledge).replace("{cleaned_text}", cleaned_text)

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.9,
        max_tokens=8192,
    )

    raw = response.choices[0].message.content or ""
    print(f"[llm_service] Pass 2 原始返回前 200 字符: {raw[:200]}")

    # ── 多策略提取 JSON ──
    rewritten = ""
    video_title = ""

    # 策略 1：直接 json.loads
    raw_clean = raw.strip()
    if raw_clean.startswith("```"):
        raw_clean = _re.sub(r'^```(?:json)?\s*', '', raw_clean)
        raw_clean = _re.sub(r'\s*```$', '', raw_clean)
        raw_clean = raw_clean.strip()
    try:
        parsed = _json.loads(raw_clean)
        rewritten = parsed.get("rewritten_transcript", "")
        video_title = parsed.get("title", "")
        if rewritten.strip():
            print(f"[llm_service] 策略1 (直接JSON) 成功: 正文 {len(rewritten)} 字, 标题: {video_title[:30] if video_title else '(无)'}")
    except _json.JSONDecodeError:
        # 策略 2：正则从全文提取 JSON 对象
        json_pattern = _re.compile(r'\{\s*"title"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"rewritten_transcript"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}', _re.DOTALL)
        match = json_pattern.search(raw)
        if match:
            for label, target in [("标题", "video_title"), ("正文", "rewritten")]:
                raw_val = match.group(1) if target == "video_title" else match.group(2)
                try:
                    decoded = _json.loads(f'"{raw_val}"')
                except _json.JSONDecodeError:
                    decoded = _re.sub(r'\\(.)', r'\1', raw_val)
                if target == "video_title":
                    video_title = decoded
                else:
                    rewritten = decoded
            print(f"[llm_service] 策略2 (正则提取JSON) 成功: 正文 {len(rewritten)} 字, 标题: {video_title[:30]}")
        else:
            # 策略 3：分别正则提取
            title_m = _re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
            if title_m:
                try:
                    video_title = _json.loads(f'"{title_m.group(1)}"')
                except _json.JSONDecodeError:
                    video_title = _re.sub(r'\\(.)', r'\1', title_m.group(1))
                print(f"[llm_service] 策略3 提取标题: {video_title[:40]}")
            body_m = _re.search(r'"rewritten_transcript"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
            if body_m:
                try:
                    rewritten = _json.loads(f'"{body_m.group(1)}"')
                except _json.JSONDecodeError:
                    rewritten = _re.sub(r'\\(.)', r'\1', body_m.group(1))
                print(f"[llm_service] 策略3 提取正文: {len(rewritten)} 字")
            else:
                # 策略 4：全文回退
                print(f"[llm_service] 所有JSON提取策略失败，全文回退为纯文本")
                rewritten = raw
                lines = raw.strip().split("\n")
                first_line = lines[0].strip() if lines else ""
                if first_line and len(first_line) <= 30 and not first_line.startswith("{"):
                    video_title = first_line

    if not rewritten.strip():
        rewritten = raw

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


# ============== 对标卡片标题两行拆分 ==============

SYSTEM_PROMPT_TITLE_SPLIT = """你是中文短视频的封面标题排版师。把给定的视频标题/主题拆成上下两行，用于竖版成片顶部的双色大标题。

排版规则:
- 第一行是铺垫短行（白色展示），4~8 个字，交代对象或背景
- 第二行是点题长行（金色展示），6~11 个字，给出核心观点/悬念/情绪钩子，必须比第一行更有分量
- 两行连读语义通顺，有递进或转折的节奏感
- 不加书名号以外的标点，不用英文
- 若原标题过长，允许提炼改写，但不能偏离原意

输出格式: 纯 JSON
{"line1": "第一行文本", "line2": "第二行文本"}
不要输出 markdown、代码围栏、解释或任何非 JSON 内容。"""


async def split_title_two_lines(title: str, book_title: str = "", book_author: str = "") -> dict:
    """
    把标题拆成对标卡片版式的两行：白色铺垫短行 + 金色点题长行。

    Args:
        title: 原始标题/主题句
        book_title: 书名（可选，辅助上下文）
        book_author: 作者（可选）

    Returns:
        {"line1": str, "line2": str}
    """
    import json

    fallback = {"line1": "", "line2": title.strip()}
    if not title.strip():
        return {"line1": "", "line2": ""}

    context = ""
    if book_title:
        context = f"\n关联书籍:《{book_title}》{book_author}"

    user_prompt = f"视频标题:{title.strip()}{context}\n请拆成两行并输出纯 JSON。"

    print(f"[llm_service] split_title_two_lines: {title[:40]}")

    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_TITLE_SPLIT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=256,
            response_format={"type": "json_object"}
        )
        raw = response.choices[0].message.content or "{}"
        result = json.loads(raw)
        line1 = (result.get("line1") or "").strip()
        line2 = (result.get("line2") or "").strip()
        if not line2:
            return fallback
        return {"line1": line1, "line2": line2}
    except Exception as e:
        print(f"[llm_service] split_title_two_lines 失败: {e}，回退单行")
        return fallback


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