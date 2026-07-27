"""
重新合成 Task 6: 《她主演作品国际获奖却被诬陷送入疯人院》
—— 使用修复后的 xfade 字幕偏移补偿逻辑 + 正确的 26 句切分
"""
import asyncio
import os
import sys
import json
import sqlite3
import re as _re

sys.path.insert(0, os.path.dirname(__file__))

from services.video_service import (
    compose_final_video_card_bench,
    get_audio_duration,
)
from services.llm_service import split_into_short_sentences


# ---- 标题自然断行（从 main.py 复制，避免导入副作用）----
def _count_cjk_local(text: str) -> int:
    return len(_re.findall(r'[一-鿿]', text))


def _split_title_local(title: str, max_chars: int = 16) -> list[str]:
    """将标题自然断行为两行，不动原文一个字。"""
    cjk = _count_cjk_local(title)
    if cjk <= max_chars:
        return [title]
    for bp in ("，", "；", "。", "：", "！", "？"):
        pos = title.find(bp)
        if pos > 2 and pos < len(title) - 4:
            return [title[:pos + 1], title[pos + 1:].lstrip()]
    mid = len(title) // 2
    best = mid
    for bp in "，,。；;、 \t":
        pos = title.find(bp, max(0, mid - len(title) // 4), min(len(title), mid + len(title) // 4))
        if pos != -1:
            best = pos + 1
            break
    if best == mid or best >= len(title) or best <= 2:
        cjk_count = _count_cjk_local(title)
        if cjk_count > max_chars:
            cjk_half = cjk_count // 2
            cnt = 0
            for j, ch in enumerate(title):
                if _re.match(r'[一-鿿]', ch):
                    cnt += 1
                    if cnt >= cjk_half:
                        return [title[:j+1], title[j+1:].lstrip()]
        return [title]
    return [title[:best], title[best:].lstrip()]


TASK_DIR = os.path.join(os.path.dirname(__file__), "data", "tasks", "6")
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "app.db")


def get_task_data():
    """收集 Task 6 所需全部数据 —— 使用正确的 26 句切分"""
    # 1. 改写全文 → split_into_short_sentences → 26 句（对齐 TTS 分段和配图）
    rewritten_path = os.path.join(TASK_DIR, "rewritten.txt")
    with open(rewritten_path, "r", encoding="utf-8") as f:
        raw = f.read()
    # 去掉行号前缀（"1\ttext" → "text"），合并为一段全文
    full_text = ""
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        full_text += (parts[1] if len(parts) > 1 else parts[0])
    sentences = split_into_short_sentences(full_text, max_chars=80, min_chars=30)
    print(f"[recompose] 句子数: {len(sentences)} (split_into_short_sentences)")

    # 2. TTS 分段时长 —— 26 句 1:1 对应 26 个 TTS 音频文件
    segments_dir = os.path.join(TASK_DIR, "segments")
    seg_files = sorted([
        f for f in os.listdir(segments_dir)
        if f.endswith(".mp3") and f.startswith("seg_")
    ])
    tts_durs = []
    for sf in seg_files:
        dur = get_audio_duration(os.path.join(segments_dir, sf))
        tts_durs.append(dur)

    total_dur = sum(tts_durs)
    print(f"[recompose] TTS 分段: {len(tts_durs)} 个, 总时长: {total_dur:.1f}s")

    # 句数 = 分段数 → 直接取 TTS 分段时长，无需插值
    if len(sentences) == len(tts_durs):
        seg_durations = tts_durs
        print(f"[recompose] 音画对齐: 26 句 1:1 映射 26 个 TTS 分段")
    else:
        print(f"[recompose] WARNING: 句数({len(sentences)}) != TTS分段数({len(tts_durs)})，回退插值")
        total_chars = sum(len(s) for s in sentences)
        tts_lens = [10] * len(tts_durs)  # 无 DB 文本，统一占位
        tts_total_chars = sum(tts_lens)
        anchors = []
        c_acc, t_acc = 0, 0.0
        for seg_len, seg_dur in zip(tts_lens, tts_durs):
            c_acc += seg_len
            t_acc += seg_dur
            anchors.append((c_acc / tts_total_chars, t_acc))

        def _time_at(frac):
            for (f0, t0), (f1, t1) in zip(anchors, anchors[1:]):
                if frac <= f1:
                    return t0 + (frac - f0) / (f1 - f0) * (t1 - t0) if f1 > f0 else t1
            return anchors[-1][1]

        seg_durations = []
        c_pos = 0
        for s in sentences:
            start_t = _time_at(c_pos / total_chars)
            c_pos += len(s)
            end_t = _time_at(c_pos / total_chars)
            seg_durations.append(end_t - start_t)

    # 3. 图片路径 —— 26 张图，1:1 对应 26 句
    images_dir = os.path.join(TASK_DIR, "images")
    img_files = sorted([
        f for f in os.listdir(images_dir)
        if f.endswith(".png") and f.startswith("seg_")
    ])
    img_map = {}
    for f in img_files:
        seg_idx = int(f.replace("seg_", "").replace(".png", ""))
        img_map[seg_idx] = os.path.join(images_dir, f)

    image_paths = []
    for i in range(len(sentences)):
        if i in img_map:
            image_paths.append(img_map[i])
        else:
            image_paths.append(image_paths[-1] if image_paths else None)
    print(f"[recompose] 图片数: {len(image_paths)}, 有效: {sum(1 for p in image_paths if p and os.path.exists(p))}")

    # 4. 音频
    final_audio = os.path.join(TASK_DIR, "final_audio.mp3")
    if not os.path.exists(final_audio):
        final_audio = os.path.join(TASK_DIR, "final_tts.mp3")
    print(f"[recompose] 音频: {os.path.basename(final_audio)} (存在: {os.path.exists(final_audio)})")

    # 5. 标题
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE id=6").fetchone()
    row_dict = dict(row) if row else {}
    conn.close()

    raw_title = ""
    meta_json = row_dict.get('4') or row_dict.get(4) or ''
    if meta_json:
        try:
            meta = json.loads(meta_json)
            raw_title = meta.get("title", "")
        except (json.JSONDecodeError, TypeError):
            pass
    if not raw_title:
        raw_title = row_dict.get('9') or row_dict.get(9) or ''
    if not raw_title:
        raw_title = "她主演作品国际获奖却被诬陷送入疯人院"

    lines = _split_title_local(raw_title, max_chars=16)
    t1 = lines[0] if len(lines) > 1 else ""
    t2 = lines[-1]
    print(f"[recompose] 标题: L1='{t1}' L2='{t2}'")

    # 清理旧产物
    old_final = os.path.join(TASK_DIR, "final_bench_1080x1920.mp4")
    if os.path.exists(old_final):
        bak = old_final + ".bak2"
        os.rename(old_final, bak)
        print(f"[recompose] 旧成片已备份: {os.path.basename(bak)}")

    return {
        "task_id": 6,
        "db": None,
        "sentences": sentences,
        "seg_durations": seg_durations,
        "image_paths": image_paths,
        "task_dir": TASK_DIR,
        "final_audio": final_audio,
        "title_line1": t1,
        "title_line2": t2,
    }


async def main():
    data = get_task_data()
    print("\n[recompose] 开始合成...")
    result = await compose_final_video_card_bench(**data)

    if "error" in result:
        print(f"\n[recompose] FAIL: {result['error']}")
    else:
        print(f"\n[recompose] OK!")
        print(f"  path: {result.get('video_path')}")
        print(f"  duration: {result.get('duration_sec')}s")
        print(f"  size: {result.get('size_mb')}MB")
        print(f"  segments: {result.get('segment_count')}")


if __name__ == "__main__":
    asyncio.run(main())
