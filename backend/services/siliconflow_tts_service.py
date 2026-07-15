"""
SiliconFlow 声音克隆 TTS 服务
基于 FunAudioLLM/CosyVoice2-0.5B 模型

使用流程：
1. upload_reference_audio(audio_path, name, text) → 返回 voice_uri
2. synthesize(text, voice_uri, output_path) → 生成同音色音频

认证：Bearer Token，环境变量 SILICONFLOW_API_KEY

限制：参考音频时长不得超过 30 秒（CosyVoice2 硬性限制）
"""
import asyncio
import datetime
import os
import base64
import json
import subprocess
import httpx
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

SILICONFLOW_KEY = os.getenv("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE = "https://api.siliconflow.cn"
TTS_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
TTS_TIMEOUT = 120.0
MAX_REF_DURATION_SEC = 30  # CosyVoice2 限制：参考音频 ≤ 30 秒


def _find_ffmpeg() -> str | None:
    """查找 ffmpeg 可执行文件路径"""
    import shutil
    path = shutil.which("ffmpeg")
    if path:
        return path
    for candidate in [r"D:\ffmpeg.exe", r"C:\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]:
        if os.path.exists(candidate):
            return candidate
    return None


def _get_audio_duration(path: str) -> float:
    """用 ffmpeg 获取音频时长（秒）。
    返回值：>=0 有效时长，-1 文件损坏/读取出错，-2 ffmpeg 不可用"""
    ffmpeg_bin = _find_ffmpeg()

    # 优先用 ffprobe（更精确），fallback 到 ffmpeg
    if ffmpeg_bin:
        ffprobe_bin = os.path.join(os.path.dirname(ffmpeg_bin), "ffprobe")
        if not os.path.exists(ffprobe_bin):
            ffprobe_bin = "ffprobe"
        try:
            result = subprocess.run(
                [ffprobe_bin, "-v", "error", "-show_entries",
                 "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, encoding="utf-8", errors="replace", timeout=10,
            )
            if result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        # Fallback：用 ffmpeg 提取时长
        try:
            result = subprocess.run(
                [ffmpeg_bin, "-i", path],
                capture_output=True, encoding="utf-8", errors="replace", timeout=10,
            )
            for line in result.stderr.splitlines():
                if "Duration:" in line:
                    token = line.split("Duration:")[1].split(",")[0].strip()
                    h, m, s = token.split(":")
                    return float(h) * 3600 + float(m) * 60 + float(s)
        except Exception:
            pass
        # ffmpeg 找到了但读取出错 → 文件可能损坏
        return -1

    # ffmpeg 未找到，尝试直接调用 ffprobe（可能在 PATH 上但 shutil.which 未找到）
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, encoding="utf-8", errors="replace", timeout=10,
        )
        if result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass

    print("[siliconflow] WARNING: ffmpeg/ffprobe 未找到，无法校验音频时长。请安装 ffmpeg 以确保时长校验。")
    return -2


def _get_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=SILICONFLOW_BASE,
        headers={"Authorization": f"Bearer {SILICONFLOW_KEY}"},
        timeout=httpx.Timeout(TTS_TIMEOUT),
    )


# ============== 参考音频上传 ==============

class SiliconFlowError(Exception):
    """携带具体错误信息的异常"""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


async def upload_reference_audio(
    audio_path: str,
    custom_name: str,
    reference_text: str = "",
) -> tuple[Optional[str], Optional[str]]:
    """
    上传参考音频，获取音色 URI

    Args:
        audio_path: 参考音频文件路径（.mp3 / .wav / .m4a）
        custom_name: 自定义音色名称（唯一标识）
        reference_text: 参考音频对应的文本（可选，用于训练）

    Returns:
        (voice_uri, error_msg) — voice_uri 成功时有值，error_msg 失败时有值
    """
    if not SILICONFLOW_KEY:
        msg = "SILICONFLOW_API_KEY 未设置"
        print(f"[siliconflow] {msg}")
        return None, msg

    if not os.path.exists(audio_path):
        msg = f"参考音频文件不存在: {audio_path}"
        print(f"[siliconflow] {msg}")
        return None, msg

    # 时长校验：CosyVoice2 上传参考音频硬性限制 ≤ 30 秒
    duration = _get_audio_duration(audio_path)
    if duration > MAX_REF_DURATION_SEC:
        msg = f"参考音频时长 {duration:.1f}s，超过 30s 上限，请先剪辑至 30 秒以内"
        print(f"[siliconflow] {msg}")
        return None, msg
    if duration == -2:
        # ffmpeg 未安装，无法校验，给警告但继续上传（API 会在超时时拒绝）
        print(f"[siliconflow] 无法获取音频时长（ffmpeg 未安装），跳过校验直接上传。如果音频超过 30 秒，API 会拒绝（错误码 20015）。")
    elif duration < 0:
        # -1: 文件损坏或读取出错
        print(f"[siliconflow] 无法读取音频时长，可能是文件损坏或格式不支持，跳过校验直接上传")

    client = _get_client()
    try:
        with open(audio_path, "rb") as f:
            files = {
                "file": (
                    os.path.basename(audio_path),
                    f,
                    "audio/mpeg",
                )
            }
            data = {
                "model": TTS_MODEL,
                "customName": custom_name,
                "text": reference_text or custom_name,
            }
            resp = await client.post(
                "/v1/uploads/audio/voice",
                files=files,
                data=data,
            )

        if resp.status_code == 200:
            result = resp.json()
            uri = result.get("uri", "")
            print(f"[siliconflow] 参考音频上传成功: {custom_name} -> {uri}")
            return uri, None
        else:
            msg = f"上传失败 {resp.status_code}: {resp.text[:200]}"
            print(f"[siliconflow] {msg}")
            return None, msg

    except Exception as e:
        msg = f"上传异常: {type(e).__name__}: {e}"
        print(f"[siliconflow] {msg}")
        return None, msg
    finally:
        await client.aclose()


# ============== 音色克隆 TTS 合成 ==============

MAX_CHUNK_CHARS = 80   # CosyVoice2 单次输出受参考音频时长限制，输入太长反而截断


def _split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """
    按句子切分文本，每段不超过 max_chars 字符。
    尽量以完整句子为边界切分。
    """
    import re
    # 按句子符号切分
    sentence_pattern = re.compile(r'([^。！？；\n]+[。！？；]?)')
    chunks, current = [], ""

    for sentence in sentence_pattern.findall(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(current) + len(sentence) <= max_chars:
            current += sentence
        else:
            if current:
                chunks.append(current)
            # 如果单句本身就超限，强切
            if len(sentence) > max_chars:
                for i in range(0, len(sentence), max_chars):
                    chunks.append(sentence[i:i + max_chars])
                current = ""
            else:
                current = sentence
    if current:
        chunks.append(current)
    return chunks


async def synthesize(
    text: str,
    voice_uri: str,
    output_path: str,
    reference_audio_path: Optional[str] = None,
    model: str = TTS_MODEL,
) -> Optional[str]:
    """
    使用指定音色合成语音。文本超长时自动分段并 FFmpeg 拼接。

    Args:
        text: 待合成文本
        voice_uri: 音色 URI（从 upload_reference_audio 获取）
        output_path: 输出文件路径（.mp3）
        reference_audio_path: 可选，直接传参考音频（绕过上传步骤）
        model: TTS 模型，默认 FunAudioLLM/CosyVoice2-0.5B

    Returns:
        output_path（成功）或 None（失败）
    """
    if not SILICONFLOW_KEY:
        print("[siliconflow] SILICONFLOW_API_KEY 未设置")
        return None

    if not voice_uri and reference_audio_path:
        voice_uri, err = await upload_reference_audio(
            reference_audio_path,
            custom_name=f"ref_{os.path.basename(reference_audio_path)}",
            reference_text="",
        )
        if not voice_uri:
            print(f"[siliconflow] 参考音频上传失败: {err}")
            return None

    if not voice_uri:
        print("[siliconflow] 缺少 voice_uri，请先上传参考音频")
        return None

    # 短文本直接合成
    if len(text) <= MAX_CHUNK_CHARS:
        return await _synthesize_single(text, voice_uri, output_path, model)

    # 长文本：分段合成 + FFmpeg 拼接
    chunks = _split_text(text, MAX_CHUNK_CHARS)
    print(f"[siliconflow] 文本过长（{len(text)} 字），自动分为 {len(chunks)} 段合成")
    return await _synthesize_segments(chunks, voice_uri, output_path, model)


async def _synthesize_single(text: str, voice_uri: str, output_path: str, model: str) -> Optional[str]:
    """单次合成（短文本）"""
    client = _get_client()
    try:
        payload = {
            "model": model,
            "input": text,
            "voice": voice_uri,
            "response_format": "mp3",
            "sample_rate": 32000,
        }
        print(f"[siliconflow] 单段合成: {len(text)}字 -> {output_path}")
        resp = await client.post("/v1/audio/speech", json=payload)

        if resp.status_code == 200:
            audio_bytes = resp.content
            ct = resp.headers.get("content-type", "")
            if len(audio_bytes) < 1000 or "text" in ct or "json" in ct:
                # 尝试从 JSON 响应中提取错误信息
                error_detail = ""
                try:
                    error_json = json.loads(audio_bytes)
                    error_detail = error_json.get("message", "") or error_json.get("error", "") or str(error_json)
                except Exception:
                    error_detail = audio_bytes.decode("utf-8", errors="replace")[:200]
                print(f"[siliconflow] 合成返回了错误而非音频: {error_detail}")
                return None
            with open(output_path, "wb") as f:
                f.write(audio_bytes)
            print(f"[siliconflow] 合成成功: {output_path} ({len(audio_bytes)} bytes)")
            return output_path
        else:
            # 非 200：尝试解析 JSON 错误体
            error_text = ""
            try:
                error_json = resp.json()
                error_text = error_json.get("message", "") or error_json.get("error", "") or resp.text[:200]
            except Exception:
                error_text = resp.text[:200]
            print(f"[siliconflow] 合成失败 {resp.status_code}: {error_text}")
            return None
    except Exception as e:
        print(f"[siliconflow] 合成异常: {type(e).__name__}: {e}")
        return None
    finally:
        await client.aclose()


async def _synthesize_segments(chunks: list[str], voice_uri: str, output_path: str, model: str) -> Optional[str]:
    """
    分段合成 + FFmpeg 拼接。
    每段最多重试 3 次（指数退避），片段之间间隔 2.5 秒，
    避免触发 SiliconFlow 免费 tier 的 RPM 限流。
    """
    ffmpeg_bin = _find_ffmpeg()
    if not ffmpeg_bin:
        print("[siliconflow] ffmpeg 未找到，无法分段拼接")
        return None

    import tempfile, uuid, shutil
    tmp_dir = os.path.join(os.path.dirname(output_path), f"sf_tmp_{uuid.uuid4().hex}")
    os.makedirs(tmp_dir, exist_ok=True)

    MAX_RETRIES = 3
    CHUNK_INTERVAL_SEC = 2.5  # 片段间间隔，避免触发限流
    failed_count = 0
    segment_files = []

    for i, chunk in enumerate(chunks):
        seg_path = os.path.join(tmp_dir, f"_seg_{i:03d}.mp3")
        success = False

        for attempt in range(1, MAX_RETRIES + 1):
            result = await _synthesize_single(chunk, voice_uri, seg_path, model)
            if result and os.path.exists(seg_path) and os.path.getsize(seg_path) >= 500:
                segment_files.append(seg_path)
                success = True
                break
            else:
                err_type = "限流/服务端错误" if attempt == 1 else f"重试 {attempt}"
                print(f"[siliconflow] 片段 {i+1}/{len(chunks)} {err_type} 失败，{2 ** attempt}s 后重试...")
                if os.path.exists(seg_path):
                    try:
                        os.remove(seg_path)
                    except Exception:
                        pass
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 ** attempt)  # 指数退避：2s → 4s

        if not success:
            failed_count += 1
            print(f"[siliconflow] 片段 {i+1}/{len(chunks)} 经过 {MAX_RETRIES} 次重试后放弃")

        # 片段间间隔，防止连续请求触发限流（最后一段不加）
        if i < len(chunks) - 1:
            await asyncio.sleep(CHUNK_INTERVAL_SEC)

    print(f"[siliconflow] 分段合成汇总: {len(segment_files)}/{len(chunks)} 段成功，{failed_count} 段失败")

    if not segment_files:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print("[siliconflow] 所有片段均失败，任务中止")
        return None

    # FFmpeg 拼接
    list_file = os.path.join(tmp_dir, "_concat.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for seg in segment_files:
            f.write(f"file '{os.path.abspath(seg)}'\n")

    # 用 concat demuxer 读取，但重编码（不用 -c copy）
    # 因为 SiliconFlow 每次 API 调用返回的 MP3 编码参数可能不一致，
    # 流拷贝拼接会产生损坏的音频（杂音、时长计算错误）
    rc = subprocess.run(
        [ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
         "-i", list_file, "-c:a", "libmp3lame", "-b:a", "128k",
         "-ar", "32000", "-ac", "1", output_path],
        capture_output=True, encoding="utf-8", errors="replace", timeout=180,
    )
    try:
        os.remove(list_file)
    except Exception:
        pass

    shutil.rmtree(tmp_dir, ignore_errors=True)

    if rc.returncode != 0:
        print(f"[siliconflow] FFmpeg 拼接失败: {rc.stderr[-200:]}")
        return None

    final_size = os.path.getsize(output_path)
    print(f"[siliconflow] 分段合成成功: {output_path} ({final_size} bytes, {len(segment_files)} 段)")
    return output_path


# ============== 列出已克隆音色 ==============

async def list_voices() -> list[dict]:
    """
    列出账户下所有已克隆的音色

    Returns:
        [{model, customName, text, uri}, ...]
    """
    if not SILICONFLOW_KEY:
        print("[siliconflow] SILICONFLOW_API_KEY 未设置")
        return []

    client = _get_client()
    try:
        resp = await client.get("/v1/audio/voice/list")
        if resp.status_code == 200:
            return resp.json().get("result", [])
        else:
            print(f"[siliconflow] 列出音色失败 {resp.status_code}: {resp.text[:200]}")
            return []
    except Exception as e:
        print(f"[siliconflow] 列出音色异常: {e}")
        return []
    finally:
        await client.aclose()


# ============== 删除音色 ==============

async def delete_voice(uri: str) -> bool:
    """删除指定音色"""
    if not SILICONFLOW_KEY:
        print("[siliconflow] SILICONFLOW_API_KEY 未设置")
        return False

    client = _get_client()
    try:
        resp = await client.post(
            "/v1/audio/voice/deletions",
            json={"uri": uri},
        )
        ok = resp.status_code == 200
        print(f"[siliconflow] 删除音色 {uri}: {'成功' if ok else f'失败 {resp.status_code}'}")
        return ok
    except Exception as e:
        print(f"[siliconflow] 删除音色异常: {e}")
        return False
    finally:
        await client.aclose()


# ============== 本地音色库（避免重复上传） ==============
# voice_name → {voice_uri, model, reference_audio_path, created_at}

def _get_library_path() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    lib_dir = os.path.join(base, "..", "data", "voice_library")
    os.makedirs(lib_dir, exist_ok=True)
    return os.path.join(lib_dir, "voice_library.json")


def list_voice_library() -> list[dict]:
    """
    返回本地音色库里所有已存档的音色。
    """
    path = _get_library_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_voice_to_library(
    voice_name: str,
    voice_uri: str,
    reference_audio_path: str,
    model: str = TTS_MODEL,
) -> bool:
    """
    把克隆好的音色存档到本地音色库。
    voice_name 相同时覆盖旧记录。
    防护：拒绝不合规的 URI（如测试占位符）。
    """
    # 基础格式校验：必须是 speech: 开头，包含有效 token
    if not voice_uri.startswith("speech:") or len(voice_uri.split(":")) < 3:
        print(f"[voice_library] 拒绝不合规的 voice_uri: {voice_uri}，不存档")
        return False

    library = list_voice_library()

    # 避免重复 name（覆盖）
    library = [v for v in library if v.get("voice_name") != voice_name]

    library.append({
        "voice_name": voice_name,
        "voice_uri": voice_uri,
        "model": model,
        "reference_audio_path": reference_audio_path,
        "created_at": datetime.datetime.now().isoformat(),
    })

    try:
        with open(_get_library_path(), "w", encoding="utf-8") as f:
            json.dump(library, f, ensure_ascii=False, indent=2)
        print(f"[voice_library] 已存档音色: {voice_name} → {voice_uri}")
        return True
    except Exception as e:
        print(f"[voice_library] 保存失败: {e}")
        return False


def remove_voice_from_library(voice_name: str) -> bool:
    """从本地音色库删除指定音色（不删除 SiliconFlow 远端音色）"""
    library = list_voice_library()
    original_len = len(library)
    library = [v for v in library if v.get("voice_name") != voice_name]

    if len(library) == original_len:
        return False

    try:
        with open(_get_library_path(), "w", encoding="utf-8") as f:
            json.dump(library, f, ensure_ascii=False, indent=2)
        print(f"[voice_library] 已删除音色: {voice_name}")
        return True
    except Exception as e:
        print(f"[voice_library] 删除失败: {e}")
        return False
