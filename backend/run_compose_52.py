"""
Task 52 v3 全量合成 runner — 独立脚本，不受 bash 超时影响
"""
import asyncio, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal
from services.video_service import compose_final_video

LOG_FILE = os.path.join(os.path.dirname(__file__), "data", "tasks", "52", "_compose_result.txt")

async def main():
    t0 = time.time()
    db = SessionLocal()
    try:
        result = await compose_final_video(
            task_id=52, db=db, style="default",
            watermark_text="", bottom_disclaimer="以上内容仅供参考，不构成医疗建议",
            font_size=52,
        )
        elapsed = time.time() - t0

        lines = []
        if "error" in result:
            lines.append(f"ERROR: {result['error']}")
        else:
            lines.append(f"DONE: {result['duration_sec']}s, {result['size_mb']}MB, {result['segment_count']} segments, {elapsed:.0f}s elapsed")
            lines.append(f"VIDEO: {result['video_path']}")
            lines.append(f"SRT: {result.get('srt_path', 'NONE')}")
            lines.append(f"ASS: {result.get('ass_path', 'NONE')}")
            lines.append(f"JIANYING: {result.get('jianying_draft_path', 'NONE')}")
            lines.append(f"BLACK: {result.get('black_placeholder_count', 0)}")

        for l in lines:
            print(l)
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    finally:
        db.close()

asyncio.run(main())
