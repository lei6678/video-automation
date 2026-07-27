"""
剪映 v11 草稿导出服务
基于模板克隆 + 增量追加策略（非全量替换）

关键规则（经 20+ 轮隔离测试验证）:
1. 在模板数组上 IN-PLACE 修改 + APPEND，不可整数组替换
2. extra_material_refs 顺序: speeds, placeholder_infos, canvases,
   material_animations, sound_channel_mappings, material_colors,
   loudnesses, vocal_separations
3. target_timerange: start=0 时省略 start 字段
4. Audio 材料无 material_id 字段; Video 材料有 material_id == id
5. Text 材料无 extra_material_refs
6. Audio segment refs: [speeds[N_video], ph[N_video], sounds[N_video], vocals[N_video]]
7. project.json / Timelines 目录名保持不变
8. 文件写入使用 quick_build 模式: 最小文件集 + 模板加密文件直接复制
"""
import json, os, uuid, subprocess, shutil, time, copy
from typing import List

# ======== 配置 ========
JY_INSTALL_DIR = r"E:/360Downloads/JianyingPro/11.0.0.14274"
SYSTEM_FONT_PATH = JY_INSTALL_DIR + "/Resources/Font/SystemFont/zh-hans.ttf"
DRAFT_ROOT = r"E:/360Downloads/JianyingPro Drafts"
TEMPLATE_DIR = r"E:/360Downloads/JianyingPro Drafts/TestReEncrypt"
REGISTRY_PATH = r"C:\Users\Admin\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json"

# 模板规定的 ref 顺序
VIDEO_REF_ORDER = [
    "speeds", "placeholder_infos", "canvases", "material_animations",
    "sound_channel_mappings", "material_colors", "loudnesses", "vocal_separations"
]
AUDIO_REF_TYPES = ["speeds", "placeholder_infos", "sound_channel_mappings", "vocal_separations"]
ALL_AUX_TYPES = [
    "canvases", "speeds", "material_animations", "material_colors",
    "sound_channel_mappings", "loudnesses", "placeholder_infos", "vocal_separations"
]


def _uid() -> str:
    return uuid.uuid4().hex


def _mk_target_timerange(start_us: float, duration_us: float) -> dict:
    """模板规则: start=0 时省略 start 字段"""
    d = int(duration_us)
    if start_us == 0:
        return {"duration": d}
    return {"start": int(start_us), "duration": d}


def _decrypt_file(enc_path: str) -> dict:
    """解密 jy-draftc 加密的 JSON 文件, 返回 dict"""
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
    """从模板提取所有原型对象"""
    return {
        "video_seg": copy.deepcopy(template["tracks"][0]["segments"][0]),
        "video_mat": copy.deepcopy(template["materials"]["videos"][0]),
        "audio_seg": copy.deepcopy(template["tracks"][1]["segments"][0]),
        "audio_mat": copy.deepcopy(template["materials"]["audios"][0]),
        "text_seg": copy.deepcopy(template["tracks"][2]["segments"][0]),
        "text_mat": copy.deepcopy(template["materials"]["texts"][0]),
        "speed": copy.deepcopy(template["materials"]["speeds"][0]),
        "canvas": copy.deepcopy(template["materials"]["canvases"][0]),
        "anim": copy.deepcopy(template["materials"]["material_animations"][0]),
        "color": copy.deepcopy(template["materials"]["material_colors"][0]),
        "sound": copy.deepcopy(template["materials"]["sound_channel_mappings"][0]),
        "loud": copy.deepcopy(template["materials"]["loudnesses"][0]),
        "ph": copy.deepcopy(template["materials"]["placeholder_infos"][0]),
        "vocal": copy.deepcopy(template["materials"]["vocal_separations"][0]),
    }


def _remap_aux_ids(draft: dict) -> dict:
    """重映射所有辅助材料 ID (TestD/S18 策略: id_map)"""
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


def _build_video_refs(draft: dict, index: int) -> list:
    """为第 index 个视频段构建正确的 extra_material_refs"""
    return [
        draft["materials"]["speeds"][index]["id"],
        draft["materials"]["placeholder_infos"][index]["id"],
        draft["materials"]["canvases"][index]["id"],
        draft["materials"]["material_animations"][index]["id"],
        draft["materials"]["sound_channel_mappings"][index]["id"],
        draft["materials"]["material_colors"][index]["id"],
        draft["materials"]["loudnesses"][index]["id"],
        draft["materials"]["vocal_separations"][index]["id"],
    ]


def _build_audio_refs(draft: dict, video_count: int) -> list:
    """构建音频段的 extra_material_refs (使用 video_count 作为索引)"""
    return [
        draft["materials"]["speeds"][video_count]["id"],
        draft["materials"]["placeholder_infos"][video_count]["id"],
        draft["materials"]["sound_channel_mappings"][video_count]["id"],
        draft["materials"]["vocal_separations"][video_count]["id"],
    ]


def _append_aux_for_video(draft: dict, proto: dict):
    """为新增的视频段追加一份全套辅助材料"""
    for cat, pkey in [
        ("canvases", "canvas"), ("speeds", "speed"),
        ("material_animations", "anim"), ("material_colors", "color"),
        ("sound_channel_mappings", "sound"), ("loudnesses", "loud"),
        ("placeholder_infos", "ph"), ("vocal_separations", "vocal"),
    ]:
        m = copy.deepcopy(proto[pkey])
        m["id"] = _uid()
        draft["materials"][cat].append(m)


def export_jianying_draft_v11(
    sentences: List[str],
    image_paths: List[str],
    audio_path: str,
    seg_durations_us: List[float],
    draft_name: str = "ExportedDraft",
    draft_cover_path: str = None,
) -> str:
    """
    导出剪映 v11 草稿

    Args:
        sentences: 句子列表 (用于字幕)
        image_paths: 每句对应的图片路径
        audio_path: 完整配音音频路径
        seg_durations_us: 每句音频时长 (微秒)
        draft_name: 草稿名称
        draft_cover_path: 封面图 (可选, 默认第一张图)

    Returns:
        草稿文件夹路径
    """
    NOW_US = int(time.time() * 1000000)
    NOW_S = int(time.time())

    # ======== 1. 加载模板 + 提取原型 ========
    template = _load_template()
    proto = _deep_clone_prototypes(template)

    # ======== 2. 初始化草稿 ========
    draft = copy.deepcopy(template)
    n_sentences = len(sentences)
    total_dur = int(sum(seg_durations_us))

    # ======== 3. 替换视频材料 (IN-PLACE: 前2个改内容, 其余追加) ========
    tmpl_vid_count = len(draft["materials"]["videos"])
    for i in range(min(tmpl_vid_count, n_sentences)):
        draft["materials"]["videos"][i]["id"] = _uid()
        draft["materials"]["videos"][i]["material_id"] = draft["materials"]["videos"][i]["id"]
        draft["materials"]["videos"][i]["path"] = image_paths[i]
        draft["materials"]["videos"][i]["material_name"] = os.path.basename(image_paths[i])

    for i in range(tmpl_vid_count, n_sentences):
        vm = copy.deepcopy(proto["video_mat"])
        vm["id"] = _uid()
        vm["material_id"] = vm["id"]
        vm["path"] = image_paths[i]
        vm["material_name"] = os.path.basename(image_paths[i])
        draft["materials"]["videos"].append(vm)

    # ======== 4. 替换文字材料 (IN-PLACE: 第1个改内容, 其余追加) ========
    from services.video_service import split_into_word_groups

    text_idx = 0
    tmpl_text_count = len(draft["materials"]["texts"])
    all_text_groups = []

    for i, text in enumerate(sentences):
        dur = seg_durations_us[i]
        if dur <= 0:
            continue
        groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
        for group in groups:
            all_text_groups.append((text_idx, group, i))
            text_idx += 1

    for gi, (ti, group, si) in enumerate(all_text_groups):
        content_json = json.dumps({
            "styles": [{
                "fill": {"alpha": 1.0, "content": {"render_type": "solid",
                    "solid": {"alpha": 1.0, "color": [1.0, 0.8, 0.0]}}},
                "range": [0, len(group["text"])],
                "size": 5.0, "bold": True, "italic": False,
                "underline": False, "strokes": []
            }],
            "text": group["text"]
        }, ensure_ascii=False)

        if gi < tmpl_text_count:
            draft["materials"]["texts"][gi]["id"] = _uid()
            draft["materials"]["texts"][gi]["content"] = content_json
            draft["materials"]["texts"][gi]["font_path"] = SYSTEM_FONT_PATH
        else:
            tm = copy.deepcopy(proto["text_mat"])
            tm["id"] = _uid()
            tm["content"] = content_json
            tm["font_path"] = SYSTEM_FONT_PATH
            draft["materials"]["texts"].append(tm)

    # ======== 5. 替换音频材料 (IN-PLACE: 只1个) ========
    draft["materials"]["audios"][0]["id"] = _uid()
    # 注意: audio 无 material_id 字段
    draft["materials"]["audios"][0]["music_id"] = draft["materials"]["audios"][0]["id"]
    draft["materials"]["audios"][0]["local_material_id"] = draft["materials"]["audios"][0]["id"]
    draft["materials"]["audios"][0]["path"] = audio_path
    draft["materials"]["audios"][0]["name"] = os.path.basename(audio_path)
    draft["materials"]["audios"][0]["duration"] = total_dur

    # ======== 6. 辅助材料: 先 remap 现有ID, 再追加新视频段所需的 ========
    _remap_aux_ids(draft)

    # 追加新视频段所需的辅助材料 (前 tmpl_vid_count 个已存在)
    for i in range(tmpl_vid_count, n_sentences):
        _append_aux_for_video(draft, proto)

    # ======== 7. 生成视频段 ========
    tmpl_vid_segs = len(draft["tracks"][0]["segments"])
    time_cursor = 0.0
    for i in range(min(tmpl_vid_segs, n_sentences)):
        seg = draft["tracks"][0]["segments"][i]
        dur = seg_durations_us[i]
        seg["id"] = _uid()
        seg["material_id"] = draft["materials"]["videos"][i]["id"]
        seg["source_timerange"]["duration"] = int(dur)
        seg["target_timerange"] = _mk_target_timerange(time_cursor, dur)
        seg["extra_material_refs"] = _build_video_refs(draft, i)
        time_cursor += dur

    for i in range(tmpl_vid_segs, n_sentences):
        dur = seg_durations_us[i]
        seg = copy.deepcopy(proto["video_seg"])
        seg["id"] = _uid()
        seg["material_id"] = draft["materials"]["videos"][i]["id"]
        seg["source_timerange"]["duration"] = int(dur)
        seg["target_timerange"] = {"start": int(time_cursor), "duration": int(dur)}
        seg["extra_material_refs"] = _build_video_refs(draft, i)
        draft["tracks"][0]["segments"].append(seg)
        time_cursor += dur

    # 删除多余的模板视频段 (如果 tmpl_vid_segs > n_sentences)
    if tmpl_vid_segs > n_sentences:
        del draft["tracks"][0]["segments"][n_sentences:]
        del draft["materials"]["videos"][n_sentences:]

    # ======== 8. 生成音频段 (IN-PLACE: 只有1个) ========
    audio_seg = draft["tracks"][1]["segments"][0]
    audio_seg["id"] = _uid()
    audio_seg["material_id"] = draft["materials"]["audios"][0]["id"]
    audio_seg["source_timerange"]["duration"] = total_dur
    audio_seg["target_timerange"] = _mk_target_timerange(0, total_dur)
    audio_seg["extra_material_refs"] = _build_audio_refs(draft, n_sentences)

    # ======== 9. 生成文字段 ========
    tmpl_text_segs = len(draft["tracks"][2]["segments"])
    stime_cursor = 0.0
    gi = 0
    for i, text in enumerate(sentences):
        dur = seg_durations_us[i]
        if dur <= 0:
            continue
        groups = split_into_word_groups(text, duration_sec=dur / 1_000_000)
        for group in groups:
            gdur = int((group["end"] - group["start"]) * 1_000_000)
            gstart = stime_cursor + group["start"] * 1_000_000

            if gi < tmpl_text_segs:
                seg = draft["tracks"][2]["segments"][gi]
                seg["id"] = _uid()
                seg["material_id"] = draft["materials"]["texts"][gi]["id"]
                seg["target_timerange"] = _mk_target_timerange(gstart, gdur)
            else:
                seg = copy.deepcopy(proto["text_seg"])
                seg["id"] = _uid()
                seg["material_id"] = draft["materials"]["texts"][gi]["id"]
                seg["target_timerange"] = _mk_target_timerange(gstart, gdur)
                draft["tracks"][2]["segments"].append(seg)
            gi += 1
        stime_cursor += dur

    # 删除多余的模板文字段
    if tmpl_text_segs > gi:
        del draft["tracks"][2]["segments"][gi:]
        del draft["materials"]["texts"][gi:]

    # ======== 10. 更新顶层字段 ========
    # 不修改 draft["id"] — 必须与 project.json UUID 和 Timelines/ 目录名一致
    draft["duration"] = total_dur

    # ======== 11. 写入文件 (quick_build 模式) ========
    draft_id = "V11-" + str(int(time.time()))
    folder_name = draft_name.replace(" ", "_")
    draft_dir = os.path.join(DRAFT_ROOT, folder_name)
    if os.path.exists(draft_dir):
        shutil.rmtree(draft_dir)
    os.makedirs(draft_dir)

    # 写入 plaintext draft_content.json
    dc_path = os.path.join(draft_dir, "draft_content.json")
    with open(dc_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    # 复制模板加密核心文件
    for fn in ["draft_meta_info.json", "draft_settings"]:
        sf = os.path.join(TEMPLATE_DIR, fn)
        if os.path.exists(sf):
            shutil.copy2(sf, os.path.join(draft_dir, fn))

    # ======== 修正 draft_meta_info.json (解密→改值→重加密) ========
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

    # 覆盖封面图
    cover_src = draft_cover_path or (image_paths[0] if image_paths else None)
    if cover_src and os.path.exists(cover_src):
        shutil.copy2(cover_src, os.path.join(draft_dir, "draft_cover.jpg"))

    # ======== 12. Timelines/ (保持 project.json 不变) ========
    tl_src = os.path.join(TEMPLATE_DIR, "Timelines")
    tl_dst = os.path.join(draft_dir, "Timelines")
    shutil.copytree(tl_src, tl_dst)

    # 复制 plaintext draft_content.json 到 timeline 子目录
    for d in os.listdir(tl_dst):
        dp = os.path.join(tl_dst, d)
        if os.path.isdir(dp) and d != "common_attachment":
            shutil.copy2(dc_path, os.path.join(dp, "draft_content.json"))
            for f in os.listdir(dp):
                if f.endswith(".tmp") or f.endswith(".bak"):
                    os.remove(os.path.join(dp, f))
            break

    # ======== 13. 加密 draft_content.json (不碰 draft_meta_info) ========
    _encrypt_file(dc_path)
    for d in os.listdir(tl_dst):
        dp = os.path.join(tl_dst, d)
        if os.path.isdir(dp) and d != "common_attachment":
            _encrypt_file(os.path.join(dp, "draft_content.json"))

    # 计算素材大小
    total_mat_size = sum(os.path.getsize(p) for p in image_paths if os.path.exists(p))
    if os.path.exists(audio_path):
        total_mat_size += os.path.getsize(audio_path)

    # ======== 14. 注册到 root_meta_info.json ========
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
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
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)

    return draft_dir
