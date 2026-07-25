"""直接合成 task 4 bench 视频（v11 多关键帧 Ken Burns）"""
import asyncio, os, sys
sys.path.insert(0, '.')
from database import SessionLocal
from models import Task, TaskImage, TaskSegment
from services.video_service import compose_final_video_card_bench
from services.llm_service import split_into_short_sentences, split_title_two_lines
from _resource import get_data_dir

TASK_ID = 4
TASK_ROOT = os.path.join(get_data_dir(), "tasks", str(TASK_ID))
os.makedirs(os.path.join(TASK_ROOT, "video"), exist_ok=True)

async def main():
    db = SessionLocal()
    task = db.query(Task).filter(Task.id == TASK_ID).first()
    if not task:
        print(f"Task {TASK_ID} not found"); return

    # 1. 文案切句
    rewritten_file = os.path.join(TASK_ROOT, "rewritten.txt")
    with open(rewritten_file, "r", encoding="utf-8") as f:
        rewritten = f.read()
    sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)
    print(f"sentences: {len(sentences)}")

    # 2. 音频对齐 → seg_durations
    final_audio = os.path.join(TASK_ROOT, "final_audio.mp3")
    if not os.path.exists(final_audio):
        final_audio = os.path.join(TASK_ROOT, "final_audio.wav")
    if not os.path.exists(final_audio):
        print("final_audio not found, checking segments...")
        # try concatenating from segments
        segments = db.query(TaskSegment).filter(
            TaskSegment.task_id == TASK_ID, TaskSegment.status == "success"
        ).order_by(TaskSegment.segment_index).all()
        if not segments:
            print("NO audio segments!"); return
        print(f"Found {len(segments)} audio segments")

    # compute seg_durations from TTS segments
    import subprocess, json
    tts_segs = db.query(TaskSegment).filter(
        TaskSegment.task_id == TASK_ID,
        TaskSegment.status == "success"
    ).order_by(TaskSegment.segment_index).all()

    seg_durations = []
    total_chars = sum(len(s) for s in sentences)
    total_dur = 0.0
    tts_durs = []
    tts_lens = []
    for seg in tts_segs:
        ap = seg.audio_path
        if ap and os.path.exists(ap):
            try:
                r = subprocess.run([
                    "ffprobe", "-v", "quiet", "-print_format", "json",
                    "-show_format", ap
                ], capture_output=True, text=True, timeout=15)
                d = float(json.loads(r.stdout)["format"]["duration"])
            except:
                d = max(len(seg.text or "") * 0.25, 1.5)
        else:
            d = max(len(seg.text or "") * 0.25, 1.5)
        tts_durs.append(d)
        tts_lens.append(max(len(seg.text or ""), 1))
        total_dur += d
    print(f"TTS: {len(tts_durs)} segments, total {total_dur:.1f}s")

    # character-position anchoring
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
    for s in sentences:
        start = _time_at(c_pos / total_chars)
        c_pos += len(s)
        end = _time_at(c_pos / total_chars)
        seg_durations.append(max(end - start, 0.5))
    print(f"seg_durations: avg {sum(seg_durations)/len(seg_durations):.1f}s, range {min(seg_durations):.1f}-{max(seg_durations):.1f}s")

    # 3. 图片路径
    img_records = db.query(TaskImage).filter(
        TaskImage.task_id == TASK_ID, TaskImage.status == "success"
    ).order_by(TaskImage.segment_index).all()
    img_map = {r.segment_index: r.image_path for r in img_records if r.image_path and os.path.exists(r.image_path)}
    images_dir = os.path.join(TASK_ROOT, "images")
    image_paths = []
    missing = 0
    for i in range(len(sentences)):
        p = img_map.get(i) or os.path.join(images_dir, f"seg_{i:03d}.png")
        if not os.path.exists(p):
            missing += 1
        image_paths.append(p)
    print(f"image_paths: {len(image_paths)} ({missing} missing)")

    # 4. 标题分行
    raw_title = task.video_title or task.book_title or ""
    title_line1, title_line2 = "", ""
    if raw_title:
        import re as _re
        cjk = len(_re.findall(r'[一-鿿]', raw_title))
        if cjk <= 16:
            from main import _split_title_local
            lines = _split_title_local(raw_title, max_chars=16)
            title_line1 = lines[0] if len(lines) > 1 else ""
            title_line2 = lines[-1]
        else:
            split = await split_title_two_lines(raw_title, task.book_title or "", task.book_author or "")
            title_line1 = split.get("line1", "")
            title_line2 = split.get("line2", "")
    print(f"title: [{title_line1}] / [{title_line2}]")

    db.close()

    # 5. 合成
    print("\n=== STARTING BENCH COMPOSITION ===")
    from database import SessionLocal as SL2
    db2 = SL2()
    result = await compose_final_video_card_bench(
        task_id=TASK_ID,
        db=db2,
        sentences=sentences,
        seg_durations=seg_durations,
        image_paths=image_paths,
        task_dir=TASK_ROOT,
        final_audio=final_audio,
        title_line1=title_line1,
        title_line2=title_line2,
        slogan="- 品读传奇人生 -",
        subtitle_line="图片由AI生成与网络下载\\n科普视频 无不良引导",
    )
    db2.close()
    print(f"\nResult: {result.get('video_url', result)}")

asyncio.run(main())
