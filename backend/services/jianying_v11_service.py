"""
剪映 v11 草稿导出服务（8轨正式版 — 含底板 + 装饰线 + 图片框）
基于 7月27日模板 克隆 + 增量追加策略

轨道布局:
  track[0] = video    — 藏青底板 #071730 + 上下装饰线 (全时长静态)
  track[1] = video    — 图片 (1080×1214, y=-0.025 → 嵌入上线373/下线1591之间)
  track[2] = text     — 字幕 (自然断句, 思源宋体, 白字黑边, y=-0.32)
  track[3] = text     — 声明/免责 (思源宋体, y=-0.85)
  track[4] = text     — 标语 (行楷, y=-0.72)
  track[5] = text     — 标题第二行-金色 (思源宋体 Heavy, y=+0.73)
  track[6] = text     — 标题第一行-白色 (仅标题拆分时存在, y=+0.844)
  track[7] = audio    — 配音

标题拆分 (对标 V5 _split_title_local):
  策略1: 全文找逗号/冒号/分号 → 语义断点
  策略2: 中点 ±1/4 范围找标点
  策略3: 无标点 → 按 CJK 字符数均分 (上白下金)

关键规则 (30+ 轮隔离测试验证):
  1. 三ID必须一致: dc.id == project.json.id == Timelines/<dirname>
  2. draft_meta_info.json 必须解密→改值→重加密
  3. IN-PLACE 修改 + APPEND，不可整数组替换
  4. 字体必须位于剪映 Resources/Font/ 目录内方可被加载
  5. 图片需设 transform.y=-0.025 以嵌入装饰线之间 (对应 V5 overlay=0:377)
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
CLR_SLOGAN    = [0.851, 0.733, 0.478]  # #D9BB7A 金色标语
CLR_SUB       = [0.996, 0.996, 0.988]  # #FEFEFC 口播字幕白
CLR_DISC      = [0.129, 0.173, 0.251]  # #212C40 免责声明低对比灰
CLR_BLACK     = [0.0, 0.0, 0.0]        # 字幕描边
CLR_LINE      = [0.910, 0.894, 0.831]  # #E8E4D4 装饰线暖白

# ======== 轨道索引 (基于模板6轨) ========
# 内部代码使用模板原始索引，最后生成时会插入底板轨道到 track[0]
TRACK_VIDEO = 0
TRACK_SUBTITLE = 1        # y≈-0.32  字幕 (思源宋体)
TRACK_DISC = 2            # y≈-0.85  免责声明
TRACK_SLOGAN = 3          # y≈-0.72  标语 (行楷)
TRACK_TITLE = 4           # y≈+0.73  标题 (两行共用, 另加title_line1 track)
TRACK_AUDIO = 5

# ======== ref 顺序 (严格匹配) ========
VIDEO_REF_TYPES = [
    "speeds", "placeholder_infos", "canvases", "material_animations",
    "sound_channel_mappings", "material_colors", "vocal_separations"
]
AUDIO_REF_TYPES = [
    "speeds", "placeholder_infos", "beats",
    "sound_channel_mappings", "vocal_separations"
]
TEXT_REF_TYPES = ["material_animations"]

# 每个视频段需要追加的全套辅助材料 (不含 beats, beats 是音频专属)
VIDEO_AUX_TYPES = [
    "canvases", "speeds", "material_animations", "material_colors",
    "sound_channel_mappings", "placeholder_infos", "vocal_separations"
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
    """从 6 轨模板提取所有原型对象"""
    tracks = template["tracks"]
    mats = template["materials"]
    return {
        "video_seg": copy.deepcopy(tracks[TRACK_VIDEO]["segments"][0]),
        "video_mat": copy.deepcopy(mats["videos"][0]),
        "subtitle_seg": copy.deepcopy(tracks[TRACK_SUBTITLE]["segments"][0]),
        "title_seg": copy.deepcopy(tracks[TRACK_TITLE]["segments"][0]),
        "audio_seg": copy.deepcopy(tracks[TRACK_AUDIO]["segments"][0]),
        "text_mat": copy.deepcopy(mats["texts"][0]),
        "audio_mat": copy.deepcopy(mats["audios"][0]),
        "speed": copy.deepcopy(mats["speeds"][0]) if mats.get("speeds") else None,
        "canvas": copy.deepcopy(mats["canvases"][0]) if mats.get("canvases") else None,
        "anim": copy.deepcopy(mats["material_animations"][0]) if mats.get("material_animations") else None,
        "color": copy.deepcopy(mats["material_colors"][0]) if mats.get("material_colors") else None,
        "sound": copy.deepcopy(mats["sound_channel_mappings"][0]) if mats.get("sound_channel_mappings") else None,
        "ph": copy.deepcopy(mats["placeholder_infos"][0]) if mats.get("placeholder_infos") else None,
        "vocal": copy.deepcopy(mats["vocal_separations"][0]) if mats.get("vocal_separations") else None,
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
    """为第 index 个视频段构建 extra_material_refs (7项)
    anim_offset: 视频动画在 material_animations 数组中的偏移补偿
    (因为模板中文字动画排在视频动画后面, 追加的视频动画索引需要跳过模板文字动画)"""
    return [
        draft["materials"]["speeds"][index]["id"],
        draft["materials"]["placeholder_infos"][index]["id"],
        draft["materials"]["canvases"][index]["id"],
        draft["materials"]["material_animations"][index + anim_offset]["id"],
        draft["materials"]["sound_channel_mappings"][index]["id"],
        draft["materials"]["material_colors"][index]["id"],
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
        ("placeholder_infos", "ph"), ("vocal_separations", "vocal"),
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
    """为新增的文字段追加 material_animations"""
    if proto.get("anim"):
        m = copy.deepcopy(proto["anim"])
        m["id"] = _uid()
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

    # ======== 2. 初始化草稿 ========
    draft = copy.deepcopy(template)
    n_sentences = len(sentences)
    total_dur = int(sum(seg_durations_us))

    # ======== 2.5. 创建草稿目录 + 生成装饰线底板 ========
    from PIL import Image as PILImage, ImageDraw
    draft_dir = os.path.join(DRAFT_ROOT, draft_name.replace(" ", "_"))
    if os.path.exists(draft_dir):
        shutil.rmtree(draft_dir)
    os.makedirs(draft_dir)
    res_dir = os.path.join(draft_dir, "Resources")
    os.makedirs(res_dir, exist_ok=True)

    # 底板: #071730 + 图片上下装饰线 (对标 V5 bench drawbox)
    bg_png_path = os.path.join(res_dir, "_bg_071730.png")
    bg_img = PILImage.new("RGB", (1080, 1920), (7, 23, 48))
    draw = ImageDraw.Draw(bg_img)
    line_color = (232, 228, 212)  # #E8E4D4
    # 上线: y=373, 4px
    draw.rectangle([0, 373, 1080, 377], fill=line_color)
    # 下线: y=1591, 4px
    draw.rectangle([0, 1591, 1080, 1595], fill=line_color)
    bg_img.save(bg_png_path, "PNG")

    # 图片保持原样 (1080×1214, 不垫底 — 底板填充上下空间)
    # image_paths 不变, 直接用原始路径

    # ======== 3. 替换视频材料 (IN-PLACE: 前N个改内容, 其余追加) ========
    tmpl_vid_count = len(draft["materials"]["videos"])
    for i in range(min(tmpl_vid_count, n_sentences)):
        draft["materials"]["videos"][i]["id"] = _uid()
        draft["materials"]["videos"][i]["material_id"] = draft["materials"]["videos"][i]["id"]
        draft["materials"]["videos"][i]["path"] = image_paths[i]
        draft["materials"]["videos"][i]["material_name"] = os.path.basename(image_paths[i])
        draft["materials"]["videos"][i]["width"] = 1080
        draft["materials"]["videos"][i]["height"] = 1214

    for i in range(tmpl_vid_count, n_sentences):
        vm = copy.deepcopy(proto["video_mat"])
        vm["id"] = _uid()
        vm["material_id"] = vm["id"]
        vm["path"] = image_paths[i]
        vm["material_name"] = os.path.basename(image_paths[i])
        vm["width"] = 1080
        vm["height"] = 1214
        draft["materials"]["videos"].append(vm)

    # 删除多余的模板视频
    if tmpl_vid_count > n_sentences:
        del draft["materials"]["videos"][n_sentences:]

    # ======== 4. 替换文字材料 ========
    from services.video_service import _split_natural_phrases, _strip_subtitle_punct, _count_cjk

    # 模板文字布局: [sub0..sub13] [upper] [lower1] [lower2] = 14 + 3 = 17
    tmpl_sub_text_count = len(template["tracks"][TRACK_SUBTITLE]["segments"])  # 14
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
        if cjk > 16:
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
                if len(cjk_chars) > 16:
                    # 找到第 ⌈cjk/2⌉ 个 CJK 字符在原串中的位置
                    half_cjk = (len(cjk_chars) + 1) // 2
                    cjk_count = 0
                    for idx, ch in enumerate(title_line2):
                        if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿':
                            cjk_count += 1
                            if cjk_count == half_cjk:
                                split_pos = idx + 1
                                break
            if split_pos > 0:
                title_line1 = title_line2[:split_pos].strip()
                title_line2 = title_line2[split_pos:].lstrip()

    # title_materials: [disclaimer, slogan, title_line2, title_line1]
    # 对应 template text indices: [14, 15, 16, 17+]
    title_materials = []
    if lower_title_2.strip():
        title_materials.append({
            "text": lower_title_2.strip(),
            "fill": CLR_DISC, "stroke": None, "stroke_width": 0,
            "font_size": 3.5, "font": FONT_DISC,
        })
    if lower_title_1.strip():
        title_materials.append({
            "text": lower_title_1.strip(),
            "fill": CLR_SLOGAN, "stroke": None, "stroke_width": 0,
            "font_size": 8.5, "font": FONT_SLOGAN,
        })
    if title_line2.strip():
        title_materials.append({
            "text": title_line2.strip(),
            "fill": CLR_GOLD, "stroke": None, "stroke_width": 0,
            "font_size": 10.0, "font": FONT_TITLE,
        })
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

    # ======== 6. 辅助材料: 先 remap, 再追加 ========
    _remap_aux_ids(draft)

    # 关键: 模板的 material_animations 排列 = [N_video] + [N_text]
    # 追加后排列 = [N_video] + [N_text_template] + [new_video] + [new_text]
    # 所以追加视频的 anim 索引需要跳过模板文字动画 (anim_offset)
    tmpl_anim_count = len(draft["materials"]["material_animations"])  # 20
    anim_offset_for_new_video = tmpl_anim_count - tmpl_vid_count      # 17 (模板文字动画数)
    anim_base_for_new_text = tmpl_anim_count + (n_sentences - tmpl_vid_count)  # 新文字的 anim 起始索引

    # 追加新视频段所需的辅助材料
    for i in range(tmpl_vid_count, n_sentences):
        _append_aux_for_video(draft, proto, duration_us=int(seg_durations_us[i]))

    # 追加新文字段所需的 material_animations
    # 新文字 = 实际总文字 - 模板已占文字
    total_text = len(draft["materials"]["texts"])
    for gi in range(tmpl_text_count, total_text):
        _append_aux_for_text(draft, proto)

    # ======== 7. 生成视频段 (track[0]) ========
    tmpl_vid_segs = len(draft["tracks"][TRACK_VIDEO]["segments"])
    time_cursor = 0.0
    for i in range(min(tmpl_vid_segs, n_sentences)):
        seg = draft["tracks"][TRACK_VIDEO]["segments"][i]
        dur = seg_durations_us[i]
        seg["id"] = _uid()
        seg["material_id"] = draft["materials"]["videos"][i]["id"]
        seg["source_timerange"]["duration"] = int(dur)
        seg["target_timerange"] = _mk_target_timerange(time_cursor, dur)
        seg["extra_material_refs"] = _build_video_refs(draft, i, 0)  # 模板视频, 无偏移
        time_cursor += dur

    # 更新 in-place 模板视频段的动画时长 (修复: 之前只更新了追加段)
    for i in range(min(tmpl_vid_segs, n_sentences)):
        dur = seg_durations_us[i]
        anim = draft["materials"]["material_animations"][i]
        for inner in anim.get("animations", []):
            inner["duration"] = int(dur)

    for i in range(tmpl_vid_segs, n_sentences):
        dur = seg_durations_us[i]
        seg = copy.deepcopy(proto["video_seg"])
        seg["id"] = _uid()
        seg["material_id"] = draft["materials"]["videos"][i]["id"]
        seg["source_timerange"]["duration"] = int(dur)
        seg["target_timerange"] = {"start": int(time_cursor), "duration": int(dur)}
        seg["extra_material_refs"] = _build_video_refs(draft, i, anim_offset_for_new_video)
        draft["tracks"][TRACK_VIDEO]["segments"].append(seg)
        time_cursor += dur

    if tmpl_vid_segs > n_sentences:
        del draft["tracks"][TRACK_VIDEO]["segments"][n_sentences:]

    # 图片定位: 嵌入上下装饰线之间 (对标 V5 bench overlay=0:377)
    # 1080×1214 图片的 top 需在 y_px=377, center=984, y_jy=(960-984)/960=-0.025
    for seg in draft["tracks"][TRACK_VIDEO]["segments"]:
        seg["clip"]["transform"]["y"] = -0.025

    # ======== 8. 生成字幕段 (track[1], 对标 V5 bench 自然断句) ========
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
            text_anim_idx = anim_base_for_new_text + (si - tmpl_sub_segs)
            seg["extra_material_refs"] = _build_text_ref(draft, text_anim_idx)
            draft["tracks"][TRACK_SUBTITLE]["segments"].append(seg)
        si += 1

    # 字幕 Y 坐标对齐 V5 bench (1269px → y_jy≈-0.32)
    for seg in draft["tracks"][TRACK_SUBTITLE]["segments"]:
        seg["clip"]["transform"]["y"] = -0.32

    if tmpl_sub_segs > si:
        del draft["tracks"][TRACK_SUBTITLE]["segments"][si:]

    # ======== 9. 声明 (TRACK_DISC[2], y=-0.85, 静态全段) ========
    if title_materials and 0 < len(title_materials):
        mt = title_materials[0]  # disclaimer
        ti = tmpl_sub_text_count + 0
        seg = draft["tracks"][TRACK_DISC]["segments"][0]
        seg["id"] = _uid()
        seg["material_id"] = draft["materials"]["texts"][ti]["id"]
        seg["clip"]["transform"]["y"] = -0.85
        seg["target_timerange"] = _mk_target_timerange(0, total_dur)
        seg["extra_material_refs"] = _build_text_ref(draft, tmpl_vid_count + ti)
        if len(draft["tracks"][TRACK_DISC]["segments"]) > 1:
            del draft["tracks"][TRACK_DISC]["segments"][1:]
    else:
        draft["tracks"][TRACK_DISC]["segments"] = []

    # ======== 10. 标语 (TRACK_SLOGAN[3], y=-0.72, 静态全段) ========
    if len(title_materials) > 1:
        mt = title_materials[1]  # slogan
        ti = tmpl_sub_text_count + 1
        seg = draft["tracks"][TRACK_SLOGAN]["segments"][0]
        seg["id"] = _uid()
        seg["material_id"] = draft["materials"]["texts"][ti]["id"]
        seg["clip"]["transform"]["y"] = -0.72
        seg["target_timerange"] = _mk_target_timerange(0, total_dur)
        seg["extra_material_refs"] = _build_text_ref(draft, tmpl_vid_count + ti)
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
        seg["extra_material_refs"] = _build_text_ref(draft, tmpl_vid_count + ti)
        if len(draft["tracks"][TRACK_TITLE]["segments"]) > 1:
            del draft["tracks"][TRACK_TITLE]["segments"][1:]
    else:
        draft["tracks"][TRACK_TITLE]["segments"] = []

    # ======== 12. 生成音频段 (track[5], 1段) ========
    # 清理音频辅助材料: 模板多个音段→只留 1 份
    # 共享数组 (speeds/ph/sounds/vocals): 保留 N_video + 1 项
    # beats: 保留 1 项 (音频专属)
    for cat in ["speeds", "placeholder_infos", "sound_channel_mappings", "vocal_separations"]:
        items = draft["materials"].get(cat, [])
        if len(items) > n_sentences + 1:
            del items[n_sentences + 1:]
        # 确保至少有 n_sentences + 1 项
        while len(items) < n_sentences + 1:
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
    audio_seg["extra_material_refs"] = _build_audio_refs(draft, n_sentences)
    # 删除多余模板音频段
    if len(draft["tracks"][TRACK_AUDIO]["segments"]) > 1:
        del draft["tracks"][TRACK_AUDIO]["segments"][1:]

    # ======== 12.5. 标题第一行 — 白色 (新建 track, y=+0.844, 静态全段) ========
    if len(title_materials) > 3:
        mt = title_materials[3]  # title_line1 (white)
        ti = tmpl_sub_text_count + 3
        t1_track = copy.deepcopy(draft["tracks"][TRACK_TITLE])
        t1_seg = t1_track["segments"][0]
        t1_seg["id"] = _uid()
        t1_seg["material_id"] = draft["materials"]["texts"][ti]["id"]
        t1_seg["clip"]["transform"]["y"] = +0.844
        t1_seg["target_timerange"] = _mk_target_timerange(0, total_dur)
        t1_seg["extra_material_refs"] = _build_text_ref(draft, tmpl_vid_count + ti)
        t1_track["segments"] = [t1_seg]
        # 插在 audio 之前 (audio 已在 step 12 处理完, 索引不受影响)
        draft["tracks"].insert(TRACK_AUDIO, t1_track)

    # ======== 13. 保持 draft["id"] 不变 (三ID一致) ========
    draft["duration"] = total_dur

    # ======== 13.5. 底板: 藏青 #071730 全画布背景 (draft_dir+bg_png 已在 step 2.5 创建) ========

    # 底板视频材料 (插入到 videos[0])
    bg_vm = copy.deepcopy(proto["video_mat"])
    bg_vm["id"] = _uid()
    bg_vm["material_id"] = bg_vm["id"]
    bg_vm["path"] = bg_png_path.replace("\\", "/")
    bg_vm["material_name"] = "_bg_071730.png"
    bg_vm["width"] = 1080
    bg_vm["height"] = 1920
    draft["materials"]["videos"].insert(0, bg_vm)

    # 底板辅助材料 (追加到各数组末尾，无 Ken Burns 动画)
    bg_aux = {}
    for cat, pkey in [
        ("canvases", "canvas"), ("speeds", "speed"),
        ("material_animations", "anim"), ("material_colors", "color"),
        ("sound_channel_mappings", "sound"),
        ("placeholder_infos", "ph"), ("vocal_separations", "vocal"),
    ]:
        if proto.get(pkey) is None:
            continue
        m = copy.deepcopy(proto[pkey])
        m["id"] = _uid()
        if cat == "material_animations":
            m["animations"] = []  # 底板无动画
        draft["materials"][cat].append(m)
        bg_aux[cat] = m

    # 底板视频段 (全时长)
    bg_seg = copy.deepcopy(proto["video_seg"])
    bg_seg["id"] = _uid()
    bg_seg["material_id"] = bg_vm["id"]
    bg_seg["source_timerange"]["duration"] = total_dur
    bg_seg["target_timerange"] = _mk_target_timerange(0, total_dur)
    bg_seg["extra_material_refs"] = [
        draft["materials"]["speeds"][-1]["id"],
        draft["materials"]["placeholder_infos"][-1]["id"],
        draft["materials"]["canvases"][-1]["id"],
        draft["materials"]["material_animations"][-1]["id"],
        draft["materials"]["sound_channel_mappings"][-1]["id"],
        draft["materials"]["material_colors"][-1]["id"],
        draft["materials"]["vocal_separations"][-1]["id"],
    ]

    # 插入底板轨道到 track[0]
    bg_track = copy.deepcopy(draft["tracks"][TRACK_VIDEO])
    bg_track["segments"] = [bg_seg]
    draft["tracks"].insert(0, bg_track)

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
    total_mat_size = sum(os.path.getsize(p) for p in image_paths if os.path.exists(p))
    if os.path.exists(audio_path):
        total_mat_size += os.path.getsize(audio_path)
    if os.path.exists(bg_png_path):
        total_mat_size += os.path.getsize(bg_png_path)

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
