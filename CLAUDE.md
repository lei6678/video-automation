# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

视频自动化制作工作流：抖音链接解析 → 逐字稿提取 → LLM 清洗 → TTS 配音 → 批量生图 → 合成成片。

- **前端**: Vite + React + TypeScript (`frontend/`)
- **后端**: Python FastAPI + SQLAlchemy + SQLite (`backend/`)

## 常用命令

### 前端
```bash
cd frontend
npm install
npm run dev       # 访问 http://localhost:5173
```

### 后端
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload  # API 文档 http://localhost:8000/docs
```

### 环境变量
- `frontend/.env`: `VITE_API_BASE_URL=http://localhost:8000`
- `backend/.env`: `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `SILICONFLOW_API_KEY`, `TIKHUB_API_KEY`

## 架构

### 数据目录
- SQLite DB: `backend/data/app.db`
- 任务文件: `backend/data/tasks/{task_id}/`
- 音频静态服务: `/audio/{task_id}/...` → `backend/data/tasks/{task_id}/...`

### 数据模型
- `Task`: 主任务表（source_url, status, current_step, raw_transcript, rewritten_transcript, douyin_meta, book_title, book_author）
- `TaskSegment`: TTS 片段表（task_id, segment_index, text, audio_path, status, error_msg）

### 后端服务层 (`backend/services/`)
| 文件 | 职责 | 外部依赖 |
|------|------|---------|
| `douyin_service.py` | 抖音视频解析（四通道串联） | httpx, Playwright, TikHub API, ixigua |
| `asr_service.py` | 语音识别 | SiliconFlow (FunAudioLLM/SenseVoiceSmall) |
| `llm_service.py` | 文本清洗/改写/书籍信息提取/短句切分 | DeepSeek API |
| `tts_service.py` | TTS 配音生成 | index-tts2 本地服务 / edge-tts |
| `siliconflow_tts_service.py` | SiliconFlow 音色克隆 TTS | FunAudioLLM/CosyVoice2-0.5B |
| `volc_tts_service.py` | 豆包 TTS v2 | 火山引擎 API |
| `volc_tts_v3_service.py` | 豆包语音合成 v3 + 声音复刻 2.0 | 火山引擎 API |
| `image_service.py` | 配图批量生成（Fal.ai 九宫格 + 可灵备选） | Fal.ai, 可灵 API, PIL |
| `video_service.py` | 视频合成（Ken Burns 动效 + 字幕 + 音轨混流） | FFmpeg, PIL |

### 工作流程
1. **文案导入**（当前主要方式）`POST /api/tasks/from-text` → 手动粘贴文案，跳过抖音解析
2. **文本清洗** `POST /api/clean-text` → DeepSeek 修正 ASR 错字
3. **候选稿生成** `POST /api/rewrite` → `mode=rewrite`（深度改写）或 `mode=light_dedupe`（轻量去重）
4. **书籍信息反推** `POST /api/book-info` → DeepSeek JSON 抽取
5. **TTS 配音** `POST /api/generate-audio` → 增量式分段生成 + FFmpeg 拼接
6. **配图批量生成** `POST /api/images/generate` → Fal.ai gpt-image-2 九宫格 → 裁切 → TaskImage 表
7. **视频合成** `POST /api/video/compose` → Ken Burns 动效 + 字幕 + 音轨混流 → final_1080x1920.mp4

> ⚠️ 抖音链接解析 (`POST /api/extract`) 因平台反爬已暂时禁用，前端已切换为纯文本导入模式。

### SiliconFlow 音色克隆
- 使用 `FunAudioLLM/CosyVoice2-0.5B` 模型（CosyVoice2）
- 两步流程：① `POST /v1/uploads/audio/voice` 上传参考音频 → 获取 `voice_uri`；② `POST /v1/audio/speech` + `voice_uri` 生成同音色音频
- API Key：`SILICONFLOW_API_KEY`（`backend/.env`）
- 参考音频格式：`mp3` / `wav` / `m4a`

### 关键设计
- **四通道下载策略**（优先级 A > B > C）：A=中转流（非抖音域名）, B=纯音频（CDN 风控弱）, C=原视频直链（15s 超时）
- **增量 TTS**：跳过已成功的片段，失败片段可单独重跑 `POST /api/tts/regenerate-segment`
- **纯文本任务**：`POST /api/tasks/from-text` 跳过下载/ASR，直接进入 Step 02（改写）
- **TTS 优先 index-tts2**（:7860），不可用时降级 edge-tts（微软云），同一音色不切换保证作品一致性
