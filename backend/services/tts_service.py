"""
TTS 配音服务
优先调用本地 index-tts2 服务（:7860），不可用时降级到 edge-tts。
支持 SiliconFlow 音色克隆（FunAudioLLM/CosyVoice2-0.5B）。

接口（供 main.py 调用）:
    generate_audio(text, voice, output_path) -> None
    generate_audio_with_reference(text, reference_audio_path, output_path) -> None
    get_voices() -> list[dict]
"""
import os
import re
import asyncio
import httpx
import edge_tts
from dotenv import load_dotenv
load_dotenv()
from edge_tts.communicate import mkssml as _orig_mkssml, TTSConfig
from typing import Optional


INDEX_TTS2_URL = "http://localhost:7860"


# ============== edge_tts SSML bug 热修复 ==============
# 背景：edge_tts 内部 mkssml() 会对整个文本调 escape()，
# 导致 build_ssml 输出的 &amp; 被二次转义为 &amp;amp;，
# 微软收到非法 XML，<break> 标签被吞，音频为空（< 2KB）。
# 修复：patch mkssml，当输入已经是 <speak> 开头时跳过二次转义。
# 这两个 patch 在 test_full.py / test_tts.py 中验证有效。

def _patched_escape(s: str) -> str:
    return s.replace("&", "&amp;")

def _patched_mkssml(tc, text):
    if isinstance(text, bytes):
        text = text.decode('utf-8')
    if text.strip().startswith('<speak'):
        return text
    return _orig_mkssml(tc, text)

edge_tts.communicate.escape = _patched_escape
edge_tts.communicate.mkssml = _patched_mkssml
INDEX_TTS2_TIMEOUT = 5.0   # 5 秒超时，7860 卡顿不应拖垮主服务


# ============== 音色列表 ==============

def get_voices() -> list[dict]:
    """返回可用音色列表（edge-tts + 豆包语音合成 V3）"""
    voices = []

    # ---- 豆包语音合成 V3 大模型音色（成熟女声 / 带货首选）----
    try:
        from services.volc_tts_v3_service import get_voices as _get_volc_voices
        voices.extend(_get_volc_voices())
    except ImportError:
        pass

    # ---- edge-tts 音色 ----
    voices.extend([
        {"id": "zf_yunxi",   "name": "云希 — 稳重中年男声（带货首选）", "language": "zh-CN"},
        {"id": "zf_yunjian", "name": "云健 — 激情男声（秒杀/高气场）", "language": "zh-CN"},
        {"id": "zf_yunxia",  "name": "云夏 — 沉稳男声（知识科普）", "language": "zh-CN"},
        {"id": "zf_yunyang", "name": "云扬 — 阳光男声（轻松风格）", "language": "zh-CN"},
        {"id": "zf_xiaoxiao","name": "晓晓 — 温柔女声（说书/慢节奏）",   "language": "zh-CN"},
        {"id": "zf_xiaoyi",  "name": "晓伊 — 轻柔女声（邻家唠嗑）",   "language": "zh-CN"},
        {"id": "zf_hsiaochen","name": "曉臻 — 台腔成熟女声（稳重可信·台湾腔）", "language": "zh-TW"},
        {"id": "zf_hsiaoyu",  "name": "曉宇 — 台腔知性女声（娓娓道来·台湾腔）", "language": "zh-TW"},
    ])

    return voices


# ============== SiliconFlow 音色克隆 TTS ==============
# 延迟导入，避免循环依赖
def _get_siliconflow_service():
    from services.siliconflow_tts_service import synthesize as sf_synthesize
    return sf_synthesize


async def generate_audio_with_reference(
    text: str,
    reference_audio_path: str,
    output_path: str,
    voice_name: str = "custom_clone",
) -> Optional[str]:
    """
    使用参考音频音色克隆生成 TTS（SiliconFlow FunAudioLLM/CosyVoice2）

    Args:
        text: 待合成文本
        reference_audio_path: 参考音频文件路径（.mp3/.wav/.m4a）
        output_path: 输出文件路径（.mp3）
        voice_name: 自定义音色名称（用于标识）

    Returns:
        output_path（成功）或 None（失败）
    """
    from services.siliconflow_tts_service import upload_reference_audio, synthesize as sf_synthesize
    import os

    if not os.path.exists(reference_audio_path):
        print(f"[tts] 参考音频不存在: {reference_audio_path}")
        return None

    # 上传参考音频获取 voice_uri
    voice_uri, err = await upload_reference_audio(
        audio_path=reference_audio_path,
        custom_name=voice_name,
        reference_text="",
    )
    if not voice_uri:
        print(f"[tts] 参考音频上传失败: {err or reference_audio_path}")
        return None

    # 用音色 URI 合成
    result = await sf_synthesize(
        text=text,
        voice_uri=voice_uri,
        output_path=output_path,
    )
    return result


# ============== 核心生成函数 ==============

async def generate_audio(
    text: str,
    voice: str = "vc_shuangsisi",
    rate: str = "+0%",
    output_path: str = "output.wav"
) -> str:
    """
    v5 生成 TTS 音频 — 3 黄金音色路由。

    路由规则：
    - vc_shuangsisi → 火山引擎 seed-tts 标准带货音色
    - vc_clone_female → SiliconFlow 历史克隆女声
    - vc_clone_wanglq → 火山引擎声音复刻 王立群 (S_FqsgYzu92)
    - 其他 vc_* → 火山引擎 V3 合成（降级 edge-tts）
    - zf_* → edge-tts
    """

    # ---- vc_clone_female: SiliconFlow 历史克隆女声 ----
    if voice == "vc_clone_female":
        from services.siliconflow_tts_service import synthesize as sf_synthesize
        # 硬编码历史克隆女声 voice_uri
        SF_FEMALE_VOICE_URI = "speech:voice_40_1783427531231:d8uv3ftsssvc73almr4g:rxcxjvoiekndkjtzyela"
        result = await sf_synthesize(text=text, voice_uri=SF_FEMALE_VOICE_URI, output_path=output_path)
        if result:
            return result
        print(f"[tts] SiliconFlow 克隆女声合成失败，降级到 edge-tts")
        await _edge_tts_fallback(text, "zf_yunxi", rate, output_path)
        return output_path

    # ---- vc_clone_wanglq: 火山引擎声音复刻 王立群 ----
    if voice == "vc_clone_wanglq":
        from services.volc_tts_v3_service import synthesize_clone as volc_clone_synth
        result = await volc_clone_synth(text=text, speaker_id="S_FqsgYzu92", output_path=output_path)
        if result:
            return result
        print(f"[tts] 火山引擎王立群克隆音色合成失败，降级到 edge-tts")
        await _edge_tts_fallback(text, "zf_yunxi", rate, output_path)
        return output_path

    # ---- 豆包语音 V3 路由（vc_shuangsisi 及其他 vc_*）----
    if voice.startswith("vc_"):
        from services.volc_tts_v3_service import synthesize as volc_synthesize
        result = await volc_synthesize(text=text, voice=voice, output_path=output_path)
        if result:
            return result
        # 豆包失败 → 降级到 edge-tts
        print(f"[tts] 豆包 V3 合成失败，降级到 edge-tts")
        await _edge_tts_fallback(text, "zf_yunxi", rate, output_path)
        return output_path

    # ---- 原有路径：index-tts2 → edge-tts ----
    success = await _try_index_tts2(text, voice, rate, output_path)
    if success:
        return output_path

    print(f"[tts] index-tts2 不可用，降级到 edge-tts")
    await _edge_tts_fallback(text, voice, rate, output_path)
    return output_path


# ============== index-tts2 本地服务调用 ==============

async def _try_index_tts2(text: str, voice: str, rate: str, output_path: str) -> bool:
    """
    尝试调用本地 index-tts2 服务。
    Returns True if successful, False if service unavailable or failed.
    """
    try:
        async with httpx.AsyncClient(timeout=INDEX_TTS2_TIMEOUT) as client:
            response = await client.post(
                f"{INDEX_TTS2_URL}/tts",
                json={"text": text, "voice": voice, "rate": rate},
            )

        if response.status_code == 200:
            audio_bytes = response.content
            if len(audio_bytes) < 1000:
                # 音频太短，可能是空响应
                print(f"[tts] index-tts2 返回异常短音频: {len(audio_bytes)} bytes")
                return False

            with open(output_path, "wb") as f:
                f.write(audio_bytes)
            print(f"[tts] index-tts2 合成成功: {output_path} ({len(audio_bytes)} bytes)")
            return True

        else:
            print(f"[tts] index-tts2 返回错误 {response.status_code}: {response.text[:200]}")
            return False

    except (httpx.ConnectError, httpx.TimeoutException):
        print(f"[tts] index-tts2 服务未启动或连接超时 (:7860)，将降级")
        return False
    except Exception as e:
        print(f"[tts] index-tts2 调用异常: {type(e).__name__}: {str(e)}，降级到 edge-tts")
        return False


# ============== edge-tts 降级引擎 ==============

EDGE_TTS_VOICE_MAP = {
    "zf_yunxi":    "zh-CN-YunxiNeural",     # 云希 — 稳重中年男声（带货首选）
    "zf_yunjian":  "zh-CN-YunjianNeural",   # 云健 — 激情男声（秒杀专用）
    "zf_yunxia":   "zh-CN-YunxiaNeural",    # 云夏 — 沉稳男声
    "zf_yunyang":  "zh-CN-YunyangNeural",   # 云扬 — 阳光男声
    "zf_xiaoxiao": "zh-CN-XiaoxiaoNeural",  # 晓晓 — 温柔女声
    "zf_xiaoyi":   "zh-CN-XiaoyiNeural",    # 晓伊 — 轻柔女声
    "zf_hsiaochen":"zh-TW-HsiaoChenNeural", # 曉臻 — 台腔成熟女声
    "zf_hsiaoyu":  "zh-TW-HsiaoYuNeural",   # 曉宇 — 台腔知性女声
    "default":     "zh-CN-YunxiNeural",     # 默认云希（带货场景首选）
}


async def _edge_tts_fallback(text: str, voice: str, rate: str, output_path: str):
    """
    edge-tts 降级引擎（严格单音色 + 熔断保护）。

    策略：
    - 全程使用用户指定的同一个音色，绝不切换（保证作品音色一致性）
    - 每个片段最多重试 3 次，每次间隔 2 秒指数退避
    - 3 次全部失败 → 立即 raise RuntimeError，触发上层熔断
    - edge-tts save() 用 asyncio.wait_for 加 30s 超时，防止无限期挂起
    """
    import subprocess

    edge_voice = EDGE_TTS_VOICE_MAP.get(voice, EDGE_TTS_VOICE_MAP["default"])

    def split_text_by_sentence(text: str, max_chars: int = 400) -> list[str]:
        paragraphs = text.split('\n')
        chunks = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(para) <= max_chars:
                chunks.append(para)
            else:
                sentence_pattern = re.compile(r'([^。！？；\n]+[。！？；])')
                sentences = sentence_pattern.findall(para)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) <= max_chars:
                        current += sent
                    else:
                        if current:
                            chunks.append(current)
                        if len(sent) > max_chars:
                            for i in range(0, len(sent), max_chars):
                                chunks.append(sent[i:i + max_chars])
                            current = ""
                        else:
                            current = sent
                if current:
                    chunks.append(current)
        return chunks

    def merge_audio_ffmpeg(segment_files: list[str], output: str) -> None:
        list_file = os.path.join(os.path.dirname(segment_files[0]) or ".", "_merge_list.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for seg in segment_files:
                f.write(f"file '{os.path.abspath(seg)}'\n")
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", output],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace",
        )
        try:
            os.remove(list_file)
        except Exception:
            pass
        if result.returncode != 0:
            stderr = (result.stderr or "")[:500]
            raise RuntimeError(f"FFmpeg 拼接失败: {stderr}")

    async def _save_with_timeout(communicate: edge_tts.Communicate, path: str, timeout: float = 30.0):
        """
        用 asyncio.wait_for 给 edge-tts save() 加超时保护。
        30 秒内未完成 → 取消任务 → 删除残片 → 抛出超时异常。
        """
        task = asyncio.create_task(communicate.save(path))
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            if not task.done():
                task.cancel()
            try:
                await task
            except Exception:
                pass
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
            raise RuntimeError(
                f"edge-tts save() 超时 {timeout}s，进程可能被挂起，请检查网络或切换音色"
            )

    chunks = split_text_by_sentence(text, max_chars=400)
    print(f"[tts][edge-tts] voice={edge_voice} rate={rate}，文字 {len(text)} 字，切分为 {len(chunks)} 段")

    segment_files: list[str] = []
    task_folder = os.path.dirname(output_path) or "."

    for i, chunk in enumerate(chunks):
        segment_path = os.path.join(task_folder, f"_tts_seg_{i:03d}.mp3")
        segment_files.append(segment_path)
        last_error = None

        for attempt in range(1, 4):
            try:
                communicate = edge_tts.Communicate(chunk, voice=edge_voice, rate=rate)
                await _save_with_timeout(communicate, segment_path, timeout=30.0)

                # 文件大小校验：小于 1KB 认定为空音频，当作失败处理
                file_size = os.path.getsize(segment_path)
                if file_size < 1024:
                    os.remove(segment_path)
                    raise RuntimeError(f"空音频文件（{file_size} bytes）")

                print(f"[tts][edge-tts] 片段 {i+1}/{len(chunks)} 成功（{file_size} bytes）")
                break  # 成功，跳出重试循环

            except Exception as e:
                last_error = e
                err_str = str(e)
                if "TimeoutError" in err_str or "超时" in err_str or "timed out" in err_str.lower():
                    print(f"[tts][edge-tts] 片段 {i+1} 第 {attempt} 次超时，{2 ** attempt}s 后重试...")
                elif "No audio was received" in err_str:
                    print(f"[tts][edge-tts] 片段 {i+1} 第 {attempt} 次无音频，{2 ** attempt}s 后重试...")
                else:
                    print(f"[tts][edge-tts] 片段 {i+1} 第 {attempt} 次异常: {e}，{2 ** attempt}s 后重试...")

                if os.path.exists(segment_path):
                    try:
                        os.remove(segment_path)
                    except Exception:
                        pass

                if attempt < 3:
                    await asyncio.sleep(2 ** attempt)  # 指数退避：2s → 4s

        # ---- 3 次重试全部失败 → 熔断：立即抛异常，不继续，不写占位 ----
        if not os.path.exists(segment_path):
            raise RuntimeError(
                f"片段 {i+1}/{len(chunks)}（{len(chunk)}字）经过 3 次重试后失败。"
                f"音色={edge_voice}，错误={last_error}。"
                f"建议：检查网络或更换音色（云希/晓晓/云健等）。"
            )

        # 片段之间错开 0.5 秒，避免高频请求触发微软限流
        if i < len(chunks) - 1:
            await asyncio.sleep(0.5)

    merge_audio_ffmpeg(segment_files, output_path)

    # 清理临时切片
    for seg in segment_files:
        try:
            os.remove(seg)
        except Exception:
            pass

    print(f"[tts][edge-tts] 合成完成: {output_path}")


def _write_silent_placeholder(path: str, duration_ms: int = 2000):
    """生成静音占位音频文件（某段完全失败时的保底）"""
    import subprocess
    try:
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
            "-t", str(duration_ms / 1000),
            "-q:a", "9", path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
           encoding="utf-8", errors="replace")
    except Exception:
        pass
