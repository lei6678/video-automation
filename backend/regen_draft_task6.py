"""
Task 6 重新生成剪映草稿 draft_content.json
—— 基于修正后的 26 段数据（与 recompose_task6.py 同源）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from services.video_service import export_jianying_draft, get_audio_duration
from services.llm_service import split_into_short_sentences

TASK_DIR = os.path.join(os.path.dirname(__file__), "data", "tasks", "6")


def main():
    # 1. 改写全文 → 26 句
    rewritten_path = os.path.join(TASK_DIR, "rewritten.txt")
    with open(rewritten_path, "r", encoding="utf-8") as f:
        raw = f.read()
    full_text = ""
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        full_text += parts[1] if len(parts) > 1 else parts[0]
    sentences = split_into_short_sentences(full_text, max_chars=80, min_chars=30)
    print(f"句子数: {len(sentences)}")

    # 2. TTS 分段时长
    segments_dir = os.path.join(TASK_DIR, "segments")
    seg_files = sorted([
        f for f in os.listdir(segments_dir)
        if f.endswith(".mp3") and f.startswith("seg_")
    ])
    tts_durs = []
    for sf in seg_files:
        dur = get_audio_duration(os.path.join(segments_dir, sf))
        tts_durs.append(dur)
    print(f"TTS 分段: {len(tts_durs)}, 总时长: {sum(tts_durs):.1f}s")

    # 句数 = 分段数 → 1:1
    if len(sentences) != len(tts_durs):
        print(f"[ERROR] 句数({len(sentences)}) != TTS分段({len(tts_durs)}), 无法 1:1 映射")
        return
    seg_durations = tts_durs

    # 3. 图片路径
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
    print(f"图片: {len(image_paths)}, 有效: {sum(1 for p in image_paths if p and os.path.exists(p))}")

    # 4. 音频
    final_audio = os.path.join(TASK_DIR, "final_audio.mp3")
    if not os.path.exists(final_audio):
        final_audio = os.path.join(TASK_DIR, "final_tts.mp3")
    print(f"音频: {os.path.basename(final_audio)}")

    # 5. 备份旧草稿
    old_draft = os.path.join(TASK_DIR, "draft_content.json")
    if os.path.exists(old_draft):
        bak = old_draft + ".old"
        os.rename(old_draft, bak)
        print(f"旧草稿已备份: draft_content.json.old")

    # 6. 生成新草稿
    result = export_jianying_draft(
        task_id=6,
        task_dir=TASK_DIR,
        sentences=sentences,
        seg_durations=seg_durations,
        image_paths=image_paths,
        audio_path=final_audio,
    )
    if result:
        print(f"\n[DONE] 新草稿: {result}")
        size_kb = os.path.getsize(result) / 1024
        print(f"       大小: {size_kb:.1f} KB")
    else:
        print("\n[FAIL] 草稿生成失败")


if __name__ == "__main__":
    main()
