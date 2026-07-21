"""
视频合成服务 — v3 1:1 绑定版
=============================
核心重构（2026-07-10）：
1. 【1:1 绝对绑定】画面、字幕、音频以生图句子为最小单位，杜绝二次切分
2. 【电影级 Ken Burns】每图动态计算 zoom_speed，全程缓慢推进至 max_zoom
3. 【黄色字幕】高曝光 #FFCC00，位置防遮挡，加大行距适配中老年
4. 【GBK 修复】所有 subprocess 强制 utf-8，errors='replace'
5. 【剪映草稿】同步导出符合剪映标准的 draft_content.json
"""

import asyncio
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Optional

# ============== 系统级 GBK 修复 ==============

def _run_ffmpeg(cmd: list[str], timeout: int = 180, description: str = "") -> subprocess.CompletedProcess:
    """
    FFmpeg 安全封装 —— 本模块所有 subprocess 调用的【唯一入口】。

    强制 utf-8 编码 + errors="replace"，彻底消灭 Windows GBK/CP936 乱码。
    全后端 9 处 subprocess.run() 调用均已验证具备 encoding="utf-8", errors="replace"：
      - video_service.py: _run_ffmpeg (所有 FFmpeg 调用)
      - main.py: _create_silent_audio, _merge_segments
      - tts_service.py: merge_audio_ffmpeg, _write_silent_placeholder
      - siliconflow_tts_service.py: _get_audio_duration (×3), ffmpeg concat

    任何新开发者：请勿直接调用 subprocess.run()，统一走此函数。
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return result
    except subprocess.TimeoutExpired:
        print(f"[video:ffmpeg] 超时 ({timeout}s): {description}")
        raise
    except Exception as e:
        print(f"[video:ffmpeg] 异常: {type(e).__name__}: {e} | {description}")
        raise


# ============== 辅助工具 ==============

def _find_chinese_font() -> str:
    """
    查找系统可用的中文字体文件路径。
    优先级：微软雅黑 → 黑体 → 宋体。
    返回 FFmpeg drawtext 可用的路径格式（反斜杠+冒号转义）。
    """
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttf",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/simkai.ttf",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            # 转换为 FFmpeg 兼容路径格式（Windows 盘符冒号需要转义）
            return path.replace(":", "\\:")
    # 最终回退
    return "C\\:/Windows/Fonts/msyh.ttc"


def _find_handwriting_font() -> str:
    """查找系统可用的书法/楷体字体（用于底部标语）。"""
    candidates = [
        "C:/Windows/Fonts/simkai.ttf",       # 楷体
        "C:/Windows/Fonts/STKAITI.TTF",       # 华文楷体
        "C:/Windows/Fonts/SIMLI.TTF",          # 隶书
        "C:/Windows/Fonts/STLITI.TTF",         # 华文隶书
    ]
    for path in candidates:
        if os.path.exists(path):
            return path.replace(":", "\\:")
    return _find_chinese_font()  # 兜底用雅黑


def _find_title_font() -> str:
    """
    对标卡片模式标题/字幕字体：优先项目内思源宋体 Heavy（fonts/XianKai_Title.otf），
    缺失时降级楷体系。返回 FFmpeg drawtext 转义路径。
    """
    from _resource import get_project_root
    project_font = os.path.join(get_project_root(), "fonts", "XianKai_Title.otf")
    if os.path.exists(project_font):
        return project_font.replace("\\", "/").replace(":", "\\:")
    return _find_handwriting_font()


def get_audio_duration(file_path: str) -> float:
    """
    通过 ffmpeg 获取音频/视频文件时长（秒）。
    失败返回 0.0。
    """
    if not os.path.exists(file_path):
        print(f"[video] 文件不存在: {file_path}")
        return 0.0
    try:
        result = _run_ffmpeg(
            ["ffmpeg", "-i", file_path, "-f", "null", "-"],
            timeout=30,
            description=f"获取时长 {file_path}",
        )
        stderr = result.stderr or ""
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", stderr)
        if match:
            h, m, s = int(match.group(1)), int(match.group(2)), float(match.group(3))
            return h * 3600 + m * 60 + s
        return 0.0
    except Exception as e:
        print(f"[video] 获取时长失败 {file_path}: {e}")
        return 0.0


def format_srt_time(seconds: float) -> str:
    """秒 → SRT 时间戳 HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def format_ass_time(seconds: float) -> str:
    """秒 → ASS 时间戳 H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    centiseconds = int((s - int(s)) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{centiseconds:02d}"


# ============== 字随音动：词级字幕切分 ==============

def split_into_word_groups(
    text: str,
    group_min: int = 8,
    group_max: int = 12,
    duration_sec: float = 0.0,
) -> list[dict]:
    """
    将一句字幕切分为多个"词级短组"，实现"字随音动"逐组切换效果。

    策略：
    1. 仅统计 CJK 字符（中文汉字/日文假名）用于比例计时，标点不计入时长权重
    2. 按 group_min~group_max 个 CJK 字符一组切分
    3. 标点符号附着在前一组末尾
    4. 过短的尾组（< group_min 个 CJK 字符）合并到前一组
    5. 按 CJK 字符数比例分配片段时长：group_dur = (group_cjk / total_cjk) * duration_sec
    6. 每组合并后最小 0.4s，防止闪烁

    Args:
        text: 完整句子文本
        group_min: 每组最少 CJK 字符数（默认 8）
        group_max: 每组最多 CJK 字符数（默认 12）
        duration_sec: 句子总配音时长（秒）

    Returns:
        [{"text": "第一组短句", "start": 0.0, "end": 1.5}, ...]
    """
    import unicodedata

    def _is_cjk(ch: str) -> bool:
        """检测是否为 CJK 字符（中文/日文假名）"""
        cp = ord(ch)
        # CJK Unified Ideographs + Extensions
        if 0x4E00 <= cp <= 0x9FFF:
            return True
        if 0x3400 <= cp <= 0x4DBF:
            return True
        if 0x20000 <= cp <= 0x2A6DF:
            return True
        # Japanese Kana
        if 0x3040 <= cp <= 0x30FF:
            return True
        # CJK Compatibility Ideographs
        if 0xF900 <= cp <= 0xFAFF:
            return True
        # Other Lo-category scripts (Korean Hangul syllables, etc.)
        cat = unicodedata.category(ch)
        if cat.startswith('Lo'):
            return True
        return False

    total_cjk = sum(1 for ch in text if _is_cjk(ch))
    if total_cjk == 0:
        return [{"text": text.strip(), "start": 0.0, "end": max(duration_sec, 0.5)}]

    # 第一轮：按 CJK 字符数上限切分，标点附着在前一组
    groups_raw: list[str] = []
    current = ""
    current_cjk = 0

    for ch in text:
        if _is_cjk(ch):
            if current_cjk >= group_max and current.strip():
                groups_raw.append(current)
                current = ""
                current_cjk = 0
            current += ch
            current_cjk += 1
        else:
            # 标点/空格/英文等非 CJK 字符，附着在当前组
            current += ch

    if current.strip():
        groups_raw.append(current)

    # 第二轮：过短的尾组合并到前一组
    merged: list[str] = []
    for g in groups_raw:
        g_cjk = sum(1 for ch in g if _is_cjk(ch))
        if g_cjk < group_min and merged:
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)

    # 第三轮：再平衡 —— 如果只剩一组但 CJK 字符 > group_max*1.5，强制在中点标点处拆分
    balanced: list[str] = []
    for g in merged:
        g_cjk = sum(1 for ch in g if _is_cjk(ch))
        if g_cjk > int(group_max * 1.5):
            # 尝试在中点附近找标点拆分
            mid = len(g) // 2
            break_pos = mid
            for bp in "，,。！？；;、":
                pos = g.find(bp, max(0, mid - 8), min(len(g), mid + 8))
                if pos != -1:
                    break_pos = pos + 1
                    break
            if break_pos != mid:
                balanced.append(g[:break_pos])
                balanced.append(g[break_pos:])
            else:
                # 找不到标点，按 CJK 字符均分
                cjk_positions = [i for i, ch in enumerate(g) if _is_cjk(ch)]
                if len(cjk_positions) > group_max:
                    split_at = cjk_positions[len(cjk_positions) // 2]
                    balanced.append(g[:split_at])
                    balanced.append(g[split_at:])
                else:
                    balanced.append(g)
        else:
            balanced.append(g)

    # 第四轮：计算每组的相对时间
    groups_result: list[dict] = []
    cumulative = 0.0

    for g in balanced:
        g_cjk = sum(1 for ch in g if _is_cjk(ch))
        if total_cjk > 0 and duration_sec > 0:
            g_dur = (g_cjk / total_cjk) * duration_sec
        else:
            g_dur = 0.5
        # 最小 0.4s，防止字幕闪烁
        g_dur = max(g_dur, 0.4)
        groups_result.append({
            "text": g.strip(),
            "start": round(cumulative, 3),
            "end": round(cumulative + g_dur, 3),
        })
        cumulative += g_dur

    return groups_result


# ============== v8 字幕辅助函数（自然断句 + 智能换行）==============

def _count_cjk(text: str) -> int:
    """统计字符串中的 CJK 字符数（中文/日文假名）。"""
    count = 0
    for ch in text:
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
            0x20000 <= cp <= 0x2A6DF or 0x3040 <= cp <= 0x30FF or
            0xF900 <= cp <= 0xFAFF):
            count += 1
        elif cp > 127:  # 其他宽字符也算一个 CJK 单位
            count += 1
    return count


def _split_natural_phrases(text: str, max_chars: int = 14) -> list[str]:
    """在逗号、分号、句号、问号、感叹号等天然停顿处拆分文本。

    返回按标点拆分的短语列表，每个短语 ≈ 7-14 个 CJK 字符，
    过长段在中间标点处再拆分，保证每段是一个完整的语意单元。
    """
    if not text.strip():
        return [text]

    # 第一轮：按强标点切分（逗号、分号、句号、冒号、省略号等）
    raw_parts = []
    current = ""
    break_points = set("，,。！？；;、：:…\n")
    # 英文标点当作弱断点（前后的中文上下文可能是同一句话）
    soft_breaks = set(".!?;,")

    for ch in text:
        current += ch
        if ch in break_points:
            raw_parts.append(current)
            current = ""
    if current.strip():
        raw_parts.append(current)

    # 第二轮：合并过短的碎片（< 4 个 CJK 字符的合并到相邻段）
    merged = []
    for part in raw_parts:
        cjk = _count_cjk(part)
        if cjk < 4 and merged:
            merged[-1] = merged[-1] + part
        else:
            merged.append(part)

    # 第三轮：拆分过长的段（递归对拆，直到每段 ≤ max_chars）
    # 修复两个旧缺陷：
    #   1) 只在"中点窗口"内找标点，窗口外有标点也会落到 14 字硬切，斩断词语
    #   2) 无标点时在第 max_chars 字硬切，产生 14+2 这种失衡断句
    def _split_long(part: str) -> list[str]:
        if _count_cjk(part) <= max_chars:
            return [part]
        mid = len(part) // 2
        # 收集全部可断标点位置，取离中点最近者
        candidates = [j + 1 for j, ch in enumerate(part[:-1])
                      if ch in "，,。！？；;、：:… \t"]
        if candidates:
            best = min(candidates, key=lambda p: abs(p - mid))
        else:
            # 无任何标点 → 按 CJK 字数对半拆，两段均衡
            cjk_half = max(1, _count_cjk(part) // 2)
            cnt = 0
            best = mid
            for j, ch in enumerate(part):
                if _count_cjk(ch) > 0:
                    cnt += 1
                    if cnt >= cjk_half:
                        best = j + 1
                        break
        if not (0 < best < len(part)):
            return [part]
        return _split_long(part[:best]) + _split_long(part[best:])

    result = []
    for part in merged:
        result.extend(_split_long(part))

    # 第四轮：拆分后重新产生的孤儿碎片（<4 字）并回前段（不超过单屏上限时）
    final = []
    for r in result:
        if final and _count_cjk(r) < 4 and _count_cjk(final[-1]) + _count_cjk(r) <= max_chars:
            final[-1] = final[-1] + r
        else:
            final.append(r)

    return [r for r in final if r.strip()]


def _wrap_phrase(phrase: str, max_cjk_per_line: int = 14) -> list[str]:
    """将一个短语拆分为 1-2 行，每行 ≤ max_cjk_per_line 个 CJK 字符。

    只在标点或空格处断行，不做暴力切分。
    """
    cjk = _count_cjk(phrase)
    if cjk <= max_cjk_per_line:
        return [phrase]

    # 在中点附近找断行位置
    mid = len(phrase) // 2
    best = mid
    for bp in "，,。；;、 \t":
        pos = phrase.find(bp, max(0, mid - len(phrase) // 4), min(len(phrase), mid + len(phrase) // 4))
        if pos != -1:
            best = pos + 1
            break
    if best == mid or best >= len(phrase) or best <= 2:
        # 找不到自然断点，保留原样
        return [phrase]
    return [phrase[:best], phrase[best:]]


_SUBTITLE_PUNCT = "，,。．.！!？?；;、：:…—～~·“”‘’\"'（）()《》〈〉【】[]"


def _strip_subtitle_punct(text: str) -> str:
    """字幕上屏前去标点：断句仍按标点计算，仅显示层擦除。

    首尾标点直接删除，中间标点替换为空格（保留语气停顿的视觉间隔）。
    """
    t = text.strip().strip(_SUBTITLE_PUNCT)
    cleaned = "".join(" " if ch in _SUBTITLE_PUNCT else ch for ch in t)
    return " ".join(cleaned.split())


def _split_title_lines(title: str, max_chars: int = 16) -> list[str]:
    """将视频标题拆分为 1-2 行，在空格或标点处自然断行。

    单行 ≤ max_chars 个字符。
    """
    cjk = _count_cjk(title)
    if cjk <= max_chars:
        return [title]

    # 在中点附近找空格或标点
    mid = len(title) // 2
    best = mid
    for bp in " 　，,。；;、-—":
        pos = title.find(bp, max(0, mid - len(title) // 4), min(len(title), mid + len(title) // 4))
        if pos != -1:
            best = pos + 1
            break
    if best == mid or best >= len(title) or best <= 2:
        return [title]
    return [title[:best], title[best:].lstrip()]


# ============== 视频片段生成（v4 Ken Burns + 字随音动）==============

def create_ken_burns_clip(
    image_path: str,
    output_path: str,
    duration_sec: float,
    subtitle_text: str = "",
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
    max_zoom: float = 1.06,
    subtitle_font_size: int = 52,
    subtitle_font_file: str = "",
    watermark_text: str = "",
    bottom_disclaimer: str = "",
) -> bool:
    """
    单图 → 带 Ken Burns 动态缩放 + 字幕的短视频片段（v4）。

    v4 改进：
    - Ken Burns 动效修复：d=total_frames 替代 d=1，实现真正逐帧插值缩放
    - 字幕"字随音动"：按 8-12 字分组，每组独立 drawtext + enable 时间窗口
    - 字幕 y = height*0.6（距底部 40%），避开平台 UI 遮挡
    - 字幕颜色硬编码 #FFCC00 高曝光黄，加大行距

    Args:
        image_path: 输入图片路径（1080×1920）
        output_path: 输出 MP4 路径
        duration_sec: 片段时长（秒），由实际音频时长决定
        subtitle_text: 单行字幕文本
        max_zoom: 最终缩放倍率（默认 1.06，即微量放大到 106%）
    """
    if not os.path.exists(image_path):
        print(f"[video:clip] 图片不存在: {image_path}")
        return False

    if duration_sec <= 0:
        print(f"[video:clip] 时长无效 {duration_sec}s, 跳过")
        return False

    # 自动检测中文字体
    if not subtitle_font_file:
        subtitle_font_file = _find_chinese_font()
    elif not os.path.exists(subtitle_font_file.replace("\\:", ":")):
        print(f"[video:clip] 指定字体不存在: {subtitle_font_file}，自动检测")
        subtitle_font_file = _find_chinese_font()

    total_frames = max(1, int(duration_sec * fps))

    # ---- v5 抗抖动缩放：pzoom + 2x 预放大 + bicubic 插值 ----
    # 根因：FFmpeg zoompan 内部 x/y 整数截断，慢速缩放时每帧位移 < 1px 被交替截断为 0/1
    # 修复：① 2x 预放大给 zoompan 子像素精度 ② pzoom 防漂移 ③ d=1 社区共识
    zoom_speed = (max_zoom - 1.0) / total_frames
    zoom_expr = f"min(max(zoom,pzoom)+{zoom_speed:.6f},{max_zoom:.4f})"

    # ---- 构建 drawtext 滤镜链 ----
    drawtext_filters = []

    # --- 主字幕（v8 自然断句：在逗号/分号/句号处切分，每段 ~10-14 字）---
    if subtitle_text.strip():
        # 按天然标点停顿拆成短语，每个短语独立显示，说完再切下一个
        phrases = _split_natural_phrases(subtitle_text.strip(), max_chars=14)
        total_phrases = len(phrases)

        # 统计每个短语的 CJK 字符数，用于按比例分配时长
        phrase_cjk_counts = [_count_cjk(p) for p in phrases]
        total_cjk = sum(phrase_cjk_counts)

        time_start = 0.0
        for p_idx, phrase in enumerate(phrases):
            p_cjk = phrase_cjk_counts[p_idx]
            # 按 CJK 字符数比例分配该短语的显示时长
            phrase_dur = (p_cjk / total_cjk) * duration_sec if total_cjk > 0 else duration_sec / total_phrases
            # 确保每个短语最少显示 0.8 秒
            phrase_dur = max(phrase_dur, 0.8)
            # 最后一段吃掉剩余时间，避免累积误差
            if p_idx == total_phrases - 1:
                phrase_end = duration_sec
            else:
                phrase_end = time_start + phrase_dur
                # 防止超出总时长
                if phrase_end > duration_sec - 0.3:
                    phrase_end = duration_sec

            # 短语内自动换行（单行 ≤ 14 个 CJK 字符）
            lines = _wrap_phrase(phrase, max_cjk_per_line=14)

            for li, line in enumerate(lines):
                if not line.strip():
                    continue
                escaped = (
                    line.replace("\\", "\\\\")
                         .replace(":", "\\:")
                         .replace("'", "\\'")
                         .replace("%", "\\%")
                         .replace("{", "\\{")
                         .replace("}", "\\}")
                )
                # 字幕放在画面下半部分，居中
                y_pos = int(height * 0.55) + li * (subtitle_font_size + 14)
                dt = (
                    f"drawtext=fontfile='{subtitle_font_file}':"
                    f"text='{escaped}':"
                    f"fontcolor=#FFCC00:"
                    f"fontsize={subtitle_font_size}:"
                    f"x=(w-text_w)/2:"
                    f"y={y_pos}:"
                    f"shadowcolor=black@0.7:shadowx=3:shadowy=3:"
                    f"bordercolor=black@0.5:borderw=4:"
                    f"enable='between(t,{time_start:.3f},{phrase_end:.3f})'"
                )
                drawtext_filters.append(dt)

            time_start = phrase_end

        print(
            f"[video:clip] 字幕: {total_phrases} 段自然断句, "
            f"每段 {phrase_cjk_counts[0] if phrase_cjk_counts else 0}~{phrase_cjk_counts[-1] if phrase_cjk_counts else 0} 字"
            if total_phrases <= 3
            else f"[video:clip] 字幕: {total_phrases} 段自然断句"
        )

    # --- 顶部居中标题（v8：渐变黑条 + 大号白色居中标题 + 自动分行）---
    if watermark_text.strip():
        scaled_fontsize = max(36, int(subtitle_font_size * 0.75))
        title_lines = _split_title_lines(watermark_text, max_chars=16)
        for ti, tline in enumerate(title_lines):
            escaped_wm = (
                tline.replace("\\", "\\\\")
                     .replace(":", "\\:")
                     .replace("'", "\\'")
                     .replace("%", "\\%")
                     .replace("{", "\\{")
                     .replace("}", "\\}")
            )
            y_pos = 55 + ti * (scaled_fontsize + 12)
            dt_wm = (
                f"drawtext=fontfile='{subtitle_font_file}':"
                f"text='{escaped_wm}':"
                f"fontcolor=white@0.92:"
                f"fontsize={scaled_fontsize}:"
                f"x=(w-text_w)/2:"
                f"y={y_pos}:"
                f"shadowcolor=black@0.6:shadowx=2:shadowy=2"
            )
            drawtext_filters.append(dt_wm)

        # 顶部半透明黑条：120px 高，确保标题在任何背景上都清晰可读
        gradient_bar = f"drawbox=x=0:y=0:w=iw:h=120:color=black@0.55:t=fill"
        drawtext_filters.insert(0, gradient_bar)

    # --- 底部声明 ---
    if bottom_disclaimer.strip():
        escaped_disc = (
            bottom_disclaimer.replace("\\", "\\\\")
                             .replace(":", "\\:")
                             .replace("'", "\\'")
                             .replace("%", "\\%")
                             .replace("{", "\\{")
                             .replace("}", "\\}")
        )
        dt_disc = (
            f"drawtext=fontfile='{subtitle_font_file}':"
            f"text='{escaped_disc}':"
            f"fontcolor=white@0.45:"
            f"fontsize=22:"
            f"x=(w-text_w)/2:"
            f"y=h-50:"
            f"shadowcolor=black@0.4:shadowx=1:shadowy=1"
        )
        drawtext_filters.append(dt_disc)

    # ---- 组装滤镜链（v5 抗抖动）----
    # 2x 预放大 → zoompan(d=1) → format 保证像素格式一致
    # drawtext 放在 format 之后，确保文字渲染在稳定像素网格上
    vf_parts = [
        f"scale=iw*2:ih*2:flags=bicubic",
        f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps={fps}",
    ]
    vf_parts.extend(drawtext_filters)
    # 滤镜链末尾显式指定像素格式，防止色度子采样舍入引入额外抖动
    vf_parts.append("format=yuv420p")
    vf_chain = ",".join(vf_parts)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-t", str(duration_sec),
        "-vf", vf_chain,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]

    actual_final_zoom = 1.0 + zoom_speed * total_frames
    print(
        f"[video:clip] {duration_sec:.1f}s, "
        f"zoom: 1.00→{actual_final_zoom:.3f} ({total_frames}frames), "
        f"字幕: {subtitle_text[:25]}..."
    )

    try:
        result = _run_ffmpeg(cmd, timeout=180, description=f"片段 {output_path}")
        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-500:]
            print(f"[video:clip] FFmpeg 错误: {stderr_tail}")
            return False
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return True
        return False
    except Exception as e:
        print(f"[video:clip] 异常: {e}")
        return False


# ============== 黑底打字机片段（v5：防搬运极简风格）==============

def create_silent_placeholder_clip(
    output_path: str,
    duration_sec: float,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    label: str = "",
) -> bool:
    """
    生成一段纯黑无声占位片段，用于填充失败的片段位置，维护 A/V 同步。

    当某个句子的视频片段生成失败时，不能简单跳过——否则后续片段会向前移位，
    导致画面与音频轨道错位。此函数生成一段"空白占位"片段，时长与目标音频段一致。

    Returns:
        True on success, False on failure.
    """
    if duration_sec <= 0:
        print(f"[video:placeholder] 时长无效 {duration_sec}s, 跳过")
        return False

    label_suffix = f" ({label})" if label else ""
    print(f"[video:placeholder] 生成占位片段 {duration_sec:.1f}s{label_suffix}")

    # 纯黑背景图
    bg_path = output_path.replace(".mp4", "_ph_bg.png")
    try:
        from PIL import Image as PILImage
        bg = PILImage.new("RGB", (width, height), (10, 10, 10))
        bg.save(bg_path, "PNG")
    except Exception as e:
        print(f"[video:placeholder] 背景图生成失败: {e}")
        return False

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", bg_path,
        "-t", str(duration_sec),
        "-vf", f"fps={fps},format=yuv420p",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]

    try:
        result = _run_ffmpeg(cmd, timeout=60, description=f"placeholder {output_path}")
        # 清理临时背景图
        try:
            os.remove(bg_path)
        except Exception:
            pass

        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-300:]
            print(f"[video:placeholder] FFmpeg 错误: {stderr_tail}")
            return False
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return True
        return False
    except Exception as e:
        print(f"[video:placeholder] 异常: {e}")
        try:
            os.remove(bg_path)
        except Exception:
            pass
        return False


# ============== 黑底打字机片段（v5：防搬运极简风格）==============

def create_typewriter_clip(
    output_path: str,
    duration_sec: float,
    subtitle_text: str = "",
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
    subtitle_font_size: int = 64,
    subtitle_font_file: str = "",
    watermark_text: str = "",
    bottom_disclaimer: str = "",
) -> bool:
    """
    纯黑底 + 大字幕逐词浮现的视频片段（打字机/知识卡片风格）。

    与 create_ken_burns_clip 的区别：
    - 无图片输入，纯黑 (#0a0a0a) 背景
    - 无 zoompan，无缩放动效
    - 字幕更大（默认 64px），白色/亮绿配色
    - 相同的水印 + 底部声明逻辑

    Returns:
        True on success, False on failure.
    """
    if duration_sec <= 0:
        print(f"[video:typewriter] 时长无效 {duration_sec}s, 跳过")
        return False

    # 字体
    if not subtitle_font_file:
        subtitle_font_file = _find_chinese_font()
    elif not os.path.exists(subtitle_font_file.replace("\\:", ":")):
        subtitle_font_file = _find_chinese_font()

    # 生成纯黑背景图
    bg_path = output_path.replace(".mp4", "_bg.png")
    try:
        from PIL import Image as PILImage
        bg = PILImage.new("RGB", (width, height), (10, 10, 10))
        bg.save(bg_path, "PNG")
    except Exception as e:
        print(f"[video:typewriter] 背景图生成失败: {e}")
        return False

    # ---- 构建 drawtext 滤镜链（字随音动）----
    drawtext_filters = []

    # 主字幕：白色大字，词级切分 + enable 时间窗口
    if subtitle_text.strip():
        word_groups = split_into_word_groups(
            subtitle_text.strip(),
            group_min=8,
            group_max=12,
            duration_sec=duration_sec,
        )
        total_groups = len(word_groups)

        for group in word_groups:
            g_text = group["text"]
            g_start = group["start"]
            g_end = group["end"]

            # 组内换行
            max_chars_per_line = 18  # typewriter 模式行宽更窄
            if len(g_text) <= max_chars_per_line:
                lines = [g_text]
            else:
                mid = len(g_text) // 2
                best = mid
                for bp in "，,。！？；;、":
                    pos = g_text.find(bp, max(0, mid - 6), min(len(g_text), mid + 6))
                    if pos != -1:
                        best = pos + 1
                        break
                if best == mid:
                    best = max_chars_per_line
                lines = [g_text[:best], g_text[best:]]

            for li, line in enumerate(lines):
                if not line.strip():
                    continue
                escaped = (
                    line.replace("\\", "\\\\")
                         .replace(":", "\\:")
                         .replace("'", "\\'")
                         .replace("%", "\\%")
                         .replace("{", "\\{")
                         .replace("}", "\\}")
                )
                # 白色大字，居中偏上（typewriter 风格）
                y_pos = int(height * 0.45) + li * (subtitle_font_size + 12)
                dt = (
                    f"drawtext=fontfile='{subtitle_font_file}':"
                    f"text='{escaped}':"
                    f"fontcolor=#E0E0E0:"       # 柔和亮白
                    f"fontsize={subtitle_font_size}:"
                    f"x=(w-text_w)/2:"
                    f"y={y_pos}:"
                    f"shadowcolor=black@0.8:shadowx=2:shadowy=2:"
                    f"enable='between(t,{g_start},{g_end})'"
                )
                drawtext_filters.append(dt)

        print(f"[video:typewriter] 字幕: {total_groups} 组")

    # 顶部水印
    if watermark_text.strip():
        escaped_wm = (
            watermark_text.replace("\\", "\\\\")
                          .replace(":", "\\:")
                          .replace("'", "\\'")
                          .replace("%", "\\%")
                          .replace("{", "\\{")
                          .replace("}", "\\}")
        )
        dt_wm = (
            f"drawtext=fontfile='{subtitle_font_file}':"
            f"text='{escaped_wm}':"
            f"fontcolor=white@0.5:"
            f"fontsize=22:"
            f"x=40:y=40:"
            f"shadowcolor=black@0.5:shadowx=2:shadowy=2"
        )
        drawtext_filters.append(dt_wm)

    # 底部声明
    if bottom_disclaimer.strip():
        escaped_disc = (
            bottom_disclaimer.replace("\\", "\\\\")
                             .replace(":", "\\:")
                             .replace("'", "\\'")
                             .replace("%", "\\%")
                             .replace("{", "\\{")
                             .replace("}", "\\}")
        )
        dt_disc = (
            f"drawtext=fontfile='{subtitle_font_file}':"
            f"text='{escaped_disc}':"
            f"fontcolor=white@0.35:"
            f"fontsize=20:"
            f"x=(w-text_w)/2:"
            f"y=h-50:"
            f"shadowcolor=black@0.4:shadowx=1:shadowy=1"
        )
        drawtext_filters.append(dt_disc)

    # 组装滤镜链（无 zoompan，仅 fps + drawtext + format）
    vf_chain = f"fps={fps}"
    if drawtext_filters:
        vf_chain += "," + ",".join(drawtext_filters)
    vf_chain += ",format=yuv420p"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", bg_path,
        "-t", str(duration_sec),
        "-vf", vf_chain,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]

    print(f"[video:typewriter] {duration_sec:.1f}s, 字幕: {subtitle_text[:25]}...")

    try:
        result = _run_ffmpeg(cmd, timeout=180, description=f"typewriter {output_path}")
        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-500:]
            print(f"[video:typewriter] FFmpeg 错误: {stderr_tail}")
            return False
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            # 清理临时背景图
            try:
                os.remove(bg_path)
            except Exception:
                pass
            return True
        return False
    except Exception as e:
        print(f"[video:typewriter] 异常: {e}")
        return False


# ============== 图书口播卡片纯画面片段（v6：骨肉分离）==============

def create_card_pure_clip(
    image_path: str,
    output_path: str,
    duration_sec: float,
    fps: int = 30,
    out_w: int = 1080,
    out_h: int = 608,
    max_zoom: float = 1.20,
) -> bool:
    """
    v6 骨肉分离：生成仅含中部画面的纯视频片段（无页眉/页脚/字幕/pad）。

    滤镜链（极简，对标 create_ken_burns_clip）：
      scale=out_w:out_h:force_original_aspect_ratio=increase  → 等比缩放至填满目标框
      crop=out_w:out_h                                         → 居中裁切到精确尺寸
      scale=iw*2:ih*2:flags=bicubic                            → 2x 预放大（抗抖动）
      zoompan z=pzoom+d s=out_w×out_h                          → Ken Burns 匀速变焦
      format=yuv420p

    兼容 16:9（1280×720）和 9:16（1080×1920）两种源图：
      - 16:9 → scale 后自然 1080×607，crop 近乎无操作
      - 9:16 → scale 后 1080×1920，crop 取中段 607px
    """
    if not os.path.exists(image_path):
        print(f"[video:v6:pure] 图片不存在: {image_path}")
        return False
    if duration_sec <= 0:
        print(f"[video:v6:pure] 时长无效 {duration_sec}s, 跳过")
        return False

    total_frames = max(1, int(duration_sec * fps))
    zoom_speed = (max_zoom - 1.0) / total_frames
    zoom_expr = f"min(max(zoom,pzoom)+{zoom_speed:.6f},{max_zoom:.4f})"

    vf_chain = (
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase:flags=bicubic,"
        f"crop={out_w}:{out_h},"
        f"scale=iw*2:ih*2:flags=bicubic,"
        f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={out_w}x{out_h}:fps={fps},"
        f"format=yuv420p"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-t", str(duration_sec),
        "-vf", vf_chain,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]

    actual_final_zoom = 1.0 + zoom_speed * total_frames
    print(
        f"[video:v6:pure] {duration_sec:.1f}s, "
        f"zoom: 1.00→{actual_final_zoom:.3f} ({total_frames}frames), "
        f"{out_w}×{out_h}"
    )

    try:
        result = _run_ffmpeg(cmd, timeout=120, description=f"纯画面 {output_path}")
        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-500:]
            print(f"[video:v6:pure] FFmpeg 错误: {stderr_tail}")
            return False
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return True
        return False
    except Exception as e:
        print(f"[video:v6:pure] 异常: {e}")
        return False


# ============== 图书口播卡片片段（v5：黄金三段式布局）==============

def create_card_clip(
    image_path: str,
    output_path: str,
    duration_sec: float,
    subtitle_text: str = "",
    card_title: str = "",
    card_author: str = "",
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
    max_zoom: float = 1.20,
    subtitle_font_size: int = 52,
    subtitle_font_file: str = "",
    bottom_disclaimer: str = "",
) -> bool:
    """
    图书口播卡片风格（v5 黄金三段式布局）：

    ┌──────────────────────┐
    │  ██████████████████  │ ← 顶部黑色页眉区 (~420px)：书名 + 作者
    │  █ 《抗老生活》 █  │
    │  █  池谷敏郎 著  █  │
    ├──────────────────────┤  y=420
    │                      │
    │   AI 配图 +          │ ← 中部动态画面区 (~960px)
    │   Ken Burns 缩放     │    图片在这里丝滑推进 1.00→1.20
    │                      │
    │ [黄色逐词字幕]      │ ← 字幕精准定位在中部区底部边界内侧
    ├──────────────────────┤  y=1380
    │  ██████████████████  │ ← 底部黑色页脚区 (~540px)
    │  █ 合规声明文本 █  │    白色/灰色小字，居中折行
    │  █ （建议两行） █  │
    └──────────────────────┘

    实现方式：crop → 2x 预放大 → zoompan s=1080x960 → pad → drawtext 全叠加
    """
    if not os.path.exists(image_path):
        print(f"[video:card] 图片不存在: {image_path}")
        return False

    if duration_sec <= 0:
        print(f"[video:card] 时长无效 {duration_sec}s, 跳过")
        return False

    # 字体
    if not subtitle_font_file:
        subtitle_font_file = _find_chinese_font()
    elif not os.path.exists(subtitle_font_file.replace("\\:", ":")):
        subtitle_font_file = _find_chinese_font()

    # === 读取实际图片尺寸，必要时预缩放 ===
    img_w, img_h = width, height  # 默认
    try:
        from PIL import Image as PILImage
        pil_img = PILImage.open(image_path)
        img_w, img_h = pil_img.size
        pil_img.close()
    except Exception:
        pass  # FFmpeg 可自行处理，继续

    need_prescale = (img_w != width or img_h != height)
    if need_prescale:
        print(f"[video:card] 图片尺寸 {img_w}x{img_h} != {width}x{height}，预缩放至标准尺寸")

    # === 黄金三段式几何常量 ===
    header_h = 420       # 顶部黑色页眉区高度
    middle_h = 960       # 中部画面区高度
    footer_h = 540       # 底部黑色页脚区高度（420+960=1380, 1380+540=1920）
    # 中部区在画布上的 y 偏移
    middle_y0 = header_h
    # 底部区起始 y
    footer_y0 = header_h + middle_h  # 1380

    total_frames = max(1, int(duration_sec * fps))

    # === v5 抗抖动 zoompan ===
    zoom_speed = (max_zoom - 1.0) / total_frames
    zoom_expr = f"min(max(zoom,pzoom)+{zoom_speed:.6f},{max_zoom:.4f})"

    # === 图片裁剪：从 1080x1920 中部裁出 1080x{middle_h*max_zoom} 给 zoom 留余量 ===
    # 例如 middle_h=960, max_zoom=1.20 → crop_h=1152, crop_y0=(1920-1152)/2=384
    crop_h = int(middle_h * max_zoom)
    crop_y0 = max(0, (height - crop_h) // 2)

    # === 字幕（词级字随音动 + enable）===
    drawtext_filters = []
    if subtitle_text.strip():
        word_groups = split_into_word_groups(
            subtitle_text.strip(),
            group_min=8, group_max=12,
            duration_sec=duration_sec,
        )
        for group in word_groups:
            g_text = group["text"]
            g_start = group["start"]
            g_end = group["end"]

            # 组内换行
            max_chars = 18
            if len(g_text) <= max_chars:
                lines = [g_text]
            else:
                mid = len(g_text) // 2
                best = mid
                for bp in "，,。！？；;、":
                    pos = g_text.find(bp, max(0, mid - 6), min(len(g_text), mid + 6))
                    if pos != -1:
                        best = pos + 1
                        break
                if best == mid:
                    best = max_chars
                lines = [g_text[:best], g_text[best:]]

            for li, line in enumerate(lines):
                if not line.strip():
                    continue
                escaped = (
                    line.replace("\\", "\\\\")
                         .replace(":", "\\:")
                         .replace("'", "\\'")
                         .replace("%", "\\%")
                         .replace("{", "\\{")
                         .replace("}", "\\}")
                )
                # 字幕定位：中部画面区底部边界内侧，y ≈ footer_y0 - 40px
                # 多行时第二行向下偏移
                base_y = footer_y0 - 50  # 1330，中部区底部内侧
                y_pos = base_y + li * (subtitle_font_size + 10)
                dt = (
                    f"drawtext=fontfile='{subtitle_font_file}':"
                    f"text='{escaped}':"
                    f"fontcolor=#FFCC00:"
                    f"fontsize={subtitle_font_size}:"
                    f"x=(w-text_w)/2:"
                    f"y={y_pos}:"
                    f"shadowcolor=black@0.7:shadowx=3:shadowy=3:"
                    f"bordercolor=black@0.5:borderw=4:"
                    f"enable='between(t,{g_start},{g_end})'"
                )
                drawtext_filters.append(dt)

    # === 顶部页眉：书名（第一行）+ 作者（第二行）===
    if card_title.strip():
        header_title = f"《{card_title}》"
        escaped_ht = (
            header_title.replace("\\", "\\\\")
                        .replace(":", "\\:")
                        .replace("'", "\\'")
                        .replace("%", "\\%")
                        .replace("{", "\\{")
                        .replace("}", "\\}")
        )
        dt_title = (
            f"drawtext=fontfile='{subtitle_font_file}':"
            f"text='{escaped_ht}':"
            f"fontcolor=white:"
            f"fontsize=56:"
            f"x=(w-text_w)/2:"
            f"y=170:"
            f"shadowcolor=black@0.5:shadowx=2:shadowy=2"
        )
        drawtext_filters.append(dt_title)

    if card_author.strip():
        header_author = f"{card_author} 著"
        escaped_ha = (
            header_author.replace("\\", "\\\\")
                         .replace(":", "\\:")
                         .replace("'", "\\'")
                         .replace("%", "\\%")
                         .replace("{", "\\{")
                         .replace("}", "\\}")
        )
        dt_author = (
            f"drawtext=fontfile='{subtitle_font_file}':"
            f"text='{escaped_ha}':"
            f"fontcolor=white@0.85:"
            f"fontsize=32:"
            f"x=(w-text_w)/2:"
            f"y=280:"
            f"shadowcolor=black@0.4:shadowx=1:shadowy=1"
        )
        drawtext_filters.append(dt_author)

    # === 底部页脚：合规声明（手动折行，确保高级排版）===
    if bottom_disclaimer.strip():
        disc_text = bottom_disclaimer.strip()
        # 折行策略：按约 25 字宽度分两行，优先在标点处断
        max_line_chars = 28
        if len(disc_text) <= max_line_chars:
            disc_lines = [disc_text]
        else:
            mid = len(disc_text) // 2
            best = mid
            for bp in "，,。！？；;、":
                pos = disc_text.find(bp, max(0, mid - 10), min(len(disc_text), mid + 10))
                if pos != -1:
                    best = pos + 1
                    break
            if best == mid:
                best = max_line_chars
            disc_lines = [disc_text[:best], disc_text[best:]]

        for li, dline in enumerate(disc_lines):
            if not dline.strip():
                continue
            escaped_d = (
                dline.replace("\\", "\\\\")
                     .replace(":", "\\:")
                     .replace("'", "\\'")
                     .replace("%", "\\%")
                     .replace("{", "\\{")
                     .replace("}", "\\}")
            )
            # 底部页脚区内居中，y 从 footer_y0+120 开始，行距 36px
            disc_y = footer_y0 + 120 + li * 36
            dt_disc = (
                f"drawtext=fontfile='{subtitle_font_file}':"
                f"text='{escaped_d}':"
                f"fontcolor=white@0.45:"
                f"fontsize=22:"
                f"x=(w-text_w)/2:"
                f"y={disc_y}:"
                f"shadowcolor=black@0.3:shadowx=1:shadowy=1"
            )
            drawtext_filters.append(dt_disc)

    # === 组装滤镜链 ===
    # [prescale?] → crop 中部 → 2x 预放大 → zoompan s=1080x960 → pad 到 1080x1920 → drawtext → format
    vf_parts = []
    if need_prescale:
        # 先用 scale 把图片标准化到 1080×1920，再走后续流程
        vf_parts.append(f"scale={width}:{height}:flags=bicubic")
    vf_parts.extend([
        f"crop={width}:{crop_h}:0:{crop_y0}",
        f"scale=iw*2:ih*2:flags=bicubic",
        f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={width}x{middle_h}:fps={fps}",
        f"pad={width}:{height}:0:{middle_y0}:black",
    ])
    vf_parts.extend(drawtext_filters)
    vf_parts.append("format=yuv420p")
    vf_chain = ",".join(vf_parts)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-t", str(duration_sec),
        "-vf", vf_chain,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]

    print(
        f"[video:card] {duration_sec:.1f}s, "
        f"zoom: 1.00→{max_zoom:.2f}, "
        f"卡片: 《{card_title}》"
    )

    try:
        result = _run_ffmpeg(cmd, timeout=180, description=f"卡片 {output_path}")
        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-500:]
            print(f"[video:card] FFmpeg 错误: {stderr_tail}")
            return False
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return True
        return False
    except Exception as e:
        print(f"[video:card] 异常: {e}")
        return False


# ============== 无损拼接 ==============

def concat_clips(clip_paths: list[str], output_path: str) -> bool:
    """使用 FFmpeg concat demuxer 无损拼接视频片段。"""
    if not clip_paths:
        print("[video:concat] 无片段可拼接")
        return False

    list_content = "\n".join(
        f"file '{os.path.abspath(p)}'" for p in clip_paths if os.path.exists(p)
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(list_content)
        list_file = f.name

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c:v", "copy",
        output_path,
    ]

    print(f"[video:concat] 拼接 {len(clip_paths)} 个片段 → {output_path}")

    try:
        result = _run_ffmpeg(cmd, timeout=180, description=f"拼接 {len(clip_paths)} clips")
        os.unlink(list_file)
        if result.returncode != 0:
            err = (result.stderr or "")[-300:]
            print(f"[video:concat] 失败: {err}")
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception as e:
        try:
            os.unlink(list_file)
        except Exception:
            pass
        print(f"[video:concat] 异常: {e}")
        return False


# ============== 音轨混流 ==============

BGM_VOLUME = 0.25   # 背景音乐音量（0.25 ≈ -12dB，对齐同事剪映 -11.9dB 标准；人声保持 1.0）
BGM_FADE_SEC = 3.0  # 背景音乐结尾淡出秒数


def _find_bgm() -> str | None:
    """
    全局背景音乐：项目根目录 bgm/ 下按文件名排序取第一个音频文件。
    目录不存在或为空 → None（不加背景音乐，行为同旧版）。
    打包模式：bgm/ 在 exe 旁边，方便同事自行换歌。
    """
    from _resource import get_bgm_dir, get_project_root
    bgm_dir = get_bgm_dir()
    if not os.path.isdir(bgm_dir):
        return None
    for name in sorted(os.listdir(bgm_dir)):
        if name.lower().endswith((".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")):
            return os.path.join(bgm_dir, name)
    return None


def mux_audio(video_path: str, audio_path: str, output_path: str) -> bool:
    """将音频轨混入视频。视频比音频长 → 末尾静音；音频比视频长 → 截断音频。
    bgm/ 目录下有音频时自动循环铺底混入（音量 BGM_VOLUME，结尾淡出），失败回退纯人声。"""
    if not os.path.exists(video_path):
        print("[video:mux] 视频文件不存在")
        return False
    if not os.path.exists(audio_path):
        print("[video:mux] 音频文件不存在，输出无声视频")
        shutil.copy2(video_path, output_path)
        return True

    bgm_path = _find_bgm()
    if bgm_path:
        # BGM 链：压音量 → 结尾淡出；amix duration=first 以人声长度为准，normalize=0 保持人声原音量
        voice_dur = get_audio_duration(audio_path)
        bg_chain = f"[2:a]volume={BGM_VOLUME}"
        if voice_dur > BGM_FADE_SEC:
            bg_chain += f",afade=t=out:st={voice_dur - BGM_FADE_SEC:.2f}:d={BGM_FADE_SEC}"
        bg_chain += "[bg]"
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-stream_loop", "-1",
            "-i", bgm_path,
            "-filter_complex",
            f"{bg_chain};"
            f"[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-map", "0:v:0",
            "-map", "[aout]",
            output_path,
        ]
        print(f"[video:mux] 混流视频 + 人声 + BGM({os.path.basename(bgm_path)}) → {output_path}")
        try:
            result = _run_ffmpeg(cmd, timeout=180, description="音轨混流（含BGM）")
            if (result.returncode == 0
                    and os.path.exists(output_path)
                    and os.path.getsize(output_path) > 1000):
                return True
            err = (result.stderr or "")[-300:]
            print(f"[video:mux] BGM 混流失败，回退纯人声混流: {err}")
        except Exception as e:
            print(f"[video:mux] BGM 混流异常，回退纯人声混流: {e}")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-map", "0:v:0",
        "-map", "1:a:0",
        output_path,
    ]

    print(f"[video:mux] 混流视频 + 音频 → {output_path}")

    try:
        result = _run_ffmpeg(cmd, timeout=180, description="音轨混流")
        if result.returncode != 0:
            err = (result.stderr or "")[-300:]
            print(f"[video:mux] 混流失败: {err}")
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception as e:
        print(f"[video:mux] 异常: {e}")
        return False


# ============== SRT 字幕导出 ==============

def export_srt(
    sentences: list[str],
    seg_durations: list[float],
    output_path: str,
    use_word_groups: bool = True,
) -> bool:
    """
    导出标准 SRT 字幕文件（v4：词级字随音动）。

    Args:
        sentences: 句子文本列表
        seg_durations: 每句对应的音频时长（秒）
        output_path: SRT 输出路径
        use_word_groups: True=词级短组字幕，False=句子级字幕（兼容旧版）
    """
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            index = 1
            cumulative = 0.0
            for text, dur in zip(sentences, seg_durations):
                if use_word_groups:
                    groups = split_into_word_groups(text, duration_sec=dur)
                    for group in groups:
                        start = cumulative + group["start"]
                        end = cumulative + group["end"]
                        f.write(f"{index}\n")
                        f.write(f"{format_srt_time(start)} --> {format_srt_time(end)}\n")
                        f.write(f"{group['text']}\n\n")
                        index += 1
                    cumulative += dur
                else:
                    start = cumulative
                    end = cumulative + dur
                    cumulative = end
                    f.write(f"{index}\n")
                    f.write(f"{format_srt_time(start)} --> {format_srt_time(end)}\n")
                    f.write(f"{text.strip()}\n\n")
                    index += 1

        print(f"[video:srt] 字幕已导出: {output_path} ({index - 1} 条)")
        return True
    except Exception as e:
        print(f"[video:srt] 导出失败: {e}")
        return False


# ============== ASS 字幕导出（高级样式） ==============

def export_ass(
    sentences: list[str],
    seg_durations: list[float],
    output_path: str,
    font_size: int = 52,
    font_color: str = "&H0000CCFF&",  # ASS 格式 ABGR: #FFCC00 → &H0000CCFF&
    width: int = 1080,
    height: int = 1920,
    use_word_groups: bool = True,
) -> bool:
    """
    导出 ASS 高级字幕文件（v4：词级字随音动 + 防遮挡位置 + 阴影描边）。
    """
    try:
        ass_header = f"""[Script Info]
Title: 视频自动化字幕
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,{font_size},{font_color},&H00FFFFFF,&H00000000,&H66000000,1,0,0,0,100,100,0,0,1,4,3,2,60,60,{int(height * 0.6)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_header)
            cumulative = 0.0
            total_entries = 0
            for text, dur in zip(sentences, seg_durations):
                if use_word_groups:
                    groups = split_into_word_groups(text, duration_sec=dur)
                    for group in groups:
                        start = cumulative + group["start"]
                        end = cumulative + group["end"]
                        escaped = (
                            group["text"]
                            .replace("\\", "\\\\")
                            .replace("\n", "\\N")
                            .replace("{", "\\{")
                            .replace("}", "\\}")
                        )
                        f.write(f"Dialogue: 0,{format_ass_time(start)},{format_ass_time(end)},Default,,0,0,0,,{escaped}\n")
                        total_entries += 1
                    cumulative += dur
                else:
                    start = cumulative
                    end = cumulative + dur
                    cumulative = end
                    escaped = (
                        text.strip()
                        .replace("\\", "\\\\")
                        .replace("\n", "\\N")
                        .replace("{", "\\{")
                        .replace("}", "\\}")
                    )
                    f.write(f"Dialogue: 0,{format_ass_time(start)},{format_ass_time(end)},Default,,0,0,0,,{escaped}\n")
                    total_entries += 1

        print(f"[video:ass] ASS 字幕已导出: {output_path} ({total_entries} 条)")
        return True
    except Exception as e:
        print(f"[video:ass] 导出失败: {e}")
        return False


# ============== 剪映草稿 JSON 导出 ==============

def export_jianying_draft(
    task_id: int,
    task_dir: str,
    sentences: list[str],
    seg_durations: list[float],
    image_paths: list[str],
    audio_path: str,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    font_size: int = 52,
    font_color_hex: str = "#FFCC00",
) -> Optional[str]:
    """
    全自动导出符合剪映（CapCut）标准的 draft_content.json 草稿文件。

    包含完整的：
    - 视频轨道：图片素材 + Ken Burns 慢速缩放关键帧动效
    - 音频轨道：对齐好的 TTS 配音
    - 字幕轨道：黄色高亮字幕

    Returns:
        draft_content.json 的路径，失败返回 None
    """
    try:
        # 剪映 draft_content.json 结构
        total_duration = sum(seg_durations)

        # --- 视频轨道 segments ---
        video_segments = []
        time_cursor = 0
        for i, (img_path, dur) in enumerate(zip(image_paths, seg_durations)):
            if dur <= 0:
                continue

            # 剪映素材 ID 格式
            material_id = f"material_img_{i:04d}"

            # Ken Burns 关键帧：scale 从 1.0 → 1.06
            video_segments.append({
                "id": f"video_seg_{i:04d}",
                "material_id": material_id,
                "source_path": img_path.replace("\\", "/"),
                "target_timerange": {
                    "start": int(time_cursor * 1_000_000),      # 微秒
                    "duration": int(dur * 1_000_000),
                },
                "source_timerange": {
                    "start": 0,
                    "duration": int(dur * 1_000_000),
                },
                "speed": 1.0,
                "volume": 0.0,
                "clip": {
                    "rotation": 0.0,
                    "scale_x": 1.0,
                    "scale_y": 1.0,
                    "alpha": 1.0,
                },
                # Ken Burns 关键帧动画
                "animation": {
                    "type": "keyframe",
                    "keyframes": [
                        {
                            "time": 0,
                            "scale": 1.0,
                            "position": {"x": 0.0, "y": 0.0},
                        },
                        {
                            "time": int(dur * 1_000_000),
                            "scale": 1.06,
                            "position": {"x": 0.0, "y": 0.0},
                        },
                    ],
                },
                # 宽高比适配
                "uniform_scale": True,
                "extra_type_option": 1,
            })
            time_cursor += dur

        # --- 音频轨道 segment ---
        audio_segments = [{
            "id": "audio_seg_main",
            "material_id": "material_audio_main",
            "source_path": audio_path.replace("\\", "/"),
            "target_timerange": {
                "start": 0,
                "duration": int(total_duration * 1_000_000),
            },
            "source_timerange": {
                "start": 0,
                "duration": int(total_duration * 1_000_000),
            },
            "speed": 1.0,
            "volume": 1.0,
        }]

        # --- 字幕轨道 segments (v4: 词级字随音动) ---
        subtitle_segments = []
        subtitle_id_counter = 0
        time_cursor = 0
        for text, dur in zip(sentences, seg_durations):
            if dur <= 0:
                continue
            groups = split_into_word_groups(text, duration_sec=dur)
            for group in groups:
                subtitle_segments.append({
                    "id": f"subtitle_{subtitle_id_counter:04d}",
                    "content": group["text"],
                    "target_timerange": {
                        "start": int((time_cursor + group["start"]) * 1_000_000),
                        "duration": int((group["end"] - group["start"]) * 1_000_000),
                    },
                    "style": {
                        "font_size": font_size,
                        "font_color": font_color_hex,
                        "font_path": "C:/Windows/Fonts/msyh.ttc",
                        "alignment": 1,          # 居中
                        "position": 2,            # 底部
                        "bold": 1,
                        "shadow": True,
                        "shadow_color": "#000000",
                        "shadow_offset_x": 3,
                        "shadow_offset_y": 3,
                    },
                })
                subtitle_id_counter += 1
            time_cursor += dur

        # --- 素材库 ---
        materials = {
            "videos": [
                {
                    "id": f"material_img_{i:04d}",
                    "path": img_path.replace("\\", "/"),
                    "type": "photo",
                    "duration": int(seg_durations[i] * 1_000_000) if i < len(seg_durations) else 5_000_000,
                }
                for i, img_path in enumerate(image_paths)
            ],
            "audios": [
                {
                    "id": "material_audio_main",
                    "path": audio_path.replace("\\", "/"),
                    "type": "music",
                    "duration": int(total_duration * 1_000_000),
                }
            ],
        }

        # --- 组装完整 draft_content.json ---
        draft = {
            "platform": {
                "name": "Desktop",
                "version": "6.0.0",
            },
            "draft": {
                "name": f"Task_{task_id}_剪映草稿",
                "width": width,
                "height": height,
                "fps": fps,
                "duration": int(total_duration * 1_000_000),
                "tracks": [
                    {
                        "id": "track_video",
                        "type": "video",
                        "segments": video_segments,
                        "attribute": 0,
                    },
                    {
                        "id": "track_audio",
                        "type": "audio",
                        "segments": audio_segments,
                        "attribute": 0,
                    },
                    {
                        "id": "track_subtitle",
                        "type": "subtitle",
                        "segments": subtitle_segments,
                        "attribute": 0,
                    },
                ],
                "materials": materials,
            },
        }

        output_path = os.path.join(task_dir, "draft_content.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(draft, f, ensure_ascii=False, indent=2)

        print(f"[video:jianying] 剪映草稿已导出: {output_path} ({len(video_segments)} 视频段, {len(subtitle_segments)} 字幕段)")
        return output_path

    except Exception as e:
        print(f"[video:jianying] 剪映草稿导出失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


# ============== 自动发布到剪映草稿箱（剪映专业版 / JianyingPro）==============

def _find_jianyingpro_meta_path() -> Optional[str]:
    """找到剪映专业版的 root_meta_info.json 路径。"""
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(local_appdata, "JianyingPro", "User Data", "Projects", "com.lveditor.draft", "root_meta_info.json"),
        os.path.join(local_appdata, "CapCut", "User Data", "Projects", "com.lveditor.draft", "root_meta_info.json"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def auto_publish_to_jianying(
    task_id: int,
    task_dir: str,
    image_paths: list[str],
    audio_path: str,
    draft_name: str = "",
) -> bool:
    """
    成片后自动将草稿发送到剪映桌面版本地草稿箱（适配剪映专业版 JianyingPro）。

    工作原理：
    1. 读取剪映的 root_meta_info.json，找到 draft_root_path（草稿根目录）
    2. 在 draft_root_path 下创建以视频标题命名的子文件夹
    3. 将 task_dir 下已有的 draft_content.json 复制过去
    4. 复制所有配图、音频素材
    5. 在 root_meta_info.json 中注册新草稿
    6. 打开剪映桌面版即可在草稿箱看到

    Returns:
        是否成功
    """
    meta_path = _find_jianyingpro_meta_path()
    if not meta_path:
        print("[jianying:publish] 未找到剪映专业版 root_meta_info.json，跳过自动发布")
        return False

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as e:
        print(f"[jianying:publish] 读取 root_meta_info.json 失败: {e}")
        return False

    # 从已有草稿中提取 draft_root_path
    all_drafts = meta.get("all_draft_store", [])
    draft_root = ""
    for d in all_drafts:
        root = d.get("draft_root_path", "")
        if root and os.path.exists(root):
            draft_root = root
            break
    if not draft_root:
        # 兜底：用 Documents 目录
        draft_root = os.path.join(os.path.expanduser("~"), "Documents", "JianyingPro Drafts")
        print(f"[jianying:publish] 未找到 draft_root_path，使用兜底: {draft_root}")

    # 草稿文件夹名（清理非法字符）
    folder_name = draft_name.strip() or f"VideoAuto_Task_{task_id}"
    for bad in '<>:"/\\|?*':
        folder_name = folder_name.replace(bad, "_")

    draft_dest = os.path.join(draft_root, folder_name)
    os.makedirs(draft_dest, exist_ok=True)

    # --- 复制 draft_content.json ---
    existing_draft_json = os.path.join(task_dir, "draft_content.json")
    if not os.path.exists(existing_draft_json):
        print("[jianying:publish] task_dir 中无 draft_content.json，跳过")
        return False

    import shutil
    dest_json = os.path.join(draft_dest, "draft_content.json")
    shutil.copy2(existing_draft_json, dest_json)

    # --- 复制素材 ---
    images_dest_dir = os.path.join(draft_dest, "images")
    os.makedirs(images_dest_dir, exist_ok=True)
    for img_path in image_paths:
        if not img_path or not os.path.exists(img_path):
            continue
        fname = os.path.basename(img_path)
        try:
            shutil.copy2(img_path, os.path.join(images_dest_dir, fname))
        except Exception as e:
            print(f"[jianying:publish] 复制图片失败 {img_path}: {e}")

    # 音频
    if audio_path and os.path.exists(audio_path):
        audio_fname = os.path.basename(audio_path)
        try:
            shutil.copy2(audio_path, os.path.join(draft_dest, audio_fname))
        except Exception as e:
            print(f"[jianying:publish] 复制音频失败: {e}")

    # 封面图（取第一张配图）
    cover_path = image_paths[0] if image_paths else None
    cover_dest = os.path.join(draft_dest, "draft_cover.jpg")
    if cover_path and os.path.exists(cover_path):
        try:
            shutil.copy2(cover_path, cover_dest)
        except Exception:
            # 封面复制失败不阻塞
            pass

    # --- 计算总时长 ---
    try:
        from mutagen.mp3 import MP3
        audio_total = MP3(audio_path).info.length if audio_path and os.path.exists(audio_path) else 30.0
    except Exception:
        audio_total = 30.0

    # --- 注册到 root_meta_info.json ---
    draft_fold = draft_dest.replace("\\", "/")
    draft_json_file = (draft_fold + "/draft_content.json").replace("\\", "/")
    draft_cover = (draft_fold + "/draft_cover.jpg").replace("\\", "/")
    draft_id = f"VideoAuto-{task_id}-{int(time.time())}"

    new_entry = {
        "cloud_draft_cover": False,
        "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False,
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": draft_cover,
        "draft_fold_path": draft_fold,
        "draft_id": draft_id,
        "draft_is_ai_shorts": False,
        "draft_is_cloud_temp_draft": False,
        "draft_is_invisible": False,
        "draft_is_web_article_video": False,
        "draft_json_file": draft_json_file,
        "draft_name": folder_name,
        "draft_new_version": "",
        "draft_root_path": draft_root,
        "draft_timeline_materials_size": 0,
        "draft_type": "",
        "draft_web_article_video_enter_from": "",
        "streaming_edit_draft_ready": True,
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0,
        "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1,
        "tm_draft_create": int(time.time() * 1000000),
        "tm_draft_modified": int(time.time() * 1000000),
        "tm_draft_removed": 0,
        "tm_duration": int(audio_total * 1_000_000),
    }

    # 检查是否已有同 task_id 的旧条目，有则替换
    replaced = False
    for i, d in enumerate(all_drafts):
        if str(task_id) in d.get("draft_name", "") or draft_id == d.get("draft_id", ""):
            all_drafts[i] = new_entry
            replaced = True
            break
    if not replaced:
        all_drafts.insert(0, new_entry)

    meta["all_draft_store"] = all_drafts

    # 写回（先备份）
    backup_path = meta_path + ".bak"
    try:
        shutil.copy2(meta_path, backup_path)
    except Exception:
        pass

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[jianying:publish] ✅ 已自动发送到剪映草稿箱: {draft_dest}")
    print(f"[jianying:publish]    素材: {len(image_paths)} 图 + 1 音频 → {folder_name}")
    print(f"[jianying:publish]    请打开剪映桌面版 → 「草稿」页面即可看到")
    return True

# ============== 主入口：v3 1:1 绑定合成 ==============

async def compose_final_video(
    task_id: int,
    db,
    style: str = "default",
    watermark_text: str = "",
    bottom_disclaimer: str = "以上内容仅供参考，不构成医疗建议",
    font_size: int = 52,
    zoom_speed: float = 0.0012,  # 此参数在 v3 被忽略，由动态计算取代
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    disclaimer_author: str = "",
    disclaimer_title: str = "",
) -> dict:
    """
    v5 核心重构：一键合成最终竖版成片。

    核心铁律（v5）：
    1. 【坚决禁止二次切分】：直接从 TaskImage 表读取句子列表，
       保证与生图阶段完全一致，消灭黑屏和图文错位。
    2. 【1:1 绝对绑定】：每个句子 = 1 张图 = 1 段音频 = 1 组词级字幕 = 1 个视频片段。
    3. 【音频时间戳驱动】：优先读取每段音频的实际时长，
       只在必要时用 TTS 大段时长按字符比例分配给内部句子。
    4. 【抗抖动电影级动效】：2x 预放大 + bicubic + pzoom + d=1，丝滑匀速推进。
    5. 【字随音动】：每句字幕拆为 8-12 字短组，逐组 enable 时间窗口精准切换。
    6. 【防遮挡字幕】：#FFCC00 高曝光黄，y=height*0.6（距底部 40%），行距加大。
    7. 【参数化声明模板】：支持 {author} / {title} 占位符动态替换。
    8. 【自动导出剪映草稿】：同步生成 draft_content.json（含词级字幕 + Ken Burns 关键帧）。

    Returns:
        {"video_path": str, "duration_sec": float, "segment_count": int,
         "srt_path": str, "ass_path": str, "jianying_draft_path": str}
    """
    from models import TaskImage, Task, TaskSegment
    from services.llm_service import split_into_short_sentences

    # ---- 1. 获取任务 ----
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return {"error": f"任务 {task_id} 不存在", "segment_count": 0}

    tasks_dir = os.path.join(os.path.dirname(__file__), "..", "data", "tasks")
    task_dir = os.path.join(os.path.abspath(tasks_dir), str(task_id))

    # ---- 2. 读取改写稿 + 用与生图一致的参数切句 ----
    rewritten = task.rewritten_transcript or ""
    rewritten_file = os.path.join(task_dir, "rewritten.txt")
    if not rewritten and os.path.exists(rewritten_file):
        with open(rewritten_file, "r", encoding="utf-8") as f:
            rewritten = f.read()

    if not rewritten.strip():
        return {"error": "没有改写稿，请先完成文本改写", "segment_count": 0}

    # ★ v3 核心：使用与 image_service 完全相同的切句参数
    # image_service: split_into_short_sentences(rewritten, max_chars=80, min_chars=30)
    sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)
    total_sentences = len(sentences)
    print(f"[video:v4] 全文 {len(rewritten)} 字 → {total_sentences} 句（与生图参数一致）")

    # ---- 3. 读取配图记录（1:1 绑定）----
    image_records = (
        db.query(TaskImage)
        .filter(TaskImage.task_id == task_id)
        .order_by(TaskImage.segment_index)
        .all()
    )
    image_map: dict[int, str] = {}
    for rec in image_records:
        if rec.status == "success" and rec.image_path and os.path.exists(rec.image_path):
            image_map[rec.segment_index] = rec.image_path
    print(f"[video:v4] 找到 {len(image_map)} 张可用配图（共 {total_sentences} 句）")

    # ---- 4. 获取音频 + 精确时间戳 ----
    # 优先方案 A：TTS 段数与句子数一致 → 1:1 直接读时长
    # 降级方案 B：TTS 段数 ≠ 句子数 → 读大段音频时长 + 按字符比例分配
    final_audio = os.path.join(task_dir, "final_tts.mp3")

    # 尝试从 segments 构建 final_tts.mp3
    if not os.path.exists(final_audio):
        segs_dir = os.path.join(task_dir, "segments")
        if os.path.exists(segs_dir):
            import glob
            wavs = sorted(glob.glob(os.path.join(segs_dir, "seg_*.mp3")))
            if wavs:
                print(f"[video:v4] 未找到 final_tts.mp3，自动从 {len(wavs)} 个片段拼接...")
                list_path = os.path.join(segs_dir, "_merge_list.txt")
                with open(list_path, "w", encoding="utf-8") as f:
                    for w in wavs:
                        f.write(f"file '{os.path.abspath(w)}'\n")
                _run_ffmpeg([
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", list_path, "-c", "copy", final_audio,
                ], timeout=60, description="拼接 final_tts.mp3")
                try:
                    os.remove(list_path)
                except Exception:
                    pass

    if not os.path.exists(final_audio):
        return {"error": "未找到 final_tts.mp3 配音文件，请先生成配音", "segment_count": 0}

    total_audio_duration = get_audio_duration(final_audio)
    print(f"[video:v4] 总配音时长: {total_audio_duration:.1f}s")

    # ---- 4a. 判断方案 A vs 方案 B ----
    tts_segments = (
        db.query(TaskSegment)
        .filter(TaskSegment.task_id == task_id, TaskSegment.status == "success")
        .order_by(TaskSegment.segment_index)
        .all()
    )

    seg_durations: list[float] = []

    if len(tts_segments) == total_sentences:
        # ★ 方案 A：完美 1:1 绑定，直接读每段音频时长
        print(f"[video:v4] 方案 A：TTS 段数({len(tts_segments)}) = 句子数({total_sentences})，1:1 绑定")
        for seg in tts_segments:
            seg_path = seg.audio_path or os.path.join(task_dir, "segments", f"seg_{seg.segment_index:03d}.mp3")
            dur = get_audio_duration(seg_path) if os.path.exists(seg_path) else 0.0
            if dur <= 0:
                # 回退：按字符比例估算
                dur = len(seg.text) / max(1, len(rewritten)) * total_audio_duration
                print(f"[video:v4] 片段 {seg.segment_index} 音频时长读取失败，估算 {dur:.1f}s")
            seg_durations.append(dur)
    else:
        # ★ 方案 B：TTS 大段 → 按字符比例分配给内部句子
        # 简单可靠：既然 TTS 段和句子都覆盖同一文本，直接用字符比例分配时长
        print(f"[video:v4] 方案 B：TTS 段数({len(tts_segments)}) != 句子数({total_sentences})，按字符比例分配")
        total_chars = sum(len(s) for s in sentences) or 1
        seg_durations = [len(s) / total_chars * total_audio_duration for s in sentences]
        avg_dur = total_audio_duration / total_sentences
        print(f"[video:v4]   平均每句 {avg_dur:.1f}s（{len(rewritten)/total_sentences:.0f} 字/句）")
        print(f"[video:v4]   提示：如需 1:1 精确绑定，请重新初始化 TTS 片段（将使用句子级切段）")

    # 确保 seg_durations 长度匹配 sentences
    while len(seg_durations) < total_sentences:
        remaining_time = total_audio_duration - sum(seg_durations)
        if remaining_time <= 0:
            seg_durations.append(0.5)
        else:
            remaining_sents = total_sentences - len(seg_durations)
            seg_durations.append(remaining_time / max(1, remaining_sents))
    seg_durations = seg_durations[:total_sentences]

    # ---- 5. 水印信息 ----
    book_title = task.book_title or ""
    book_author = task.book_author or ""
    wm_text = watermark_text or (f"《{book_title}》{book_author}" if book_title else "")

    # ---- 5b. v5 声明模板参数化 ----
    # 如果提供了 author/title 参数且 disclaimer 包含 {author}/{title} 占位符，动态替换
    author_val = disclaimer_author or book_author or ""
    title_val = disclaimer_title or book_title or ""
    try:
        rendered_disclaimer = bottom_disclaimer.format(author=author_val, title=title_val)
    except (KeyError, ValueError):
        # 模板不含占位符或格式化失败，使用原始字符串
        rendered_disclaimer = bottom_disclaimer
    if rendered_disclaimer != bottom_disclaimer:
        print(f"[video:v5] 声明模板渲染: {rendered_disclaimer[:60]}...")
    bottom_disclaimer = rendered_disclaimer

    # ---- 6. 数据目录 ----
    clips_dir = os.path.join(task_dir, "video_clips")
    os.makedirs(clips_dir, exist_ok=True)

    # ---- 7. v3 动态 max_zoom（根据片段时长自动调整）----
    def calc_max_zoom(dur: float) -> float:
        """
        根据片段时长计算最大缩放倍率（v4 增强版）。

        缩放是向内裁剪（zoom-in），不会扩展画面边界，
        因此不存在黑边穿帮风险，可以大胆推进。
        """
        if dur < 5:
            return 1.12   # 短片段：快速明显推进
        elif dur < 10:
            return 1.18   # 中片段：肉眼可感知的深呼吸感
        elif dur < 20:
            return 1.20   # 长片段（10-16s 主力区间）：对标爆款视频的明显持续推进
        else:
            return 1.22   # 超长片段：最大推进，彻底消灭静态 PPT 感

    # ---- 8. 逐句生成视频片段（v3 1:1 绑定）----
    clip_paths = []
    image_paths_ordered = []  # 用于剪映导出
    success_count = 0
    black_count = 0

    for i, (sentence, dur) in enumerate(zip(sentences, seg_durations)):
        if dur < 0.3:
            print(f"[video:v4] 句子 {i} 时长过短({dur:.1f}s)，跳过")
            continue

        # ★ v3 核心：找配图，1:1 绑定，绝不产生黑屏
        img_path = image_map.get(i)
        if not img_path:
            # 尝试直接读文件
            fallback = os.path.join(task_dir, "images", f"seg_{i:03d}.png")
            if os.path.exists(fallback):
                img_path = fallback

        if not img_path:
            # ★★★ 最后的最后才生成黑色占位图（这种情况不应发生）★★★
            print(f"[video:v4] WARNING: 句子 {i} 无配图！生成深色占位图")
            from PIL import Image as PILImage
            img_path = os.path.join(clips_dir, f"_placeholder_{i:03d}.png")
            dark = PILImage.new("RGB", (width, height), (30, 30, 35))
            dark.save(img_path, "PNG")
            black_count += 1

        image_paths_ordered.append(img_path)

        clip_path = os.path.join(clips_dir, f"clip_{i:03d}.mp4")
        my_max_zoom = calc_max_zoom(dur)

        ok = create_ken_burns_clip(
            image_path=img_path,
            output_path=clip_path,
            duration_sec=dur,
            subtitle_text=sentence,
            fps=fps,
            width=width,
            height=height,
            max_zoom=my_max_zoom,
            subtitle_font_size=font_size,
            watermark_text=wm_text,
            bottom_disclaimer=bottom_disclaimer,
        )

        if ok:
            clip_paths.append(clip_path)
            success_count += 1
            if (i + 1) % 15 == 0 or i == total_sentences - 1:
                pct = (i + 1) / total_sentences * 100
                print(f"[video:v4] segment {i + 1}/{total_sentences} ({pct:.0f}%) OK {success_count}")
        else:
            # ★ A/V 同步保护：失败片段用静音占位替代
            print(f"[video:v4] segment {i + 1}/{total_sentences} FAIL → 占位填充 {dur:.1f}s")
            ph_path = os.path.join(clips_dir, f"clip_{i:03d}_ph.mp4")
            if create_silent_placeholder_clip(ph_path, dur, width, height, fps, label=f"seg{i}"):
                clip_paths.append(ph_path)

    if black_count > 0:
        print(f"[video:v4] WARNING: {black_count} 个句子无配图（深色占位）")

    if not clip_paths:
        return {"error": "所有视频片段生成失败", "segment_count": total_sentences}

    print(f"[video:v4] 成功生成 {success_count}/{total_sentences} 个视频片段")

    # ---- 9. 拼接所有片段 ----
    concat_path = os.path.join(task_dir, "concat_video.mp4")
    if not concat_clips(clip_paths, concat_path):
        return {"error": "视频拼接失败", "segment_count": len(clip_paths)}

    # ---- 10. 混入音轨 ----
    final_path = os.path.join(task_dir, "final_1080x1920.mp4")
    if not mux_audio(concat_path, final_audio, final_path):
        return {"error": "音轨混流失败", "segment_count": len(clip_paths)}

    final_duration = get_audio_duration(final_path)
    final_size = os.path.getsize(final_path) if os.path.exists(final_path) else 0

    # ---- 11. 导出 SRT 字幕 ----
    srt_path = os.path.join(task_dir, "subtitles.srt")
    export_srt(sentences, seg_durations, srt_path)

    # ---- 12. 导出 ASS 高级字幕 ----
    ass_path = os.path.join(task_dir, "subtitles.ass")
    export_ass(sentences, seg_durations, ass_path, font_size=font_size, font_color="&H0000CCFF&")

    # ---- 13. 导出剪映草稿 ----
    jianying_path = export_jianying_draft(
        task_id=task_id,
        task_dir=task_dir,
        sentences=sentences,
        seg_durations=seg_durations,
        image_paths=image_paths_ordered,
        audio_path=final_audio,
        font_size=font_size,
        font_color_hex="#FFCC00",
    )

    # ---- 14. 收尾 ----
    print(f"[video:v4] >>> 成片完成: {final_path}")
    print(f"[video:v4]    时长: {final_duration:.1f}s, 大小: {final_size / 1024 / 1024:.1f}MB")
    print(f"[video:v4]    分镜数: {success_count} 句, 每句约 {total_audio_duration / max(1, success_count):.1f}s")
    if black_count > 0:
        print(f"[video:v4]    WARNING 黑屏占位: {black_count} 句（建议重跑该句配图）")
    if srt_path and os.path.exists(srt_path):
        print(f"[video:v4]    SRT 字幕: {srt_path}")
    if ass_path and os.path.exists(ass_path):
        print(f"[video:v4]    ASS 字幕: {ass_path}")
    if jianying_path:
        print(f"[video:v4]    剪映草稿: {jianying_path}")

    # 更新 Task
    if task:
        task.current_step = 5
        db.commit()

    result = {
        "video_path": final_path,
        "video_url": f"/video/{task_id}/final_1080x1920.mp4",
        "duration_sec": round(final_duration, 1),
        "size_mb": round(final_size / 1024 / 1024, 1),
        "segment_count": success_count,
        "width": width,
        "height": height,
        "srt_path": srt_path,
        "srt_url": f"/video/{task_id}/subtitles.srt",
        "ass_path": ass_path,
        "ass_url": f"/video/{task_id}/subtitles.ass",
        "jianying_draft_path": jianying_path,
        "jianying_draft_url": f"/video/{task_id}/draft_content.json" if jianying_path else None,
        "black_placeholder_count": black_count,
    }

    return result


async def compose_final_video_typewriter(
    task_id: int,
    db,
    sentences: list[str],
    seg_durations: list[float],
    task_dir: str,
    final_audio: str,
    watermark_text: str = "",
    bottom_disclaimer: str = "",
    font_size: int = 64,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> dict:
    """
    v5: 黑底打字机风格合成 —— 复用同一套配音和句子，全自动产出防搬运版本。

    与 compose_final_video 的区别：
    - 无图片，纯黑底
    - 无 Ken Burns 动效
    - 字幕更大、白色，居中偏上
    - 输出文件名为 final_typewriter_1080x1920.mp4

    Returns:
        {"video_path": str, "video_url": str, "duration_sec": float, "size_mb": float, ...}
    """
    clips_dir = os.path.join(task_dir, "video_clips_typewriter")
    os.makedirs(clips_dir, exist_ok=True)

    clip_paths = []
    success_count = 0

    for i, (sentence, dur) in enumerate(zip(sentences, seg_durations)):
        if dur < 0.3:
            continue

        clip_path = os.path.join(clips_dir, f"clip_tw_{i:03d}.mp4")
        ok = create_typewriter_clip(
            output_path=clip_path,
            duration_sec=dur,
            subtitle_text=sentence,
            fps=fps,
            width=width,
            height=height,
            subtitle_font_size=font_size,
            watermark_text=watermark_text,
            bottom_disclaimer=bottom_disclaimer,
        )

        if ok:
            clip_paths.append(clip_path)
            success_count += 1
            if (i + 1) % 15 == 0 or i == len(sentences) - 1:
                print(f"[video:v5:tw] segment {i + 1}/{len(sentences)} OK {success_count}")
        else:
            # ★ A/V 同步保护：失败片段用静音占位替代
            print(f"[video:v5:tw] segment {i + 1}/{len(sentences)} FAIL → 占位填充 {dur:.1f}s")
            ph_path = os.path.join(clips_dir, f"clip_tw_{i:03d}_ph.mp4")
            if create_silent_placeholder_clip(ph_path, dur, width, height, fps, label=f"tw seg{i}"):
                clip_paths.append(ph_path)

    if not clip_paths:
        return {"error": "所有打字机片段生成失败", "segment_count": 0}

    # 拼接
    concat_path = os.path.join(task_dir, "concat_typewriter.mp4")
    if not concat_clips(clip_paths, concat_path):
        return {"error": "打字机视频拼接失败", "segment_count": len(clip_paths)}

    # 混音
    final_path = os.path.join(task_dir, "final_typewriter_1080x1920.mp4")
    if not mux_audio(concat_path, final_audio, final_path):
        return {"error": "打字机音轨混流失败", "segment_count": len(clip_paths)}

    final_duration = get_audio_duration(final_path)
    final_size = os.path.getsize(final_path) if os.path.exists(final_path) else 0

    print(f"[video:v5:tw] >>> 打字机成片完成: {final_path}")
    print(f"[video:v5:tw]    时长: {final_duration:.1f}s, 大小: {final_size / 1024 / 1024:.1f}MB")

    # 清理 concat 中间文件
    try:
        os.remove(concat_path)
    except Exception:
        pass

    return {
        "video_path": final_path,
        "video_url": f"/video/{task_id}/final_typewriter_1080x1920.mp4",
        "duration_sec": round(final_duration, 1),
        "size_mb": round(final_size / 1024 / 1024, 1),
        "segment_count": success_count,
        "width": width,
        "height": height,
    }


async def compose_final_video_card(
    task_id: int,
    db,
    sentences: list[str],
    seg_durations: list[float],
    image_paths: list[str],
    task_dir: str,
    final_audio: str,
    card_title: str = "",
    card_author: str = "",
    bottom_disclaimer: str = "",
    font_size: int = 52,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> dict:
    """
    v5: 图书口播卡片风格 —— 黄金三段式布局。

    同一个配音/句子/配图，渲染为：
    - 顶部黑色页眉区：书名 + 作者
    - 中部画面区：AI 配图 Ken Burns 缩放 + 黄色逐词字幕
    - 底部黑色页脚区：合规声明

    Returns:
        {"video_path": str, "video_url": str, "duration_sec": float, ...}
    """

    def calc_max_zoom(dur: float) -> float:
        if dur < 5:     return 1.12
        elif dur < 10:  return 1.18
        elif dur < 20:  return 1.20
        else:           return 1.22

    clips_dir = os.path.join(task_dir, "video_clips_card")
    os.makedirs(clips_dir, exist_ok=True)

    clip_paths = []
    success_count = 0

    for i, (sentence, dur) in enumerate(zip(sentences, seg_durations)):
        if dur < 0.3:
            continue

        img_path = image_paths[i] if i < len(image_paths) else None
        if not img_path or not os.path.exists(img_path):
            # 占位图
            from PIL import Image as PILImage
            img_path = os.path.join(clips_dir, f"_ph_{i:03d}.png")
            dark = PILImage.new("RGB", (width, height), (10, 10, 10))
            dark.save(img_path, "PNG")

        clip_path = os.path.join(clips_dir, f"clip_card_{i:03d}.mp4")
        ok = create_card_clip(
            image_path=img_path,
            output_path=clip_path,
            duration_sec=dur,
            subtitle_text=sentence,
            card_title=card_title,
            card_author=card_author,
            fps=fps,
            width=width,
            height=height,
            max_zoom=calc_max_zoom(dur),
            subtitle_font_size=font_size,
            bottom_disclaimer=bottom_disclaimer,
        )

        if ok:
            clip_paths.append(clip_path)
            success_count += 1
            if (i + 1) % 15 == 0 or i == len(sentences) - 1:
                print(f"[video:v5:card] segment {i + 1}/{len(sentences)} OK {success_count}")
        else:
            # ★ A/V 同步保护：失败片段用静音占位替代，防止后续片段前移导致音画脱节
            print(f"[video:v5:card] segment {i + 1}/{len(sentences)} FAIL → 占位填充 {dur:.1f}s")
            ph_path = os.path.join(clips_dir, f"clip_card_{i:03d}_ph.mp4")
            if create_silent_placeholder_clip(ph_path, dur, width, height, fps, label=f"card seg{i}"):
                clip_paths.append(ph_path)
            # 占位也失败则完全跳过（极端情况）

    if not clip_paths:
        return {"error": "所有卡片片段生成失败", "segment_count": 0}

    concat_path = os.path.join(task_dir, "concat_card.mp4")
    if not concat_clips(clip_paths, concat_path):
        return {"error": "卡片视频拼接失败", "segment_count": len(clip_paths)}

    final_path = os.path.join(task_dir, "final_card_1080x1920.mp4")
    if not mux_audio(concat_path, final_audio, final_path):
        return {"error": "卡片音轨混流失败", "segment_count": len(clip_paths)}

    final_duration = get_audio_duration(final_path)
    final_size = os.path.getsize(final_path) if os.path.exists(final_path) else 0

    print(f"[video:v5:card] >>> 卡片成片完成: {final_path}")
    print(f"[video:v5:card]    时长: {final_duration:.1f}s, 大小: {final_size / 1024 / 1024:.1f}MB")
    print(f"[video:v5:card]    书名: 《{card_title}》 {card_author} 著")

    try:
        os.remove(concat_path)
    except Exception:
        pass

    return {
        "video_path": final_path,
        "video_url": f"/video/{task_id}/final_card_1080x1920.mp4",
        "duration_sec": round(final_duration, 1),
        "size_mb": round(final_size / 1024 / 1024, 1),
        "segment_count": success_count,
        "width": width,
        "height": height,
    }


# ============== v6 骨肉分离：全局 FFmpeg 滤镜链 ==============

async def compose_final_video_card_v6(
    task_id: int,
    db,
    sentences: list[str],
    seg_durations: list[float],
    image_paths: list[str],
    task_dir: str,
    final_audio: str,
    card_title: str = "",
    card_author: str = "",
    bottom_disclaimer: str = "",
    font_size: int = 52,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    aspect_ratio: str = "16:9",    # "16:9" | "3:4"
    slogan: str = "- 品读传奇人生 -",
    subtitle_line: str = "图片由AI生成与网络下载\n科普视频 无不良引导",
) -> dict:
    """
    v6 骨肉分离架构：分镜只做纯画面 + Ken Burns，
    页眉/页脚/字幕在最终 FFmpeg filter_complex 中全局完成。

    v7 升级：
    - 3:4 / 16:9 双画幅中部视窗
    - 暗夜海军蓝 #0A162C 顶部/底部遮罩
    - 底部核心标语（行楷 #CBA052）+ 免责小字（思源黑体 #666666）
    """
    # ---- 画幅配置 ----
    if aspect_ratio == "3:4":
        MIDDLE_W = 720
        MIDDLE_H = 960
        HEADER_H = 420      # 顶部遮罩高度
        FOOTER_H = 540      # 底部遮罩高度
        MIDDLE_X = (width - MIDDLE_W) // 2  # 180
        MIDDLE_Y = HEADER_H                  # 420
        FOOTER_Y = MIDDLE_Y + MIDDLE_H       # 1380
    else:
        MIDDLE_W = width    # 1080
        MIDDLE_H = 608
        HEADER_H = 420
        FOOTER_H = 540
        MIDDLE_X = 0
        MIDDLE_Y = (height - MIDDLE_H) // 2  # 656
        FOOTER_Y = MIDDLE_Y + MIDDLE_H       # 1264

    NAVY_BG = "#0A162C"
    GOLD = "#CBA052"
    GRAY_SUB = "#666666"

    def _calc_max_zoom(dur: float) -> float:
        if dur < 5:     return 1.12
        elif dur < 10:  return 1.18
        elif dur < 20:  return 1.20
        else:           return 1.22

    # ---- 目录 ----
    clips_dir = os.path.join(task_dir, "video_clips_card_v6")
    os.makedirs(clips_dir, exist_ok=True)

    # =================================================================
    # Step 1: "Meat" — 逐段生成纯画面 1080×607 片段
    # =================================================================
    pure_clip_paths = []
    success_count = 0
    placeholder_count = 0

    for i, (sentence, dur) in enumerate(zip(sentences, seg_durations)):
        if dur < 0.3:
            continue

        img_path = image_paths[i] if i < len(image_paths) else None
        if not img_path or not os.path.exists(img_path):
            from PIL import Image as PILImage
            ph_img = os.path.join(clips_dir, f"_ph_{i:03d}.png")
            dark = PILImage.new("RGB", (MIDDLE_W, MIDDLE_H), (10, 10, 10))
            dark.save(ph_img, "PNG")
            img_path = ph_img

        clip_path = os.path.join(clips_dir, f"pure_{i:03d}.mp4")
        ok = create_card_pure_clip(
            image_path=img_path,
            output_path=clip_path,
            duration_sec=dur,
            fps=fps,
            out_w=MIDDLE_W,
            out_h=MIDDLE_H,
            max_zoom=_calc_max_zoom(dur),
        )

        if ok:
            pure_clip_paths.append(clip_path)
            success_count += 1
        else:
            print(f"[video:v6:card] pure clip {i + 1}/{len(sentences)} FAIL → 占位 {dur:.1f}s")
            ph_path = os.path.join(clips_dir, f"pure_{i:03d}_ph.mp4")
            if create_silent_placeholder_clip(ph_path, dur, width, MIDDLE_H, fps,
                                              label=f"card_v6 seg{i}"):
                pure_clip_paths.append(ph_path)
                placeholder_count += 1

        if (i + 1) % 15 == 0 or i == len(sentences) - 1:
            print(f"[video:v6:card] pure clip {i + 1}/{len(sentences)} OK {success_count}")

    if not pure_clip_paths:
        return {"error": "所有纯画面片段生成失败", "segment_count": 0}

    # ---- 拼接纯画面 → middle_video.mp4 ----
    middle_video = os.path.join(task_dir, "middle_video_card_v6.mp4")
    if not concat_clips(pure_clip_paths, middle_video):
        return {"error": "纯画面拼接失败", "segment_count": len(pure_clip_paths)}

    total_duration = sum(d for d in seg_durations if d >= 0.3)
    print(f"[video:v6:card] middle_video 拼接完成: {total_duration:.1f}s")

    # =================================================================
    # Step 2 & 3: "Bone + Union" — 分批处理
    # =================================================================
    # v6.1: 62 句 × ~3 组词级字幕 → ~320 drawtext + 746s × 30fps 计算量
    # 单次 FFmpeg 无法在合理时间内完成，改为每 12 句一批独立 overlay + drawtext
    BATCH_SIZE = 12
    font_file = _find_chinese_font()
    hw_font_file = _find_handwriting_font()

    # --- 辅助：drawtext 文本转义 ---
    def _esc(text: str) -> str:
        return (
            text.replace("\\", "\\\\")
                .replace(":", "\\:")
                .replace("'", "\\'")
                .replace("%", "\\%")
                .replace("{", "\\{")
                .replace("}", "\\}")
        )

    # --- 辅助：按标点折行 ---
    def _wrap(text: str, max_chars: int) -> list[str]:
        if len(text) <= max_chars:
            return [text]
        lines = []
        remaining = text
        while len(remaining) > max_chars:
            chunk = remaining[:max_chars]
            best = max_chars
            for bp in "，,。！？；;、":
                pos = chunk.rfind(bp, max(0, max_chars - 10))
                if pos != -1:
                    best = pos + 1
                    break
            lines.append(remaining[:best].strip())
            remaining = remaining[best:].strip()
        if remaining:
            lines.append(remaining)
        return lines

    total_batches = (len(sentences) + BATCH_SIZE - 1) // BATCH_SIZE
    batch_videos = []

    for batch_idx in range(total_batches):
        batch_start = batch_idx * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, len(sentences))
        batch_sentences = sentences[batch_start:batch_end]
        batch_durations = seg_durations[batch_start:batch_end]
        batch_pure = [pure_clip_paths[i] for i in range(batch_start, batch_end)
                      if i < len(pure_clip_paths)]

        if not batch_pure:
            print(f"[video:v6:card] Batch {batch_idx+1}/{total_batches} 无可用纯画面片段，跳过")
            continue

        # 2a. 拼接批内纯画面
        batch_middle = os.path.join(clips_dir, f"middle_batch_{batch_start:03d}.mp4")
        if not concat_clips(batch_pure, batch_middle):
            print(f"[video:v6:card] Batch {batch_idx+1}/{total_batches} 纯画面拼接失败，跳过")
            continue

        batch_dur = sum(d for d in batch_durations if d >= 0.3)

        # 2b. 构建批内 drawtext（v7：海军蓝遮罩 + 哑光金标语 + 灰免责）
        dt_list = []

        # 顶部标题（海军蓝 #0A162C 底 + 白字）
        if card_title.strip():
            if card_author.strip():
                # 图书赛道：《书名》+ 作者
                title_text = f"《{card_title}》"
                dt_list.append(
                    f"drawtext=fontfile='{font_file}':"
                    f"text='{_esc(title_text)}':"
                    f"fontcolor=white:fontsize=56:"
                    f"x=(w-text_w)/2:y=180:"
                    f"shadowcolor=black@0.5:shadowx=2:shadowy=2"
                )
                author_text = f"{card_author} 著"
                dt_list.append(
                    f"drawtext=fontfile='{font_file}':"
                    f"text='{_esc(author_text)}':"
                    f"fontcolor=white@0.85:fontsize=32:"
                    f"x=(w-text_w)/2:y=280:"
                    f"shadowcolor=black@0.4:shadowx=1:shadowy=1"
                )
            else:
                # 百货赛道：纯爆款标题，居中偏上
                dt_list.append(
                    f"drawtext=fontfile='{font_file}':"
                    f"text='{_esc(card_title)}':"
                    f"fontcolor=white:fontsize=48:"
                    f"x=(w-text_w)/2:y=200:"
                    f"shadowcolor=black@0.5:shadowx=2:shadowy=2"
                )

        # 底部核心标语（哑光金 #CBA052，50px，楷体/手写体）
        if slogan.strip():
            dt_list.append(
                f"drawtext=fontfile='{hw_font_file}':"
                f"text='{_esc(slogan.strip())}':"
                f"fontcolor={GOLD}:fontsize=50:"
                f"x=(w-text_w)/2:y={FOOTER_Y + 70}:"
                f"shadowcolor=black@0.3:shadowx=1:shadowy=1"
            )

        # 底部免责小字（浅灰 #666666，26px，支持 \n 折行）
        if subtitle_line.strip():
            sub_lines = subtitle_line.strip().split("\\n")
            for sli, sline in enumerate(sub_lines):
                if not sline.strip():
                    continue
                sy = FOOTER_Y + 160 + sli * 32
                dt_list.append(
                    f"drawtext=fontfile='{font_file}':"
                    f"text='{_esc(sline.strip())}':"
                    f"fontcolor={GRAY_SUB}:fontsize=26:"
                    f"x=(w-text_w)/2:y={sy}:"
                    f"shadowcolor=black@0.2:shadowx=1:shadowy=1"
                )

        # 词级字幕（字随音动，批内累计时间戳 + enable）
        subtitle_base_y = MIDDLE_Y + MIDDLE_H - 50  # 中部区底部内侧
        batch_cumulative = 0.0
        for sentence, dur in zip(batch_sentences, batch_durations):
            if dur < 0.3 or not sentence.strip():
                batch_cumulative += dur
                continue

            word_groups = split_into_word_groups(
                sentence.strip(), group_min=8, group_max=12, duration_sec=dur,
            )
            for group in word_groups:
                g_text = group["text"]
                g_start = batch_cumulative + group["start"]
                g_end = batch_cumulative + group["end"]

                # 组内换行
                max_chars = 18
                if len(g_text) <= max_chars:
                    sub_lines = [g_text]
                else:
                    mid = len(g_text) // 2
                    best = mid
                    for bp in "，,。！？；;、":
                        pos = g_text.find(bp, max(0, mid - 6), min(len(g_text), mid + 6))
                        if pos != -1:
                            best = pos + 1
                            break
                    if best == mid:
                        best = max_chars
                    sub_lines = [g_text[:best], g_text[best:]]

                for li, line in enumerate(sub_lines):
                    if not line.strip():
                        continue
                    y_pos = subtitle_base_y + li * (font_size + 10)
                    dt_list.append(
                        f"drawtext=fontfile='{font_file}':"
                        f"text='{_esc(line)}':"
                        f"fontcolor=#FFCC00:fontsize={font_size}:"
                        f"x=(w-text_w)/2:y={y_pos}:"
                        f"shadowcolor=black@0.7:shadowx=3:shadowy=3:"
                        f"bordercolor=black@0.5:borderw=4:"
                        f"enable='between(t,{g_start},{g_end})'"
                    )
            batch_cumulative += dur

        # 2c. 组装批内 filter_complex（v7：海军蓝遮罩 + 中部视窗 + pad）
        # color 背景 → pad 撑高 → overlay 中部画面 → drawtext → format
        if aspect_ratio == "3:4":
            # 3:4: 中部 720×960，左右黑边自然形成，上下海军蓝 pad
            filter_parts = [
                f"color=c={NAVY_BG}:s={width}x{height}:d={batch_dur}:r={fps},format=yuv420p[bg]",
            ]
            overlay_with_subs = f"[bg][0:v]overlay={MIDDLE_X}:{MIDDLE_Y}:shortest=1"
        else:
            # 16:9: 中部 1080×608，顶部 420 + 底部 540 = 1920
            filter_parts = [
                f"color=c={NAVY_BG}:s={width}x{height}:d={batch_dur}:r={fps},format=yuv420p[bg]",
            ]
            overlay_with_subs = f"[bg][0:v]overlay=0:{MIDDLE_Y}:shortest=1"

        if dt_list:
            overlay_with_subs += "," + ",".join(dt_list)
        overlay_with_subs += f",format=yuv420p[outv]"
        filter_parts.append(overlay_with_subs)

        filter_complex = ";".join(filter_parts)

        # 2d. 滤镜脚本写入临时文件（绕过 Windows 命令行长度限制）
        filter_script_path = os.path.join(clips_dir, f"filter_batch_{batch_start:03d}.txt")
        with open(filter_script_path, "w", encoding="utf-8") as f:
            f.write(filter_complex)

        # 2e. FFmpeg 执行
        batch_output = os.path.join(clips_dir, f"batch_{batch_start:03d}_card.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-i", batch_middle,
            "-filter_complex_script", filter_script_path,
            "-map", "[outv]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            batch_output,
        ]

        print(
            f"[video:v6:card] Batch {batch_idx+1}/{total_batches}: "
            f"段 {batch_start}-{batch_end-1}, {batch_dur:.1f}s, "
            f"{len(dt_list)} drawtext"
        )

        try:
            result = _run_ffmpeg(cmd, timeout=300, description=f"card v6 batch {batch_idx}")
            # 清理批内临时文件
            try:
                os.remove(filter_script_path)
            except Exception:
                pass
            try:
                os.remove(batch_middle)
            except Exception:
                pass

            if result.returncode != 0:
                stderr_tail = (result.stderr or "")[-500:]
                print(f"[video:v6:card] Batch {batch_idx+1} FFmpeg 错误: {stderr_tail}")
                continue
            if os.path.exists(batch_output) and os.path.getsize(batch_output) > 1000:
                batch_videos.append(batch_output)
            else:
                print(f"[video:v6:card] Batch {batch_idx+1} 输出文件异常")
        except Exception as e:
            try:
                os.remove(filter_script_path)
            except Exception:
                pass
            try:
                os.remove(batch_middle)
            except Exception:
                pass
            print(f"[video:v6:card] Batch {batch_idx+1} 异常: {e}")
            continue

    if not batch_videos:
        return {"error": "所有批次复合均失败", "segment_count": success_count}

    # ---- 拼接所有批次视频 ----
    concat_card_path = os.path.join(task_dir, "concat_card.mp4")
    if not concat_clips(batch_videos, concat_card_path):
        return {"error": "批次拼接失败", "segment_count": success_count}

    # 清理批次中间视频
    for bv in batch_videos:
        try:
            os.remove(bv)
        except Exception:
            pass

    # ---- 混入音轨 ----
    final_path = os.path.join(task_dir, "final_card_1080x1920.mp4")
    has_audio = os.path.exists(final_audio)

    if has_audio:
        if not mux_audio(concat_card_path, final_audio, final_path):
            return {"error": "音轨混流失败", "segment_count": success_count}
        try:
            os.remove(concat_card_path)
        except Exception:
            pass
    else:
        final_path = concat_card_path

    # ---- 验证 ----
    final_duration = get_audio_duration(final_path)
    final_size = os.path.getsize(final_path) if os.path.exists(final_path) else 0

    if final_size < 1000:
        return {"error": "输出文件过小或缺失", "segment_count": success_count}

    print(f"[video:v6:card] >>> 卡片 v6 成片完成: {final_path}")
    print(f"[video:v6:card]    时长: {final_duration:.1f}s, 大小: {final_size / 1024 / 1024:.1f}MB")
    print(f"[video:v6:card]    分镜: {success_count}, 占位: {placeholder_count}")
    print(f"[video:v6:card]    书名: 《{card_title}》 {card_author} 著")

    return {
        "video_path": final_path,
        "video_url": f"/video/{task_id}/final_card_1080x1920.mp4",
        "duration_sec": round(final_duration, 1),
        "size_mb": round(final_size / 1024 / 1024, 1),
        "segment_count": success_count,
        "width": width,
        "height": height,
    }


# ============== v8 对标卡片模式：深藏青底 + 8:9 满宽大图 + 双色标题 ==============

# ---- 版式常量（模块级，复用）----
_BENCH_BG       = "#071730"
_BENCH_WHITE    = "#FBFBF7"
_BENCH_GOLD     = "#C9B38C"
_BENCH_SLOGAN   = "#D9BB7A"
_BENCH_SUB      = "#FEFEFC"
_BENCH_DISC     = "#212C40"
_BENCH_LINE_CLR = "0xE8E4D4"
_BENCH_TITLE_FS  = 80
_BENCH_SUB_FS    = 64
_BENCH_SLOGAN_FS = 68
_BENCH_DISC_FS   = 28
_BENCH_TITLE1_Y  = 150
_BENCH_TITLE2_Y  = 259
_BENCH_IMG_Y     = 377
_BENCH_IMG_H     = 1214
_BENCH_LINE_H    = 4
_BENCH_SUB_Y     = 377 + 1214 - 258 - 64   # 1269，字幕底边距图底 258px
_BENCH_SLOGAN_Y  = 377 + 1214 + 4 + 56     # 1651
_BENCH_DISC1_Y   = 1774
_BENCH_DISC_PITCH = 36


def _composite_bench_segment(
    pure_clip_path: str,
    output_path: str,
    sentence_text: str,
    duration_sec: float,
    title_line1: str = "",
    title_line2: str = "",
    slogan: str = "- 品读传奇人生 -",
    subtitle_line: str = "图片由AI生成与网络下载\n科普视频 无不良引导",
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> bool:
    """
    v9 逐段复合（替代 v8 批量 filter_complex）。

    将一段已生成好的纯画面 clip（1080×1214 Ken Burns）叠到藏青底 +
    双色标题 + 细线 + 金色标语 + 免责 + 口播字幕，输出完整 1080×1920 片段。

    逐段编码消除了原 v8 批量复合的 FFmpeg 崩溃风险（enable 窗口跨段计算溢出），
    且在单段失败时可自动占位，保证 A/V 同步。
    """
    import os as _os

    if not _os.path.exists(pure_clip_path):
        print(f"[video:bench:seg] pure clip missing: {pure_clip_path}")
        return False
    if duration_sec <= 0:
        return False

    title_font = _find_title_font()
    slogan_font = _find_handwriting_font()  # 标语用行楷/手写体，对齐对标成片风格

    def _esc(text: str) -> str:
        return (
            text.replace("\\", "\\\\").replace(":", "\\:")
                .replace("'", "\\'").replace("%", "\\%")
                .replace("{", "\\{").replace("}", "\\}")
        )

    # ---- filter_complex：bg → overlay pure → drawtext ----
    dt_parts = []

    # 细线（图片上 / 下）
    dt_parts.append(
        f"drawbox=x=0:y={_BENCH_IMG_Y - _BENCH_LINE_H}:w={width}:h={_BENCH_LINE_H}:"
        f"color={_BENCH_LINE_CLR}@0.95:t=fill"
    )
    dt_parts.append(
        f"drawbox=x=0:y={_BENCH_IMG_Y + _BENCH_IMG_H}:w={width}:h={_BENCH_LINE_H}:"
        f"color={_BENCH_LINE_CLR}@0.95:t=fill"
    )

    # 双色标题
    if title_line1.strip() and title_line2.strip():
        dt_parts.append(
            f"drawtext=fontfile='{title_font}':text='{_esc(title_line1.strip())}':"
            f"fontcolor={_BENCH_WHITE}:fontsize={_BENCH_TITLE_FS}:"
            f"x=(w-text_w)/2:y={_BENCH_TITLE1_Y}"
        )
        dt_parts.append(
            f"drawtext=fontfile='{title_font}':text='{_esc(title_line2.strip())}':"
            f"fontcolor={_BENCH_GOLD}:fontsize={_BENCH_TITLE_FS}:"
            f"x=(w-text_w)/2:y={_BENCH_TITLE2_Y}"
        )
    elif title_line1.strip() or title_line2.strip():
        single = (title_line1 or title_line2).strip()
        single_y = (_BENCH_TITLE1_Y + _BENCH_TITLE2_Y) // 2
        dt_parts.append(
            f"drawtext=fontfile='{title_font}':text='{_esc(single)}':"
            f"fontcolor={_BENCH_GOLD}:fontsize={_BENCH_TITLE_FS}:"
            f"x=(w-text_w)/2:y={single_y}"
        )

    # 标语（行楷/手写体）
    if slogan.strip():
        dt_parts.append(
            f"drawtext=fontfile='{slogan_font}':text='{_esc(slogan.strip())}':"
            f"fontcolor={_BENCH_SLOGAN}:fontsize={_BENCH_SLOGAN_FS}:"
            f"x=(w-text_w)/2:y={_BENCH_SLOGAN_Y}"
        )

    # 免责
    if subtitle_line.strip():
        disc_lines = subtitle_line.replace("\\n", "\n").split("\n")
        for dli, dline in enumerate(disc_lines[:2]):
            if not dline.strip():
                continue
            dt_parts.append(
                f"drawtext=fontfile='{title_font}':text='{_esc(dline.strip())}':"
                f"fontcolor={_BENCH_DISC}:fontsize={_BENCH_DISC_FS}:"
                f"x=(w-text_w)/2:y={_BENCH_DISC1_Y + dli * _BENCH_DISC_PITCH}"
            )

    # 口播字幕（单段，自然断句 + enable 窗口）
    if sentence_text.strip():
        phrases = _split_natural_phrases(sentence_text.strip(), max_chars=14)
        phrase_cjk_counts = [_count_cjk(p) for p in phrases]
        total_cjk = sum(phrase_cjk_counts)

        t_cursor = 0.0
        for pi, phrase in enumerate(phrases):
            p_cjk = phrase_cjk_counts[pi]
            p_dur = (p_cjk / total_cjk) * duration_sec if total_cjk > 0 else duration_sec / len(phrases)
            p_dur = max(p_dur, 0.8)
            p_end = duration_sec if pi == len(phrases) - 1 else t_cursor + p_dur
            if p_end > duration_sec - 0.3:
                p_end = duration_sec

            display = _strip_subtitle_punct(phrase)
            if display:
                dt_parts.append(
                    f"drawtext=fontfile='{title_font}':text='{_esc(display)}':"
                    f"fontcolor={_BENCH_SUB}:fontsize={_BENCH_SUB_FS}:"
                    f"x=(w-text_w)/2:y={_BENCH_SUB_Y}:"
                    f"shadowcolor=black@0.6:shadowx=2:shadowy=2:"
                    f"bordercolor=black@0.5:borderw=4:"
                    f"enable='between(t,{t_cursor:.3f},{p_end:.3f})'"
                )
            t_cursor = p_end
            if t_cursor >= duration_sec:
                break

    # 组装 filter_complex
    chain = f"[bg][0:v]overlay=0:{_BENCH_IMG_Y}:shortest=1"
    if dt_parts:
        chain += "," + ",".join(dt_parts)
    chain += ",format=yuv420p[outv]"

    filter_complex = (
        f"color=c={_BENCH_BG}:s={width}x{height}:d={duration_sec}:r={fps},"
        f"format=yuv420p[bg];"
        + chain
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", pure_clip_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
    ]

    try:
        result = _run_ffmpeg(cmd, timeout=120,
                             description=f"bench composite seg {_os.path.basename(output_path)}")
        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-400:]
            print(f"[video:bench:seg] FFmpeg error: {stderr_tail}")
            return False
        return _os.path.exists(output_path) and _os.path.getsize(output_path) > 1000
    except Exception as e:
        print(f"[video:bench:seg] exception: {e}")
        return False

async def compose_final_video_card_bench(
    task_id: int,
    db,
    sentences: list[str],
    seg_durations: list[float],
    image_paths: list[str],
    task_dir: str,
    final_audio: str,
    title_line1: str = "",     # 第一行（白色，铺垫短行）
    title_line2: str = "",     # 第二行（金色，点题长行）
    slogan: str = "- 品读传奇人生 -",   # 图片下方静态金色标语
    subtitle_line: str = "图片由AI生成与网络下载\\n科普视频 无不良引导",  # 底部低对比免责小字
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> dict:
    """
    v8 对标卡片版式（像素级复刻对标成片，参数来自 1080×2340 截图实测）：

    ┌──────────────────────┐ 深藏青 #071730 背景
    │   标题行1（白 #FBFBF7）│ y=150, 字号 80
    │   标题行2（金 #C9B38C）│ y=259, 行距 29
    │ ──── 4px 浅白细线 ──── │ y=373
    │▓▓▓ 8:9 大图满宽出血 ▓▓│ y=377, 1080×1214, Ken Burns
    │▓▓ 口播字幕（白，描边）▓│ 字幕底边距图片底边 258px（实测）
    │ ──── 4px 浅白细线 ──── │ y=1591
    │  静态标语（金 #D9BB7A）│ y=1651, 字号 68, 单行居中
    │  免责两行小字 #212C40  │ y=1774/1810, 字号 28, 低对比
    └──────────────────────┘
    架构沿用 v6 骨肉分离：纯画面片段 → 分批全局 filter_complex。
    """
    # ---- 实测版式常量 ----  # v9: 静态常量移至模块级 _BENCH_*
    IMG_W, IMG_H = width, 1214  # 8:9 满宽出血

    def _calc_max_zoom(dur: float) -> float:
        if dur < 5:     return 1.10
        elif dur < 10:  return 1.14
        else:           return 1.16

    clips_dir = os.path.join(task_dir, "video_clips_card_bench")
    os.makedirs(clips_dir, exist_ok=True)

    # =================================================================
    # Step 1: 逐段生成纯画面 1080×1215 片段（Ken Burns）
    # =================================================================
    pure_clip_paths = []
    success_count = 0
    placeholder_count = 0

    for i, (sentence, dur) in enumerate(zip(sentences, seg_durations)):
        if dur < 0.3:
            continue

        img_path = image_paths[i] if i < len(image_paths) else None
        if not img_path or not os.path.exists(img_path):
            from PIL import Image as PILImage
            ph_img = os.path.join(clips_dir, f"_ph_{i:03d}.png")
            dark = PILImage.new("RGB", (IMG_W, IMG_H), (10, 16, 28))
            dark.save(ph_img, "PNG")
            img_path = ph_img

        clip_path = os.path.join(clips_dir, f"pure_{i:03d}.mp4")
        ok = create_card_pure_clip(
            image_path=img_path,
            output_path=clip_path,
            duration_sec=dur,
            fps=fps,
            out_w=IMG_W,
            out_h=IMG_H,
            max_zoom=_calc_max_zoom(dur),
        )

        if ok:
            pure_clip_paths.append(clip_path)
            success_count += 1
        else:
            print(f"[video:bench] pure clip {i + 1}/{len(sentences)} FAIL → 占位 {dur:.1f}s")
            ph_path = os.path.join(clips_dir, f"pure_{i:03d}_ph.mp4")
            if create_silent_placeholder_clip(ph_path, dur, IMG_W, IMG_H, fps,
                                              label=f"bench seg{i}"):
                pure_clip_paths.append(ph_path)
                placeholder_count += 1

        if (i + 1) % 15 == 0 or i == len(sentences) - 1:
            print(f"[video:bench] pure clip {i + 1}/{len(sentences)} OK {success_count}")

    if not pure_clip_paths:
        return {"error": "所有纯画面片段生成失败", "segment_count": 0}

    total_duration = sum(d for d in seg_durations if d >= 0.3)

    # =================================================================
    # Step 2: 逐段复合（v9 替代 v8 批量 filter_complex）
    # =================================================================
    # v8 原方案将 12 段拼在一起用 filter_complex_script 做全局复合，
    # 字幕 enable 窗口跨段计算在 FFmpeg 长滤镜链中易静默失败（返回 0
    # 但无输出），导致 batch 丢失 → 最终成片时间轴断裂、音画不同步。
    # v9 改为逐段独立复合：每段单独 background + overlay + drawtext，
    # 单段失败自动占位保护 A/V 同步。
    composite_clips = []
    composite_success = 0

    for i, (sentence, dur) in enumerate(zip(sentences, seg_durations)):
        if dur < 0.3:
            continue

        pure_clip = pure_clip_paths[i] if i < len(pure_clip_paths) else None
        if not pure_clip or not os.path.exists(pure_clip):
            # 纯画面片段生成失败 → 占位
            ph_path = os.path.join(clips_dir, f"full_{i:03d}_ph.mp4")
            if create_silent_placeholder_clip(ph_path, dur, width, height, fps,
                                              label=f"bench full seg{i}"):
                composite_clips.append(ph_path)
                placeholder_count += 1
            continue

        comp_path = os.path.join(clips_dir, f"full_{i:03d}.mp4")
        ok = _composite_bench_segment(
            pure_clip_path=pure_clip,
            output_path=comp_path,
            sentence_text=sentence,
            duration_sec=dur,
            title_line1=title_line1,
            title_line2=title_line2,
            slogan=slogan,
            subtitle_line=subtitle_line,
            width=width,
            height=height,
            fps=fps,
        )

        if ok:
            composite_clips.append(comp_path)
            composite_success += 1
        else:
            print(f"[video:bench] composite seg {i+1}/{len(sentences)} FAIL → 占位 {dur:.1f}s")
            ph_path = os.path.join(clips_dir, f"full_{i:03d}_ph.mp4")
            if create_silent_placeholder_clip(ph_path, dur, width, height, fps,
                                              label=f"bench full seg{i}"):
                composite_clips.append(ph_path)
                placeholder_count += 1

        if (i + 1) % 15 == 0 or i == len(sentences) - 1:
            print(f"[video:bench] composite {i+1}/{len(sentences)} OK {composite_success}")

    if not composite_clips:
        return {"error": "所有片段复合失败", "segment_count": success_count}

    # ---- 拼接所有复合片段 ----
    concat_path = os.path.join(task_dir, "concat_bench.mp4")
    if not concat_clips(composite_clips, concat_path):
        return {"error": "片段拼接失败", "segment_count": success_count}

    for bv in composite_clips:
        try:
            os.remove(bv)
        except Exception:
            pass

    # ---- 混入音轨 ----
    final_path = os.path.join(task_dir, "final_bench_1080x1920.mp4")
    if os.path.exists(final_audio):
        if not mux_audio(concat_path, final_audio, final_path):
            return {"error": "音轨混流失败", "segment_count": success_count}
        try:
            os.remove(concat_path)
        except Exception:
            pass
    else:
        final_path = concat_path

    final_duration = get_audio_duration(final_path)
    final_size = os.path.getsize(final_path) if os.path.exists(final_path) else 0
    if final_size < 1000:
        return {"error": "输出文件过小或缺失", "segment_count": success_count}

    print(f"[video:bench] >>> 对标卡片成片完成: {final_path}")
    print(f"[video:bench]    时长: {final_duration:.1f}s, 大小: {final_size / 1024 / 1024:.1f}MB")
    print(f"[video:bench]    分镜: {success_count}, 占位: {placeholder_count}")
    print(f"[video:bench]    标题: {title_line1} / {title_line2}")

    return {
        "video_path": final_path,
        "video_url": f"/video/{task_id}/final_bench_1080x1920.mp4",
        "duration_sec": round(final_duration, 1),
        "size_mb": round(final_size / 1024 / 1024, 1),
        "segment_count": success_count,
        "width": width,
        "height": height,
    }


# ============== 风格预设（v5：多模式裂变）==============

VIDEO_STYLES = {
    "default": {
        "name": "标准书单",
        "mode": "cinematic",
        "font_size": 52,
        "zoom_speed": 0.0012,
        "max_zoom": 1.20,
        "subtitle_color": "#FFCC00",
    },
    "warm": {
        "name": "温暖治愈",
        "mode": "cinematic",
        "font_size": 54,
        "zoom_speed": 0.0008,
        "max_zoom": 1.18,
        "subtitle_color": "#FFCC00",
    },
    "elder": {
        "name": "中老年大字版",
        "mode": "cinematic",
        "font_size": 64,
        "zoom_speed": 0.0006,
        "max_zoom": 1.15,
        "subtitle_color": "#FFCC00",
    },
    "dynamic": {
        "name": "动感快节奏",
        "mode": "cinematic",
        "font_size": 48,
        "zoom_speed": 0.0020,
        "max_zoom": 1.22,
        "subtitle_color": "#FFCC00",
    },
    "card_16x9": {
        "name": "经典图书三段式 (16:9 视窗版)",
        "mode": "card",
        "font_size": 52,
        "max_zoom": 1.20,
        "subtitle_color": "#FFCC00",
        "aspect_ratio": "16:9",
    },
    "card_3x4": {
        "name": "黄金遮罩三段式 (3:4 视窗版)",
        "mode": "card",
        "font_size": 52,
        "max_zoom": 1.20,
        "subtitle_color": "#FFCC00",
        "aspect_ratio": "3:4",
    },
    "card_bench": {
        "name": "对标卡片 (深藏青 + 8:9 满宽大图)",
        "mode": "bench",
        "font_size": 68,
        "max_zoom": 1.16,
        "subtitle_color": "#D9BB7A",
        "aspect_ratio": "8:9",
    },
}
