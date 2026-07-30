"""
剪映 v11 草稿导出服务（线框嵌入版 — 暖白线框预复合到图片上）
基于 7月27日模板 克隆 + 增量追加策略

轨道布局 (v2 — 无 BG/无 matte, 线框已画在图上):
  track[0] = video    — 图片 (1080×1920 全画布, 藏青底+暖白线框+图, y=0)
  track[1] = text     — 字幕 (自然断句, 思源宋体, y=-0.32)
  track[2] = text     — 声明/免责 (y=-0.85)
  track[3] = text     — 标语 (行楷, y=-0.72)
  track[4] = text     — 标题第二行-金色 (y=+0.73)
  track[5] = text     — 标题第一行-白色 (仅标题拆分, y=+0.844)
  track[6] = audio    — 配音

标题拆分 (对标 V5 _split_title_local):
  策略1: 全文找逗号/冒号/分号 → 语义断点
  策略2: 中点 ±1/4 范围找标点
  策略3: 无标点 → 按 CJK 字符数均分 (上白下金)

关键规则 (30+ 轮隔离测试验证):
  1. 三ID必须一致: dc.id == project.json.id == Timelines/<dirname>
  2. draft_meta_info.json 必须解密→改值→重加密
  3. IN-PLACE 修改 + APPEND，不可整数组替换
  4. 字体必须位于剪映 Resources/Font/ 目录内方可被加载
  5. 图片已预复合为 1080×1920 全画布 (含藏青底+暖白线框)，transform.y=0 居中
"""
import json, os, uuid, subprocess, shutil, time, copy
from typing import List, Optional

# ======== 字体辅助函数 ========
def _find_project_font(font_name: str) -> str:
    """查找项目 fonts/ 目录下的字体，返回原始路径"""
    import _resource
    root = _resource.get_project_root()
    path = os.path.join(root, "fonts", font_name)
    if os.path.exists(path):
        return path.replace("\\", "/")
    return ""

def _find_system_font() -> str:
    """系统可用中文字体"""
    for p in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttf",
              "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc"]:
        if os.path.exists(p):
            return p.replace("\\", "/")
    return "C:/Windows/Fonts/msyh.ttc"

# ======== 配置 ========
JY_INSTALL_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
SYSTEM_FONT_PATH = JY_INSTALL_DIR + "/Resources/Font/SystemFont/zh-hans.ttf"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
TEMPLATE_DIR = r"E:/360Downloads/JianyingPro Drafts/Template_v11_6T"
REGISTRY_PATH = r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json"

# ======== 字体 (对标 V5 bench: subtitle也用思源宋体, slogan用行楷) ========
JY_FONT_DIR = JY_INSTALL_DIR + "/Resources/Font"

def _find_jy_font(font_name: str) -> str:
    """查找字体：优先 JY 字体目录（剪映可加载），其次项目 fonts/"""
    jy_path = os.path.join(JY_FONT_DIR, font_name)
    if os.path.exists(jy_path):
        return jy_path.replace("\\", "/")
    proj_path = _find_project_font(font_name)
    if proj_path:
        return proj_path
    return SYSTEM_FONT_PATH

FONT_TITLE    = _find_jy_font("XianKai_Title.otf")  # 标题+字幕: 思源宋体 Heavy
FONT_SLOGAN   = _find_jy_font("Slogan_Xingkai.ttf")  # 标语: 钟齐志莽行书
FONT_SUBTITLE = FONT_TITLE                            # 字幕: 思源宋体 (同V5 bench)
FONT_DISC     = FONT_TITLE                            # 声明: 思源宋体 (同V5 bench)

# ======== 颜色常量 (对标 bench 模式 #071730 藏青底) ========
# 格式: [R, G, B] 0.0-1.0
CLR_BG        = [0.027, 0.09, 0.188]   # #071730 藏青底板
CLR_WHITE     = [0.984, 0.984, 0.969]  # #FBFBF7 标题白
CLR_GOLD      = [0.788, 0.702, 0.549]  # #C9B38C 标题金
CLR_SLOGAN    = [0.843, 0.675, 0.392]  # #D7AC64 暖琥珀金标语（对标截图校准）
CLR_SUB       = [0.996, 0.996, 0.988]  # #FEFEFC 口播字幕白
CLR_DISC      = [0.129, 0.173, 0.251]  # #212C40 免责声明低对比灰
CLR_BLACK     = [0.0, 0.0, 0.0]        # 字幕描边
CLR_LINE      = [0.910, 0.894, 0.831]  # #E8E4D4 装饰线暖白

# ======== 轨道索引 (v4: 遮盖条架构 - 3视频轨 + 4文字轨 + 1音频 = 8轨) ========
# 模板写死索引: track[0]=video, [1]=sub, [2]=disc, [3]=slogan, [4]=title, [5]=audio
TRACK_VIDEO = 0           # 图片 (1080x1214, y=377, Ken Burns later)
TRACK_COVER_TOP = 1       # 上遮盖条 (1080x377, 藏青+暖白下线, y=+0.804)
TRACK_COVER_BOT = 2       # 下遮盖条 (1080x329, 暖白上线+藏青, y=-0.829)
TRACK_SUBTITLE = 3        # y≈-0.32  字幕 (思源宋体)
TRACK_DISC = 4            # y≈-0.85  免责声明
TRACK_SLOGAN = 5          # y≈-0.72  标语 (行楷)
TRACK_TITLE = 6           # y≈+0.73  标题第二行-金色
# TRACK_TITLE_LINE1 = 7   # 标题第一行-白色 (动态插入, 位于 audio 之前)
TRACK_AUDIO = 7           # 配音 (插入 title_line1 后变为 index 8)

# ======== ref 顺序 (严格匹配) ========
VIDEO_REF_TYPES = [
    "speeds", "placeholder_infos", "canvases", "material_animations",
    "sound_channel_mappings", "material_colors", "loudnesses", "vocal_separations"
]
AUDIO_REF_TYPES = [
    "speeds", "placeholder_infos", "beats",
    "sound_channel_mappings", "vocal_separations"
]
TEXT_REF_TYPES = ["material_animations"]

# 每个视频段需要追加的全套辅助材料 (不含 beats, beats 是音频专属)
VIDEO_AUX_TYPES = [
    "canvases", "speeds", "material_animations", "material_colors",
    "sound_channel_mappings", "placeholder_infos", "loudnesses", "vocal_separations"
]
# 每个文字段需要追加的辅助材料
TEXT_AUX_TYPES = ["material_animations"]
# 每个音频段需要追加的辅助材料
AUDIO_AUX_TYPES = [
    "speeds", "placeholder_infos", "beats",
    "sound_channel_mappings", "vocal_separations"
]

# 所有辅助材料类型 (用于 ID 重映射)
ALL_AUX_TYPES = list(set(VIDEO_AUX_TYPES + AUDIO_AUX_TYPES + TEXT_AUX_TYPES))


def _uid() -> str:
    return uuid.uuid4().hex


def _mk_target_timerange(start_us: float, duration_us: float) -> dict:
    """start=0 时省略 start 字段"""
    d = int(duration_us)
    if start_us == 0:
        return {"duration": d}
    return {"start": int(start_us), "duration": d}


def _decrypt_file(enc_path: str) -> dict:
    """解密 jy-draftc 加密的 JSON 文件"""
    import tempfile
    tmp = tempfile.mktemp(suffix=".json")
    env = os.environ.copy()
    env["JY_INSTALL_DIR"] = JY_INSTALL_DIR
    subprocess.run(["jy-draftc", "-d", enc_path, tmp], env=env,
                   capture_output=True, text=True)
    with open(tmp, "r", encoding="utf-8") as f:
        data = json.load(f)
    os.remove(tmp)
    return data


def _encrypt_file(json_path: str) -> bool:
    """加密 JSON 文件 (原地替换)"""
    env = os.environ.copy()
    env["JY_INSTALL_DIR"] = JY_INSTALL_DIR
    cwd = os.path.dirname(json_path)
    subprocess.run(["jy-draftc", "-e", json_path], cwd=cwd, env=env,
                   capture_output=True, text=True)
    enc_out = json_path + ".enc.json"
    if os.path.exists(enc_out):
        os.remove(json_path)
        os.rename(enc_out, json_path)
        return True
    return False


def _load_template() -> dict:
    """加载并解密模板草稿"""
    enc = os.path.join(TEMPLATE_DIR, "draft_content.json")
    return _decrypt_file(enc)


def _deep_clone_prototypes(template: dict) -> dict:
    """从 6 轨模板提取所有原型对象。模板索引写死(不受 TRACK 常量影响)"""
    tracks = template["tracks"]
    mats = template["materials"]
    return {
        "video_seg": copy.deepcopy(tracks[0]["segments"][0]),    # 模板 track[0] = video
        "video_mat": copy.deepcopy(mats["videos"][0]),
        "subtitle_seg": copy.deepcopy(tracks[1]["segments"][0]), # 模板 track[1] = subtitle
        "title_seg": copy.deepcopy(tracks[4]["segments"][0]),    # 模板 track[4] = title
        "audio_seg": copy.deepcopy(tracks[5]["segments"][0]),    # 模板 track[5] = audio
        "text_mat": copy.deepcopy(mats["texts"][0]),
        "audio_mat": copy.deepcopy(mats["audios"][0]),
        "speed": copy.deepcopy(mats["speeds"][0]) if mats.get("speeds") else None,
        "canvas": copy.deepcopy(mats["canvases"][0]) if mats.get("canvases") else None,
        "anim": copy.deepcopy(mats["material_animations"][0]) if mats.get("material_animations") else None,
        "color": copy.deepcopy(mats["material_colors"][0]) if mats.get("material_colors") else None,
        "sound": copy.deepcopy(mats["sound_channel_mappings"][0]) if mats.get("sound_channel_mappings") else None,
        "ph": copy.deepcopy(mats["placeholder_infos"][0]) if mats.get("placeholder_infos") else None,
        "vocal": copy.deepcopy(mats["vocal_separations"][0]) if mats.get("vocal_separations") else None,
        "loudness": copy.deepcopy(mats["loudnesses"][0]) if mats.get("loudnesses") else None,
        "beat": copy.deepcopy(mats["beats"][0]) if mats.get("beats") else None,
    }


def _remap_aux_ids(draft: dict) -> dict:
    """重映射所有辅助材料 ID"""
    id_map = {}
    for cat in ALL_AUX_TYPES:
        for item in draft["materials"].get(cat, []):
            old_id = item["id"]
            new_id = _uid()
            id_map[old_id] = new_id
            item["id"] = new_id

    for track in draft["tracks"]:
        for seg in track["segments"]:
            if "extra_material_refs" in seg:
                seg["extra_material_refs"] = [
                    id_map.get(r, r) for r in seg["extra_material_refs"]
                ]
    return id_map


def _build_video_refs(draft: dict, index: int, anim_offset: int = 0) -> list:
    """为第 index 个视频段构建 extra_material_refs (8项)
    anim_offset: 视频动画在 material_animations 数组中的偏移补偿
    (因为模板中文字动画排在视频动画后面, 追加的视频动画索引需要跳过模板文字动画)"""
    return [
        draft["materials"]["speeds"][index]["id"],
        draft["materials"]["placeholder_infos"][index]["id"],
        draft["materials"]["canvases"][index]["id"],
        draft["materials"]["material_animations"][index + anim_offset]["id"],
        draft["materials"]["sound_channel_mappings"][index]["id"],
        draft["materials"]["material_colors"][index]["id"],
        draft["materials"]["loudnesses"][index]["id"],
        draft["materials"]["vocal_separations"][index]["id"],
    ]


def _build_audio_refs(draft: dict, index: int) -> list:
    """为音频段构建 extra_material_refs (5项, 含 beats)
    beats 始终用索引 0 (音频段专属, 不与视频共享)
    其他数组共享 index (位于视频段之后)"""
    return [
        draft["materials"]["speeds"][index]["id"],
        draft["materials"]["placeholder_infos"][index]["id"],
        draft["materials"]["beats"][0]["id"],           # beats 始终 index 0
        draft["materials"]["sound_channel_mappings"][index]["id"],
        draft["materials"]["vocal_separations"][index]["id"],
    ]


def _build_text_ref(draft: dict, index: int) -> list:
    """为文字段构建 extra_material_refs (1项: material_animations)"""
    return [draft["materials"]["material_animations"][index]["id"]]


def _append_aux_for_video(draft: dict, proto: dict, duration_us: int = None):
    """为新增的视频段追加一份全套辅助材料 (不含 beats), 更新动画时长"""
    for cat, pkey in [
        ("canvases", "canvas"), ("speeds", "speed"),
        ("material_animations", "anim"), ("material_colors", "color"),
        ("sound_channel_mappings", "sound"),
        ("placeholder_infos", "ph"), ("loudnesses", "loudness"),
        ("vocal_separations", "vocal"),
    ]:
        if proto.get(pkey) is None:
            continue
        m = copy.deepcopy(proto[pkey])
        m["id"] = _uid()
        # 视频动画: 更新 duration 匹配实际片段时长
        if cat == "material_animations" and duration_us is not None:
            for inner in m.get("animations", []):
                inner["duration"] = int(duration_us)
        draft["materials"][cat].append(m)


def _append_aux_for_text(draft: dict, proto: dict):
    """为新增的文字段追加 material_animations (空的, 文字不需要动画)"""
    m = {"id": _uid(), "animations": []}
    draft["materials"]["material_animations"].append(m)


def _append_aux_for_audio(draft: dict, proto: dict):
    """为新增的音频段追加辅助材料"""
    for cat, pkey in [
        ("speeds", "speed"), ("placeholder_infos", "ph"),
        ("beats", "beat"), ("sound_channel_mappings", "sound"),
        ("vocal_separations", "vocal"),
    ]:
        if proto.get(pkey) is None:
            continue
        m = copy.deepcopy(proto[pkey])
        m["id"] = _uid()
        draft["materials"][cat].append(m)


def _make_text_content(text: str, fill_color: list, font_size: float = 5.0,
                       font_path: str = "",
                       stroke_color: list = None,
                       stroke_width: float = 0.0) -> str:
    """构建文字 content JSON 字符串 (匹配剪映 v11 格式)"""
    style = {
        "fill": {
            "alpha": 1.0,
            "content": {
                "render_type": "solid",
                "solid": {"alpha": 1.0, "color": fill_color}
            }
        },
        "font": {"id": "", "path": font_path},
        "range": [0, len(text)],
        "size": font_size,
    }
    if stroke_color and stroke_width > 0:
        style["strokes"] = [{
            "alpha": 1.0,
            "content": {
                "render_type": "solid",
                "solid": {"alpha": 1.0, "color": stroke_color}
            },
            "width": stroke_width
        }]
    return json.dumps({"styles": [style], "text": text}, ensure_ascii=False)


def export_jianying_draft_v11(
    sentences: List[str],
    image_paths: List[str],
    audio_path: str,
    seg_durations_us: List[float],
    draft_name: str = "ExportedDraft",
    upper_title: str = "",
    lower_title_1: str = "",
    lower_title_2: str = "",
    draft_cover_path: str = None,
) -> str:
    """
    导出剪映 v11 草稿（6轨正式版）

    Args:
        sentences: 句子列表 (用于字幕)
        image_paths: 每句对应的图片路径
        audio_path: 完整配音音频路径
        seg_durations_us: 每句音频时长 (微秒)
        draft_name: 草稿名称
        upper_title: 上标题文字 (书名/标题)
        lower_title_1: 下标题1 (标语/作者)
        lower_title_2: 下标题2 (免责声明)
        draft_cover_path: 封面图
    """
    NOW_US = int(time.time() * 1000000)

    # ======== 1. 加载模板 + 提取原型 ========
    template = _load_template()
    proto = _deep_clone_prototypes(template)
    TMPL_VID_COUNT = 3  # 模板固定: 3个视频材料

    # ======== 2. 初始化草稿 ========
    draft = copy.deepcopy(template)
    n_sentences = len(sentences)
    total_dur = int(sum(seg_durations_us))

    # ======== 2.5. 创建草稿目录 + 生成辅助图片 ========
    from PIL import Image as PILImage, ImageDraw
    draft_dir = os.path.join(DRAFT_ROOT, draft_name.replace(" ", "_"))
    if os.path.exists(draft_dir):
        shutil.rmtree(draft_dir)
    os.makedirs(draft_dir)
    res_dir = os.path.join(draft_dir, "Resources")
    os.makedirs(res_dir, exist_ok=True)

    # ====== 遮盖条架构: 图片(1080x1214) + 藏青底板(1080x1920) + 上下遮盖条(纯RGB) ======
    NAVY = (7, 23, 48)       # #071730 藏青底
    WARM_WHITE = (232, 228, 212)  # #E8E4D4 暖白线

    # 内容图片: 纯 1080x1214 (无线框, 无底板)
    content_image_paths = []
    for i, img_path in enumerate(image_paths):
        try:
            img = PILImage.open(img_path).convert("RGB")
            if img.size != (1080, 1214):
                img = img.resize((1080, 1214), PILImage.LANCZOS)
        except Exception:
            img = PILImage.new("RGB", (1080, 1214), NAVY)
        content_path = os.path.join(res_dir, f"img_{i:03d}.png")
        img.save(content_path, "PNG")
        content_image_paths.append(content_path.replace("\\", "/"))

    # 上遮盖条: 1080x377 (藏青底 + 底部 4px 暖白线) — 遮盖图片缩放溢出到上方的部分
    ct_path = os.path.join(res_dir, "cover_top.png")
    ct_img = PILImage.new("RGB", (1080, 377), NAVY)
    ImageDraw.Draw(ct_img).rectangle([0, 373, 1080, 377], fill=WARM_WHITE)
    ct_img.save(ct_path, "PNG")

    # 下遮盖条: 1080x329 (顶部 4px 暖白线 + 藏青底) — 遮盖图片缩放溢出到下方的部分
    cb_path = os.path.join(res_dir, "cover_bot.png")
    cb_img = PILImage.new("RGB", (1080, 329), NAVY)
    ImageDraw.Draw(cb_img).rectangle([0, 0, 1080, 4], fill=WARM_WHITE)
    cb_img.save(cb_path, "PNG")

    # ======== 3. 视频材料: 内容图(N) + 遮盖条(2) ========
    draft["materials"]["videos"] = []
    # [0..N-1] 内容图片
    for i in range(n_sentences):
        vm = copy.deepcopy(proto["video_mat"])
        vm["id"] = _uid(); vm["material_id"] = vm["id"]
        vm["path"] = content_image_paths[i]; vm["material_name"] = f"img_{i:03d}.png"
        vm["width"] = 1080; vm["height"] = 1214
        draft["materials"]["videos"].append(vm)
    # [N] 上遮盖条
    ct_vm = copy.deepcopy(proto["video_mat"])
    ct_vm["id"] = _uid(); ct_vm["material_id"] = ct_vm["id"]
    ct_vm["path"] = ct_path.replace("\\", "/"); ct_vm["material_name"] = "cover_top.png"
    ct_vm["width"] = 1080; ct_vm["height"] = 377
    draft["materials"]["videos"].append(ct_vm)
    # [N+1] 下遮盖条
    cb_vm = copy.deepcopy(proto["video_mat"])
    cb_vm["id"] = _uid(); cb_vm["material_id"] = cb_vm["id"]
    cb_vm["path"] = cb_path.replace("\\", "/"); cb_vm["material_name"] = "cover_bot.png"
    cb_vm["width"] = 1080; cb_vm["height"] = 329
    draft["materials"]["videos"].append(cb_vm)

    # 视频材料索引: [0..N-1]=图片, [N]=上遮盖, [N+1]=下遮盖
    vid_img_start = 0; vid_ct = n_sentences; vid_cb = n_sentences + 1
    total_vid_count = n_sentences + 2

    # ======== 4. 替换文字材料 ========
    from services.video_service import _split_natural_phrases, _strip_subtitle_punct, _count_cjk

    # 模板文字布局: [sub0..sub13] [upper] [lower1] [lower2] = 14 + 3 = 17
    tmpl_sub_text_count = len(template["tracks"][1]["segments"])  # 14 (模板写死: track[1]=字幕)
    tmpl_title_text_start = tmpl_sub_text_count  # 14
    tmpl_text_count = len(template["materials"]["texts"])  # 17

    # --- 4a. 构建字幕文字材料 (对标 V5 bench: _split_natural_phrases + _strip_subtitle_punct) ---
    subtitle_materials = []
    subtitle_groups = []  # [(global_index, {text, start, end}, sentence_index), ...]
    for i, text in enumerate(sentences):
        dur = seg_durations_us[i]
        if dur <= 0:
            continue
        duration_sec = dur / 1_000_000
        phrases = _split_natural_phrases(text.strip(), max_chars=14)
        phrase_cjk_counts = [_count_cjk(p) for p in phrases]
        total_cjk = sum(phrase_cjk_counts)

        t_cursor = 0.0
        for pi, phrase in enumerate(phrases):
            p_cjk = phrase_cjk_counts[pi]
            if total_cjk > 0:
                p_dur = (p_cjk / total_cjk) * duration_sec
            else:
                p_dur = duration_sec / len(phrases)
            p_dur = max(p_dur, 0.8)
            p_end = duration_sec if pi == len(phrases) - 1 else t_cursor + p_dur
            if p_end > duration_sec - 0.3:
                p_end = duration_sec

            display = _strip_subtitle_punct(phrase)
            if display:
                subtitle_groups.append((len(subtitle_groups), {
                    "text": display,
                    "start": t_cursor,
                    "end": p_end,
                }, i))
                subtitle_materials.append({
                    "text": display,
                    "fill": CLR_SUB,
                    "stroke": CLR_BLACK,
                    "stroke_width": 0.08,
                    "font_size": 8.0,
                    "font": FONT_SUBTITLE,
                })
            t_cursor = p_end
            if t_cursor >= duration_sec:
                break

    # --- 4b. 构建标题文字材料 ---
    # V5 bench 布局: 标题拆两行 (白色短行 + 金色长行), 标语行楷, 声明白字
    # 字号映射: V5 80px→10.0, 68px→8.5, 64px→8.0, 28px→3.5

    # 标题拆行 (对标 V5 _split_title_local: 策略1逗号断句 → 策略2中点标点 → 策略3均分字数)
    title_line1 = ""
    title_line2 = upper_title.strip()
    if title_line2:
        from services.video_service import _count_cjk as _cjk_count
        cjk = _cjk_count(title_line2)
        # ★ 降低阈值: ≥6 CJK 字即拆两行，确保上白下金格式始终生效
        if cjk >= 6:
            # 策略1: 全文找第一个逗号/冒号/分号 → 天然语义断点 (同V5)
            split_pos = -1
            for bp in ("，", "；", "。", "：", "！", "？"):
                pos = title_line2.find(bp)
                if pos > 2 and pos < len(title_line2) - 4:
                    split_pos = pos + 1
                    break
            # 策略2: 中点 ±1/4 范围找标点 (同V5: " 　,、-—")
            if split_pos < 0:
                mid = len(title_line2) // 2
                best = mid
                for bp in " 　,、-—":
                    pos = title_line2.find(bp, max(0, mid - len(title_line2) // 4),
                                           min(len(title_line2), mid + len(title_line2) // 4))
                    if pos != -1:
                        best = pos + 1
                        break
                if best != mid and best < len(title_line2) and best > 2:
                    split_pos = best
            # 策略3: 无标点 → 按 CJK 字符数均分 (字数大致相等, 上白下金)
            if split_pos < 0:
                cjk_chars = [ch for ch in title_line2 if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿']
                if len(cjk_chars) >= 6:
                    # 找到第 ⌈cjk/2⌉ 个 CJK 字符在原串中的位置
                    half_cjk = (len(cjk_chars) + 1) // 2
                    cjk_count = 0
                    for idx, ch in enumerate(title_line2):
                        if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿':
                            cjk_count += 1
                            if cjk_count == half_cjk:
                                split_pos = idx + 1
                                break
            # ★ 底线: 拆分后每行至少3字，否则保持单行
            if split_pos > 0:
                candidate = title_line2[:split_pos].strip()
                if _cjk_count(candidate) >= 3 and _cjk_count(title_line2[split_pos:].lstrip()) >= 3:
                    title_line1 = title_line2[:split_pos].strip()
                    title_line2 = title_line2[split_pos:].lstrip()

    # title_materials: [disclaimer, slogan, title_line2, title_line1]
    # 对应 template text indices: [14, 15, 16, 17+]
    # ★ 固定索引：前4项必须存在（空文本占位），后续代码按索引 0/1/2/3 读取
    title_materials = []
    # [0] 声明 (可能为空)
    disc_text = lower_title_2.strip()
    while '  ' in disc_text:
        disc_text = disc_text.replace('  ', '\n')
    title_materials.append({
        "text": disc_text,
        "fill": CLR_DISC, "stroke": None, "stroke_width": 0,
        "font_size": 5.0, "font": FONT_DISC,
    })
    # [1] 标语 (可能为空)
    title_materials.append({
        "text": lower_title_1.strip(),
        "fill": CLR_SLOGAN, "stroke": None, "stroke_width": 0,
        "font_size": 12.0, "font": FONT_SLOGAN,
    })
    # [2] 标题第二行 — 金色
    if title_line2.strip():
        title_materials.append({
            "text": title_line2.strip(),
            "fill": CLR_GOLD, "stroke": None, "stroke_width": 0,
            "font_size": 10.0, "font": FONT_TITLE,
        })
    # [3] 标题第一行 — 白色 (仅标题拆分时)
    if title_line1.strip():
        title_materials.append({
            "text": title_line1.strip(),
            "fill": CLR_WHITE, "stroke": None, "stroke_width": 0,
            "font_size": 10.0, "font": FONT_TITLE,
        })

    # --- 4c. 应用到 texts 数组 ---
    # 先 in-place 改模板位, 再 append 其余
    def _apply_text(mt):
        content = _make_text_content(
            mt["text"], mt["fill"], mt["font_size"],
            font_path=mt.get("font", ""),
            stroke_color=mt["stroke"], stroke_width=mt["stroke_width"]
        )
        return content

    # 字幕: 填模板的 14 个位
    for gi in range(min(tmpl_sub_text_count, len(subtitle_materials))):
        mt = subtitle_materials[gi]
        draft["materials"]["texts"][gi]["id"] = _uid()
        draft["materials"]["texts"][gi]["content"] = _apply_text(mt)
        draft["materials"]["texts"][gi]["font_path"] = mt["font"]

    # 标题/标语/声明: 填模板的 3+ 个位 (可能4个材料, 第4个 append)
    for gi, mt in enumerate(title_materials):
        ti = tmpl_title_text_start + gi
        if ti < tmpl_text_count:
            draft["materials"]["texts"][ti]["id"] = _uid()
            draft["materials"]["texts"][ti]["content"] = _apply_text(mt)
            draft["materials"]["texts"][ti]["font_path"] = mt["font"]
        else:
            tm = copy.deepcopy(proto["text_mat"])
            tm["id"] = _uid()
            tm["content"] = _apply_text(mt)
            tm["font_path"] = mt["font"]
            draft["materials"]["texts"].append(tm)

    # 追加剩余字幕
    for gi in range(tmpl_sub_text_count, len(subtitle_materials)):
        mt = subtitle_materials[gi]
        tm = copy.deepcopy(proto["text_mat"])
        tm["id"] = _uid()
        tm["content"] = _apply_text(mt)
        tm["font_path"] = mt["font"]
        draft["materials"]["texts"].append(tm)

    # 清理多余的模板标题文字位 (如果实际标题少于模板的 3 个)
    actual_title_count = len(title_materials)
    keep_text_count = max(tmpl_sub_text_count, len(subtitle_materials)) + actual_title_count
    if tmpl_text_count > keep_text_count:
        del draft["materials"]["texts"][keep_text_count:tmpl_text_count]

    # ======== 5. 替换音频材料 (1个, IN-PLACE) ========
    draft["materials"]["audios"][0]["id"] = _uid()
    draft["materials"]["audios"][0]["music_id"] = draft["materials"]["audios"][0]["id"]
    draft["materials"]["audios"][0]["local_material_id"] = draft["materials"]["audios"][0]["id"]
    draft["materials"]["audios"][0]["path"] = audio_path
    draft["materials"]["audios"][0]["name"] = os.path.basename(audio_path)
    draft["materials"]["audios"][0]["duration"] = total_dur

    # 删除多余的模板音频
    tmpl_audio_count = len(draft["materials"]["audios"])
    if tmpl_audio_count > 1:
        del draft["materials"]["audios"][1:]

    # ======== 6. 辅助材料: remap + 清理模板视频aux + 全部重建 ========
    _remap_aux_ids(draft)

    # 删除模板视频 aux (前 TMPL_VID_COUNT 项)，全部重建使视频 aux 连续
    for cat in ["speeds", "canvases", "material_colors", "loudnesses",
                "sound_channel_mappings", "placeholder_infos", "vocal_separations"]:
        arr = draft["materials"].get(cat, [])
        if len(arr) >= TMPL_VID_COUNT:
            del arr[:TMPL_VID_COUNT]
    # material_animations: 也删除前 TMPL_VID_COUNT 项 (视频动画)
    anims = draft["materials"]["material_animations"]
    if len(anims) >= TMPL_VID_COUNT:
        del anims[:TMPL_VID_COUNT]
    # 记录当前文字动画数 (视频动画将追加在此之后)
    text_anim_count = len(anims)

    # 追加视频 aux: 图片用各自段时长, 遮盖条用全片时长
    for i in range(n_sentences):
        _append_aux_for_video(draft, proto, duration_us=seg_durations_us[i])
    for _ in range(2):  # 上遮盖条 + 下遮盖条
        _append_aux_for_video(draft, proto, duration_us=total_dur)

    # 视频 aux 全部连续, vid_idx 直接对应 aux 索引
    # ★ anim_offset = text_anim_count: 因为视频 anim 追加在文字 anim 之后
    vid_anim_offset = text_anim_count
    vid_img_start = 0
    vid_ct = n_sentences
    vid_cb = n_sentences + 1

    # 追加新文字段的 material_animations
    total_text = len(draft["materials"]["texts"])
    for gi in range(tmpl_text_count, total_text):
        _append_aux_for_text(draft, proto)

    # 新文字 anim 起始索引 = total_vid_count + text_anim_count
    anim_base_for_new_text = total_vid_count + text_anim_count

    # ======== 7. 插入遮盖条轨 + 生成视频段 ========
    # 模板有 6 轨 [video, sub, disc, slogan, title, audio]
    # 草稿需要 8 轨 [video, cover_top, cover_bot, sub, disc, slogan, title, audio]
    tmpl_video_track = draft["tracks"][0]  # 模板 track[0] = video
    # 插入上遮盖条轨 (track[1])
    ct_track = copy.deepcopy(tmpl_video_track)
    ct_track["id"] = _uid(); ct_track["segments"] = []
    draft["tracks"].insert(1, ct_track)
    # 插入下遮盖条轨 (track[2])
    cb_track = copy.deepcopy(tmpl_video_track)
    cb_track["id"] = _uid(); cb_track["segments"] = []
    draft["tracks"].insert(2, cb_track)

    # ----- 7a. 图片轨 (TRACK_VIDEO=0): N 段, 1080x1214 at y=377 -----
    draft["tracks"][TRACK_VIDEO]["segments"] = []
    time_cursor = 0.0
    for i in range(n_sentences):
        dur = seg_durations_us[i]
        seg = copy.deepcopy(proto["video_seg"])
        seg["id"] = _uid()
        vid_idx = vid_img_start + i
        seg["material_id"] = draft["materials"]["videos"][vid_idx]["id"]
        seg["source_timerange"]["duration"] = int(dur)
        seg["target_timerange"] = {"start": int(time_cursor), "duration": int(dur)}
        seg["clip"]["transform"]["y"] = -0.025  # JY: 1-984/960=-0.025
        seg["extra_material_refs"] = _build_video_refs(draft, vid_idx, vid_anim_offset)
        draft["tracks"][TRACK_VIDEO]["segments"].append(seg)
        time_cursor += dur

    # ----- 7b. 上遮盖条轨 (TRACK_COVER_TOP=1): 1 段, 1080x377 at y=0 -----
    ct_seg = copy.deepcopy(proto["video_seg"])
    ct_seg["id"] = _uid()
    ct_seg["material_id"] = draft["materials"]["videos"][vid_ct]["id"]
    ct_seg["source_timerange"]["duration"] = total_dur
    ct_seg["target_timerange"] = _mk_target_timerange(0, total_dur)
    ct_seg["clip"]["transform"]["y"] = +0.804  # JY: 1-188.5/960=+0.804
    ct_seg["extra_material_refs"] = _build_video_refs(draft, vid_ct, vid_anim_offset)
    draft["tracks"][TRACK_COVER_TOP]["segments"] = [ct_seg]

    # ----- 7c. 下遮盖条轨 (TRACK_COVER_BOT=2): 1 段, 1080x329 at y=1591 -----
    cb_seg = copy.deepcopy(proto["video_seg"])
    cb_seg["id"] = _uid()
    cb_seg["material_id"] = draft["materials"]["videos"][vid_cb]["id"]
    cb_seg["source_timerange"]["duration"] = total_dur
    cb_seg["target_timerange"] = _mk_target_timerange(0, total_dur)
    cb_seg["clip"]["transform"]["y"] = -0.829  # JY: 1-1755.5/960=-0.829
    cb_seg["extra_material_refs"] = _build_video_refs(draft, vid_cb, vid_anim_offset)
    draft["tracks"][TRACK_COVER_BOT]["segments"] = [cb_seg]

    # 遮盖条不需要动画，清除其 Ken Burns
    cover_anim_ids = set()
    for seg in (draft["tracks"][TRACK_COVER_TOP]["segments"] +
                draft["tracks"][TRACK_COVER_BOT]["segments"]):
        if len(seg.get("extra_material_refs", [])) >= 4:
            cover_anim_ids.add(seg["extra_material_refs"][3])
    for anim in draft["materials"]["material_animations"]:
        if anim["id"] in cover_anim_ids:
            anim["animations"] = []

    # ======== 8. 生成字幕段 (track[TRACK_SUBTITLE], 对标 V5 bench 自然断句) ========
    tmpl_sub_segs = len(draft["tracks"][TRACK_SUBTITLE]["segments"])
    tmpl_sub_text_count = tmpl_sub_segs  # 模板字幕文字数 = 字幕段数 (14)

    # 预计算每句的时间偏移 (秒)
    sent_start_times = [0.0]
    for dur in seg_durations_us:
        sent_start_times.append(sent_start_times[-1] + dur / 1_000_000)

    si = 0
    for gi, ginfo, sent_i in subtitle_groups:
        gstart_abs = sent_start_times[sent_i] + ginfo["start"]
        gdur = int((ginfo["end"] - ginfo["start"]) * 1_000_000)
        gstart_us = int(gstart_abs * 1_000_000)

        # 字幕文字材料索引: 标题材料插在模板字幕之后
        # (title_materials 可能比模板多1个 title_line1, 需补偿偏移)
        title_overhang = max(0, len(title_materials) - (tmpl_text_count - tmpl_sub_text_count))
        if si < tmpl_sub_text_count:
            text_idx = si
        else:
            text_idx = tmpl_text_count + title_overhang + (si - tmpl_sub_text_count)

        if si < tmpl_sub_segs:
            seg = draft["tracks"][TRACK_SUBTITLE]["segments"][si]
            seg["id"] = _uid()
            seg["material_id"] = draft["materials"]["texts"][text_idx]["id"]
            seg["target_timerange"] = _mk_target_timerange(gstart_us, gdur)
            seg["extra_material_refs"] = _build_text_ref(draft, si)
        else:
            seg = copy.deepcopy(proto["subtitle_seg"])
            seg["id"] = _uid()
            seg["material_id"] = draft["materials"]["texts"][text_idx]["id"]
            seg["target_timerange"] = _mk_target_timerange(gstart_us, gdur)
            text_anim_idx = anim_base_for_new_text + title_overhang + (si - tmpl_sub_segs)
            seg["extra_material_refs"] = _build_text_ref(draft, text_anim_idx)
            draft["tracks"][TRACK_SUBTITLE]["segments"].append(seg)
        si += 1

    # 字幕 Y 坐标对齐 V5 bench (1269px → y_jy≈-0.32)
    for seg in draft["tracks"][TRACK_SUBTITLE]["segments"]:
        seg["clip"]["transform"]["y"] = -0.32

    if tmpl_sub_segs > si:
        del draft["tracks"][TRACK_SUBTITLE]["segments"][si:]

    # ======== 9. 声明 (TRACK_DISC[2], y=-0.85, 静态全段) ========
    if title_materials and title_materials[0]["text"]:
        mt = title_materials[0]  # disclaimer
        ti = tmpl_sub_text_count + 0
        seg = draft["tracks"][TRACK_DISC]["segments"][0]
        seg["id"] = _uid()
        seg["material_id"] = draft["materials"]["texts"][ti]["id"]
        seg["clip"]["transform"]["y"] = -0.85
        seg["target_timerange"] = _mk_target_timerange(0, total_dur)
        seg["extra_material_refs"] = _build_text_ref(draft, ti)
        if len(draft["tracks"][TRACK_DISC]["segments"]) > 1:
            del draft["tracks"][TRACK_DISC]["segments"][1:]
    else:
        draft["tracks"][TRACK_DISC]["segments"] = []

    # ======== 10. 标语 (TRACK_SLOGAN[3], y=-0.72, 静态全段) ========
    if len(title_materials) > 1 and title_materials[1]["text"]:
        mt = title_materials[1]  # slogan
        ti = tmpl_sub_text_count + 1
        seg = draft["tracks"][TRACK_SLOGAN]["segments"][0]
        seg["id"] = _uid()
        seg["material_id"] = draft["materials"]["texts"][ti]["id"]
        seg["clip"]["transform"]["y"] = -0.72
        seg["target_timerange"] = _mk_target_timerange(0, total_dur)
        seg["extra_material_refs"] = _build_text_ref(draft, ti)
        if len(draft["tracks"][TRACK_SLOGAN]["segments"]) > 1:
            del draft["tracks"][TRACK_SLOGAN]["segments"][1:]
    else:
        draft["tracks"][TRACK_SLOGAN]["segments"] = []

    # ======== 11. 标题第二行 — 金色 (TRACK_TITLE[4], y=+0.73, 静态全段) ========
    if len(title_materials) > 2:
        mt = title_materials[2]  # title_line2 (gold)
        ti = tmpl_sub_text_count + 2
        seg = draft["tracks"][TRACK_TITLE]["segments"][0]
        seg["id"] = _uid()
        seg["material_id"] = draft["materials"]["texts"][ti]["id"]
        seg["clip"]["transform"]["y"] = +0.73
        seg["target_timerange"] = _mk_target_timerange(0, total_dur)
        seg["extra_material_refs"] = _build_text_ref(draft, ti)
        if len(draft["tracks"][TRACK_TITLE]["segments"]) > 1:
            del draft["tracks"][TRACK_TITLE]["segments"][1:]
    else:
        draft["tracks"][TRACK_TITLE]["segments"] = []

    # ======== 12. 生成音频段 (1段) ========
    # 共享数组 (speeds/ph/sounds/vocals): 保留 total_vid_count + 1 项 (所有视频+音频)
    # beats: 保留 1 项 (音频专属)
    audio_aux_index = total_vid_count
    for cat in ["speeds", "placeholder_infos", "sound_channel_mappings", "vocal_separations"]:
        items = draft["materials"].get(cat, [])
        target = audio_aux_index + 1
        if len(items) > target:
            del items[target:]
        while len(items) < target:
            m = copy.deepcopy(proto[{"speeds":"speed","placeholder_infos":"ph","sound_channel_mappings":"sound","vocal_separations":"vocal"}[cat]])
            m["id"] = _uid()
            items.append(m)

    # beats: 只留 1 项
    if "beats" in draft["materials"]:
        beats = draft["materials"]["beats"]
        del beats[1:]  # 只保留第一个
        # beats 的 ID 已在 _remap_aux_ids 中处理

    audio_seg = draft["tracks"][TRACK_AUDIO]["segments"][0]
    audio_seg["id"] = _uid()
    audio_seg["material_id"] = draft["materials"]["audios"][0]["id"]
    audio_seg["source_timerange"]["duration"] = total_dur
    audio_seg["target_timerange"] = _mk_target_timerange(0, total_dur)
    # 音频 refs 用 n_sentences 作为索引（音频辅助在视频之后）
    audio_seg["extra_material_refs"] = _build_audio_refs(draft, audio_aux_index)
    # 删除多余模板音频段
    if len(draft["tracks"][TRACK_AUDIO]["segments"]) > 1:
        del draft["tracks"][TRACK_AUDIO]["segments"][1:]

    # ======== 12.5. 标题第一行 — 白色 (新建 track, y=+0.844, 静态全段) ========
    if len(title_materials) > 3:
        mt = title_materials[3]  # title_line1 (white)
        ti = tmpl_sub_text_count + 3
        t1_track = copy.deepcopy(draft["tracks"][TRACK_TITLE])
        t1_track["id"] = _uid()  # ★ 必须改 track id，否则与金色标题轨同ID导致金轨不渲染
        t1_seg = t1_track["segments"][0]
        t1_seg["id"] = _uid()
        t1_seg["material_id"] = draft["materials"]["texts"][ti]["id"]
        t1_seg["clip"]["transform"]["y"] = +0.844
        t1_seg["target_timerange"] = _mk_target_timerange(0, total_dur)
        # ★ ti=17 指向 material_animations[17] (视频anim), 正确索引在 anim_base_for_new_text 之后
        white_anim_idx = anim_base_for_new_text + (ti - tmpl_text_count)
        t1_seg["extra_material_refs"] = _build_text_ref(draft, white_anim_idx)
        t1_track["segments"] = [t1_seg]
        # 插在 audio 之前 (audio 已在 step 12 处理完, 索引不受影响)
        draft["tracks"].insert(TRACK_AUDIO, t1_track)

    # ======== 13. 保持 draft["id"] 不变 (三ID一致) ========
    draft["duration"] = total_dur

    # ====== BG 轨和 matte 轨已移除：framed 图片自带藏青底+线框 (1080×1920) ======
    # 不再需要独立的底板轨道和遮罩轨道，线框已直接画在每张图片上

    # ======== 13.7. 最终清理：去 flag + 修正字幕 Y ========
    # flag 会导致剪映隐藏视频轨道
    for tr in draft["tracks"]:
        tr.pop("flag", None)

    # 字幕轨在所有轨插入后可能 Y 坐标错位，按段数最多+type=text 定位强制修正
    for tr in draft["tracks"]:
        if tr.get("type") == "text" and len(tr.get("segments", [])) > 10:
            for seg in tr["segments"]:
                seg["clip"]["transform"]["y"] = -0.32
            break

    # ======== 14. 写入文件 ========
    draft_id = "V11-" + str(int(time.time()))

    # 写 plaintext draft_content.json
    dc_path = os.path.join(draft_dir, "draft_content.json")
    with open(dc_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    # 复制模板加密文件
    for fn in ["draft_meta_info.json", "draft_settings"]:
        sf = os.path.join(TEMPLATE_DIR, fn)
        if os.path.exists(sf):
            shutil.copy2(sf, os.path.join(draft_dir, fn))

    # 修正 draft_meta_info.json
    dm_path = os.path.join(draft_dir, "draft_meta_info.json")
    dm = _decrypt_file(dm_path)
    dm["draft_id"] = draft_id
    dm["draft_name"] = draft_name
    dm["draft_fold_path"] = draft_dir.replace("\\", "/")
    dm["draft_root_path"] = DRAFT_ROOT.replace("\\", "/")
    dm["tm_draft_create"] = NOW_US
    dm["tm_draft_modified"] = NOW_US
    dm["tm_duration"] = total_dur
    dm["draft_new_version"] = "164.0.0"

    # 重建 draft_materials: 模板遗留旧引用(seg_*.png/mp3)导致剪映打开报失效链接
    def _make_mat_entry(file_path, filename, metetype, duration, width, height):
        return {
            "ai_group_type": "",
            "create_time": 0,
            "duration": duration,
            "enter_from": 0,
            "extra_info": filename,
            "file_Path": file_path,
            "height": height,
            "id": str(uuid.uuid4()),
            "import_time": 0,
            "import_time_ms": 0,
            "item_source": 1,
            "material_color_tag": "",
            "md5": "",
            "metetype": metetype,
            "roughcut_time_range": {"duration": -1, "start": -1},
            "sub_time_range": {"duration": -1, "start": -1},
            "type": 0,
            "width": width,
        }

    mat_value = []

    # 内容图片: img_000.png ~ img_{N-1}.png (1080×1214)
    for i in range(n_sentences):
        mat_value.append(_make_mat_entry(
            f"./Resources/img_{i:03d}.png", f"img_{i:03d}.png",
            "photo", 5000000, 1080, 1214))

    # 遮盖条
    mat_value.append(_make_mat_entry(
        "./Resources/cover_top.png", "cover_top.png", "photo", 5000000, 1080, 377))
    mat_value.append(_make_mat_entry(
        "./Resources/cover_bot.png", "cover_bot.png", "photo", 5000000, 1080, 329))

    # 配音音频
    audio_filename = os.path.basename(audio_path)
    mat_value.append(_make_mat_entry(
        audio_path.replace("\\", "/"), audio_filename, "music", total_dur, 0, 0))

    dm["draft_materials"] = [
        {"type": 0, "value": mat_value},
        {"type": 1, "value": []}, {"type": 2, "value": []}, {"type": 3, "value": []},
        {"type": 6, "value": []}, {"type": 7, "value": []}, {"type": 8, "value": []},
    ]

    with open(dm_path, "w", encoding="utf-8") as f:
        json.dump(dm, f, ensure_ascii=False, indent=2)
    _encrypt_file(dm_path)

    # 封面图
    cover_src = draft_cover_path or (image_paths[0] if image_paths else None)
    if cover_src and os.path.exists(cover_src):
        shutil.copy2(cover_src, os.path.join(draft_dir, "draft_cover.jpg"))

    # Timelines/
    tl_src = os.path.join(TEMPLATE_DIR, "Timelines")
    tl_dst = os.path.join(draft_dir, "Timelines")
    shutil.copytree(tl_src, tl_dst)
    for d in os.listdir(tl_dst):
        dp = os.path.join(tl_dst, d)
        if os.path.isdir(dp) and d != "common_attachment":
            shutil.copy2(dc_path, os.path.join(dp, "draft_content.json"))
            for f in os.listdir(dp):
                if f.endswith(".tmp") or f.endswith(".bak"):
                    os.remove(os.path.join(dp, f))
            break

    # 加密
    _encrypt_file(dc_path)
    for d in os.listdir(tl_dst):
        dp = os.path.join(tl_dst, d)
        if os.path.isdir(dp) and d != "common_attachment":
            _encrypt_file(os.path.join(dp, "draft_content.json"))

    # 素材大小
    total_mat_size = sum(os.path.getsize(p) for p in content_image_paths if os.path.exists(p))
    for p in [ct_path, cb_path]:
        if os.path.exists(p):
            total_mat_size += os.path.getsize(p)
    if os.path.exists(audio_path):
        total_mat_size += os.path.getsize(audio_path)

    # ======== 15. 注册 ========
    with open(REGISTRY_PATH, "r", encoding="utf-8-sig") as f:
        reg = json.load(f)

    all_drafts = reg.get("all_draft_store", [])
    all_drafts = [d for d in all_drafts if draft_id not in str(d.get("draft_id", ""))]

    dfold = draft_dir.replace("\\", "/")
    all_drafts.insert(0, {
        "cloud_draft_cover": False, "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False,
        "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "", "draft_cloud_videocut_purchase_info": "",
        "draft_cover": dfold + "/draft_cover.jpg",
        "draft_fold_path": dfold,
        "draft_id": draft_id,
        "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
        "draft_is_invisible": False, "draft_is_web_article_video": False,
        "draft_json_file": dfold + "/draft_content.json",
        "draft_name": draft_name,
        "draft_new_version": "164.0.0",
        "draft_root_path": DRAFT_ROOT.replace("\\", "/"),
        "draft_timeline_materials_size": total_mat_size, "draft_type": "",
        "draft_web_article_video_enter_from": "",
        "streaming_edit_draft_ready": True,
        "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1, "tm_draft_cloud_user_id": -1,
        "tm_draft_create": NOW_US, "tm_draft_modified": NOW_US, "tm_draft_removed": 0,
    })
    reg["all_draft_store"] = all_drafts
    with open(REGISTRY_PATH, "w", encoding="utf-8-sig") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)

    return draft_dir
