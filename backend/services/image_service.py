"""
配图生成服务 — Fal.ai gpt-image-2 主 · 可灵备 — v3
================================================
1. 按句切片（每句 ~60 字 / 约 18 秒口播）
2. 每 9 句一组构建 3×3 九宫格 Prompt
3. 调用 Fal.ai gpt-image-2 生成九宫格总图（3840×2160, low quality）
4. PIL 裁切：16:9 格子 → 中心裁 9:16 → 1080×1920 竖屏
5. 写入 TaskImage 表

成本: 7 组九宫格 × $0.012 ≈ $0.084（约 0.6 元人民币）
"""

import asyncio
import base64
import json
import os
import re
import time
from typing import Optional

import httpx
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

# ============== 凭证 ==============
FAL_KEY = os.getenv("FAL_KEY", "")
FAL_QUALITY = os.getenv("FAL_QUALITY", "low")  # low | medium | high，默认 low

KELING_API_KEY = os.getenv("KELING_API_KEY", "")
KELING_BASE_URL = os.getenv("KELING_BASE_URL", "https://api.kuaishou.com/keling/v1")

# ============== 模型配置 ==============
FAL_MODEL = "openai/gpt-image-2"
KELING_IMAGE_MODEL = "keling-v1"


# ============== 样式圣经库（来自大佬白皮书）==============

STYLE_BIBLES = {
    "default": (
        "固定美术方向:明亮电影感真实摄影，安静、克制、有知识短视频质感。"
        "固定色彩:暖白、浅木色、柔和灰蓝、低饱和绿色，少量温暖阳光点缀。"
        "固定光线:窗边自然光、清晨或傍晚柔光，阴影干净，整体曝光偏明亮。"
        "固定镜头:35mm/50mm人文镜头语言，主体明确，背景简洁。"
        "人物气质:普通成年人，安静、理性、克制，优先背影、侧影、手部动作和生活场景。"
        "所有图片必须共享同一套色彩、光线、镜头、人物气质、材质和时代感。"
    ),
    "warm_book": (
        "温暖治愈书单风。暖黄光线，柔焦质感，仿佛午后窗边翻书的氛围。"
        "色调偏奶油色+琥珀色，画面像旧胶片相机拍摄。"
        "常见元素：书架一角、茶杯、绿植、阳光透过窗帘、手写字条。"
    ),
    "clean_health": (
        "明亮干净的健康生活方式风。清晨自然光，白色+浅木色为主调。"
        "场景：厨房备餐、晨跑背影、公园长椅、水杯特写、瑜伽垫一角。"
        "传达平静、自律、积极的生活态度，避免医疗感。"
    ),
    "philosophy": (
        "哲学思辨风。广角远景，人物渺小于自然或城市之中。"
        "冷暖对比色调，画面留白多，有呼吸感。"
        "场景：海边独行、山顶远眺、城市天台、空旷图书馆。"
        "传达人生感悟、认知成长的深邃感。"
    ),
}

# ============== 风格后缀映射（注入 Fal.ai prompt 末端）==============

STYLE_PROMPT_MAP = {
    "default": ", cinematic lighting, photorealistic, 35mm lens, depth of field",
    "warm_book": ", warm pastel colors, soft morning sunlight, cozy atmosphere, studio Ghibli aesthetic style",
    "clean_health": ", bright natural lighting, clean minimalism, vibrant colors, commercial photography",
    "philosophy": ", moody dramatic lighting, melancholic low key tone, surrealism artistic texture",
}

# ============== 画面后置防线（防崩坏补丁）==============

SAFETY_SUFFIX = ", highly detailed faces, no duplicate characters, perfect anatomy, masterpiece"


# ============== 单图直生 Prompt（v4：单句独立生图，彻底废弃九宫格）==============


def build_single_segment_prompt(
    text: str,
    book_title: str = "",
    book_author: str = "",
    segment_index: int = 0,
    total_segments: int = 1,
    style_bible: str = "",
    aspect_ratio: str = "9:16",
) -> str:
    """
    构建单句配图 User Prompt（v4：单图直生，无九宫格）。
    """
    if not style_bible:
        style_bible = STYLE_BIBLES.get("default", "")

    prompt = f"""为中文短视频口播生成一张独立意境配图。

最终用途:
这张图作为短视频的连续分镜之一，对应一段约 18 秒的口播配音。

画幅要求:
{aspect_ratio}，主体放在中央安全区，方便后期排版。

主题方向:
图书启发、认知成长、人生感悟、关系洞察、命运转折。

统一视觉风格:
{style_bible}

风格要求:
明亮电影感，真实摄影或高级插画风
光线自然，画面干净，低信息密度
与同一条视频的其他配图保持相同视觉调性

内容来源限制:
只参考当前段落文案，不引用原视频标题、账号、作者或来源信息。

整条视频主题:{book_title}
书籍作者:{book_author}
当前分镜序号:第 {segment_index + 1}/{total_segments} 镜

当前段落文案:
{text.strip()}

请直接生成单张配图。
不要在图片里放任何文字。
不要输出解释。"""
    return prompt


# ============== 通道 A：Fal.ai gpt-image-2（主力）==============

async def _generate_fal(
    prompt: str,
    width: int = 3840,
    height: int = 2160,
    quality: str = "low",
) -> Optional[str]:
    """
    调用 Fal.ai gpt-image-2 生成图片。

    Args:
        prompt: 生图 prompt
        width, height: 画布尺寸（必须 16 的倍数，最大 3840px，总像素 ≤ 8,294,400）
        quality: "low" | "medium" | "high"

    Returns:
        base64 图片字符串，失败返回 None
    """
    if not FAL_KEY:
        print("[image:fal] FAL_KEY 未设置")
        return None

    url = "https://fal.run/openai/gpt-image-2"
    headers = {
        "Authorization": f"Key {FAL_KEY}",
        "Content-Type": "application/json",
    }

    # ★ gpt-image-2 要求宽高均为 16 的倍数，否则自动向下取整导致尺寸偏差
    # 例如 1080 会被取整为 1072（1080/16=67.5, 67*16=1072）
    original_w, original_h = width, height
    width = (width // 16) * 16
    height = (height // 16) * 16
    if (width, height) != (original_w, original_h):
        print(f"[image:fal] 尺寸对齐 16 倍数: {original_w}x{original_h} → {width}x{height}")

    payload = {
        "prompt": prompt,
        "image_size": {"width": width, "height": height},
        "quality": quality,
        "num_images": 1,
        "output_format": "png",
        "sync_mode": True,  # 同步返回 base64 data URI，跳过队列轮询
    }

    total_pixels = width * height
    print(
        f"[image:fal] 请求 {FAL_MODEL}, "
        f"size={width}x{height} ({total_pixels / 1e6:.1f}MP), "
        f"quality={quality}, prompt_len={len(prompt)}"
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code == 200:
            data = resp.json()
            images = data.get("images", [])
            if images and len(images) > 0:
                img = images[0]
                img_url = img.get("url", "")

                # sync_mode=True 可能返回 data URI 或 HTTP URL
                if img_url.startswith("data:"):
                    # data:image/png;base64,xxxx
                    b64 = img_url.split(",", 1)[1] if "," in img_url else img_url
                    print(f"[image:fal] 生图成功 (data URI), base64_len={len(b64)}")
                    return b64
                elif img_url.startswith("http"):
                    print(f"[image:fal] 生图成功, 从 URL 下载: {img_url[:80]}...")
                    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as dl:
                        img_resp = await dl.get(img_url)
                        if img_resp.status_code == 200:
                            b64 = base64.b64encode(img_resp.content).decode("utf-8")
                            print(f"[image:fal] 下载完成, base64_len={len(b64)}")
                            return b64
                else:
                    print(f"[image:fal] 未知 URL 格式: {img_url[:100]}")
                    return None
            print(f"[image:fal] 返回数据无 images: {json.dumps(data, ensure_ascii=False)[:300]}")
            return None
        else:
            err = resp.text[:500]
            print(f"[image:fal] API 错误 {resp.status_code}: {err}")
            return None

    except httpx.TimeoutException:
        print("[image:fal] 请求超时 (300s)")
        return None
    except Exception as e:
        print(f"[image:fal] 异常: {type(e).__name__}: {e}")
        return None


# ============== 通道 B：可灵（备）==============

async def _generate_keling(prompt: str, size: str = "1080x1920") -> Optional[str]:
    """调用快手可灵 API 生成图片（兜底通道）。"""
    if not KELING_API_KEY:
        print("[image:keling] KELING_API_KEY 未设置，跳过")
        return None

    url = f"{KELING_BASE_URL}/images/generations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {KELING_API_KEY}",
    }

    payload = {
        "model": KELING_IMAGE_MODEL,
        "prompt": prompt,
        "n": 1,
        "size": size,
    }

    print(f"[image:keling] 尝试可灵 API")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code == 200:
            data = resp.json()
            images = data.get("data", [])
            if images and len(images) > 0:
                b64 = images[0].get("b64_json", "") or images[0].get("image_base64", "")
                if b64:
                    return b64
                url_val = images[0].get("url", "")
                if url_val:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as dl:
                        img_resp = await dl.get(url_val)
                        if img_resp.status_code == 200:
                            return base64.b64encode(img_resp.content).decode("utf-8")
            return None
        else:
            print(f"[image:keling] API 错误 {resp.status_code}: {resp.text[:300]}")
            return None

    except Exception as e:
        print(f"[image:keling] 异常: {type(e).__name__}: {e}")
        return None


# ============== 主入口：按句批量生图（v4 单图直生）==============

async def generate_all_images(
    task_id: int,
    db,
    style: str = "default",
    book_title: str = "",
    book_author: str = "",
    aspect_ratio: str = "9:16",
) -> dict:
    """
    v4 单图直生：每个句段独立请求 Fal.ai 生成一张高精单图。

    彻底废弃 v3 九宫格模式，解决：
    - 人像重影、肢体多指、面部表情扭曲崩坏
    - 裁切导致构图失控、焦点失焦

    流程:
    1. 读取 rewritten.txt → split_into_short_sentences() 切句
    2. for each sentence → build_single_segment_prompt + STYLE_PROMPT_MAP + SAFETY_SUFFIX
    3. Fal.ai gpt-image-2 单图直生（按 aspect_ratio 决定尺寸）
    4. PIL resize 到精确目标分辨率 → 写入 TaskImage 表
    5. 异常兜底：单张失败不阻塞后续 → 生成占位图

    Returns:
        {"total_segments": N, "total_images": N, "success": N, "failed": N}
    """
    from models import TaskImage, Task
    from services.llm_service import split_into_short_sentences

    # 1. 读取改写稿
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return {"error": f"任务 {task_id} 不存在", "total_segments": 0}

    rewritten = task.rewritten_transcript or ""
    if not rewritten.strip():
        tasks_dir = os.path.join(os.path.dirname(__file__), "..", "data", "tasks")
        task_dir = os.path.join(os.path.abspath(tasks_dir), str(task_id))
        rewritten_file = os.path.join(task_dir, "rewritten.txt")
        if os.path.exists(rewritten_file):
            with open(rewritten_file, "r", encoding="utf-8") as f:
                rewritten = f.read()

    if not rewritten.strip():
        return {"error": "没有改写稿，请先完成文本改写", "total_segments": 0}

    # 2. 按强标点切句（与视频合成阶段参数完全一致）
    sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)
    total_segments = len(sentences)

    avg_chars = len(rewritten) / max(1, total_segments)
    print(
        f"[image:v4] 任务 {task_id}: "
        f"全文 {len(rewritten)} 字 → {total_segments} 句 "
        f"(平均 {avg_chars:.0f} 字/句) → {total_segments} 张单图直生"
    )

    book_title = book_title or task.book_title or ""
    book_author = book_author or task.book_author or ""
    style_bible = STYLE_BIBLES.get(style, STYLE_BIBLES["default"])
    quality = os.getenv("FAL_QUALITY", "low")

    # 3. 根据画幅比确定请求尺寸与目标尺寸
    if aspect_ratio == "16:9":
        REQUEST_W, REQUEST_H = 3840, 2160
        TARGET_W, TARGET_H = 1280, 720
    elif aspect_ratio == "3:4":
        REQUEST_W, REQUEST_H = 768, 1024
        TARGET_W, TARGET_H = 768, 1024
    else:
        REQUEST_W, REQUEST_H = 2160, 3840  # 9:16 超采样
        TARGET_W, TARGET_H = 1080, 1920

    # 4. 数据目录
    tasks_dir = os.path.join(os.path.dirname(__file__), "..", "data", "tasks")
    task_dir = os.path.join(os.path.abspath(tasks_dir), str(task_id))
    images_dir = os.path.join(task_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # 5. 清理旧配图记录
    old_count = db.query(TaskImage).filter(TaskImage.task_id == task_id).delete()
    db.commit()
    if old_count > 0:
        print(f"[image:v4] 已清除 {old_count} 条旧配图记录")

    # 6. 逐段单图直生
    total_success = 0
    total_failed = 0

    for seg_idx, sentence in enumerate(sentences):
        target_path = os.path.join(images_dir, f"seg_{seg_idx:03d}.png")

        # 跳过已存在的成功图片（支持断点续跑）
        if os.path.exists(target_path) and os.path.getsize(target_path) > 1000:
            print(f"[image:v4] 段 {seg_idx + 1}/{total_segments} 已存在，跳过")
            total_success += 1
            continue

        text_len = len(sentence.strip())
        print(
            f"[image:v4] 段 {seg_idx + 1}/{total_segments}: "
            f"{text_len} 字, size={REQUEST_W}x{REQUEST_H}, aspect={aspect_ratio}"
        )

        # 6a. 构建 Prompt（风格圣经 + 风格后缀 + 安全补丁）
        base_prompt = build_single_segment_prompt(
            text=sentence,
            book_title=book_title,
            book_author=book_author,
            segment_index=seg_idx,
            total_segments=total_segments,
            style_bible=style_bible,
            aspect_ratio=aspect_ratio,
        )
        style_suffix = STYLE_PROMPT_MAP.get(style, STYLE_PROMPT_MAP["default"])
        final_prompt = base_prompt + style_suffix + SAFETY_SUFFIX

        # 6b. 保存 prompt 到文件
        prompt_path = os.path.join(images_dir, f"seg_{seg_idx:03d}_prompt.txt")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(final_prompt)

        # 6c. 多通道生图（fal → keling fallback）
        img_bytes = None
        error_msg = ""
        try:
            b64 = await _generate_fal(final_prompt, width=REQUEST_W, height=REQUEST_H, quality=quality)
            if b64:
                img_bytes = base64.b64decode(b64)
            else:
                # fal 失败 → 尝试 keling
                keling_size = f"{TARGET_W}x{TARGET_H}"
                b64 = await _generate_keling(final_prompt, size=keling_size)
                if b64:
                    img_bytes = base64.b64decode(b64)
                else:
                    error_msg = "所有生图通道均失败"
        except Exception as e:
            error_msg = f"生图异常: {type(e).__name__}: {e}"
            print(f"[image:v4] 段 {seg_idx + 1} 异常: {error_msg}")

        # 6d. 写入 & 校验
        if img_bytes:
            tmp_path = target_path + ".tmp"
            try:
                with open(tmp_path, "wb") as f:
                    f.write(img_bytes)
                from PIL import Image as PILImage
                pil_img = PILImage.open(tmp_path).convert("RGB")
                actual_w, actual_h = pil_img.size
                if (actual_w, actual_h) != (TARGET_W, TARGET_H):
                    print(f"[image:v4] 缩图: {actual_w}x{actual_h} → {TARGET_W}x{TARGET_H}")
                    pil_img = pil_img.resize((TARGET_W, TARGET_H), PILImage.LANCZOS)
                pil_img.save(target_path, "PNG", optimize=True)
                pil_img.close()
                os.remove(tmp_path)
                print(f"[image:v4] 段 {seg_idx + 1} 落盘: {target_path} ({os.path.getsize(target_path)} bytes)")
                total_success += 1
            except Exception as e:
                print(f"[image:v4] 段 {seg_idx + 1} 写盘失败: {e}")
                img_bytes = None
                error_msg = f"写盘失败: {e}"
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        # 6e. 失败兜底：生成占位图
        if not img_bytes:
            print(f"[image:v4] 段 {seg_idx + 1} 失败 → 占位图: {error_msg}")
            try:
                from PIL import Image as PILImage
                ph = PILImage.new("RGB", (TARGET_W, TARGET_H), (30, 30, 35))
                ph.save(target_path, "PNG", optimize=True)
                ph.close()
            except Exception:
                pass
            total_failed += 1

        # 6f. 写入数据库
        ti = TaskImage(
            task_id=task_id,
            segment_index=seg_idx,
            grid_index=-1,  # v4: 无九宫格，统一 -1
            cell_position=1,
            image_path=target_path if (os.path.exists(target_path) and os.path.getsize(target_path) > 1000) else None,
            prompt_used=final_prompt,
            status="success" if img_bytes else "failed",
            error_msg=error_msg if error_msg else None,
        )
        db.add(ti)
        db.commit()

        # 段间稍息
        if seg_idx < total_segments - 1:
            await asyncio.sleep(0.5)

    # 7. 收尾
    task.current_step = max(task.current_step, 4)
    db.commit()

    print(
        f"[image:v4] all done: {total_success} ok, {total_failed} fail | "
        f"style={style}, aspect={aspect_ratio}"
    )
    return {
        "total_segments": total_segments,
        "total_images": total_success,
        "success": total_success,
        "failed": total_failed,
    }


async def regenerate_single_image(
    task_id: int,
    segment_index: int,
    db,
    style: str = "default",
    book_title: str = "",
    book_author: str = "",
    aspect_ratio: str = "9:16",
) -> dict:
    """
    v4 单段配图重跑：单张独立生图（高精直出，不走九宫格）。
    """
    from models import TaskImage, Task
    from services.llm_service import split_into_short_sentences

    task = db.query(Task).filter(Task.id == task_id).first()
    book_title = book_title or (task.book_title if task else "") or ""
    book_author = book_author or (task.book_author if task else "") or ""
    style_bible = STYLE_BIBLES.get(style, STYLE_BIBLES["default"])
    quality = os.getenv("FAL_QUALITY", "low")

    tasks_dir = os.path.join(os.path.dirname(__file__), "..", "data", "tasks")
    task_dir = os.path.join(os.path.abspath(tasks_dir), str(task_id))

    rewritten = task.rewritten_transcript or ""
    rewritten_file = os.path.join(task_dir, "rewritten.txt")
    if not rewritten and os.path.exists(rewritten_file):
        with open(rewritten_file, "r", encoding="utf-8") as f:
            rewritten = f.read()

    sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)

    if segment_index < 0 or segment_index >= len(sentences):
        return {"error": f"句子索引 {segment_index} 越界 (共 {len(sentences)} 句)"}

    text = sentences[segment_index]
    images_dir = os.path.join(task_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # v4: 尺寸由 aspect_ratio 决定
    if aspect_ratio == "16:9":
        REQUEST_W, REQUEST_H = 3840, 2160
        TARGET_W, TARGET_H = 1280, 720
    else:
        REQUEST_W, REQUEST_H = 2160, 3840
        TARGET_W, TARGET_H = 1080, 1920

    # 构建 Prompt + 风格后缀 + 安全补丁
    base_prompt = build_single_segment_prompt(
        text=text,
        book_title=book_title,
        book_author=book_author,
        segment_index=segment_index,
        total_segments=len(sentences),
        style_bible=style_bible,
        aspect_ratio=aspect_ratio,
    )
    style_suffix = STYLE_PROMPT_MAP.get(style, STYLE_PROMPT_MAP["default"])
    prompt = base_prompt + style_suffix + SAFETY_SUFFIX

    print(f"[image:single] 单句配图 task={task_id} sent={segment_index}, text_len={len(text)}, aspect={aspect_ratio}")

    b64 = await _generate_fal(prompt, width=REQUEST_W, height=REQUEST_H, quality=quality)
    img_bytes = base64.b64decode(b64) if b64 else None

    target_path = os.path.join(images_dir, f"seg_{segment_index:03d}.png")

    if not img_bytes:
        existing = db.query(TaskImage).filter(
            TaskImage.task_id == task_id, TaskImage.segment_index == segment_index
        ).first()
        if existing:
            existing.status = "failed"
            existing.error_msg = "单图生图失败：所有通道均失败"
            existing.prompt_used = prompt
        else:
            db.add(TaskImage(
                task_id=task_id,
                segment_index=segment_index,
                grid_index=-1,
                cell_position=1,
                image_path=None,
                prompt_used=prompt,
                status="failed",
                error_msg="单图生图失败：所有通道均失败",
            ))
        db.commit()
        return {"error": "所有生图通道均失败", "segment_index": segment_index}

    # --- 写入临时文件 → PIL 校验尺寸 → resize 到精确 TARGET_W×TARGET_H ---
    tmp_path = target_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(img_bytes)

    try:
        from PIL import Image as PILImage
        pil_img = PILImage.open(tmp_path).convert("RGB")
        actual_w, actual_h = pil_img.size
        if (actual_w, actual_h) != (TARGET_W, TARGET_H):
            print(f"[image:single] 超采样缩图: {actual_w}x{actual_h} → {TARGET_W}x{TARGET_H}")
            pil_img = pil_img.resize((TARGET_W, TARGET_H), PILImage.LANCZOS)
        else:
            print(f"[image:single] 尺寸已正确: {actual_w}x{actual_h}，无需缩放")
        pil_img.save(target_path, "PNG", optimize=True)
        print(f"[image:single] 单图已保存: {target_path} ({os.path.getsize(target_path)} bytes, {TARGET_W}x{TARGET_H})")
    except Exception as e:
        print(f"[image:single] PIL 校验/缩放失败: {e}，直接使用原始数据")
        with open(target_path, "wb") as f:
            f.write(img_bytes)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    existing = db.query(TaskImage).filter(
        TaskImage.task_id == task_id, TaskImage.segment_index == segment_index
    ).first()
    if existing:
        existing.image_path = target_path
        existing.grid_index = -1
        existing.cell_position = 1
        existing.prompt_used = prompt
        existing.status = "success"
        existing.error_msg = None
    else:
        db.add(TaskImage(
            task_id=task_id,
            segment_index=segment_index,
            grid_index=-1,
            cell_position=1,
            image_path=target_path,
            prompt_used=prompt,
            status="success",
        ))
    db.commit()

    return {
        "segment_index": segment_index,
        "image_url": f"/images/{task_id}/images/seg_{segment_index:03d}.png",
        "status": "success",
        "message": f"句子 {segment_index + 1} 配图已重新生成",
    }


def get_images_for_task(task_id: int, db) -> list[dict]:
    """查询任务的所有配图记录（v4：按 segment_index 排序，无九宫格）"""
    from models import TaskImage
    from services.llm_service import split_into_short_sentences

    records = (
        db.query(TaskImage)
        .filter(TaskImage.task_id == task_id)
        .order_by(TaskImage.segment_index)
        .all()
    )

    # 读取句子文本用于前端展示
    tasks_dir = os.path.join(os.path.dirname(__file__), "..", "data", "tasks")
    task_dir = os.path.join(os.path.abspath(tasks_dir), str(task_id))
    rewritten_file = os.path.join(task_dir, "rewritten.txt")
    sentences = []
    if os.path.exists(rewritten_file):
        with open(rewritten_file, "r", encoding="utf-8") as f:
            rewritten = f.read()
        sentences = split_into_short_sentences(rewritten, max_chars=80, min_chars=30)

    import time as _time
    _cache_buster = int(_time.time())

    return [
        {
            "id": r.id,
            "task_id": r.task_id,
            "segment_index": r.segment_index,
            "grid_index": -1,  # v4: 单图直生，无九宫格
            "cell_position": 1,
            "image_url": f"/images/{task_id}/images/seg_{r.segment_index:03d}.png?t={_cache_buster}" if r.image_path else None,
            "image_exists": bool(r.image_path and os.path.exists(r.image_path)),
            "status": r.status,
            "error_msg": r.error_msg,
            "sentence_text": sentences[r.segment_index] if r.segment_index < len(sentences) else "",
        }
        for r in records
    ]
