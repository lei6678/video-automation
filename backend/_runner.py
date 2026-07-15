import asyncio, os, sys, time
os.chdir(r"E:\video-automation\backend")
sys.path.insert(0, r"E:\video-automation\backend")

from database import SessionLocal
from services.video_service import compose_final_video

RESULT = r"E:\video-automation\backend\data\tasks\52\_result.txt"

async def main():
    t0 = time.time()
    db = SessionLocal()
    try:
        result = await compose_final_video(
            task_id=52, db=db, style="default",
            font_size=52,
        )
        elapsed = time.time() - t0
        lines = []
        if "error" in result:
            lines.append(f"ERROR: {result['error']}")
        else:
            lines.append(f"DONE|dur={result['duration_sec']}s|size={result['size_mb']}MB|segs={result['segment_count']}|time={elapsed:.0f}s")
            lines.append(f"VIDEO={result['video_path']}")
            lines.append(f"SRT={result.get('srt_path','')}")
            lines.append(f"ASS={result.get('ass_path','')}")
            lines.append(f"JIANYING={result.get('jianying_draft_path','')}")
            lines.append(f"BLACK={result.get('black_placeholder_count',0)}")
        with open(RESULT, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        for l in lines:
            print(l)
    finally:
        db.close()

asyncio.run(main())
