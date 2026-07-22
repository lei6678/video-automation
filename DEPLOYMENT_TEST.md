# 部署验收指南 (Deployment Test Guide)

> 在新电脑（台式机）上从零部署本视频自动化工作台，按本文档逐项验证即可。

---

## 1. 环境要求

| 项目 | 要求 | 验证命令 |
|------|------|----------|
| **操作系统** | Windows 10/11 64-bit | — |
| **Python** | **3.10 ~ 3.12**（推荐 3.11） | `python --version` |
| **Node.js** | 18.x / 20.x LTS | `node --version` |
| **FFmpeg** | 5.0+（需在 PATH 中） | `ffmpeg -version` |
| **Git** | 任意版本 | `git --version` |

### 安装 FFmpeg（Windows）

```powershell
# 方式一：winget（推荐）
winget install ffmpeg

# 方式二：手动下载
# 1. 打开 https://www.gyan.dev/ffmpeg/builds/
# 2. 下载 ffmpeg-release-essentials.zip
# 3. 解压到 C:\ffmpeg\
# 4. 将 C:\ffmpeg\bin\ 加入系统 PATH 环境变量
```

验证：
```bash
ffmpeg -version
# 应输出版本信息，无报错
```

---

## 2. 克隆项目 & 安装依赖

```bash
# 克隆仓库
git clone <你的仓库地址> video-automation
cd video-automation

# -------- 后端 --------
cd backend
python -m venv venv
# 激活虚拟环境（Windows）:
venv\Scripts\activate
pip install -r requirements.txt

# 安装 Playwright 浏览器（抖音解析备用通道）
playwright install chromium

# -------- 前端 --------
cd ..\frontend
npm install
npm run build
# 产物在 frontend/dist/，后端会自动托管
```

---

## 3. 环境变量配置 (.env)

在 `backend/.env` 中配置以下密钥。可直接复制 `backend/.env.example` 改名为 `.env` 后填入：

```bash
cd backend
cp .env.example .env
# 然后用文本编辑器编辑 .env
```

### 必填项（缺一不可）

| 变量名 | 用途 | 获取地址 |
|--------|------|----------|
| `DEEPSEEK_API_KEY` | 文本改写 / LLM 清洗 / 句切分 | https://platform.deepseek.com/api_keys |
| `SILICONFLOW_API_KEY` | 语音识别 ASR + TTS 音色克隆 | https://siliconflow.cn/ → API 密钥 |
| `FAL_KEY` | AI 配图生成（主力） | https://fal.ai/dashboard → Settings → API Keys |

### 选填项（按需启用）

| 变量名 | 用途 | 获取地址 |
|--------|------|----------|
| `TIKHUB_API_KEY` | 抖音视频解析（备选通道） | https://api.tikhub.io/ |
| `VOLC_ACCESS_TOKEN` | 豆包 TTS v2 配音 | https://console.volcengine.com/ → 语音技术 |
| `ARK_API_KEY` | 豆包 TTS v3 + 声音复刻 | https://console.volcengine.com/ark/ → API Keys |
| `FAL_QUALITY` | Fal.ai 画质（low/medium/high） | 默认 `low`，余额充足可调 `high` |
| `FINAL_OUTPUT_DIR` | 成片自动归档目录 | 默认 `E:\成片输出`，可自定义 |

### .env 示例

```ini
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SILICONFLOW_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FAL_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
FAL_QUALITY=low
# 以下选填：
# TIKHUB_API_KEY=your_tikhub_key
# VOLC_ACCESS_TOKEN=your_volc_token
# ARK_API_KEY=your_ark_key
```

---

## 4. 字体文件

项目使用两个字体文件，确保它们存在：

| 文件 | 路径 | 用途 |
|------|------|------|
| **思源宋体 Heavy** | `fonts/XianKai_Title.otf` | 对标卡片 bench 模式的标题/字幕字体 |
| **钟齐志莽行书** | `fonts/Slogan_Xingkai.ttf` | 底部标语书法字体 |

> FFmpeg drawtext 还会使用系统自带中文字体（微软雅黑 / 黑体 / 宋体）作为兜底。Windows 10/11 自带这些字体，无需额外安装。

验证：
```bash
ls -la fonts/XianKai_Title.otf fonts/Slogan_Xingkai.ttf
# 两个文件大小均应 > 1MB
```

---

## 5. 目录结构确认

部署完成后，项目根目录应包含以下关键路径：

```
video-automation/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── database.py           # SQLite 数据库
│   ├── models.py             # 数据模型
│   ├── requirements.txt      # Python 依赖
│   ├── .env                  # 环境变量（手动创建）
│   ├── services/             # 服务层
│   │   ├── llm_service.py
│   │   ├── asr_service.py
│   │   ├── tts_service.py
│   │   ├── siliconflow_tts_service.py
│   │   ├── volc_tts_v3_service.py
│   │   ├── image_service.py
│   │   ├── video_service.py
│   │   └── douyin_service.py
│   ├── prompts/              # LLM 提示词模板
│   │   ├── rewrite_system.txt
│   │   ├── rewrite_user.txt
│   │   ├── rewrite_research.txt
│   │   └── image_context.txt
│   └── data/                 # 运行时数据（自动创建）
│       ├── app.db
│       └── tasks/
├── frontend/
│   ├── package.json
│   ├── src/
│   └── dist/                 # 构建产物（npm run build 后生成）
├── fonts/
│   ├── XianKai_Title.otf
│   └── Slogan_Xingkai.ttf
├── bgm/                      # 背景音乐（可选）
│   └── 使用说明.txt
├── 启动工作台.bat             # 一键启动脚本
└── DEPLOYMENT_TEST.md        # 本文件
```

---

## 6. 端口号

| 服务 | 端口 | 说明 |
|------|------|------|
| **后端 API + 前端静态文件** | **8000** | 单端口全栈部署，浏览器访问 `http://localhost:8000` |
| 前端开发服务器（可选） | 5173 | 仅 `npm run dev` 时使用 |

> 局域网同事访问：`http://<服务器局域网IP>:8000`

---

## 7. 核心测试命令（一次完整测试出片）

### 7.1 启动服务

```bash
# 方式一：双击启动脚本
启动工作台.bat

# 方式二：命令行
cd backend
venv\Scripts\activate
python main.py
```

启动成功标志：
```
==========================================================
  Video Automation Server
==========================================================
  Colleagues:       http://192.168.x.x:8000
  Yourself:         http://localhost:8000
  API docs:         http://localhost:8000/docs
==========================================================
```

### 7.2 快速冒烟测试（API 健康检查）

```bash
curl http://localhost:8000/api/health
# 预期: {"status":"healthy"}
```

### 7.3 端到端出片测试（手动粘贴文案）

这是最快的验证路径——跳过抖音下载和 ASR，直接粘贴一段文案出片。

#### Step 1: 导入文案

浏览器打开 `http://localhost:8000`，在工作台界面操作：

1. 点击 **"手动粘贴文案"**
2. 粘贴一段测试文案（100~500 字即可，例如一篇读书分享短文）
3. 输入标题后点击提交

或使用 API：

```bash
curl -X POST http://localhost:8000/api/tasks/from-text \
  -H "Content-Type: application/json" \
  -d '{"raw_text": "今天给大家分享一本好书《被讨厌的勇气》。这本书基于阿德勒心理学，告诉我们：真正的自由，来自于被讨厌的勇气。我们不必活在他人的期待中，也不必寻求他人的认可。人生的意义，由你自己赋予。当你不再害怕被人讨厌，你就获得了真正的自由。", "title": "被讨厌的勇气"}'
```

#### Step 2: 文本改写（AI 洗稿）

在工作台点击 **"AI 改写"**，等待 DeepSeek 返回改写结果和爆款标题。

或：
```bash
curl -X POST http://localhost:8000/api/rewrite \
  -H "Content-Type: application/json" \
  -d '{"task_id": 1}'
```

#### Step 3: TTS 配音

在工作台点击 **"生成配音"**，选择音色后开始。

或：
```bash
curl -X POST http://localhost:8000/api/generate-audio \
  -H "Content-Type: application/json" \
  -d '{"task_id": 1, "voice": "vc_shuangsisi"}'
```

#### Step 4: 配图生成

在工作台点击 **"生成配图"**，选择风格。

或：
```bash
curl -X POST http://localhost:8000/api/images/generate \
  -H "Content-Type: application/json" \
  -d '{"task_id": 1, "style": "warm_book"}'
```

#### Step 5: 视频合成

在工作台点击 **"合成视频"**，选择模式和比例。

或：
```bash
curl -X POST http://localhost:8000/api/video/compose \
  -H "Content-Type: application/json" \
  -d '{"task_id": 1, "modes": ["bench"], "aspect_ratio": "9:16", "slogan": "- 品读传奇人生 -"}'
```

### 7.4 验证产出

合成完成后，检查以下产出物：

```bash
# 成片视频
ls -la backend/data/tasks/1/final_*.mp4

# 字幕文件
ls -la backend/data/tasks/1/subtitles.srt
ls -la backend/data/tasks/1/subtitles.ass

# 剪映草稿
ls -la backend/data/tasks/1/draft_content.json

# 成品库归档（如有配置 FINAL_OUTPUT_DIR）
ls -la E:/成片输出/
```

> ✅ **验收标准**：`final_*.mp4` 文件存在且大小 > 1MB，用播放器打开有画面、有配音、有字幕即为部署成功。

---

## 8. 常见问题排查

| 现象 | 可能原因 | 解决 |
|------|----------|------|
| `ffmpeg: command not found` | FFmpeg 未安装或未加入 PATH | 参照第 1 节安装 FFmpeg |
| `DEEPSEEK_API_KEY 未设置` | .env 文件缺失或未配置 | 检查 `backend/.env` 文件 |
| `SILICONFLOW_API_KEY 未设置` | 同上 | 同上 |
| 前端页面空白 | 未构建 `frontend/dist/` | `cd frontend && npm run build` |
| 局域网同事无法访问 | Windows 防火墙拦截 | 入站规则放行 TCP 8000；网络设为"专用" |
| TTS 生成超时 | SiliconFlow API 限流 | 等待 30 秒后重试 |
| 配图生成失败 | Fal.ai 余额不足或内容审查拦截 | 检查 Fal.ai 控制台余额；尝试更换文案 |
| 视频合成乱码 | Windows 控制台编码问题 | 确保 `chcp 65001` 已执行（启动脚本已包含） |

---

## 9. 多用户协作说明

- **服务端**：只需在一台电脑上启动 `python main.py`，全团队通过浏览器访问
- **API Key 共享**：所有同事共用服务器上的同一套 `.env` 密钥，无需各自申请
- **局域网访问**：`http://<服务器IP>:8000`，所有设备需在同一局域网，服务器网络模式需为"专用"
- **成品下载**：成片自动归档到 `FINAL_OUTPUT_DIR` 目录，同事可从浏览器下载或直接访问共享文件夹

---

> 📅 最后更新：2026-07-22
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)
