"""task 6 bench 合成（v11 多关键帧 Ken Burns）"""
import asyncio, os, sys, subprocess, json
sys.path.insert(0, '.')
from database import SessionLocal
from models import Task, TaskImage, TaskSegment
from services.llm_service import split_into_short_sentences, split_title_two_lines
from _resource import get_data_dir

TASK_ID = 6
TASK_ROOT = os.path.join(get_data_dir(), "tasks", str(TASK_ID))

async def main():
    print("=" * 50)
    print(f"Task {TASK_ID}: bench 合成 (v11 多关键帧 Ken Burns)")
    print("=" * 50)

    # 1. 文案切句
    rewritten_file = os.path.join(TASK_ROOT, "rewritten.txt")
    with open(rewritten_file, "r", encoding="utf-8") as f:
        rewritten = f.read()
    sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)
    print(f"sentences: {len(sentences)}, {len(rewritten)} chars")

    # 2. 拼接 final_audio
    FINAL_AUDIO = os.path.join(TASK_ROOT, "final_audio.mp3")
    if not os.path.exists(FINAL_AUDIO):
        print("拼接 final_audio...")
        db = SessionLocal()
        segs_audio = sorted(
            db.query(TaskSegment).filter(
                TaskSegment.task_id == TASK_ID, TaskSegment.status == "success"
            ).all(), key=lambda s: s.segment_index
        )
        db.close()
        concat_list = os.path.join(TASK_ROOT, "audio_concat.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for s in segs_audio:
                if s.audio_path and os.path.exists(s.audio_path):
                    f.write(f"file '{s.audio_path.replace(chr(92), '/')}'\n")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list, "-c", "copy", FINAL_AUDIO
        ], capture_output=True, timeout=120)
        print(f"final_audio: {os.path.getsize(FINAL_AUDIO)} bytes")

    # 3. 音频对齐 → seg_durations
    db = SessionLocal()
    tts_segs = db.query(TaskSegment).filter(
        TaskSegment.task_id == TASK_ID, TaskSegment.status == "success"
    ).order_by(TaskSegment.segment_index).all()
    db.close()

    total_chars = sum(len(s) for s in sentences)
    tts_durs, tts_lens = [], []
    for seg in tts_segs:
        ap = seg.audio_path
        if ap and os.path.exists(ap):
            try:
                r = subprocess.run([
                    "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", ap
                ], capture_output=True, text=True, timeout=15)
                d = float(json.loads(r.stdout)["format"]["duration"])
            except:
                d = max(len(seg.text or "") * 0.25, 1.5)
        else:
            d = max(len(seg.text or "") * 0.25, 1.5)
        tts_durs.append(d)
        tts_lens.append(max(len(seg.text or ""), 1))

    tts_total_chars = sum(tts_lens)
    anchors = [(0.0, 0.0)]
    c_acc, t_acc = 0, 0.0
    for sl, sd in zip(tts_lens, tts_durs):
        c_acc += sl; t_acc += sd
        anchors.append((c_acc / tts_total_chars, t_acc))

    def _time_at(frac):
        for (f0, t0), (f1, t1) in zip(anchors, anchors[1:]):
            if frac <= f1:
                return t0 + (frac - f0) / (f1 - f0) * (t1 - t0) if f1 > f0 else t1
        return anchors[-1][1]

    c_pos = 0
    seg_durations = []
    for s in sentences:
        start = _time_at(c_pos / total_chars)
        c_pos += len(s)
        end = _time_at(c_pos / total_chars)
        seg_durations.append(max(end - start, 0.5))
    print(f" seg_durations: avg {sum(seg_durations)/len(seg_durations):.1f}s")

    # 4. 图片路径
    db = SessionLocal()
    img_records = db.query(TaskImage).filter(
        TaskImage.task_id == TASK_ID, TaskImage.status == "success"
    ).order_by(TaskImage.segment_index).all()
    img_map = {r.segment_index: r.image_path for r in img_records if r.image_path and os.path.exists(r.image_path)}
    images_dir = os.path.join(TASK_ROOT, "images")
    image_paths = []
    for i in range(len(sentences)):
        p = img_map.get(i) or os.path.join(images_dir, f"seg_{i:03d}.png")
        image_paths.append(p)
    db.close()
    print(f"image_paths: {len(image_paths)}, all exist: {all(os.path.exists(p) for p in image_paths)}")

    # 5. 标题
    db = SessionLocal()
    task = db.query(Task).filter(Task.id == TASK_ID).first()
    db.close()
    raw_title = task.video_title or task.book_title or ""
    t1, t2 = "", ""
    if raw_title:
        import re
        cjk = len(re.findall(r'[一-鿿]', raw_title))
        if cjk <= 16:
            from main import _split_title_local
            lines = _split_title_local(raw_title, max_chars=16)
            t1, t2 = lines[0] if len(lines) > 1 else "", lines[-1]
        else:
            split = await split_title_two_lines(raw_title, "", "")
            t1, t2 = split.get("line1", ""), split.get("line2", "")
    print(f"title: [{t1}] / [{t2}]")

    # 6. 合成
    from services.video_service import compose_final_video_card_bench
    db = SessionLocal()
    result = await compose_final_video_card_bench(
        task_id=TASK_ID, db=db,
        sentences=sentences,
        seg_durations=seg_durations,
        image_paths=image_paths,
        task_dir=TASK_ROOT,
        final_audio=FINAL_AUDIO,
        title_line1=t1, title_line2=t2,
        slogan="- 品读传奇人生 -",
        subtitle_line="图片由AI生成与网络下载\\n科普视频 无不良引导",
    )
    db.close()
    print(f"\nDone: {result.get('video_url', result)}")

asyncio.run(main())
