# 项目备忘录

## 2026-07-17 局域网多人协作部署（里程碑）

### 一、问题背景

服务器 `python main.py` 启动后，本机 `localhost:8000` 正常访问，同事电脑/手机无法打开。三个层面原因叠加：

| 层级 | 问题 | 修复 |
|------|------|------|
| **前端硬编码** | `App.tsx` 所有 fetch 写死 `http://localhost:8000`，同事浏览器把请求发到**自己的** localhost | 全部改为 `` `${API_BASE}/api/...` ``，生产环境走相对路径（同源） |
| **CORS 白名单** | `main.py` 中间件只允许 `localhost:5173/5174`，LAN IP 全部拒绝 | 扩展到 `192.168.*`、`10.*`、`172.*` 等内网前缀 |
| **网络隔离** | `ChinaNet-bU6v-5G`（电信公共 WiFi）被 Windows 标记为 Public + 路由器 AP 隔离 | `Set-NetConnectionProfile -NetworkCategory Private` + 防火墙放行 8000/5173 |
| **Vite 监听** | 默认只绑 `127.0.0.1`，外部不可达 | `host: '0.0.0.0'` + proxy 扩展 audio/images/video 路径 |

### 二、改动文件清单

| 文件 | 改动 | 目的 |
|------|------|------|
| `frontend/src/App.tsx` | 全部 fetch URL 从硬编码 `localhost:8000` → `` `${API_BASE}/...` `` | 生产环境走相对路径 |
| `frontend/.env` | `VITE_API_BASE_URL=` 清空 | 构建时不注入 localhost |
| `frontend/vite.config.ts` | `host: '0.0.0.0'` + proxy 补全 `/audio` `/images` `/video` | 开发模式也允许局域网访问 |
| `frontend/dist/*` | `npm run build` 重新构建 | 产物中零 localhost 硬编码 |
| `backend/main.py` | CORS 白名单扩展到内网段 + 启动时自动探测 LAN IP 并打印 | 同事浏览器不被 CORS 拦截 |
| `启动工作台.bat` | 切换为 `python main.py`（触发 IP 探测逻辑）+ 纯 ASCII 防乱码 | 每次启动自动显示真实 LAN IP |
| Windows 防火墙 | 入站规则放行 TCP 8000、5173 | 系统级连接不被拦截 |
| Windows 网络 | Public → Private | 允许局域网设备互访 |

### 三、团队协作最终方案

```
你（服务器）:  双击 启动工作台.bat → 看到 "Colleagues: http://192.168.1.6:8000" → 发 IP 给同事 → 最小化窗口干活
同事（台式机）: 浏览器打开 http://192.168.1.6:8000 → 跟上网一样，零安装
收工:          关掉黑窗口即停止服务
```

### 四、v8 对标卡片模式（Bench Card）

| 项目 | 内容 |
|------|------|
| 背景 | 深藏青 `#0A162C` 满屏铺底（比 card v7 更深沉） |
| 画幅 | 1080×1920（9:16 竖版） |
| 图片区 | 8:9 大图（1080×1214），几乎满宽，仅左右各留 1px |
| 标题 | 双色两行：行1 琥珀金 `#D4A843` 55px / 行2 暖白 `#E8DCC8` 46px，思源宋体 Heavy |
| 标语 | 哑光金小字，底部居中 |
| 字幕 | 半透明黑底白字，14 字自然断句 + AST 智能折行 |
| 技术 | 同 card v6 全局复合架构 —— 分镜循环只做纯画面 + Ken Burns，全局一次性 overlay/drawtext |

**新增函数**：`compose_final_video_card_bench()`、`_find_title_font()`、`_split_natural_phrases()`、`_count_cjk()`、`split_title_two_lines()`（LLM 调用）

**新增文件**：`fonts/XianKai_Title.otf` — 思源宋体 Heavy（项目内置，无需系统安装）

### 五、Fal.ai 内容审查规避系统

`image_service.py` 新增 70+ 敏感词映射表 `_CONTENT_SANITIZE_MAP`：
- 暴力/伤害类（碰高压电 → 遭遇意外、捅死 → 伤害、割腕 → 伤害自己 等）
- 性/裸露类（强奸 → 侵害、裸体 → 删除 等）
- 少儿安全类（虐待儿童 → 删除、拐卖 → 带走了 等）
- 自残类（跳楼 → 轻生、上吊 → 轻生 等）

`_sanitize_prompt()` 在生图请求前自动替换；全部替换后内容仍被拒时，`_build_generic_prompt()` 构建不引用原文的通用场景 prompt。

### 六、前端"直接导入"模式

`POST /api/tasks/import-rewritten` — 用户在其他平台（如网页版 DeepSeek）手工改好文案后，直接粘贴回来：
- 跳过 Step 02（AI 清洗/改写）
- 自动填充标题、赛道模式
- 灌入 `rewritten_transcript` → 直接进入配音/生图/合成

### 七、LLM Prompt 外部化

System/user prompts 从 `llm_service.py` 内联字符串迁移到 `backend/prompts/*.txt`：
- `rewrite_system.txt` — 改写 System Prompt（市井烟火气对抗型洗稿）
- `rewrite_user.txt` — 改写 User Prompt（三段去重逻辑）
- `rewrite_research.txt` — 研究模式 prompt
- `image_context.txt` — 配图视觉档案提取 prompt

便于非开发人员直接修改 prompt 而无需接触代码。

### 八、数据模型新增字段

`tasks` 表新增 `visual_context TEXT` — 配图视觉档案（LLM 提取的主角外貌、年龄、场景特征），供所有分镜共用，确保人物一致性。

---

## 2026-07-11 最终成果

### 一、音画脱节 Bug 修复（四层防御）

**故障现象**：task 53 card 风格成片严重音画脱节——声音播放开头文案，画面渲染最后配图。

**根因链**：Fal.ai API 1080÷16 非整数 → 向下取整为 1072 → seg_000~008 保存为 1072×1920 → `create_card_clip` 硬编码 `crop=1080` 失败 → 输出 0 字节空文件 → concat 只剩 seg_9~11 → 混入完整音频 → 错位。

**四层修复**：

| 层级 | 文件 | 修复 |
|------|------|------|
| API 请求 | `image_service.py:_generate_fal` | 请求尺寸自动对齐 16 倍数 |
| 九宫格落盘 | `image_service.py:generate_all_images` | PIL 校验尺寸，不符则 resize |
| 单图落盘 | `image_service.py:regenerate_single_image` | 下载后 PIL resize 到精确 1080×1920 |
| 视频合成 | `video_service.py:create_card_clip` | 读取实际图片尺寸，非标准时预缩放 |
| 同步保护 | `video_service.py` 三处 compose 函数 | 片段失败时注入等长静音占位片段 |

### 二、图片清晰度提升（4K 超采样）

**`regenerate_single_image` 单图重生**：API 请求尺寸从 1088×1920 → **2160×3840**（4K 竖版，8.29MP 恰好卡 Fal.ai API 上限），落盘时 PIL LANCZOS 缩到 1080×1920。4× 超采样，成本不变，清晰度显著提升。

### 三、Card v6 骨肉分离架构重构

**问题**：旧架构每个分镜都重复渲染三段式外壳（crop→pad→页眉drawtext→页脚drawtext），N 个分镜 = N 次全帧 1080×1920 H.264 编码。

**新架构**：分镜只做纯画面 1080×608 + Ken Burns，页眉/页脚/字幕在最终一次 FFmpeg `filter_complex` 中全局完成。

```
分镜循环: create_card_pure_clip() → 1080×608 纯画面 × N
  scale=1080:608:increase → crop → 2x prescale → zoompan

全局复合 (仅 1 次 FFmpeg):
  color=c=black:s=1080x1920 (内存黑底，零 I/O)
  overlay=0:656 (中部视频居中)
  drawtext 书名/作者/声明/词级字幕 (全局累计时间戳)
```

**改动**：仅 `video_service.py`（新增 2 函数 ~270 行）+ `main.py`（改 1 行调用）。零 PIL，零 image_service.py 改动，旧函数全部保留。

### 新增/修改文件

| 文件 | 内容 |
|------|------|
| `backend/services/video_service.py` | +`create_card_pure_clip`、+`compose_final_video_card_v6`、+`create_silent_placeholder_clip`、`create_card_clip` 图片尺寸自适应、三处 compose A/V 同步保护 |
| `backend/services/image_service.py` | `_generate_fal` 16 倍数对齐、`generate_all_images` 九宫格尺寸校验、`regenerate_single_image` 4K 超采样 + resize |
| `backend/main.py` | card 模式切换到 v6 |

## 明天计划（2026-07-12）

> 见上，略。

---

## 2026-07-14 成果

### 一、九宫格全线废弃 → 单图直生架构（v4）

彻底推翻大佬极度控本策略，全面切换"品质第一，单图直生"：
- `image_service.py` 大幅重构：删除 `build_grid_user_prompt`、`generate_grid_image`、`slice_grid_3x3` 全部九宫格函数，删除 4 个废弃常量
- 新增 `build_single_segment_prompt` 单句配图 Prompt 构建器
- `generate_all_images` 重写：`for grid in 7 grids` → `for each of 63 sentences`，每段独立 Fal.ai 请求
- 新增 `STYLE_PROMPT_MAP`（4 风格后缀映射）+ `SAFETY_SUFFIX` 画面安全补丁

### 二、前端生图实时轮询

`handleGenerateImages` 从 `await fetch` 改为 `fetch().then()` fire-and-forget + `setInterval` 每 2 秒轮询。图片逐张浮现，操作者可即时审查、不满意立刻手动重跑。不改后端。

### 三、Card v6 批处理修复

**Bug 1**：`WinError 206` 文件名过长（320 drawtext × 500 字符 = 93,000 字符 > 32,767 Windows 命令行上限）→ 改用 `-filter_complex_script` 从文件读取滤镜链。

**Bug 2**：303s 超时 → 全局 filter_complex 改为分批处理：每 12 句一批，6 批独立 overlay + drawtext → concat。

---

## 2026-07-15 成果

### 一、文案改写提示词全面升级 + 爆款标题生成

`llm_service.py` 提示词经多次迭代：
- **v1**："像素级微调，最大化复刻"（旧）
- **v2**："通用对抗型像素洗稿技术" — 因果翻转、排比打碎、词群洗牌
- **v3**（最终）："市井烟火气对抗型洗稿技术" — 民间拉家常口吻、深度质感词汇、三大去重逻辑

**System Prompt 新增第 4 条死律**：「爆款标题生成规则」
- 15-25 字，二选一杯公式（极限反差 / 数字具象化）
- **数字红线**：标题用阿拉伯数字（10岁）、正文用中文汉字（十岁）
- 输出格式：`{"title":"...","rewritten_transcript":"..."}` 纯 JSON

**`rewrite_script` 函数签名变更**：`-> str` → `-> dict`，启用 `response_format={"type": "json_object"}`，自动清理 markdown 围栏，解析失败兜底纯文本。

### 二、TTS 配音工作台极简重构

**删除**：参考音频上传组件、克隆音色按钮、音色库标签页、音色库弹窗 modal、8 个废弃 API 路由、8 个废弃 Pydantic 模型（backend −408 行代码）。

**3 黄金音色**：仅保留 `爽快思思` / `克隆女声` / `王立群`，后端路由：
```python
vc_shuangsisi   → volc_tts_v3_service.synthesize()         # 火山标准
vc_clone_female → siliconflow_tts_service.synthesize()     # SiliconFlow clone
vc_clone_wanglq → volc_tts_v3_service.synthesize_clone()   # S_zT84tud82
```

**🔊 试听**：3 个真实 TTS 样本（`public/audio/`），前端按钮播放。

**Bug 修复**：`tts_service.py`、`volc_tts_v3_service.py`、`siliconflow_tts_service.py` 补了 `load_dotenv()`，修复独立脚本调用时 API Key 为空。

### 三、赛道模式 + 多画幅

**`models.py` 新字段**：`video_title`、`content_mode`（"book" / "general"）。

**前端**："📚 书籍信息识别" → "🎬 画面顶部文案识别与填充"。图书赛道显示书名/作者，百货赛道仅显示爆款标题输入框。AI 改写后自动灌装标题。页面恢复时完整还原。

**生图画幅**：16:9 / 3:4 / 9:16 三选一 Radio Group + 🎬 导演指南动态组件。

### 四、视频合成 v7：暗夜海军蓝 + 标语模板化

| 改动 | 说明 |
|------|------|
| 背景色 | `black` → `#0A162C`（暗夜海军蓝） |
| 标语 | 哑光金 `#CBA052` · 楷体 50px · 可编辑输入框 |
| 免责小字 | 浅灰 `#666666` · 26px · 支持 `\n` 折行 · 可编辑输入框 |
| 3:4 画幅 | 中部 720×960，左右 180px 海军蓝边框自然形成 |
| 风格精简 | 仅保留经典图书三段式 (16:9) + 黄金遮罩三段式 (3:4) |

**删除**：旧风格下拉、作者/书名/声明模板输入、黑底大字版/卡片 checkbox、typewriter 分轨。−9 个 TS 错误。

### 五、工程基础设施

| 项 | 内容 |
|---|---|
| `load_dotenv()` | 补全到 3 个 TTS service 文件，消除独立调用时的 API Key 空值 |
| DB 迁移 | `tasks` 表新增 `video_title` (TEXT) + `content_mode` (TEXT) |
| `.gitignore` | 新建，排除 .env / node_modules / data / __pycache__ |
| Git + GitHub | `git init` · 114 文件 · 1 commit · push 到私有仓库 `xiankai378/video-automation` |

### 六、前端累计删减

| 删除项 | 数量 |
|---|---|
| VOICE_OPTIONS | 21 个 → 3 个 |
| clone 相关 state | 7 个 |
| 废弃函数 | `handleCloneVoice`、`handleFileChange`、`handleOpenVoiceLibrary` 等 6 个 |
| 视频合成 state | `videoDisclaimer`、`disclaimerAuthor`、`enableTypewriter`、`enableCard` 等 9 个 |
| UI 组件 | 参考音频上传、克隆按钮、音色库、风格下拉、模板预览、多风格 checkbox |
