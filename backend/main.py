"""
视频自动化制作工作流 - FastAPI 后端
"""
import asyncio
import os
import requests
from concurrent.futures import ThreadPoolExecutor
from moviepy import VideoFileClip
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, BackgroundTasks
from fastapi.staticfiles import StaticFiles

load_dotenv()

# ★ 打包模式：将 exe 目录及 _internal 子目录加入 PATH，确保 subprocess 能找到捆绑的 ffmpeg.exe
_SYS = __import__("sys")
if getattr(_SYS, "frozen", False):
    _exe_dir = os.path.dirname(_SYS.executable)
    _internal_dir = os.path.join(_exe_dir, "_internal")
    _current_path = os.environ.get("PATH", "")
    for _d in (_internal_dir, _exe_dir):
        if os.path.isdir(_d) and _d not in _current_path:
            os.environ["PATH"] = _d + os.pathsep + _current_path
            _current_path = os.environ["PATH"]  # 更新，避免重复添加

from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import engine, get_db, SessionLocal
from models import Base, Task, TaskSegment, TaskImage
from services.douyin_service import fetch_douyin_video_info
from services.asr_service import transcribe_media
from services.llm_service import rewrite_script
from _resource import get_data_dir, get_project_root

# 确保应用启动时创建必要的目录
TASKS_DIR = os.path.join(get_data_dir(), "tasks")
os.makedirs(TASKS_DIR, exist_ok=True)

# 创建数据库表
Base.metadata.create_all(bind=engine)

# 安全地给 tasks 表添加新列（如果列不存在的话，幂等迁移）
from sqlalchemy import text
with engine.connect() as conn:
    for col_sql in [
        "ALTER TABLE tasks ADD COLUMN error_msg TEXT",
        "ALTER TABLE tasks ADD COLUMN images_generating BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN images_complete BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN total_images INTEGER NOT NULL DEFAULT 0",
    ]:
        try:
            conn.execute(text(col_sql))
            conn.commit()
        except Exception:
            pass  # 列已存在则忽略

app = FastAPI(
    title="视频自动化制作工作流",
    description="抖音链接解析、逐字稿提取、LLM清洗、TTS配音、批量生图、视频合成",
    version="0.1.0",
)

# 挂载静态音频目录，前端可通过 /audio/{task_id}/final_audio.mp3 访问
AUDIO_DIR = TASKS_DIR
app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")

# 配图 & 视频静态服务
IMAGES_DIR = TASKS_DIR
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
app.mount("/video", StaticFiles(directory=IMAGES_DIR), name="video")

# CORS 配置 - 自定义中间件处理所有 preflight（解决 CORSMiddleware OPTIONS 400 问题）
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

@app.middleware("http")
async def cors_preflight_middleware(request: Request, call_next):
    origin = request.headers.get("origin", "")
    # 允许的开发服务器 & 局域网 origin（vite dev / LAN 直连）
    allowed_prefixes = [
        "http://localhost:", "http://127.0.0.1:",
        "http://192.168.", "http://10.", "http://172.",
    ]
    if origin and any(origin.startswith(p) for p in allowed_prefixes):
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
            "Access-Control-Max-Age": "86400",
        }
    else:
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }

    if request.method == "OPTIONS":
        return Response(status_code=200, headers=headers)

    response = await call_next(request)
    for k, v in headers.items():
        response.headers[k] = v
    return response


@app.get("/")
async def root():
    """首页：有前端构建产物时返回工作台页面，否则返回 API 状态"""
    dist_index = os.path.join(get_project_root(), "frontend", "dist", "index.html")
    if os.path.exists(dist_index):
        from fastapi.responses import FileResponse
        return FileResponse(dist_index, media_type="text/html")
    return {"status": "ok", "message": "视频自动化制作工作流 API"}


@app.get("/api/health")
async def health():
    """健康检查"""
    return {"status": "healthy"}


# ============== 请求/响应模型 ==============

class CreateTaskRequest(BaseModel):
    """创建任务请求"""
    source_url: str


class CreateTaskResponse(BaseModel):
    """创建任务响应"""
    task_id: int


class ImageSummary(BaseModel):
    """配图进度摘要（供前端状态条和按钮锁定使用）"""
    total: int = 0
    success: int = 0
    failed: int = 0
    generating: bool = False
    complete: bool = False


class TaskDetailResponse(BaseModel):
    """任务详情响应（v9：含配图进度摘要）"""
    id: int
    source_url: str
    status: str
    current_step: int
    raw_transcript: str | None
    rewritten_transcript: str | None
    douyin_meta: dict
    book_title: str | None = None
    book_author: str | None = None
    video_title: str | None = None
    content_mode: str | None = "book"
    visual_context: str | None = None
    image_summary: ImageSummary | None = None
    error_msg: str | None
    created_at: datetime


class CleanTextRequest(BaseModel):
    """清洗文本请求"""
    task_id: int = 1
    raw_text: str


class CleanTextResponse(BaseModel):
    """清洗文本响应"""
    cleaned: str


class RewriteRequest(BaseModel):
    """脚本改写请求"""
    task_id: int
    mode: str = "rewrite"  # 深度改写（已合并为单一模式，保留字段为兼容）


class RewriteResponse(BaseModel):
    """脚本改写响应（v5：含爆款标题）"""
    rewritten: str
    video_title: str = ""


class BookInfoRequest(BaseModel):
    """书籍信息反推请求"""
    task_id: int


class BookInfoResponse(BaseModel):
    """书籍信息反推响应"""
    book_title: str
    book_author: str
    confidence: float
    evidence: str


class GenerateAudioRequest(BaseModel):
    """TTS 音频生成请求"""
    task_id: int
    voice: str = "vc_wenroumama"   # 音色 ID
    rate: str = "+0%"            # 语速，如 "+10%", "+20%", "-10%"


class GenerateAudioResponse(BaseModel):
    """TTS 音频生成响应"""
    audio_url: str
    message: str
    segments: list[dict]   # 每段信息 [{index, text, audio_url}]
    error_msg: str | None  # 熔断时报错原因


class RegenerateSegmentRequest(BaseModel):
    """单段重跑请求"""
    task_id: int
    segment_index: int     # 从 0 开始的段号
    text: str              # 该段的文本内容
    voice: str = "zf_xiaoqiu"
    rate: str = "+0%"


class RegenerateSegmentResponse(BaseModel):
    """单段重跑响应"""
    segment_index: int
    segment_url: str
    final_audio_url: str
    message: str
    error_msg: str | None
    segments: list[dict]  # 重跑后返回全量片段列表供前端更新


class MergeSegmentsRequest(BaseModel):
    """手动拼装请求（前端主动触发拼接）"""
    task_id: int


class MergeSegmentsResponse(BaseModel):
    """拼装结果响应"""
    audio_url: str
    segment_count: int
    message: str


class SegmentInfoResponse(BaseModel):
    """任务切片信息响应"""
    task_id: int
    segments: list[dict]   # [{index, text, audio_url}]
    final_audio_url: str | None


class ExtractRequest(BaseModel):
    """解析视频请求"""
    url: str


class CreateTaskFromTextRequest(BaseModel):
    """手动粘贴文案创建任务"""
    raw_text: str
    title: str = "手动录入"


class CreateTaskFromTextResponse(BaseModel):
    """手动录入任务响应"""
    task_id: int
    raw_transcript: str
    status: str
    current_step: int


class ImportRewrittenRequest(BaseModel):
    """直接导入已改好的文案（跳过 AI 改写）"""
    rewritten_text: str       # 改写后的完整文案正文
    video_title: str = ""     # 爆款标题
    raw_text: str = ""        # 原始文案（可选，留空则用 rewritten_text 代替）
    content_mode: str = "book"  # "book" | "general"


class ImportRewrittenResponse(BaseModel):
    """导入改写文案响应"""
    task_id: int
    rewritten: str
    video_title: str
    message: str


class ExtractResponse(BaseModel):
    """解析视频响应"""
    task_id: int
    title: str
    author: str
    likes: int
    comments: int
    shares: int
    duration: str
    cover_url: str
    video_url: str
    transcript: str
    is_mock: bool = False


# ============== 配图生成请求/响应 ==============

class GenerateImagesRequest(BaseModel):
    """批量生图请求（v4 单图直生）"""
    task_id: int
    style: str = "default"  # default | warm_book | clean_health | philosophy
    aspect_ratio: str = "9:16"  # "9:16" | "16:9"
    force: bool = False  # True=强制重跑，忽略已有图片缓存和视觉档案缓存


class GenerateImagesResponse(BaseModel):
    """批量生图响应（v4）"""
    task_id: int
    total_segments: int
    total_images: int
    success: int
    failed: int
    message: str


class RegenerateGridRequest(BaseModel):
    """单组九宫格重跑"""
    task_id: int
    grid_index: int
    style: str = "default"


class RegenerateSegmentImageRequest(BaseModel):
    """单段配图重跑（v4 单图直生）"""
    task_id: int
    segment_index: int
    style: str = "default"
    aspect_ratio: str = "9:16"  # "9:16" | "16:9"


class RegenerateSegmentImageResponse(BaseModel):
    """单段配图重跑响应"""
    segment_index: int
    image_url: str
    status: str
    message: str


class ImageInfo(BaseModel):
    """单张配图信息"""
    id: int
    task_id: int
    segment_index: int
    grid_index: int
    cell_position: int
    image_url: str | None
    image_exists: bool
    status: str
    error_msg: str | None


class ImageListResponse(BaseModel):
    """配图列表响应（v9：含进度摘要）"""
    task_id: int
    images: list[dict]
    total: int
    success_count: int
    failed_count: int
    image_summary: ImageSummary | None = None


# ============== 视频合成请求/响应 ==============

class ComposeVideoRequest(BaseModel):
    """合成成片请求（v7：三段式精简 + 标语模板化）"""
    task_id: int
    style: str = "card_16x9"    # card_16x9 | card_3x4
    aspect_ratio: str = "16:9"  # "16:9" | "3:4" | "9:16"
    watermark_text: str = ""
    bottom_disclaimer: str = "以上内容仅供参考，不构成医疗建议"
    font_size: int = 52
    author: str = ""
    title: str = ""
    disclaimer_template: str = ""
    modes: list[str] = ["card"]
    content_mode: str = "book"
    video_title: str = ""
    slogan: str = "- 品读传奇人生 -"
    subtitle_line: str = "图片由AI生成与网络下载\\n科普视频 无不良引导"
    # v8 对标卡片模式：双色标题两行（留空则由 LLM 自动拆分 video_title/书名）
    title_line1: str = ""
    title_line2: str = ""


class ComposeVideoResponse(BaseModel):
    """合成成片响应（v5：多风格裂变 + 声明模板参数化）"""
    task_id: int
    video_url: str
    duration_sec: float
    size_mb: float
    segment_count: int
    width: int
    height: int
    message: str
    srt_url: str | None = None
    ass_url: str | None = None
    jianying_draft_url: str | None = None
    jianying_published: bool = False
    jianying_draft_name: str | None = None
    black_placeholder_count: int = 0
    # v5: typewriter 裂变成品
    video_url_typewriter: str | None = None
    duration_sec_typewriter: float | None = None
    size_mb_typewriter: float | None = None
    # v5: card 图书卡片裂变成品
    video_url_card: str | None = None
    duration_sec_card: float | None = None
    size_mb_card: float | None = None
    # v8: bench 对标卡片裂变成品
    video_url_bench: str | None = None
    duration_sec_bench: float | None = None
    size_mb_bench: float | None = None
    # v9: 成品库归档路径
    archive_path: str | None = None


class VideoStyleInfo(BaseModel):
    """视频风格预设"""
    key: str
    name: str
    font_size: int
    zoom_speed: float
    max_zoom: float


class VideoStatusResponse(BaseModel):
    """视频文件状态"""
    task_id: int
    exists: bool
    video_url: str | None
    duration_sec: float
    size_mb: float
    srt_url: str | None = None
    ass_url: str | None = None
    jianying_draft_url: str | None = None


# ============== 任务管理接口 ==============

@app.post("/api/tasks", response_model=CreateTaskResponse)
async def create_task(request: CreateTaskRequest, db: Session = Depends(get_db)):
    """
    创建新任务
    - 在数据库中创建 Task 记录
    - 自动创建 backend/data/tasks/{task_id}/ 文件夹
    """
    # 创建任务记录
    task = Task(
        source_url=request.source_url,
        status="pending",
        current_step=1,
        douyin_meta={},
        created_at=datetime.utcnow()
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 创建任务专属文件夹
    task_folder = os.path.join(TASKS_DIR, str(task.id))
    os.makedirs(task_folder, exist_ok=True)

    return CreateTaskResponse(task_id=task.id)


@app.post("/api/tasks/from-text", response_model=CreateTaskFromTextResponse)
async def create_task_from_text(request: CreateTaskFromTextRequest, db: Session = Depends(get_db)):
    """
    纯文本创建任务：用户直接粘贴文案，绕过抖音解析。
    直接创建 Task，跳过 download/asr，直接灌入 Step 02（改写）。
    """
    task = Task(
        source_url="manual:text",
        status="text_ready",
        current_step=2,
        raw_transcript=request.raw_text,
        douyin_meta={"title": request.title, "author": "手动录入"},
        created_at=datetime.utcnow()
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 创建任务专属文件夹
    task_folder = os.path.join(TASKS_DIR, str(task.id))
    os.makedirs(task_folder, exist_ok=True)

    # 保存原始文本到文件
    raw_file = os.path.join(task_folder, "raw.txt")
    with open(raw_file, "w", encoding="utf-8") as f:
        f.write(request.raw_text)

    print(f"[from-text] 手动创建任务 {task.id}，文案长度 {len(request.raw_text)} 字")
    return CreateTaskFromTextResponse(
        task_id=task.id,
        raw_transcript=request.raw_text,
        status="text_ready",
        current_step=2,
    )


@app.post("/api/tasks/import-rewritten", response_model=ImportRewrittenResponse)
async def import_rewritten(request: ImportRewrittenRequest, db: Session = Depends(get_db)):
    """
    直接导入已改写好的文案——跳过清洗和 AI 改写步骤，直接进入配音/生图/合成。

    适用场景：用户在网页版 DeepSeek 对话窗口中手动改写后，粘贴回来继续生产。
    """
    raw_text = request.raw_text.strip() or request.rewritten_text
    rewritten_text = request.rewritten_text

    task = Task(
        source_url="manual:import",
        status="rewritten",
        current_step=2,
        raw_transcript=raw_text,
        rewritten_transcript=rewritten_text,
        video_title=request.video_title,
        content_mode=request.content_mode,
        douyin_meta={"title": request.video_title, "author": "手动导入"},
        created_at=datetime.utcnow()
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 创建任务文件夹 + 写入所有需要的文件
    task_folder = os.path.join(TASKS_DIR, str(task.id))
    os.makedirs(task_folder, exist_ok=True)

    for fname, content in [
        ("raw.txt", raw_text),
        ("cleaned.txt", rewritten_text),    # 清洗稿=改写稿，保持一致
        ("rewritten.txt", rewritten_text),
    ]:
        with open(os.path.join(task_folder, fname), "w", encoding="utf-8") as f:
            f.write(content)

    print(f"[import-rewritten] 导入任务 {task.id}: {len(rewritten_text)} 字, 标题: {request.video_title[:30] if request.video_title else '(无)'}")
    return ImportRewrittenResponse(
        task_id=task.id,
        rewritten=rewritten_text,
        video_title=request.video_title,
        message=f"已导入，可直接开始配音/生图/合成",
    )


@app.get("/api/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task_detail(task_id: int, db: Session = Depends(get_db)):
    """
    查询单个任务的详细信息，供前端轮询使用

    Returns:
        任务完整信息，包括各步骤产出字段
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    # 构建配图进度摘要
    from models import TaskImage
    img_records = db.query(TaskImage).filter(TaskImage.task_id == task_id).all()
    img_success = sum(1 for r in img_records if r.status == "success")
    img_failed = sum(1 for r in img_records if r.status == "failed")
    image_summary = ImageSummary(
        total=task.total_images or len(img_records) or 0,
        success=img_success,
        failed=img_failed,
        generating=task.images_generating,
        complete=task.images_complete,
    )

    return TaskDetailResponse(
        id=task.id,
        source_url=task.source_url,
        status=task.status,
        current_step=task.current_step,
        raw_transcript=task.raw_transcript,
        rewritten_transcript=task.rewritten_transcript,
        book_title=task.book_title,
        book_author=task.book_author,
        video_title=task.video_title,
        content_mode=task.content_mode,
        visual_context=task.visual_context,
        image_summary=image_summary,
        douyin_meta=task.douyin_meta or {},
        error_msg=task.error_msg,
        created_at=task.created_at,
    )


# ============== 下载器（多重避障策略） ==============

def _sync_download(url: str, save_path: str, timeout: tuple = (5, 30)) -> tuple[bool, str]:
    """
    同步下载器（requests 版，稳定对抗反爬）

    Args:
        url: 下载 URL
        save_path: 本地保存路径
        timeout: (connect_timeout, read_timeout)，默认 (5, 30)

    Returns:
        (是否成功, 错误信息或文件大小)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
    }

    try:
        response = requests.get(url, headers=headers, stream=True, timeout=timeout)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        last_progress = 0

        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = int(downloaded / total_size * 100)
                        if progress >= last_progress + 20:
                            print(f"[download] 下载进度... {progress}% ({downloaded // 1024 // 1024}MB / {total_size // 1024 // 1024}MB)")
                            last_progress = progress

        print(f"[download] 下载完成: {save_path} ({downloaded // 1024 // 1024}MB)")
        return True, f"{downloaded // 1024 // 1024}MB"

    except requests.Timeout:
        return False, "请求超时"
    except requests.HTTPError as e:
        return False, f"HTTP错误 {e.response.status_code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)}"


async def download_video_multi_channel(
    video_meta: dict,
    task_folder: str,
    db_session_factory,
    task_id: int,
) -> tuple[bool, str]:
    """
    多重避障下载策略，按优先级依次尝试：

    通道 A（中转流优先）：从 TikHub 元数据中提取经过代理中转的非抖音域名链接
    通道 B（极速纯音频）：提取纯音频链接，CDN 风控极弱，适合作为音频素材
    通道 C（原视频保底）：使用原始视频直链，15 秒超时强制切断

    Args:
        video_meta: TikHub API 返回的完整元数据字典
        task_folder: 任务文件夹路径
        db_session_factory: 数据库会话工厂（用于后台线程中创建会话）
        task_id: 任务 ID

    Returns:
        (是否成功, 结果描述)
    """
    def _update_status(status: str, step: int = None, raw_transcript: str = None):
        """后台线程中更新数据库状态的辅助函数"""
        db = db_session_factory()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = status
                if step is not None:
                    task.current_step = step
                if raw_transcript is not None:
                    task.raw_transcript = raw_transcript
                db.commit()
        finally:
            db.close()

    video_path = os.path.join(task_folder, "raw_video.mp4")
    audio_path = os.path.join(task_folder, "raw_audio.mp3")

    # 收集所有候选链接
    candidates: list[tuple[str, str, str]] = []  # (url, channel_label, description)

    # ========== 通道 A：中转流优先 ==========
    douyin_meta = video_meta.get("douyin_meta", {})
    # 尝试所有非抖音官方域名的链接（中转代理）
    for key in ["video_url", "play_url", "download_addr", "h265_url", "h264_url"]:
        val = video_meta.get(key, "") or douyin_meta.get(key, "")
        if val and isinstance(val, str) and "douyin.com" not in val and "byted" not in val and val.startswith("http"):
            candidates.append((val, "A", f"中转流-{key}"))

    # 尝试 video_meta 顶层的中转 URL
    for k, v in video_meta.items():
        if k in ("proxy_url", "relay_url", "transcoded_url", "hd_url", "sd_url"):
            if v and isinstance(v, str) and v.startswith("http"):
                candidates.append((v, "A", f"中转流-{k}"))

    # ========== 通道 B：纯音频 ==========
    audio_url = video_meta.get("audio_url", "") or douyin_meta.get("music", {}).get("play_url", {}).get("url_list", [None])[0]
    if audio_url and isinstance(audio_url, str) and audio_url.startswith("http"):
        candidates.append((audio_url, "B", "纯音频-music.play_url"))

    # ========== 通道 C：原始视频直链 ==========
    original_url = video_meta.get("video_url", "") or douyin_meta.get("video_url", "")
    if original_url and isinstance(original_url, str) and original_url.startswith("http"):
        candidates.append((original_url, "C", "原始视频直链"))

    # 去重保持顺序
    seen = set()
    unique_candidates = []
    for url, label, desc in candidates:
        if url not in seen:
            seen.add(url)
            unique_candidates.append((url, label, desc))

    print(f"[download][{task_id}] 共收集到 {len(unique_candidates)} 个候选下载链接")
    for i, (u, label, desc) in enumerate(unique_candidates):
        print(f"[download][{task_id}] 候选 {i+1} [{label}]: {desc} -> {u[:80]}...")

    # 按优先级逐个尝试
    success_channel = None  # 记录哪个通道下载成功

    for attempt_idx, (url, channel, desc) in enumerate(unique_candidates):
        # 通道 C 使用更短的 15 秒超时
        timeout = (5, 15) if channel == "C" else (5, 30)
        print(f"[download][{task_id}] 尝试通道 {channel} [{desc}]，超时 {timeout}，URL: {url[:80]}...")

        # 通道 B 直接下载为 .mp3；其他通道下载为 .mp4
        save_path = audio_path if channel == "B" else video_path

        loop = __import__("asyncio").get_running_loop()
        success, result = await loop.run_in_executor(
            None, _sync_download, url, save_path, timeout
        )

        if success:
            downloaded_size = os.path.getsize(save_path) if os.path.exists(save_path) else 0
            success_channel = channel
            print(f"[download][{task_id}] 通道 {channel} 下载成功! 文件大小: {downloaded_size // 1024 // 1024}MB")
            _update_status("transcribing", step=3)
            break
        else:
            print(f"[download][{task_id}] 通道 {channel} 下载失败: {result}，尝试下一个通道...")

    # 如果所有通道都失败，标记为 mock
    if success_channel is None:
        print(f"[download][{task_id}] 所有下载通道均失败，使用 fallback 逐字稿")
        _update_status(
            "extracted",
            step=1,
            raw_transcript=f"【下载全部失败】视频标题：{video_meta.get('title', '')}，作者：{video_meta.get('author', '')}"
        )
        return False, "all_channels_failed"

    # ===== 音频准备（按通道区分处理）=====
    audio_extracted = False

    if success_channel == "B":
        # 通道 B：下载的本身就是 MP3，直接作为音频使用，跳过 MoviePy 脱壳
        print(f"[download][{task_id}] 纯音频文件下载成功，跳过 MoviePy 脱壳，直接进入 ASR。")
        # rename save_path (which was audio_path) to audio_path if they differ
        # save_path is already audio_path, just verify it exists
        if os.path.exists(audio_path):
            audio_extracted = True
    else:
        # 通道 A / C：下载的是视频文件，需要用 MoviePy 提取音频
        if os.path.exists(video_path):
            try:
                print(f"[download][{task_id}] 正在从视频中提取音频...")
                video_clip = VideoFileClip(video_path)
                try:
                    if video_clip.audio is None:
                        raise Exception("该视频轨道无音频流，无法提取")
                    video_clip.audio.write_audiofile(audio_path, logger=None)
                    audio_extracted = True
                    print(f"[download][{task_id}] 音频提取完成: {audio_path}")
                finally:
                    video_clip.close()
            except Exception as e:
                print(f"[download][{task_id}] 音频提取失败: {e}")
                audio_extracted = False

    # ===== ASR 识别 =====
    if audio_extracted and os.path.exists(audio_path):
        try:
            print(f"[download][{task_id}] 开始 ASR 识别...")
            _update_status("transcribing", step=3)
            transcript = await transcribe_media(audio_path)
            print(f"[download][{task_id}] ASR 识别成功，文字长度: {len(transcript)}")
            _update_status("extracted", step=1, raw_transcript=transcript)
        except Exception as e:
            print(f"[download][{task_id}] ASR 识别失败: {e}")
            _update_status(
                "extracted",
                step=1,
                raw_transcript=f"【ASR识别失败，仅获取到元数据】视频标题：{video_meta.get('title', '')}，作者：{video_meta.get('author', '')}"
            )
    else:
        _update_status(
            "extracted",
            step=1,
            raw_transcript=f"【音频提取失败，仅获取到元数据】视频标题：{video_meta.get('title', '')}，作者：{video_meta.get('author', '')}"
        )

    # ===== 删除原始视频文件节省磁盘空间（仅通道 A/C 下载了视频文件）=====
    if success_channel != "B":
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
                print(f"[download][{task_id}] 已删除原始视频文件: {video_path}")
        except Exception as e:
            print(f"[download][{task_id}] 删除原始视频失败: {e}")

    return True, "pipeline_completed"


# ============== 后台流水线 ==============

async def run_full_pipeline_in_background(
    task_id: int,
    source_url: str,
    video_meta: dict,
):
    """
    后台运行的完整流水线：

    1. 多重避障下载视频
    2. 从视频提取音频
    3. ASR 语音识别
    4. 清理视频文件
    5. 实时更新数据库状态

    在独立数据库会话中运行，不阻塞主请求。
    """
    print(f"[pipeline][{task_id}] 后台流水线启动，source_url: {source_url}")

    task_folder = os.path.join(TASKS_DIR, str(task_id))
    os.makedirs(task_folder, exist_ok=True)

    try:
        await download_video_multi_channel(
            video_meta=video_meta,
            task_folder=task_folder,
            db_session_factory=SessionLocal,
            task_id=task_id,
        )
    except Exception as e:
        print(f"[pipeline][{task_id}] 后台流水线异常! 报错类型: {type(e).__name__}, 详情: {str(e)}")
        # 尝试更新状态为失败
        try:
            db = SessionLocal()
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = "failed"
                db.commit()
            db.close()
        except Exception:
            pass

    print(f"[pipeline][{task_id}] 后台流水线结束")


# ============== 视频解析接口（后台异步模式） ==============

@app.post("/api/extract", response_model=ExtractResponse)
async def extract_video(request: ExtractRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    解析抖音视频 URL，获取元数据并立刻返回（后台异步执行下载+ASR）

    流程（主请求线程）：
        1. 调用 TikHub API 获取基本元数据（title/author/cover_url 等）
        2. 在数据库中创建 Task 记录，状态设为 "downloading"
        3. 立刻返回 200 OK 给前端（不等待下载/ASR）

    流程（后台任务）：
        4. 多重避障下载视频
        5. 从视频提取音频
        6. ASR 语音识别
        7. 更新数据库状态和 raw_transcript 字段
    """
    # 1. 调用 TikHub API 获取基本元数据
    video_meta = await fetch_douyin_video_info(request.url)
    video_url = video_meta.get("video_url", "")

    # 2. 在数据库中创建新任务，状态设为 "downloading"
    task = Task(
        source_url=request.url,
        status="downloading",
        current_step=2,
        douyin_meta={
            "title": video_meta.get("title", ""),
            "author": video_meta.get("author", ""),
            "duration": video_meta.get("duration", ""),
            "likes": video_meta.get("likes", 0),
            "comments": video_meta.get("comments", 0),
            "shares": video_meta.get("shares", 0),
            "cover_url": video_meta.get("cover_url", ""),
            "video_url": video_url,
        },
        created_at=datetime.utcnow()
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 3. 创建任务专属文件夹
    task_folder = os.path.join(TASKS_DIR, str(task.id))
    os.makedirs(task_folder, exist_ok=True)

    # 4. 将完整流水线注册为后台任务，立刻返回
    background_tasks.add_task(
        run_full_pipeline_in_background,
        task_id=task.id,
        source_url=request.url,
        video_meta={
            **video_meta,
            "douyin_meta": task.douyin_meta,  # 携带原始 douyin_meta 字典
        },
    )

    print(f"[extract] 任务 {task.id} 已创建，后台流水线已启动，立刻返回前端")

    # 5. 立刻返回响应，不等待后台任务
    return ExtractResponse(
        task_id=task.id,
        title=video_meta.get("title", ""),
        author=video_meta.get("author", ""),
        likes=video_meta.get("likes", 0),
        comments=video_meta.get("comments", 0),
        shares=video_meta.get("shares", 0),
        duration=video_meta.get("duration", ""),
        cover_url=video_meta.get("cover_url", ""),
        video_url=video_url,
        transcript="",  # 前端需通过轮询或任务详情接口获取
        is_mock=video_meta.get("is_mock", False),
    )


# ============== 逐字稿清洗接口 ==============

@app.post("/api/clean-text", response_model=CleanTextResponse)
async def clean_text(request: CleanTextRequest, db: Session = Depends(get_db)):
    """
    清洗原始逐字稿，修复 ASR 识别错误。

    - 调用 DeepSeek API 进行清洗
    - 将原始文本和清洗结果保存到文件
    - 更新数据库中 Task 的状态
    """
    from services.llm_service import clean_asr_text

    raw_text = request.raw_text
    task_id = request.task_id

    # 调用 LLM 服务清洗文本
    cleaned_text = await clean_asr_text(transcript=raw_text)

    # 获取任务文件夹路径
    task_folder = os.path.join(TASKS_DIR, str(task_id))
    os.makedirs(task_folder, exist_ok=True)

    # 保存原始文本
    raw_file = os.path.join(task_folder, "raw.txt")
    with open(raw_file, "w", encoding="utf-8") as f:
        f.write(raw_text)

    # 保存清洗后的文本
    cleaned_file = os.path.join(task_folder, "cleaned.txt")
    with open(cleaned_file, "w", encoding="utf-8") as f:
        f.write(cleaned_text)

    # 更新数据库中的 Task 状态
    task = db.query(Task).filter(Task.id == task_id).first()
    if task:
        task.status = "cleaned"
        task.current_step = 2
        db.commit()

    return CleanTextResponse(cleaned=cleaned_text)


# ============== 脚本改写接口 ==============

@app.post("/api/rewrite", response_model=RewriteResponse)
async def rewrite(request: RewriteRequest, db: Session = Depends(get_db)):
    """
    v5 改写：深度改写 + 生成爆款标题，输出 JSON 结构化数据。

    结果保存到 task.rewritten_transcript / task.video_title 和本地文件
    """
    from services.llm_service import rewrite_script as do_rewrite

    task_id = request.task_id
    mode = request.mode

    # 获取任务的清洗后正文
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return {"rewritten": f"任务 {task_id} 不存在", "video_title": ""}

    # 尝试从 cleaned.txt 读取清洗后的正文
    task_folder = os.path.join(TASKS_DIR, str(task_id))
    cleaned_file = os.path.join(task_folder, "cleaned.txt")

    if os.path.exists(cleaned_file):
        with open(cleaned_file, "r", encoding="utf-8") as f:
            cleaned_text = f.read()
    else:
        cleaned_text = ""

    # 调用改写函数（v5 返回 dict）
    try:
        result = await do_rewrite(task_id, cleaned_text, db, mode)
        rewritten = result["rewritten_transcript"]
        video_title = result.get("video_title", "")
    except Exception as e:
        print(f"[rewrite] 改写失败: {e}")
        return {"rewritten": f"改写失败: {str(e)}", "video_title": ""}

    # 保存到数据库（do_rewrite 内部已写入 task.rewritten_transcript 和 task.video_title）
    # 此处补充确保 commit
    task.rewritten_transcript = rewritten
    task.video_title = video_title
    db.commit()

    # 保存到本地文件
    rewritten_file = os.path.join(task_folder, "rewritten.txt")
    with open(rewritten_file, "w", encoding="utf-8") as f:
        f.write(rewritten)

    return {"rewritten": rewritten, "video_title": video_title}


# ============== 书籍信息反推接口 =============

@app.post("/api/book-info", response_model=BookInfoResponse)
async def book_info(request: BookInfoRequest, db: Session = Depends(get_db)):
    """
    从视频标题、描述和文案中反推被讲解/带货的书籍信息

    调用 DeepSeek API，temperature=0.05，输出 JSON 格式
    """
    from services.llm_service import extract_book_info as do_extract

    task_id = request.task_id

    # 获取任务
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return BookInfoResponse(book_title="", book_author="", confidence=0.0, evidence=f"任务 {task_id} 不存在")

    try:
        result = await do_extract(task_id, db)

        # 更新数据库
        task.book_title = result.get("book_title", "")
        task.book_author = result.get("book_author", "")
        db.commit()

        return BookInfoResponse(**result)
    except Exception as e:
        print(f"[book-info] 书籍信息反推失败: {e}")
        return BookInfoResponse(book_title="", book_author="", confidence=0.0, evidence=f"错误: {str(e)}")


# ============== 初始化片段表接口 =============

@app.post("/api/tts/init-segments", response_model=SegmentInfoResponse)
async def init_segments(request: GenerateAudioRequest, db: Session = Depends(get_db)):
    """
    为任务初始化/重置片段表（v2：LLM 智能语义切段，每段 24~28 秒口播）。

    - 删除该任务旧的 TaskSegment 记录和物理音频文件
    - 调用 DeepSeek 做语义自然切段
    - 回退：LLM 失败时降级为标点切段
    """
    task_id = request.task_id

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    text = task.rewritten_transcript or task.raw_transcript or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="无可用文案生成分段")

    # 删除旧的 TaskSegment 记录
    db.query(TaskSegment).filter(TaskSegment.task_id == task_id).delete()
    db.commit()

    # 删除旧的物理音频文件
    task_folder = os.path.join(TASKS_DIR, str(task_id))
    segments_folder = os.path.join(task_folder, "segments")
    if os.path.exists(segments_folder):
        import shutil
        shutil.rmtree(segments_folder)
    os.makedirs(segments_folder, exist_ok=True)

    # ---- v3: 与生图对齐的句子级切段（max_chars=80, min_chars=30）----
    # 关键改变：不再使用 LLM 大段语义切分，改用与 image_service 完全相同的
    # split_into_short_sentences()，确保 TTS 段数 = 配图数 = 视频分镜数。
    from services.llm_service import split_into_short_sentences

    try:
        chunks = split_into_short_sentences(text, max_chars=80, min_chars=30)
        print(f"[init-segments] v3 句子级切段: {len(chunks)} 段（与生图参数一致）")
    except Exception as e:
        print(f"[init-segments] 句子切段失败: {e}，降级为标点切段")
        # 回退：按标点切段
        import re as _re
        def _fallback_split(text, max_chars=90):
            paras = text.split('\n')
            chunks = []
            for para in paras:
                para = para.strip()
                if not para:
                    continue
                if len(para) <= max_chars:
                    chunks.append(para)
                else:
                    sp = _re.compile(r'([^。！？；：，、…—\n]+[。！？；：，、…—])')
                    sents = sp.findall(para)
                    cur = ""
                    for s in sents:
                        if len(cur) + len(s) <= max_chars:
                            cur += s
                        else:
                            if cur:
                                chunks.append(cur)
                            if len(s) > max_chars:
                                _start = 0
                                while _start < len(s):
                                    _end = min(_start + max_chars, len(s))
                                    if _end < len(s):
                                        _best = _end
                                        for _off in range(max_chars // 4, -(max_chars // 4), -1):
                                            _chk = _end - _off
                                            if 0 < _chk < len(s) and s[_chk] in '，,.、…— ；;：:。！？':
                                                _best = _chk
                                                break
                                        _end = _best
                                    chunks.append(s[_start:_end].strip())
                                    _start = _end
                                cur = ""
                            else:
                                cur = s
                    if cur:
                        chunks.append(cur)
            return chunks
        chunks = _fallback_split(text)

    segments = []
    for i, chunk_text in enumerate(chunks):
        seg = TaskSegment(
            task_id=task_id,
            segment_index=i,
            text=chunk_text,
            audio_path=None,
            status="pending",
            error_msg=None,
        )
        db.add(seg)
        segments.append(seg)

    db.commit()

    print(f"[init-segments] 任务 {task_id} 初始化 {len(segments)} 个片段（v2 LLM 语义切段）")

    return SegmentInfoResponse(
        task_id=task_id,
        segments=[{
            "index": s.segment_index,
            "text": s.text,
            "audio_url": f"/audio/{task_id}/segments/seg_{s.segment_index:03d}.mp3",
            "audio_exists": False,
            "status": s.status,
        } for s in segments],
        final_audio_url=None,
    )


# ============== TTS 音频生成接口（增量模式）==============

@app.post("/api/generate-audio", response_model=GenerateAudioResponse)
async def generate_audio_endpoint(request: GenerateAudioRequest, db: Session = Depends(get_db)):
    """
    增量式分段 TTS 配音生成。

    - 自动初始化片段表（如不存在）
    - 跳过 status=success 且物理文件存在的片段
    - 只对 pending/failed 片段发起 TTS 请求
    - 某段 3 次重试失败 → 标记 failed → 继续处理后续片段
    - 全部完成后 FFmpeg 合并所有 success 片段
    """
    import re
    from services.tts_service import generate_audio as do_generate_audio
    from shutil import rmtree as shutil_rmtree

    task_id = request.task_id
    voice = request.voice
    rate = request.rate

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return GenerateAudioResponse(audio_url="", message=f"任务 {task_id} 不存在", segments=[], error_msg=None)

    task_folder = os.path.join(TASKS_DIR, str(task_id))
    segments_folder = os.path.join(task_folder, "segments")
    os.makedirs(segments_folder, exist_ok=True)

    # ---- 检查/初始化片段表 ----
    existing = db.query(TaskSegment).filter(TaskSegment.task_id == task_id).all()
    if not existing:
        # 自动触发初始化
        init_req = GenerateAudioRequest(task_id=task_id, voice=voice, rate=rate)
        init_result = await init_segments(init_req, db)
        segments = db.query(TaskSegment).filter(TaskSegment.task_id == task_id).all()
    else:
        segments = existing

    print(f"[generate-audio] 任务 {task_id}，共 {len(segments)} 片段，voice={voice} rate={rate}")

    failed_count = 0
    success_count = 0

    for seg in segments:
        seg_path = os.path.join(segments_folder, f"seg_{seg.segment_index:03d}.mp3")

        # ---- 跳过已成功的片段 ----
        if seg.status == "success" and os.path.exists(seg_path):
            print(f"[generate-audio] 片段 {seg.segment_index+1} 已存在且成功，跳过")
            success_count += 1
            continue

        # ---- 需要生成或重跑的片段 ----
        print(f"[generate-audio] 处理片段 {seg.segment_index+1}/{len(segments)}，当前状态={seg.status}，文本长度={len(seg.text)} 字")
        seg.status = "pending"
        seg.error_msg = None
        db.commit()

        try:
            await do_generate_audio(seg.text, voice=voice, rate=rate, output_path=seg_path)
            # 生成成功
            seg.status = "success"
            seg.audio_path = seg_path
            seg.error_msg = None
            db.commit()
            success_count += 1
            print(f"[generate-audio] 片段 {seg.segment_index+1} 生成成功")

        except Exception as e:
            # 3 次重试耗尽，标记失败，继续处理后续片段
            seg.status = "failed"
            seg.error_msg = f"{type(e).__name__}: {str(e)}"
            db.commit()
            failed_count += 1
            print(f"[generate-audio] 片段 {seg.segment_index+1} 失败: {e}，继续下一片段")

        if seg.segment_index < len(segments) - 1:
            await asyncio.sleep(0.3)

    # ---- FFmpeg 合并所有成功片段 ----
    final_path = os.path.join(task_folder, "final_tts.mp3")
    success_segs = db.query(TaskSegment).filter(
        TaskSegment.task_id == task_id,
        TaskSegment.status == "success"
    ).order_by(TaskSegment.segment_index).all()

    if success_segs:
        _merge_segments([os.path.join(segments_folder, f"seg_{s.segment_index:03d}.mp3") for s in success_segs], final_path)
        task.status = "audio_ready"
        task.error_msg = None
    else:
        task.status = "failed"
        task.error_msg = f"所有片段均失败（{failed_count} 个）"
        if os.path.exists(final_path):
            os.remove(final_path)

    task.current_step = 3
    db.commit()

    # ---- 构建返回 ----
    all_segs = db.query(TaskSegment).filter(TaskSegment.task_id == task_id).order_by(TaskSegment.segment_index).all()
    seg_info = [{
        "index": s.segment_index,
        "text": s.text,
        "audio_url": f"/audio/{task_id}/segments/seg_{s.segment_index:03d}.mp3",
        "audio_exists": s.status == "success" and os.path.exists(s.audio_path or ""),
        "status": s.status,
        "error_msg": s.error_msg,
    } for s in all_segs]

    final_url = f"/audio/{task_id}/final_tts.mp3" if success_segs and os.path.exists(final_path) else ""
    msg = f"完成：{success_count} 成功，{failed_count} 失败"
    if failed_count > 0:
        msg += f"，请重试失败的片段"
    print(f"[generate-audio] {msg}")

    return GenerateAudioResponse(
        audio_url=final_url,
        message=msg,
        segments=seg_info,
        error_msg=None if failed_count == 0 else f"{failed_count} 个片段失败",
    )


def _create_silent_audio(path: str, duration_ms: int = 1000):
    """生成静音占位音频（某段生成失败时保底）"""
    import subprocess
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
        "-t", str(duration_ms / 1000),
        "-q:a", "9", path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
       encoding="utf-8", errors="replace")


def _merge_segments(file_list: list[str], output_path: str):
    """
    将指定文件列表按顺序拼接为单一音频文件。
    file_list: 已经按 segment_index 排序的文件路径列表
    """
    import subprocess
    if not file_list:
        print("[merge] 文件列表为空，跳过拼接")
        return

    list_file = os.path.join(os.path.dirname(file_list[0]), "_merge_list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for fp in file_list:
            f.write(f"file '{os.path.abspath(fp)}'\n")

    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy", output_path
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
       encoding="utf-8", errors="replace")

    try:
        os.remove(list_file)
    except Exception:
        pass

    if result.returncode != 0:
        stderr = (result.stderr or "")[:200]
        print(f"[merge] FFmpeg 拼接失败: {stderr}")
    else:
        print(f"[merge] 拼接完成: {output_path}（{len(file_list)} 个片段）")


# ============== 切片信息查询 ==============

@app.get("/api/tts/segments/{task_id}", response_model=SegmentInfoResponse)
async def get_segments(task_id: int, db: Session = Depends(get_db)):
    """
    从 TaskSegment 表查询切片列表，返回完整状态。
    用于前端渲染分段控制台（GET 时直接查询数据库，跳过 HTTP 调用）。
    """
    task_folder = os.path.join(TASKS_DIR, str(task_id))
    final_path = os.path.join(task_folder, "final_tts.mp3")

    db_segs = db.query(TaskSegment).filter(
        TaskSegment.task_id == task_id
    ).order_by(TaskSegment.segment_index).all()

    if not db_segs:
        return SegmentInfoResponse(
            task_id=task_id,
            segments=[],
            final_audio_url=f"/audio/{task_id}/final_tts.mp3" if os.path.exists(final_path) else None,
        )

    segments = [{
        "index": s.segment_index,
        "text": s.text,
        "audio_url": f"/audio/{task_id}/segments/seg_{s.segment_index:03d}.mp3",
        "audio_exists": s.status == "success" and os.path.exists(s.audio_path or ""),
        "status": s.status,
        "error_msg": s.error_msg,
    } for s in db_segs]

    return SegmentInfoResponse(
        task_id=task_id,
        segments=segments,
        final_audio_url=f"/audio/{task_id}/final_tts.mp3" if os.path.exists(final_path) else None,
    )


# ============== 单段重跑接口 ==============

@app.post("/api/tts/regenerate-segment", response_model=RegenerateSegmentResponse)
async def regenerate_segment(request: RegenerateSegmentRequest, db: Session = Depends(get_db)):
    """
    单独重跑指定段落的 TTS 配音。

    - 更新 DB 中的片段状态（成功/失败）
    - 只重新生成该片段音频文件
    - FFmpeg 只合并 status=success 的片段
    - 返回全量片段列表供前端更新
    """
    from services.tts_service import generate_audio as do_generate_audio

    task_id = request.task_id
    idx = request.segment_index
    text = request.text.strip()
    voice = request.voice
    rate = request.rate

    task_folder = os.path.join(TASKS_DIR, str(task_id))
    segments_folder = os.path.join(task_folder, "segments")
    os.makedirs(segments_folder, exist_ok=True)

    # 更新该片段的文本
    seg_record = db.query(TaskSegment).filter(
        TaskSegment.task_id == task_id,
        TaskSegment.segment_index == idx
    ).first()
    if seg_record:
        seg_record.text = text
        seg_record.status = "pending"
        seg_record.error_msg = None
        db.commit()

    seg_path = os.path.join(segments_folder, f"seg_{idx:03d}.mp3")
    print(f"[regen-seg] 任务 {task_id} 片段 {idx}，voice={voice} rate={rate}，文本长度={len(text)}")

    try:
        await do_generate_audio(text, voice=voice, rate=rate, output_path=seg_path)
        if seg_record:
            seg_record.status = "success"
            seg_record.audio_path = seg_path
            seg_record.error_msg = None
            db.commit()
        print(f"[regen-seg] 片段 {idx} 生成成功")
    except Exception as e:
        if seg_record:
            seg_record.status = "failed"
            seg_record.error_msg = f"{type(e).__name__}: {str(e)}"
            db.commit()
        print(f"[regen-seg] 片段 {idx} 生成失败: {e}")

    # 只合并 status=success 的片段
    success_segs = db.query(TaskSegment).filter(
        TaskSegment.task_id == task_id,
        TaskSegment.status == "success"
    ).order_by(TaskSegment.segment_index).all()

    final_path = os.path.join(task_folder, "final_tts.mp3")
    if success_segs:
        _merge_segments([os.path.join(segments_folder, f"seg_{s.segment_index:03d}.mp3") for s in success_segs], final_path)
    elif os.path.exists(final_path):
        os.remove(final_path)

    # 返回全量片段列表
    all_segs = db.query(TaskSegment).filter(
        TaskSegment.task_id == task_id
    ).order_by(TaskSegment.segment_index).all()
    seg_info = [{
        "index": s.segment_index,
        "text": s.text,
        "audio_url": f"/audio/{task_id}/segments/seg_{s.segment_index:03d}.mp3",
        "audio_exists": s.status == "success" and os.path.exists(s.audio_path or ""),
        "status": s.status,
        "error_msg": s.error_msg,
    } for s in all_segs]

    return RegenerateSegmentResponse(
        segment_index=idx,
        segment_url=f"/audio/{task_id}/segments/seg_{idx:03d}.mp3",
        final_audio_url=f"/audio/{task_id}/final_tts.mp3" if success_segs else "",
        message="片段更新并重新拼装完成",
        error_msg=None,
        segments=seg_info,
    )


# ============== 手动拼装接口 ==============

@app.post("/api/tts/merge", response_model=MergeSegmentsResponse)
async def merge_segments_endpoint(request: MergeSegmentsRequest):
    """
    手动触发拼接：只合并 status=success 的片段。
    """
    task_id = request.task_id
    task_folder = os.path.join(TASKS_DIR, str(task_id))
    segments_folder = os.path.join(task_folder, "segments")
    final_path = os.path.join(task_folder, "final_tts.mp3")

    # 只合并成功的片段
    import glob
    success_files = sorted(glob.glob(os.path.join(segments_folder, "seg_*.mp3")))

    if not success_files:
        return MergeSegmentsResponse(audio_url="", segment_count=0, message="没有已完成的片段可拼装")

    _merge_segments(success_files, final_path)

    return MergeSegmentsResponse(
        audio_url=f"/audio/{task_id}/final_tts.mp3",
        segment_count=len(success_files),
        message=f"{len(success_files)} 个片段拼接完成",
    )
# ============== Step 04：配图批量生成 ==============

@app.post("/api/images/generate", response_model=GenerateImagesResponse)
async def generate_images(request: GenerateImagesRequest, db: Session = Depends(get_db)):
    """
    v4 一键生成全部配图：逐句单图直生，高精无裁切。
    - 读取 rewritten.txt → 按短句切分（~63 句/10min）
    - 每句独立 Fal.ai 单图请求 + 风格后缀 + 安全补丁
    - 不再使用九宫格 → 不再裁切 → 无重影/崩坏
    """
    from services.image_service import generate_all_images

    task_id = request.task_id
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    rewritten = task.rewritten_transcript or ""
    if not rewritten.strip():
        task_dir = os.path.join(TASKS_DIR, str(task_id))
        rewritten_file = os.path.join(task_dir, "rewritten.txt")
        if os.path.exists(rewritten_file):
            with open(rewritten_file, "r", encoding="utf-8") as f:
                rewritten = f.read()
    if not rewritten.strip():
        return GenerateImagesResponse(
            task_id=task_id, total_segments=0, total_images=0,
            success=0, failed=0,
            message="没有改写稿，请先完成文本改写（Step 02）",
        )

    try:
        result = await generate_all_images(
            task_id=task_id,
            db=db,
            style=request.style,
            book_title=task.book_title or "",
            book_author=task.book_author or "",
            aspect_ratio=request.aspect_ratio,
            force=request.force,
        )
    except Exception as e:
        # 生图过程异常崩了 → 复位 generating 标记，避免任务永久卡死
        task.images_generating = False
        db.commit()
        return GenerateImagesResponse(
            task_id=task_id, total_segments=0, total_images=0,
            success=0, failed=0, message=f"生图异常: {type(e).__name__}: {str(e)}",
        )

    if "error" in result:
        # 如果 generate_all_images 返回了错误（含"正在生成中"），确保 generating 已复位
        return GenerateImagesResponse(
            task_id=task_id, total_segments=0, total_images=0,
            success=0, failed=0, message=result["error"],
        )

    return GenerateImagesResponse(
        task_id=task_id,
        total_segments=result.get("total_segments", 0),
        total_images=result.get("total_images", 0),
        success=result.get("success", 0),
        failed=result.get("failed", 0),
        message=f"{result.get('success', 0)} 张配图生成完成，{result.get('failed', 0)} 张失败",
    )


@app.post("/api/images/generate-grid", response_model=dict)
async def regenerate_grid(request: RegenerateGridRequest, db: Session = Depends(get_db)):
    """单组九宫格重跑"""
    from services.image_service import regenerate_grid as do_regen

    task_id = request.task_id
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    result = await do_regen(
        task_id=task_id,
        grid_index=request.grid_index,
        db=db,
        style=request.style,
        book_title=task.book_title or "",
        book_author=task.book_author or "",
    )
    return result


@app.post("/api/images/regenerate-segment", response_model=RegenerateSegmentImageResponse)
async def regenerate_segment_image(request: RegenerateSegmentImageRequest, db: Session = Depends(get_db)):
    """
    单独重跑某一段的配图（单张独立生图，不走九宫格）。
    - 更快（只生一张 2K 图）
    - 更省（单张 vs 九宫格 9 张）
    - 不对该段所在九宫格的其他格产生影响
    """
    from services.image_service import regenerate_single_image

    task_id = request.task_id
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    result = await regenerate_single_image(
        task_id=task_id,
        segment_index=request.segment_index,
        db=db,
        style=request.style,
        book_title=task.book_title or "",
        book_author=task.book_author or "",
        aspect_ratio=request.aspect_ratio,
    )

    if "error" in result:
        return RegenerateSegmentImageResponse(
            segment_index=request.segment_index,
            image_url="",
            status="failed",
            message=result["error"],
        )

    return RegenerateSegmentImageResponse(
        segment_index=result["segment_index"],
        image_url=result["image_url"],
        status=result["status"],
        message=result["message"],
    )


@app.get("/api/images/{task_id}", response_model=ImageListResponse)
async def get_images(task_id: int, db: Session = Depends(get_db)):
    """查询任务的所有配图（v9：含进度摘要，前端用于状态条和按钮锁定）"""
    from services.image_service import get_images_for_task
    from models import Task

    records = get_images_for_task(task_id, db)
    success_count = sum(1 for r in records if r["status"] == "success")
    failed_count = sum(1 for r in records if r["status"] == "failed")

    task = db.query(Task).filter(Task.id == task_id).first()
    image_summary = ImageSummary(
        total=task.total_images if task else len(records),
        success=success_count,
        failed=failed_count,
        generating=task.images_generating if task else False,
        complete=task.images_complete if task else False,
    )

    return ImageListResponse(
        task_id=task_id,
        images=records,
        total=len(records),
        success_count=success_count,
        failed_count=failed_count,
        image_summary=image_summary,
    )


# ============== 本地标题断行（避免 AI 擅自改写）==============

def _count_cjk_local(text: str) -> int:
    import re
    return len(re.findall(r'[一-鿿]', text))


def _split_title_local(title: str, max_chars: int = 16) -> list[str]:
    """将标题自然断行为两行，不动原文一个字。

    策略（优先级递减）：
    1. 全文找第一个逗号/分号 → 天然语义断点，直接一刀
    2. 无逗号 → 中点 ±1/4 范围找标点
    3. 无标点 → 不拆分
    """
    cjk = _count_cjk_local(title)
    if cjk <= max_chars:
        return [title]

    # 策略1：优先在逗号/分号处断句（最自然的语义边界）
    for bp in ("，", "；", "。", "：", "！", "？"):
        pos = title.find(bp)
        if pos > 2 and pos < len(title) - 4:
            return [title[:pos + 1], title[pos + 1:].lstrip()]

    # 策略2：中点附近找标点
    mid = len(title) // 2
    best = mid
    for bp in " 　,、-—":
        lo = max(0, mid - len(title) // 4)
        hi = min(len(title), mid + len(title) // 4)
        pos = title.find(bp, lo, hi)
        if pos != -1:
            best = pos + 1
            break
    if best == mid or best >= len(title) or best <= 2:
        return [title]
    return [title[:best], title[best:].lstrip()]


# ============== Step 05：视频合成 ==============

@app.post("/api/video/compose", response_model=ComposeVideoResponse)
async def compose_video(request: ComposeVideoRequest, db: Session = Depends(get_db)):
    """
    一键合成最终竖版成片（v5）。
    - 抗抖动 Ken Burns 缩放动效（2x 预放大 + bicubic）
    - 字随音动词级字幕
    - 参数化底部声明模板
    - 叠音轨 + 导出剪映草稿
    - 支持多风格并发裂变（cinematic / typewriter / card）
    """
    from services.video_service import (
        compose_final_video, compose_final_video_typewriter,
        compose_final_video_card, compose_final_video_card_v6,
        compose_final_video_card_bench, VIDEO_STYLES,
        split_into_word_groups, get_audio_duration,
    )
    from services.llm_service import split_into_short_sentences
    import os as _os

    task_id = request.task_id
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    # v5: 赛道模式持久化
    task.content_mode = request.content_mode
    if request.video_title:
        task.video_title = request.video_title
    task.current_step = 5
    db.commit()

    style_cfg = VIDEO_STYLES.get(request.style, VIDEO_STYLES["default"])

    # v5: 声明模板参数化
    if request.author or request.title:
        try:
            rendered_disclaimer = request.disclaimer_template.format(
                author=request.author, title=request.title
            )
        except (KeyError, ValueError):
            rendered_disclaimer = request.bottom_disclaimer
    else:
        rendered_disclaimer = request.bottom_disclaimer

    # === 提取共享数据（所有模式共用） ===
    tasks_dir = TASKS_DIR
    task_dir = _os.path.join(_os.path.abspath(tasks_dir), str(task_id))
    final_audio = _os.path.join(task_dir, "final_tts.mp3")

    rewritten = task.rewritten_transcript or ""
    rewritten_file = _os.path.join(task_dir, "rewritten.txt")
    if not rewritten and _os.path.exists(rewritten_file):
        with open(rewritten_file, "r", encoding="utf-8") as f:
            rewritten = f.read()

    sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)
    wm_text = request.watermark_text or (
        f"《{task.book_title or ''}》{task.book_author or ''}" if task.book_title else ""
    )

    # 共享的 seg_durations
    total_dur = get_audio_duration(final_audio) if _os.path.exists(final_audio) else 0.0
    total_chars = sum(len(s) for s in sentences) or 1

    # v8: 优先用 TTS 实际分段时长构建"字符进度→时间"分段线性映射（修复音画渐进漂移）。
    # 纯字符比例假设语速恒定，误差随时长累积；实际映射让误差在每个 TTS 段边界归零。
    from models import TaskImage, TaskSegment
    seg_durations_shared = None
    tts_segs = (
        db.query(TaskSegment)
        .filter(TaskSegment.task_id == task_id, TaskSegment.status == "success")
        .order_by(TaskSegment.segment_index)
        .all()
    )
    if tts_segs and total_dur > 0:
        tts_durs: list[float] = []
        tts_lens: list[int] = []
        for seg in tts_segs:
            d = (
                get_audio_duration(seg.audio_path)
                if seg.audio_path and _os.path.exists(seg.audio_path)
                else 0.0
            )
            if d <= 0:
                tts_durs = []
                break
            tts_durs.append(d)
            tts_lens.append(max(len(seg.text or ""), 1))
        if tts_durs:
            # final_tts 是无缝 concat，按实际总时长微调（消除封装误差）
            scale = total_dur / sum(tts_durs)
            tts_durs = [d * scale for d in tts_durs]
            # 锚点：(字符进度占比, 累计时间)
            tts_total_chars = sum(tts_lens)
            anchors: list[tuple[float, float]] = [(0.0, 0.0)]
            c_acc, t_acc = 0, 0.0
            for seg_len, seg_dur in zip(tts_lens, tts_durs):
                c_acc += seg_len
                t_acc += seg_dur
                anchors.append((c_acc / tts_total_chars, t_acc))

            def _time_at(frac: float) -> float:
                for (f0, t0), (f1, t1) in zip(anchors, anchors[1:]):
                    if frac <= f1:
                        return t0 + (frac - f0) / (f1 - f0) * (t1 - t0) if f1 > f0 else t1
                return anchors[-1][1]

            seg_durations_shared = []
            c_pos = 0
            for s in sentences:
                start_t = _time_at(c_pos / total_chars)
                c_pos += len(s)
                end_t = _time_at(c_pos / total_chars)
                seg_durations_shared.append(end_t - start_t)
            print(
                f"[compose] 音画对齐: 用 {len(tts_durs)} 个 TTS 实际分段时长映射 "
                f"{len(sentences)} 个句子时长（替代纯字符比例估算）"
            )
    if seg_durations_shared is None:
        # 回退：纯字符比例估算（TTS 分段音频缺失时）
        seg_durations_shared = [len(s) / total_chars * total_dur for s in sentences]
        print("[compose] 音画对齐: TTS 分段时长不可用，回退字符比例估算")

    # 共享的 image_paths（供 card 使用）
    image_records = (
        db.query(TaskImage)
        .filter(TaskImage.task_id == task_id, TaskImage.status == "success")
        .order_by(TaskImage.segment_index)
        .all()
    )
    image_map: dict[int, str] = {}
    for rec in image_records:
        if rec.image_path and _os.path.exists(rec.image_path):
            image_map[rec.segment_index] = rec.image_path
    image_paths_shared = [
        image_map.get(i) or _os.path.join(task_dir, "images", f"seg_{i:03d}.png")
        for i in range(len(sentences))
    ]

    result_cinematic = {}
    result_tw = {}
    result_card = {}
    result_bench = {}

    # === 1) cinematic（主力：AI 配图 + Ken Burns） ===
    if "cinematic" in request.modes:
        result_cinematic = await compose_final_video(
            task_id=task_id,
            db=db,
            style=request.style,
            watermark_text=request.watermark_text,
            bottom_disclaimer=rendered_disclaimer,
            font_size=request.font_size or style_cfg["font_size"],
            zoom_speed=style_cfg["zoom_speed"],
            disclaimer_author=request.author,
            disclaimer_title=request.title,
        )

    # === 2) typewriter（黑底大字版） ===
    if "typewriter" in request.modes:
        tw_style = VIDEO_STYLES.get("typewriter", {"font_size": 64})
        result_tw = await compose_final_video_typewriter(
            task_id=task_id,
            db=db,
            sentences=sentences,
            seg_durations=seg_durations_shared,
            task_dir=task_dir,
            final_audio=final_audio,
            watermark_text=wm_text,
            bottom_disclaimer=rendered_disclaimer,
            font_size=tw_style["font_size"],
        )

    # === 3) card（v7 三段式：暗夜海军蓝遮罩 + 标语模板化） ===
    if "card" in request.modes:
        ar = request.aspect_ratio or "16:9"
        card_style = VIDEO_STYLES.get("card_3x4" if ar == "3:4" else "card_16x9", {"font_size": 52})
        is_general = request.content_mode == "general"
        result_card = await compose_final_video_card_v6(
            task_id=task_id,
            db=db,
            sentences=sentences,
            seg_durations=seg_durations_shared,
            image_paths=image_paths_shared,
            task_dir=task_dir,
            final_audio=final_audio,
            card_title=request.video_title if is_general else (request.title or task.book_title or ""),
            card_author="" if is_general else (request.author or task.book_author or ""),
            bottom_disclaimer=rendered_disclaimer,
            font_size=card_style["font_size"],
            aspect_ratio=ar,
            slogan=request.slogan,
            subtitle_line=request.subtitle_line,
        )

    # === 4) bench（v8 对标卡片：深藏青底 + 8:9 满宽大图 + 双色标题） ===
    if "bench" in request.modes:
        t1 = request.title_line1.strip()
        t2 = request.title_line2.strip()
        if not (t1 or t2):
            raw_title = request.video_title or request.title or task.book_title or ""
            if raw_title:
                import re as _title_re
                cjk_count = len(_title_re.findall(r'[一-鿿]', raw_title))
                if cjk_count <= 16:
                    # 短标题：本地断行，不调 AI（避免 AI 擅自提炼改写）
                    lines = _split_title_local(raw_title, max_chars=16)
                    t1 = lines[0] if len(lines) > 1 else ""
                    t2 = lines[-1]
                else:
                    from services.llm_service import split_title_two_lines
                    split = await split_title_two_lines(
                        raw_title,
                        book_title=task.book_title or "",
                        book_author=task.book_author or "",
                    )
                    t1 = split.get("line1", "")
                    t2 = split.get("line2", "")
        result_bench = await compose_final_video_card_bench(
            task_id=task_id,
            db=db,
            sentences=sentences,
            seg_durations=seg_durations_shared,
            image_paths=image_paths_shared,
            task_dir=task_dir,
            final_audio=final_audio,
            title_line1=t1,
            title_line2=t2,
            slogan=request.slogan,
            subtitle_line=request.subtitle_line,
        )

    # === 组装响应 ===
    # 主输出优先级：bench > card > cinematic > typewriter
    primary = result_bench if result_bench else (
        result_card if result_card else (result_cinematic if result_cinematic else result_tw)
    )

    # === 剪映 v11 草稿导出（matte 遮罩三轨分层架构）===
    jianying_published = False
    jianying_draft_name = None
    if primary and "error" not in primary:
        try:
            from services.jianying_v11_service import export_jianying_draft_v11
            from services.video_service import _find_bgm, BGM_VOLUME, BGM_FADE_SEC, get_audio_duration

            draft_name = (request.video_title or f"Task_{task_id}").strip()
            seg_durations_us = [d * 1_000_000 for d in seg_durations_shared]

            # ★ BGM 混入：对标 FFmpeg 合成，剪映草稿也需要背景音乐
            draft_audio = final_audio
            bgm_path = _find_bgm()
            if bgm_path and _os.path.exists(final_audio):
                import subprocess as _sp
                voice_dur = get_audio_duration(final_audio)
                bg_chain = f"[1:a]volume={BGM_VOLUME}"
                if voice_dur > BGM_FADE_SEC:
                    bg_chain += f",afade=t=out:st={voice_dur - BGM_FADE_SEC:.2f}:d={BGM_FADE_SEC}"
                bg_chain += "[bg]"
                draft_audio = _os.path.join(task_dir, "_draft_mixed_audio.mp3")
                cmd = [
                    "ffmpeg", "-y",
                    "-i", final_audio,
                    "-stream_loop", "-1", "-i", bgm_path,
                    "-filter_complex",
                    f"{bg_chain};[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]",
                    "-map", "[aout]", "-c:a", "libmp3lame", "-b:a", "192k",
                    "-shortest", draft_audio,
                ]
                _sp.run(cmd, capture_output=True, timeout=120)
                if _os.path.exists(draft_audio) and _os.path.getsize(draft_audio) > 1000:
                    print(f"[compose] BGM 已混入草稿音频: {draft_audio}")
                else:
                    draft_audio = final_audio  # 回退

            print(f"[compose] disclaimer value: {repr(rendered_disclaimer)}")
            print(f"[compose] slogan value: {repr(request.slogan)}")

            draft_dir = await asyncio.to_thread(
                export_jianying_draft_v11,
                sentences=sentences,
                image_paths=image_paths_shared,
                audio_path=draft_audio,
                seg_durations_us=seg_durations_us,
                draft_name=draft_name,
                upper_title=request.video_title or "",
                lower_title_1=request.slogan or "",
                lower_title_2=request.subtitle_line or rendered_disclaimer or "",
            )
            jianying_published = True
            jianying_draft_name = draft_name
            for bad in '<>:"/\\|?*':
                jianying_draft_name = jianying_draft_name.replace(bad, "_")
            print(f"[compose] v11 剪映草稿已导出: {draft_dir}")
        except Exception as e:
            print(f"[compose] v11 剪映草稿导出失败: {e}")
            import traceback
            traceback.print_exc()

    # === 成品库归档：复制成片到统一平铺目录（v9：便于直接上传发布平台）===
    archive_path = None
    if primary and "error" not in primary and primary.get("video_path"):
        try:
            import shutil as _shutil
            out_dir = os.getenv("FINAL_OUTPUT_DIR", "")
            if not out_dir:
                import sys as _out_sys
                if getattr(_out_sys, 'frozen', False):
                    out_dir = _os.path.join(os.path.dirname(_out_sys.executable), "成片输出")
                else:
                    out_dir = r"D:\成片输出"
            _os.makedirs(out_dir, exist_ok=True)
            safe_title = (request.video_title or task.book_title or f"task{task_id}").strip()
            for bad in '<>:"/\\|?*\n\r\t':
                safe_title = safe_title.replace(bad, "_")
            safe_title = safe_title[:60] or f"task{task_id}"
            date_tag = datetime.now().strftime("%m%d")
            base_name = f"{date_tag}_{safe_title}"
            dest = _os.path.join(out_dir, f"{base_name}.mp4")
            n = 1
            while _os.path.exists(dest):
                n += 1
                dest = _os.path.join(out_dir, f"{base_name}_{n}.mp4")
            _shutil.copy2(primary["video_path"], dest)
            archive_path = dest
            print(f"[compose] 成片已归档: {dest}")
        except Exception as e:
            print(f"[compose] 成片归档失败（不影响成片）: {e}")

    if "error" in primary:
        return ComposeVideoResponse(
            task_id=task_id,
            video_url="",
            duration_sec=0,
            size_mb=0,
            segment_count=primary.get("segment_count", 0),
            width=1080,
            height=1920,
            message=primary["error"],
        )

    msg_parts = []
    if result_cinematic:
        msg_parts.append(f"电影感 {result_cinematic.get('duration_sec', 0)}s")
    if result_tw:
        msg_parts.append(f"大字版 {result_tw.get('duration_sec', 0)}s")
    if result_card:
        msg_parts.append(f"卡片 {result_card.get('duration_sec', 0)}s")
    if result_bench:
        msg_parts.append(f"对标卡片 {result_bench.get('duration_sec', 0)}s")

    return ComposeVideoResponse(
        task_id=task_id,
        video_url=primary.get("video_url", ""),
        duration_sec=primary.get("duration_sec", 0),
        size_mb=primary.get("size_mb", 0),
        segment_count=primary.get("segment_count", 0),
        width=primary.get("width", 1080),
        height=primary.get("height", 1920),
        message="成片完成！" + " + ".join(msg_parts),
        srt_url=primary.get("srt_url"),
        ass_url=primary.get("ass_url"),
        jianying_draft_url=primary.get("jianying_draft_url") or (
            f"/video/{task_id}/draft_content.json"
            if _os.path.exists(_os.path.join(task_dir, "draft_content.json")) else None
        ),
        jianying_published=jianying_published,
        jianying_draft_name=jianying_draft_name,
        black_placeholder_count=primary.get("black_placeholder_count", 0),
        video_url_typewriter=result_tw.get("video_url") if "error" not in result_tw else None,
        duration_sec_typewriter=result_tw.get("duration_sec") if "error" not in result_tw else None,
        size_mb_typewriter=result_tw.get("size_mb") if "error" not in result_tw else None,
        video_url_card=result_card.get("video_url") if "error" not in result_card else None,
        duration_sec_card=result_card.get("duration_sec") if "error" not in result_card else None,
        size_mb_card=result_card.get("size_mb") if "error" not in result_card else None,
        video_url_bench=result_bench.get("video_url") if "error" not in result_bench else None,
        duration_sec_bench=result_bench.get("duration_sec") if "error" not in result_bench else None,
        size_mb_bench=result_bench.get("size_mb") if "error" not in result_bench else None,
        archive_path=archive_path,
    )


@app.get("/api/video/status/{task_id}", response_model=VideoStatusResponse)
async def get_video_status(task_id: int):
    """检查视频文件是否存在"""
    task_dir = os.path.join(TASKS_DIR, str(task_id))
    final_video = os.path.join(task_dir, "final_1080x1920.mp4")

    exists = os.path.exists(final_video)
    duration = 0.0
    size = 0.0
    srt_url = None
    ass_url = None
    jianying_draft_url = None

    if exists:
        from services.video_service import get_audio_duration
        duration = get_audio_duration(final_video)
        size = os.path.getsize(final_video) / 1024 / 1024
        # v4: 检查并返回下载链接
        if os.path.exists(os.path.join(task_dir, "subtitles.srt")):
            srt_url = f"/video/{task_id}/subtitles.srt"
        if os.path.exists(os.path.join(task_dir, "subtitles.ass")):
            ass_url = f"/video/{task_id}/subtitles.ass"
        if os.path.exists(os.path.join(task_dir, "draft_content.json")):
            jianying_draft_url = f"/video/{task_id}/draft_content.json"

    return VideoStatusResponse(
        task_id=task_id,
        exists=exists,
        video_url=f"/video/{task_id}/final_1080x1920.mp4" if exists else None,
        duration_sec=round(duration, 1),
        size_mb=round(size, 1),
        srt_url=srt_url,
        ass_url=ass_url,
        jianying_draft_url=jianying_draft_url,
    )


@app.get("/api/video/styles")
async def get_video_styles():
    """获取视频风格预设列表"""
    from services.video_service import VIDEO_STYLES
    return {
        "styles": [
            {"key": k, **v} for k, v in VIDEO_STYLES.items()
        ]
    }


# ============== 成品库（v9）==============

@app.post("/api/open-output-dir")
async def open_output_dir():
    """在服务器本机打开成品库文件夹（仅主机浏览器点击有意义，远程同事请用下载按钮）"""
    out_dir = os.getenv("FINAL_OUTPUT_DIR", "")
    if not out_dir:
        import sys as _out_sys2
        if getattr(_out_sys2, 'frozen', False):
            out_dir = os.path.join(os.path.dirname(_out_sys2.executable), "成片输出")
        else:
            out_dir = r"D:\成片输出"
    os.makedirs(out_dir, exist_ok=True)
    try:
        os.startfile(out_dir)  # Windows 资源管理器打开
        return {"ok": True, "path": out_dir}
    except Exception as e:
        return {"ok": False, "path": out_dir, "error": str(e)}


# ============== 剪映草稿下载接口 ==============

@app.get("/api/video/jianying-draft/{task_id}")
async def download_jianying_draft(task_id: int):
    """
    下载剪映草稿文件（draft_content.json）。

    运营同事通过此接口一键下载，导入本地剪映后
    可直接看到 1:1 对齐的视频、音频、字幕轨道。
    """
    from fastapi.responses import FileResponse

    task_dir = os.path.join(TASKS_DIR, str(task_id))
    draft_path = os.path.join(task_dir, "draft_content.json")

    if not os.path.exists(draft_path):
        raise HTTPException(
            status_code=404,
            detail=f"剪映草稿不存在，请先完成视频合成（任务 {task_id}）"
        )

    return FileResponse(
        path=draft_path,
        filename=f"Task_{task_id}_剪映草稿.json",
        media_type="application/json",
    )


@app.get("/api/video/subtitles/{task_id}")
async def download_subtitles(task_id: int, format: str = "srt"):
    """
    下载字幕文件。
    - format=srt → subtitles.srt
    - format=ass → subtitles.ass（高级样式）
    """
    from fastapi.responses import FileResponse

    task_dir = os.path.join(TASKS_DIR, str(task_id))
    if format == "ass":
        sub_path = os.path.join(task_dir, "subtitles.ass")
    else:
        sub_path = os.path.join(task_dir, "subtitles.srt")

    if not os.path.exists(sub_path):
        raise HTTPException(
            status_code=404,
            detail=f"字幕文件不存在，请先完成视频合成（任务 {task_id}）"
        )

    ext = "ass" if format == "ass" else "srt"
    return FileResponse(
        path=sub_path,
        filename=f"Task_{task_id}_字幕.{ext}",
        media_type="text/plain; charset=utf-8",
    )


# ============== 前端静态托管（v9：局域网单端口部署）==============
# 挂在所有 API 路由之后：/api /audio /images /video /docs 优先命中，
# 其余路径由前端 SPA 接管。frontend/dist 不存在时跳过（纯开发模式）。
_FRONTEND_DIST = os.path.join(get_project_root(), "frontend", "dist")
if os.path.isdir(_FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
    print(f"[main] 前端已托管: {os.path.abspath(_FRONTEND_DIST)} → http://<本机>:8000/")
else:
    print("[main] frontend/dist 不存在，跳过前端托管（开发模式请用 npm run dev）")


def _detect_lan_ip() -> str:
    """
    探测本机真实的局域网 IP（排除虚拟网卡 / WSL / VPN 等虚拟适配器）。
    优先返回 WiFi，其次返回有线网卡。只有一台，不需要辨认。
    """
    import subprocess
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             # 取 IPv4，排除回环和虚拟适配器 → 按 PhysicalAdapter 优先 → 取 IP
             "(Get-NetIPAddress -AddressFamily IPv4 "
             "-InterfaceAlias 'WLAN','Wi-Fi','Ethernet','以太网','WLAN*','Wi-Fi*','以太网*' "
             "-PolicyStore ActiveStore -ErrorAction SilentlyContinue "
             "| Sort-Object -Property { -not $_.InterfaceAlias.match('WLAN|Wi-Fi') } "
             "| Select-Object -First 1).IPAddress"],
            timeout=5, encoding="utf-8", errors="replace")
        ip = out.strip()
        if ip:
            return ip
    except Exception:
        pass
    # 回退：socket 探测
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("192.168.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        ip_str = str(ip)
        if ip_str.startswith("192.168.") or ip_str.startswith("10.") or ip_str.startswith("172."):
            return ip_str
    except Exception:
        pass
    return ""


def _auto_open_browser():
    """延迟 1.5 秒后自动打开浏览器（零门槛使用）。"""
    import threading
    import webbrowser
    import sys as _auto_sys

    def _open():
        import time
        time.sleep(1.5)
        try:
            webbrowser.open("http://localhost:8000")
        except Exception:
            pass  # 静默失败，不影响主程序

    threading.Thread(target=_open, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    import sys as _sys

    print("=" * 56)
    print("  Video Automation Server")
    print("=" * 56)
    lan_ip = _detect_lan_ip()
    if lan_ip:
        print(f"  Colleagues:       http://{lan_ip}:8000")
    else:
        print("  Colleagues:       (not detected — check WiFi/cable)")
    print(f"  Yourself:         http://localhost:8000")
    print(f"  API docs:         http://localhost:8000/docs")
    print("=" * 56)
    print()

    # ★ 自动打开浏览器（方便同事零门槛使用）
    _auto_open_browser()

    _frozen = getattr(_sys, 'frozen', False)
    if _frozen:
        uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
    else:
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
