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
npm run dev       # 开发模式，http://localhost:5173（仅本机）
npm run build     # 生产构建 → dist/（供后端单端口托管）
```

### 后端
```bash
cd backend
pip install -r requirements.txt
python main.py                  # 生产模式：单端口 8000，托管前端 dist/ + API
# 或
uvicorn main:app --reload       # 开发模式：仅 API，http://localhost:8000/docs
```

### 团队协作启动
双击 `启动工作台.bat` → 黑窗口自动打印 LAN IP → 同事浏览器打开 `http://<IP>:8000`。
关闭黑窗口 = 停止服务。

### 环境变量
- `frontend/.env`: `VITE_API_BASE_URL=`（留空 = 生产相对路径；开发时可临时改为 `http://localhost:8000`）
- `backend/.env`: `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `SILICONFLOW_API_KEY`, `TIKHUB_API_KEY`

## 架构

### 数据目录
- SQLite DB: `backend/data/app.db`
- 任务文件: `backend/data/tasks/{task_id}/`
- 音频静态服务: `/audio/{task_id}/...` → `backend/data/tasks/{task_id}/...`

### 数据模型
- `Task`: 主任务表（source_url, status, current_step, raw_transcript, rewritten_transcript, douyin_meta, book_title, book_author, video_title, content_mode, visual_context, error_msg）
- `TaskSegment`: TTS 片段表（task_id, segment_index, text, audio_path, status, error_msg）
- `TaskImage`: 配图表（task_id, segment_index, grid_index, cell_position, image_path, status）

### 局域网多人部署（v8）
- **架构**：后端单端口 8000 同时托管 API + 前端静态文件（`frontend/dist/`）
- **CORS**：`main.py` 中间件允许内网前缀（`192.168.*`、`10.*`、`172.*`）
- **防火墙**：入站规则放行 TCP 8000（服务端口）
- **启动**：双击 `启动工作台.bat` → `python main.py` → 自动探测并打印 LAN IP
- **同事访问**：浏览器打开 `http://<服务器IP>:8000`，零安装
- **网络要求**：服务器网络必须是"专用"模式（非 Public），所有设备需在同一局域网

### 新增资产
| 路径 | 说明 |
|------|------|
| `backend/prompts/rewrite_system.txt` | 改写 System Prompt |
| `backend/prompts/rewrite_user.txt` | 改写 User Prompt |
| `backend/prompts/rewrite_research.txt` | 研究模式 Prompt |
| `backend/prompts/image_context.txt` | 配图视觉档案提取 Prompt |
| `fonts/XianKai_Title.otf` | 思源宋体 Heavy（bench 卡片标题字体） |
| `bgm/` | 全局背景音乐目录：放入任意音频文件即自动混入所有成片（循环铺底，25% 音量 ≈ 剪映 -12dB + 结尾淡出），清空则不加 BGM |
| `团队每日操作指南.md` | 团队协作 SOP |

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
1. **文案导入** `POST /api/tasks/from-text` → 手动粘贴文案（标准模式）/ `POST /api/tasks/import-rewritten` → 直接导入已改好文案（跳过 AI 改写）
2. **文本清洗** `POST /api/clean-text` → DeepSeek 修正 ASR 错字（仅标准模式触发）
3. **候选稿生成** `POST /api/rewrite` → 市井烟火气对抗型洗稿 + 爆款标题 JSON 输出
   - LLM Prompt 外部化到 `backend/prompts/rewrite_*.txt`，非开发人员可直接编辑
4. **书籍信息反推** `POST /api/book-info` → DeepSeek JSON 抽取
5. **TTS 配音** `POST /api/generate-audio` → 增量式分段生成 + FFmpeg 拼接（3 黄金音色：vc_shuangsisi / vc_clone_female / vc_clone_wanglq）
6. **配图批量生成** `POST /api/images/generate` → Fal.ai 单图直生（v4 架构，不再使用九宫格）
   - 内置 70+ 敏感词过滤 → Fal.ai 内容审查规避
   - 单句配图 Prompt 构建器 + 4 风格后缀 + 安全补丁
   - `regenerate_single_image` 支持 4K 超采样（2160×3840 → LANCZOS 缩到 1080×1920）
7. **视频合成** `POST /api/video/compose` → 三模式并行裂变：
   - **cinematic** — AI 配图 + Ken Burns 电影感动效
   - **typewriter** — 黑底大字版
   - **card (v7)** — 暗夜海军蓝三段式卡片，全局 filter_complex 复合
   - **bench (v8)** — 对标卡片：深藏青底 + 8:9 满宽大图 + 双色标题（琥珀金/暖白），思源宋体 Heavy
   - 自动生成剪映草稿 + 字幕文件（SRT/ASS）+ 成品库归档

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
