# 视频自动化制作工作流

抖音链接解析、提取逐字稿、大模型清洗（修复ASR错字）、TTS配音、批量生图、合成成片 — 全流程可视化控制。

## 技术栈

- **前端**: Vite + React + TypeScript
- **后端**: Python FastAPI

## 项目结构

```
video-automation/
├── frontend/          # Vite + React 前端
├── backend/           # Python FastAPI 后端
└── README.md
```

## 快速启动

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端服务启动后访问: http://localhost:5173

### 后端

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

后端服务启动后访问: http://localhost:8000

API 文档: http://localhost:8000/docs

## 环境变量

### 前端 (.env)

```env
VITE_API_BASE_URL=http://localhost:8000
```

### 后端 (.env)

```env
OPENAI_API_KEY=your_api_key_here
```

## 工作流程说明

1. **链接解析** - 输入抖音视频链接，系统解析提取视频信息
2. **逐字稿提取** - 提取视频/音频的原始文字稿
3. **大模型清洗** - 使用 LLM 修正 ASR 识别错误
4. **TTS配音** - 将清洗后的文字转换为语音
5. **批量生图** - 根据文案内容生成配套图片
6. **合成成片** - 将音频、图片合成为最终视频
