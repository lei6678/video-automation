"""
调试 generate-audio API 流程
"""
import sys, os, asyncio, traceback
sys.path.insert(0, '.')
os.chdir('E:/video-automation/backend')

import main as app_module
from database import SessionLocal
from models import Task, TaskSegment
from services.tts_service import generate_audio as do_generate_audio
from datetime import datetime

TASKS_DIR = os.path.join(os.path.dirname(__file__), 'data', 'tasks')

async def test():
    # 1. 创建测试任务
    db = SessionLocal()
    task = Task(
        source_url='manual:test',
        status='text_ready',
        current_step=2,
        raw_transcript='今天想跟大家分享一下如何养成好习惯。我觉得养成好习惯最重要的是坚持。',
        rewritten_transcript='养成好习惯的关键在于坚持。只要你坚持二十一天，就能形成一个新习惯。',
        douyin_meta={'title': '测试', 'author': '测试'},
        created_at=datetime.utcnow()
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    task_id = task.id
    print(f'任务 {task_id} 创建成功')
    db.close()

    task_folder = os.path.join(TASKS_DIR, str(task_id))
    segments_folder = os.path.join(task_folder, 'segments')
    os.makedirs(segments_folder, exist_ok=True)

    # 2. 模拟 init_segments 逻辑
    import re
    text = '养成好习惯的关键在于坚持。只要你坚持二十一天，就能形成一个新习惯。'
    def split_text(text, max_chars=400):
        paras = text.split('\n')
        chunks = []
        for para in paras:
            para = para.strip()
            if not para: continue
            if len(para) <= max_chars:
                chunks.append(para)
            else:
                sp = re.compile(r'([^。！？；\n]+[。！？；])')
                sents = sp.findall(para)
                cur = ''
                for s in sents:
                    if len(cur) + len(s) <= max_chars:
                        cur += s
                    else:
                        if cur: chunks.append(cur)
                        if len(s) > max_chars:
                            for k in range(0, len(s), max_chars):
                                chunks.append(s[k:k+max_chars])
                            cur = ''
                        else:
                            cur = s
                if cur: chunks.append(cur)
        return chunks

    chunks = split_text(text)
    print(f'分 {len(chunks)} 段')

    db = SessionLocal()
    db.query(TaskSegment).filter(TaskSegment.task_id == task_id).delete()
    for i, chunk_text in enumerate(chunks):
        seg = TaskSegment(task_id=task_id, segment_index=i, text=chunk_text, audio_path=None, status='pending', error_msg=None)
        db.add(seg)
    db.commit()
    print('片段初始化完成')
    db.close()

    # 3. 模拟 generate-audio 端点的片段处理逻辑
    db = SessionLocal()
    segments = db.query(TaskSegment).filter(TaskSegment.task_id == task_id).all()
    print(f'查询到 {len(segments)} 片段')

    for seg in segments:
        seg_path = os.path.join(segments_folder, f'seg_{seg.segment_index:03d}.mp3')
        print(f'处理片段 {seg.segment_index}: "{seg.text[:30]}..."')

        try:
            await do_generate_audio(seg.text, voice='zf_xiaobei', rate='+0%', output_path=seg_path)
            seg.status = 'success'
            seg.audio_path = seg_path
            db.commit()
            size = os.path.getsize(seg_path)
            print(f'  成功: {size} bytes')
        except Exception as e:
            seg.status = 'failed'
            seg.error_msg = f'{type(e).__name__}: {str(e)}'
            db.commit()
            print(f'  失败: {type(e).__name__}: {e}')

    db.close()
    print('完成')

if __name__ == '__main__':
    asyncio.run(test())
