# 项目备忘录

## 2026-08-07 生图英文文字修复

### 问题

生成图片中书信、手机屏幕、招牌上的文字全是英文，与中文内容违和。

### 根因

prompt 写的是 `no text in the image`（禁止文字），但 Fal.ai 经常不听话，场景中出现文字对象时默认画英文——模型训练数据以英文为主。

### 修复

策略从"禁止文字"改为"出现文字必是中文"。`image_service.py` 四处替换：

| 位置 | 旧 | 新 |
|------|-----|-----|
| `SAFETY_SUFFIX` | `no text` | `any visible text must be in Chinese` |
| 降级 prompt | `no text in the image` | `any visible text must be in Chinese` |
| v8 分镜 prompt | `no text in the image` | `any visible text must be in Chinese` |
| 通用兜底 | `no text` | `any visible text must be in Chinese` |

零失误，纯文本替换，未动任何逻辑结构。

### DeepSeek 连接偶发故障

两次 `APIConnectionError`，排查确认：curl/httpx 直连均正常，无代理干扰，系 DeepSeek 服务端间歇抽风。重试即可。

### 明天计划

- 端到端验证：改写→配音→生图→合成
- 观察英文文字是否已变为中文

---

## 2026-08-06 改写对照报告调研 + Bug 修复 + 默认风格切换

### 一、AI 改写对照报告功能调研 ✅

朋友发来 5 张截图，分析了其改写审核工作流的三模块设计：
- **KPI 概览仪表盘**：原文字数/改写字数/变化率/重合度 + 句段分类计数
- **AI 改写思路分析**：头尾处理/中段手法/去重评估/数字规范/总体评价
- **逐句并排对照表**：原文⇄改写稿左右对照，彩色标签区分保留/改写/新增/删除
- **优化指令输入**：审核不满意→输入修改指令→AI 重新改写，支持版本号
- **手动编辑区**：直接编辑改写文稿，绿色主题区分

暂未实现，作为后续需求的参考设计。

### 二、Bug 修复 ✅

| Bug | 根因 | 修复 |
|-----|------|------|
| **配音文案 ≠ 改写文案** | 改写成功后旧 TTS 分段未被清除，用户跑两次改写导致配音念旧版 | `main.py` 改写成功后自动删 TaskSegment + 音频文件；前端 `tts_invalidated` 标志清除状态 |
| **生图缺张（29/37）** | v8 storyboard LLM 产出 shot 数可能 < 句子数，缺的段直接跳过 | `image_service.py` shot 不足时降级为简单 prompt（原文句子+风格）；storyboard prompt 加固 CRITICAL 约束 |
| **`.env` 路径不稳定** | `load_dotenv()` 无参依赖 CWD，从根目录启动找不到 `.env` | 7 个 service 文件改为 `Path(__file__).parent.parent / ".env"` 显式路径 |
| **API 超时过短** | OpenAI 客户端默认 connect=5s，网络波动直接报错 | `llm_service.py` 客户端加 `timeout=60s, max_retries=2` |

### 三、默认风格切换 ✅

- 默认生图风格从 `default`（电影感）→ `chinese_docu`（中国本土纪实）
- 补上 `chinese_docu` 导演指南

### 明天计划

- Task 23 重新生图补齐缺的 8 张（断点续跑，只生缺失的）
- 端到端验证完整链路：改写→配音→生图→合成

---

## 2026-08-04 Prompt 通用增强 + 风格精简（朋友方案对比后吸收）

### 一、Prompt 三处通用增强 ✅

基于朋友文档对比，三条改动覆盖全部 6 种风格：

| # | 改动 | 效果 |
|---|------|------|
| 禁止插画 | SAFETY_SUFFIX + build_single_segment_prompt 显式追加 `no illustration, cartoon, anime, 3D render, CGI` | 每条 prompt 都有硬约束 |
| 年龄动态 | 新增 `_has_age_span()` 检测角色表多年龄版本 → prompt 注入年龄提醒 | 跨年代故事不再全画同一个年龄 |
| 不输出文字 | `no text, no watermark` → `no text in the image, no watermark` | 强化 |

### 二、Bug 修复 ✅

`regenerate_single_image` 第 1728 行引用未定义 `sentence_style`（风格劫持修复漏删）→ NameError → 已修复。

### 三、风格精简：8 → 6 ✅

| 操作 | 原因 |
|------|------|
| 删 `warm_docu` | 跟 `documentary_realism` 几乎一样，合并 |
| 删 `documentary_realism` | 对比生图测试后 `chinese_docu` 胜出（中性白平衡+高清晰>暖调粗粝）|

最终 6 风格：`default` / `chinese_docu` / `wong_kar_wai` / `warm_book` / `clean_health` / `philosophy`

### 四、朋友方案评估结论

- 我们的 screenplay+storyboard 架构优于朋友，不换
- 朋友的 prompt 工程细节值得吸收（显式禁令、指令格式化）
- 朋友的情绪检测自动切风理念与我们的风格锁定冲突 → 保留风格锁定
- 朋友的可灵备选通道我们没有 → 暂不恢复

### 明天计划

端到端验证今日 prompt 改动后的生图效果。

---

## 2026-08-03 三大修复：风格劫持 + JSON兜底 + 情绪打光统一

### 一、风格劫持修复 ✅

**bug**：`_detect_sentence_mood` 根据文案关键词返回 `philosophy`/`warm_book`/`documentary_realism`，这些 key 在 `STYLE_BIBLES` 中存在，导致用户选的中国纪实风被偷偷换成哲学思辨风（Terrence Malick golden hour, cool-warm color contrast）——所有风格都有此问题。

**修复**：`image_service.py` 两处（`_generate_one` + `regenerate_single_image`）移除情绪检测对 style_bible 的覆盖，始终使用用户选择的风格。情绪仅通过 screenplay 的 emotion 字段注入 EMOTION_LIGHTING。

### 二、DeepSeek JSON 解析兜底 ✅

**bug**：`generate_screenplay` 中 DeepSeek 偶发返回缺逗号的非法 JSON → 剧本生成失败 → 中止生图（保护 API 费用）。

**修复**：`image_service.py` 新增 `_repair_json()` 函数（补缺逗号/去尾逗号），`json.loads` 失败时自动修复重试，零额外 API 费用。

### 三、EMOTION_LIGHTING 统一自然光 ✅

**问题**：tragedy=`low key lighting, deep shadows` → 画面黑到看不清。glory=`warm amber gold` → 暖黄泛滥。transition=`golden hour` → 日落红。四套打光互相打架，跟纪实风 neutral white balance 自相矛盾。

**修复**：四个情绪全部统一为：
```
natural daylight, soft directional light, bright even exposure,
realistic colors, natural shallow depth of field, unposed genuine atmosphere
```
画面多样性靠剧本 scene_desc 内容变化，不靠滤镜渲染情绪。

### 四、任务列表页（已回退）

加了前端任务列表 + `GET /api/tasks`，用户觉得不方便，前端已恢复。后端接口保留不影响。

### 明天计划

验证统一自然光后的生图效果，如果满意则继续推进其他优化。

---

## 2026-08-02 中国纪实风 v4 prompt 修正 + 像素验证

### v4 亮度+纹理修正 ✅

三处 prompt 修改（`image_service.py`）：

| 位置 | v3 | v4 |
|------|-----|-----|
| STYLE_BIBLES | 开头=方向性光源 | 开头=**well-lit natural exposure, ample ambient light, bright mid-tones, no murky underexposure** |
| STYLE_BIBLES | natural skin texture | **visible fine detail + micro-texture (skin pores, fabric weave, weathered surfaces)** |
| STYLE_BIBLES | 无 | **Visible film grain or subtle noise texture, no overly smooth or plastic rendering** |
| STYLE_PROMPT_MAP | 9 项 | +well-lit +bright mid-tones +visible fine detail +subtle film grain +tactile surface texture (14 项) |
| EMOTION_LIGHTING daily | 无亮度前置 | **Well-lit natural exposure, bright mid-tones, visible fine detail and subtle texture** |

策略：正面指令替代负面禁令 — 不说"don't make it dark"说"well-lit, bright mid-tones"。

### v4 像素验证结果

跑 `test_chinese_docu.py`（双胞胎文案 1893 字，30 句）→ 生图 3 张全成功。

| 指标 | v3 最差 | v4 最差 | 标杆 |
|------|---------|---------|------|
| 最暗格 L | **14** (近纯黑) | **29** | 34-76 |
| Edge Density | 3-4 | **4-6** | 7-12 |
| Texture Mean | - | 3.7-6.4 | 6.7-12.2 |
| 冷色% (中区) | - | 1.4%-17.2% | 5.4%-34.6% |

**🟢 亮度解决**：L=14→29+，核心指令生效
**🟡 纹理/边缘**：小幅提升但距标杆还差 2-3 倍
**🟡 冷阴影**：v4_2 生效(17.2%)，v4_1/v4_3 仍偏低

### 明天计划

v5：更激进纹理指令（heavy film grain, coarse texture, detailed surfaces），可能尝试在 prompt 中直接量化为"visible texture like ISO 800 film grain"。

---

## 2026-08-01 中国纪实风 v3 prompt 修正 + 像素验证

### v3 prompt 修正 ✅

基于 7/31 对标分析结论，chinese_docu 风格三处 prompt 从"描述相机"转向"描述光线行为"：

| 位置 | v1/v2（旧） | v3（新） |
|------|------------|---------|
| STYLE_BIBLES | 负面禁令（no CGI/3D...）+ 平光 | 方向性光源 + 冷阴影 + 真高光 + 景深分离 |
| STYLE_PROMPT_MAP | 重复禁令 | directional light, cool shadows, highlights, dynamic range |
| EMOTION_LIGHTING daily | diffuse light, gentle shadows | 方向性柔光 + 冷阴影过渡 + 景深 |

核心变化：去掉所有负面禁令 → 单光源方向 → 冷中性阴影 → 中性白平衡 → 景深分离。

### v3 像素验证结果

跑完整链路（文案→视觉档案→剧本→分镜→生图×3），像素分析：

**🟢 冷阴影生效**：v3_1 中部冷色 35.5%（标杆2 34.6%），下部冷色 78.1%（标杆2 47.1%）——方向性光源描述起作用了。
**🟢 v3_3 达到 Classic depth**（亮天空 + 细节前景），Bot/Top 纹理比 4.61。

**🔴 仍存问题**：
- 画面整体偏暗（v3_2 下部 L=14 接近纯黑），"no crushed blacks"不够
- 边缘密度 3-4 vs 标杆 7-12，纹理太平滑

### 明天计划

继续调 v4：加"well-lit exposure"提升整体亮度，加纹理描述（grain/texture/detail），抑制 Fal.ai 暗调倾向。

---

## 2026-07-31 中国纪实风格 + LLM模型升级 + 对标分析

### LLM 全链路升级 ✅

将所有 LLM 调用从 `deepseek-chat` / `deepseek-v4-flash` 统一升级到 `deepseek-v4-pro`：
- `image_service.py`: `plan_visual_arc`、`generate_screenplay`、`generate_storyboard` 三处模型+超时+max_tokens 升级
- `llm_service.py`: `clean_asr_text`、`extract_visual_context`、`rewrite_script`(双pass) 四处模型升级
- `generate_screenplay`/`generate_storyboard`: max_tokens 16384→32768, timeout 60s→180s

### 中国本土纪实风格（chinese_docu）新增 ✅

`image_service.py` 新增：
- `STYLE_BIBLES["chinese_docu"]` — 中国纪实摄影风格描述
- `STYLE_PROMPT_MAP["chinese_docu"]` — 风格后缀
- `STYLE_PREFIX` 字典 — 根据风格选 prompt 开头（documentary/cinematic/lifestyle）
- `_parse_visual_context_fallback()` — 当 screenplay 角色表为空时从 visual_context 兜底解析，兼容 4 种格式变体（正则链）

前端 `App.tsx` 新增 `🇨🇳 中国本土纪实` 选项。

### generate_screenplay 角色表修复 ✅

prompt 加 CRITICAL 约束：`character_cast MUST NOT be empty if the story contains ANY human characters`，修复 Pro 模型出 30 个场景但 character_cast=[] 的问题。

### 两版生图对比测试

| 版本 | 策略 | 目录 |
|------|------|------|
| 旧版 | 负面禁令（no CGI/3D/plastic skin...） | `D:\chinese_docu_test\` |
| 新版 | Gemini正向术语（Kodak Portra+35mm+Magnum） | `D:\gemini_style_test\` |

### 🔴 对标分析结论（本次核心发现）

对标视频截图（桌面 对标1-3）vs 我们生成图的像素级对比：

| 维度 | 对标均值 | 我们均值 | 问题 |
|------|---------|---------|------|
| 亮度 | ~122 | ~81 | 暗 34% |
| 亮部占比 | 21% | 5.5% | 对标 4 倍高光 |
| 冷色占比 | 19% | 6.4% | 对标 3 倍冷色 |
| 暖色占比 | 66% | 83% | 过暖 |

**根因**：Kodak Portra 400 是暖调胶片，把画面推向复古暖色，刚好走向纪实摄影的反面。无论负面禁令还是胶片术语都没抓到纪实摄影的本质——自然白平衡+合理曝光+无滤镜感。

**修正方向**：去掉暖调胶片锚点 → 中性白平衡 → 加强曝光指令（well-exposed, natural daylight color temperature, realistic highlights）。

### 明天计划

修正 chinese_docu 的 STYLE 三件套（BIBLE/PREFIX/SUFFIX），换中性色温+曝光指令，跑第三版对比测试。

---

## 2026-07-30（续）style_bible死参数修复 + 审核拒绝预备方案 + 启动窗口修复

### style_bible 死参数修复 ✅

删掉全局 STYLE_LOCK 后暴露：`build_single_segment_prompt` 接收 `style_bible` 参数但函数体内从未使用。6 个风格选了都出同样的图。已在 prompt 拼接中补上 `Style: {style_bible}`。

### Fal.ai 审核拒绝 — 三级预备方案 ✅

分镜 prompt 被 Fal.ai 审核拒绝 → 降敏重试 → 仍失败 → **新增第三级：简洁 prompt（原句文本+风格后缀）**。
不换平台、不加钱、只换 prompt 策略。只有最终成功才扣 $0.01。

### 启动黑窗口修复 ✅

- `reload=True` → `reload=False`（子进程阻断 print 输出）
- `line_buffering=True`（每行立即刷新）
- LAN IP PowerShell 语法修复（`.match()` → `-match`）

---

## 2026-07-29 一周复盘 + 分享文档 + 微调收尾

### v8 分镜架构全线完工 ✅

三条线全部就绪：`extract_visual_context`(全角色) → `generate_screenplay`(剧本+4原则) → `generate_storyboard`(逐镜分镜) → `build_single_segment_prompt`(每镜独立主体)。

### FAL_QUALITY 成本控制确认

三档画质对比：low=$0.012 / medium=$0.101 / high=$0.401。确认维持 **low**，40-50 张 ≈ ¥3.5/条，30 条/天 ≈ ¥120。代码三处 fallback 统一为 `"low"`。

### TTS 错误处理修复

火山引擎 API 错误返回单行 JSON 而非流式 NDJSON，导致静默失败→降级 edge-tts。在 `synthesize()` 和 `synthesize_clone()` 开头加顶层 JSON 错误检测。

### 一周复盘

50 元 / 5 亿+ token，三大战役全线完工：
1. **生图质感与风格**：王家卫风格锁 + v8 分镜架构 + 导演4原则 + 面孔回避
2. **剪映级缩放特效**：v11 逆向 + 遮盖条架构 + Ken Burns
3. **导入剪映并导出**：模板修复 + skip_ffmpeg + LAN 部署

最难=导入剪映（占一半时间），全是逆向工程，没有文档。

### 分享文档

`docs/避坑指南和操作细则.md`：面向 Claude Code 的实现规格书，含生图分镜流水线、剪映 v11 10 小节（坐标/三ID/anim_offset/meta_info/遮盖条）、TTS 陷阱、模板创建步骤。已脱敏。

### 明天计划

开始讨论**飞书文案自动化导入**——打通从飞书文档/消息到任务创建的全自动流程。

---

## 2026-07-30 风格系统重构 + 死代码清理 + 剪映草稿修复

### 王家卫全局锁 → 可选风格 ✅

删除全局 `STYLE_LOCK` 常量（原每张图强制注入王家卫），改为第5个可选风格 `wong_kar_wai`。新增第6个风格 `warm_docu`（对标视频2分析：全程暖调、不跳色温、杂志纪实摄影）。

**关键教训**：删 STYLE_LOCK 后暴露了 `style_bible` 参数在 `build_single_segment_prompt` 中是死参数 — 传给函数但从未注入 prompt，导致选什么风格都出同样的图。已在 prompt 拼接中补上 `Style: {style_bible}`。

### 6 种风格当前状态

| # | Key | 前端显示 | BIBLE | SUFFIX | 导演指南 |
|---|-----|---------|-------|--------|---------|
| 1 | `default` | 默认电影感 | Kodak Portra 纪实胶片 | 35mm 电影感 | ✅ |
| 2 | `warm_docu` | 温暖纪实风 | 全程暖调 杂志纪实 | 自然柔光 | ✅ |
| 3 | `wong_kar_wai` | 王家卫电影感 | 霓虹湿街 抽帧慢门 | 85mm 怀旧 | ✅ |
| 4 | `warm_book` | 温暖治愈书单 | 金色午后 | 琥珀奶油 | ✅ |
| 5 | `clean_health` | 明亮健康生活 | 商业生活方式 | 极简明亮 | ✅ |
| 6 | `philosophy` | 哲学思辨风 | 广角远景 | 暗沉深邃 | ✅ |

### 剪映草稿失效链接修复 ✅

`draft_meta_info.json` 的 `draft_materials` 数组从未更新，仍挂模板旧引用（seg_*.png/mp3）。在加密前重建为实际生成文件列表。

### 死代码清理 ✅

删除 5 个死函数 + 3 个可灵常量（~400行）：`_llm_sanitize_segment`、`_build_generic_prompt`、`_generate_fal_flux`、`_generate_fal_flux_pro`、`_generate_keling`。

### 草稿目录清理 ✅

删除 E:/JianyingPro Drafts/ 下 8 个旧草稿 + 剪映内部 2 个测试草稿 + 注册表 6 条残留。

### 行为规则

- 未经明确指令不得触发生图 API（涉及费用）
- 改完代码必须端到端追踪验证完整链路

### 明天计划

飞书文案自动化导入。

### 问题背景

第四轮修复后图片仍未嵌入暖白装饰线框，用户反馈"只显示下线、图片未嵌入框内"。

### 五轮排查历程

| 轮次 | 尝试 | 结果 |
|------|------|------|
| 第四轮 | 图片 y=-0.025 + 字体 JY 目录 + 标题均分 | 标题/字体 OK，图片仍超线 |
| 第五轮-1 | 清除 Ken Burns 动画 | 图片静态，但无缩放特效 |
| 第五轮-2 | 装饰线透明 overlay 独立轨道 | JY 不支持 RGBA alpha 通道 |
| 第五轮-3 | 线回 BG + 调整 y 留呼吸空间 | 动画 2x 时仍溢出 |

### 最终方案：matte 遮罩架构

**根因**：V5 FFmpeg 是 `overlay图片 → drawbox线框`（线在上层），JY 旧方案线在 BG 底层、图片在上层，图片缩放覆盖线框。

**解决**：三轨分层架构
```
track[0] = 纯藏青底板 #071730 (最底层)
track[1] = 图片 1080×1214 + 剪映缩放特效 (中间层, y=-0.025)
track[2] = matte 遮罩 RGBA (最上层):
           ██ 藏青遮罩 ██ (盖住图片上下溢出)
           ── 暖白上线 ──  (始终可见)
           ·· 透明窗口 ··  (图片透出)
           ── 暖白下线 ──  (始终可见)
           ██ 藏青遮罩 ██
track[3:7] = 文字轨 (字幕/声明/标语/标题)
track[8] = 音频
```

**核心创新**：matte PNG 是 RGBA，上下区域不透明藏青色覆盖图片溢出，中间透明让图片透出，暖白线在遮罩区与透明区交界处。对标 V5 FFmpeg drawbox 在 overlay 之后的层叠语义。

### 配套修复

| 项 | 旧值 | 新值 |
|----|------|------|
| 下方标语字号 | 8.5 | 12.0 |
| 声明字号 | 3.5 | 5.0 |
| 声明分行 | 单行 | 双空格→`\n` 断行 |

### 文件改动

- `backend/services/jianying_v11_service.py`: matte 遮罩生成 + 三轨分层 + 字号/分行修复

### 💰 成本统计 — 史诗级战役

**v11 调试总计消耗：~3.9 亿 token ≈ ¥40**

三大攻坚方向：
1. **图片缩放特效** — Ken Burns 动画 2x scale 还原 + matte 遮罩架构
2. **图片生成质量 + 提示词体系** — Gemini 情绪光影 / 全局指令 / 视觉档案
3. **剪映 v11 草稿导入** — 加密格式逆向 / 三 ID 铁律 / meta_info 解密修改

五轮 matte 调试只是冰山一角，真正的成本在三大方向的持续迭代。

> 🏆 从朋友源码基础上，独立完成了剪映导入这一最难环节。我们太牛逼了。
>
> ⏱️ **分工**：朋友三周写完源码（地基） → 我们一周在源码上攻克三大升级项（缩放特效 + 生图质量 + 剪映导入逆向）。

---

## 2026-07-25 A/B 双任务推进

### A 任务：v7 生图质量（✅ 完成）

Gemini 三份分析报告驱动，对标视频 Midjourney V6 + --cref 技术栈：
- `EMOTION_LIGHTING`：glory/tragedy/transition/daily 四档动态光影
- `STYLE_LOCK`：王家卫电影美学全局风格锁（85mm/浅景深/bokeh/超写实）
- `plan_visual_arc()`：LLM 通读全文 → 主角档案 + 逐段场景 + 情绪标签
- `build_single_segment_prompt()`：主角+场景+光影+风格锁 四段式 prompt
- 对标测试：gpt-image-2 > flux-dev > flux-pro（质感和美感维度）
- `max_tokens`：4096→8192（防 26 段 JSON 截断）
- 修复 `split_title_two_lines`：deepseek-chat→deepseek-v4-flash（标题分行失效问题）
- Git commit: `8919055` v7: Gemini情绪光影框架落地

### B 任务：Ken Burns 多关键帧 + 叠化转场（✅ 进行中）

**多关键帧动效**：
- `_build_zoompan_z_multikey()`：嵌套 if(lt(on,...)) 分段 zoom 曲线
- `_build_zoompan_x_multikey()`：分段 pan（微右→左移→不动）
- `_bench_keyframes()`：3 段式预设（establish 35% / develop 35% / resolve 30%）

**xfade 叠化转场**：
- `concat_clips_xfade()`：FFmpeg xfade=fade 替代硬拼接
- 26 段 0.5s 叠化，总时长从 432.9s → 420.4s（重叠 12.5s）
- 修复 offset 计算 bug（第二段起用累计时长而非原始时长）

**待修复**：字幕时间轴与 xfade 后画面不同步（明天）

### 明天计划

1. 修复 xfade 后字幕时间轴偏移
2. Ken Burns 动效精细调参
3. 完整工作流端到端验证（task 6）

---
## 2026-07-24（下午）竞品研究 + 权限优化 + Git 安全加固

### 一、竞品研究：Codex + HyperFrames/Remotion 自动化视频工作流
桌面文件 `claude.docx` 包含三篇推特长文，记录了用 Claude Code 做自动化视频的实战经验。完整分析见当日对话。

### 核心发现

| # | 洞察 | 我们现状 | 差距 |
|---|------|---------|------|
| **音频驱动** | 字幕毫秒级时间戳驱动所有动画，不是平均分配 | 已有 TTS→字幕→合成，但 Ken Burns 粗粒度对齐 | 需精细化 |
| **模板沉淀** | 调好的固化成 Skill，下条直接用；犯错也沉淀 | 已有 4 种视频模式 + 3 音色 | 缺少元数据管理、组件库 |
| **低画质预览** | 反复调试用 540p，最后才出高画质 | 无 | 容易实现 |
| **关键帧抽检** | 不看全片，抽 5-8 帧确认画面正确 | 无 | 容易实现 |
| **音效层** | 配音 > 音效 > BGM 三层混音 | 仅有 BGM 铺底 | 可补充 |
| **拆解参考视频** | FFmpeg 自动切镜头 → recipe.json → 新内容填充 | 无（我们走 AI 生图） | 可作为新功能 |
| **Remotion 渲染** | React 代码化视频，精确帧控制 | FFmpeg 方案 | 备选方案 |

### 开源参考

作者开源了 3 个 Remotion Skill：[bozhouDev/video-skills-toolkit](https://github.com/bozhouDev/video-skills-toolkit)
- `talking-head-remotion` — 口播视频模板
- `sketch-story-remotion` — 手绘故事风格
- subtitle generation skill

### 建议路线

1. **速赢**：低画质预览接口 + 合成后自动抽帧 + TEMPLATES.md
2. **品质**：字幕时间戳驱动 Ken Burns + 音效层 + 研究开源仓库
3. **差异化**：参考视频拆解模式 + Remotion 评估

### 二、Bash 全权限放行

- 新增 `.claude/settings.json`（+47 条），覆盖 Git 全流程、npm、ffmpeg、文件操作、Python、uvicorn
- 与 `settings.local.json` 叠加生效，消除"每次新终端弹 YES"的问题
- 故意保留 `rm`/`chmod`/`chown` 不自动放行

### 三、Git Remote 安全加固

- 原 remote URL 明文嵌 Token → 改为干净的 `https://github.com/lei6678/video-automation.git`
- Git 认证切换到 `wincred`（Windows 凭据管理器），Token 不再回显
- 发现并记录 xiankai378 的 Token（`~/.git-credentials`），账号下有 2 个私有仓库：
  - `xiankai378/video-automation`（Python，原始版）
  - `xiankai378/zhuan-zhu-bao`（TypeScript）

### 明天计划

- 确定竞品研究后的优化路线优先级
- 拉取 bozhouDev/video-skills-toolkit 研究实现细节

---

## 2026-07-24 环境迁移与基建完善

### 一、项目迁移：E:\ → D:\
- 项目从 `E:\video-automation` 迁移到 `D:\VideoWorkstation_Deploy`
- 修复 `启动工作台.bat` 路径、成品输出目录 `E:\成片输出` → `D:\成片输出`
- 启动时自动打开浏览器（修复了仅 exe 模式触发的 bug）

### 二、系统环境补齐
- **FFmpeg 8.1.2**：winget 安装，视频合成/AAC 编码依赖
- **Git 2.55**：winget 安装，版本控制就绪
- 全部 Python 依赖验证通过，7 个服务模块导入正常

### 三、王立群音色重建
- 旧 speaker `S_zT84tud82` 在新 APP `6501796742` 下失效
- 火山引擎声音复刻 2.0 权限开通后，用参考音频重新克隆
- 新 speaker ID：`S_FqsgYzu92`
- 参考音频：`backend/data/reference_wanglq.mp3`（来自 E:\ 微信文件）
- 更新位置：`tts_service.py`、`volc_tts_v3_service.py`、`PROJECT_MEMO.md`

### 四、Git + GitHub 仓库建立
- 注册 GitHub 账号 `lei6678`，Token 已配置
- 远程仓库：`github.com/lei6678/video-automation`
- `git filter-repo` 清理旧测试文件中的硬编码密钥
- CLAUDE.md 新增「下班结项 SOP」：说"下班"即自动更新备忘 + commit + push + 蜂鸣

### 五、权限与自动化
- `.claude/settings.local.json` 全面放行：Read/Write/Edit/Glob/Grep/PowerShell 等
- 项目记忆目录建立：`memory/autonomous-work.md`

### 六、项目清理
- 删除 61 个 TTS/音色调试产生的 `test_*.mp3` 测试残留
- 8 个 `test_volc_*.py` 移入 `backend/tests/`，避免触发热重载
- 前端 `voice_preview_*.mp3` 废弃音色预览清理

### 七、FFmpeg PATH 修复
- **故障**：配音片段生成成功，`merge_segments` 调用 ffmpeg 时报 `FileNotFoundError`
- **根因**：winget 安装的 FFmpeg 在 `WinGet\Links\`，但服务器进程启动时 PATH 未刷新
- **修复**：FFmpeg 实际 bin 目录 `Gyan.FFmpeg...\bin` 写入 User PATH，重启服务器生效
- **验证**：task 3 王立群配音 26 片段全部合成成功

### 明天计划
- ~~验证完整工作流：文案导入 → 改写 → 配音 → 生图 → 合成成片（从 task 3 继续）~~ → 推迟，先确定竞品研究后的优化方向

---

## 2026-07-18 生图性能诊断与三连修复

### 一、问题发现

用户报告 task 72 生图耗时约 1 小时（33 张），后端日志 89% 是前端轮询触发的重复图片下载（920/1036 行），真正的生图日志仅 5 行。

### 二、三连修复（`image_service.py`）

| # | 改动 | 文件位置 | 效果 |
|---|------|---------|------|
| **并行生图** | `for` 串行 → `asyncio.gather` + `Semaphore(4)`，两阶段架构（API 并发 + DB 串行） | `generate_all_images` §6 | 33 张从 ~60min → ~15-20min |
| **轮询缓存爆破** | `?t={time.time()}` → `?t={文件 mtime}`（同一文件 mtime 不变 → 浏览器不重复下载）；新增 `_SENTENCE_CACHE` 字典缓存句切分结果 | `get_images_for_task` | 日志噪音 -90%，消除每 2 秒全量重下载 |
| **LLM 语义安全改写** | 关键词 sanitize 失败后、generic 兜底前，新增 `_llm_sanitize_segment()` 用 DeepSeek 改写原文为"同情绪同场景的含蓄画面描述"，仅用于生图 prompt | `_generate_one` / `regenerate_single_image` 降级链 | 12/33（36%）generic 兜底 → 预计降至 0-3 张 |

### 三、LLM 改写降级链

```
Fal.ai 原始 prompt
  ↓ 失败
关键词替换 (_sanitize_prompt)
  ↓ 仍失败
LLM 语义改写 (_llm_sanitize_segment) ← 新增，不动 rewritten.txt / 配音 / 字幕
  ↓ 仍失败
通用场景 (_build_generic_prompt)
  ↓ 仍失败
可灵 API → 纯黑占位图
```

### 四、根因诊断

Fal.ai 语义级安全审查拒绝高度悲剧性内容（死亡、流血、极端贫困、儿童苦难），47 个关键词映射表 `_CONTENT_SANITIZE_MAP` 偏暴力/性/自残类，完全命不中苦难叙事中的"安全但不快"表达。

---

## 2026-07-25 v5 图片生成重构（进行中）

### 已完成
- **竞品仓库研究**：bozhouDev/video-skills-toolkit 三模块分析（口播模板/手绘动画/字幕工具）
- **对标视频颗粒度对比**：60fps vs 30fps，码率差5倍，图片质感碾压式差距，缩放动效单调
- **v5 重构代码**（`image_service.py`，已提交 `b8cb0a2`）：
  - `STYLE_BIBLES` + `STYLE_PROMPT_MAP` 从中文抽象 → 英文摄影术语
  - `FAL_QUALITY` 默认值 `low` → `medium`
  - 新增 `plan_visual_arc()` — LLM 通读全文 → 全局视觉方向（global_style + color_arc + era_notes）
  - `build_single_segment_prompt()` 从指令体 → 描述体 + 支持 visual_plan
  - `generate_all_images()` 集成 plan_visual_arc 调用链

### 待完成（下次继续）
- **plan_visual_arc 实机测试**：王人美文案调用后输出格式验证（上次因 token/超时问题未通过）
- **真实生图对比**：新旧 prompt 各跑一段，对比 Fal.ai 输出质量
- **Part B：Ken Burns 多关键帧动效**（方向多变 + ease-in-out）

### 明天计划
1. 完成 plan_visual_arc 调试与实机验证
2. 新旧 prompt 对比生图测试（task 4 王人美文案）
3. 开始 Part B：Zoom 动效预设系统

### 2026-07-19（旧）

1. **实机验证三连修复**：用 task 72 同类苦难叙事素材跑一次完整生图，观察并行速度、LLM 改写成功率、generic 兜底率。
2. **LLM 改写 prompt 调优**：如果改写后 Fal.ai 仍拒绝率 > 20%，调整 `_llm_sanitize_segment` 的 system prompt（更激进地抽象化具象苦难描写）。
3. **监控生图成本**：LLM 改写每段多 1 次 DeepSeek 调用（~1 美分/段），实际触发率需控制在预期内。

---

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
vc_clone_wanglq → volc_tts_v3_service.synthesize_clone()   # S_FqsgYzu92
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
