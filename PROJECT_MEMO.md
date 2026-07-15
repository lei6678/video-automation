# 项目备忘录

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

1. **播放验收 card v6 成片**：打开 task 53 的 `final_card_1080x1920.mp4`，确认三段式布局、Ken Burns 动效、词级字幕、音画同步全部正常
2. **高性能九宫格生图改造**（大佬建议）：九宫格 `CELL_ASPECT_RATIO` 改为 `9:16`，让 AI 直接在竖版格子内构图——避免 16:9→9:16 中心裁切损失 68% 像素。总图画布也需重新计算（3×3 个 9:16 格 → 竖版布局）
3. **如 card v6 验收通过**：对 task 54 跑完整流水线（文案导入→清洗→改写→TTS→生图→合成）检验全流程
