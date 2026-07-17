"""
SQLAlchemy 数据模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.types import JSON
from database import Base


class Task(Base):
    """任务模型"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    source_url = Column(String, nullable=False)
    status = Column(String, default="pending")
    current_step = Column(Integer, default=1)
    douyin_meta = Column(JSON, default=dict)
    raw_transcript = Column(Text, default="")
    rewritten_transcript = Column(Text, nullable=True)
    book_title = Column(String, nullable=True)
    book_author = Column(String, nullable=True)
    video_title = Column(String, nullable=True)      # AI 生成的爆款标题（百货/流量赛道）
    content_mode = Column(String, default="book")     # "book"=图书赛道 | "general"=百货与流量赛道
    visual_context = Column(Text, nullable=True)       # 配图视觉档案（LLM 提取的主角特征，确保人物一致性）
    error_msg = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TaskSegment(Base):
    """任务片段模型：细粒度跟踪每个音频片段的状态"""
    __tablename__ = "task_segments"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, nullable=False, index=True)
    segment_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False, default="")
    audio_path = Column(String, nullable=True)   # 物理文件路径
    status = Column(String, default="pending")  # pending / success / failed
    error_msg = Column(String, nullable=True)    # 失败原因
    duration_sec = Column(Integer, nullable=True)  # 音频时长（秒）
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=lambda: datetime.utcnow())


class TaskImage(Base):
    """配图表：跟踪每个片段的配图生成状态"""
    __tablename__ = "task_images"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, nullable=False, index=True)
    segment_index = Column(Integer, nullable=False)     # 对应 TaskSegment.segment_index
    grid_index = Column(Integer, nullable=False)         # 所属九宫格编号（从 0 开始）
    cell_position = Column(Integer, nullable=False)      # 九宫格内位置 (1-9)
    image_path = Column(String, nullable=True)           # 裁切后的单图路径
    grid_path = Column(String, nullable=True)            # 九宫格总图路径
    prompt_used = Column(Text, nullable=True)            # 生成用的 prompt
    status = Column(String, default="pending")           # pending / success / failed
    error_msg = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=lambda: datetime.utcnow())