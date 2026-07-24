"""
火山引擎豆包语音合成 V3 服务 + 声音复刻 2.0

=== 常规合成（预置音色）===
- 端点: POST /api/v3/tts/unidirectional
- Resource-Id: volc.seedtts.default
- speaker: zh_female_xxx_uranus_bigtts

=== 声音复刻（上传参考音频克隆音色）===
- 端点: POST /api/v3/tts/voice_clone
- 上传参考音频 → 获得 S_xxx speaker_id

=== 复刻音色合成 ===
- 端点: POST /api/v3/tts/unidirectional
- Resource-Id: seed-icl-2.0
- speaker: S_xxx（克隆返回的 ID）
- 不需要分段！一次请求合成完整文本

鉴权方式：X-Api-App-Id + X-Api-Access-Key（应用级密钥）
"""

import asyncio
import base64
import json
import os
import datetime
from typing import Optional

import httpx
from dotenv import load_dotenv
load_dotenv()

# ============== 凭证 ==============
VOLC_APP_ID = os.getenv("VOLC_APP_ID", "5373024197")
VOLC_ACCESS_TOKEN = os.getenv("VOLC_ACCESS_TOKEN", "")

VOLC_TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
VOLC_CLONE_URL = "https://openspeech.bytedance.com/api/v3/tts/voice_clone"
VOLC_RESOURCE_ID = "volc.seedtts.default"       # 普通合成
VOLC_CLONE_RESOURCE_ID = "seed-icl-2.0"          # 复刻音色合成
VOLC_UID = os.getenv("VOLC_UID", "2104534266")

# ============== 音色列表 ==============

VOLC_VOICES = {
    # v5 极致精简：仅保留 3 个黄金音色
    "vc_shuangsisi":  {"speaker": "zh_female_shuangkuaisisi_uranus_bigtts", "label": "爽快思思 — 通用带货首选"},
    "vc_clone_female": {"speaker": "SILICONFLOW_CLONE",                     "label": "我的克隆音色 — 女声1"},
    "vc_clone_wanglq": {"speaker": "S_FqsgYzu92",                           "label": "我的克隆音色 — 王立群"},
}

# ============== 辅助 ==============

def get_voices() -> list[dict]:
    """返回可用音色列表"""
    return [
        {"id": voice_id, "name": info["label"], "language": "zh-CN"}
        for voice_id, info in VOLC_VOICES.items()
    ]


def _get_speaker(voice_id: str) -> str | None:
    """根据 voice_id 获取 speaker 名称"""
    info = VOLC_VOICES.get(voice_id)
    return info["speaker"] if info else None


# ============== 核心合成 ==============

async def synthesize(
    text: str,
    voice: str = "vc_wenroumama",
    output_path: str | None = None,
) -> Optional[str]:
    """
    调用豆包语音合成 V3 API，生成 MP3 音频。

    Args:
        text: 待合成文本
        voice: 音色 ID（vc_xxx）
        output_path: 输出文件路径，为 None 时自动生成

    Returns:
        output_path（成功）或 None（失败）
    """
    token = VOLC_ACCESS_TOKEN
    if not token:
        print("[volc-v3] VOLC_ACCESS_TOKEN 未设置，请在 .env 中配置")
        return None

    speaker = _get_speaker(voice)
    if not speaker:
        print(f"[volc-v3] 未知音色: {voice}")
        return None

    # 克隆音色（S_xxx）需要用不同的 Resource-Id
    is_clone = speaker.startswith("S_")
    resource_id = VOLC_CLONE_RESOURCE_ID if is_clone else VOLC_RESOURCE_ID

    if not output_path:
        import tempfile
        fd, output_path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)

    headers = {
        "Content-Type": "application/json",
        "X-Api-App-Id": VOLC_APP_ID,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": resource_id,
    }

    payload = {
        "user": {"uid": VOLC_UID},
        "req_params": {
            "text": text,
            "speaker": speaker,
            "audio_params": {"format": "mp3", "sample_rate": 24000},
        },
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(VOLC_TTS_URL, json=payload, headers=headers)

            if resp.status_code != 200:
                err_text = resp.text[:300]
                print(f"[volc-v3] API 返回 {resp.status_code}: {err_text}")
                return None

            audio_data = bytearray()
            latest_code = 0

            for line in resp.text.strip().split("\n"):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                code = chunk.get("header", {}).get("code", 0)
                latest_code = code

                if code == 0 and chunk.get("data"):
                    audio_data.extend(base64.b64decode(chunk["data"]))
                elif code == 20000000:
                    # 流结束标志
                    break
                elif code > 0:
                    msg = chunk.get("header", {}).get("message", "")
                    print(f"[volc-v3] 服务端错误 code={code}: {msg}")
                    # 不中断，继续读后续 chunk（可能有错误后有有效数据）

            if not audio_data:
                print(f"[volc-v3] 未收到任何音频数据（最终 code={latest_code}）")
                return None

            with open(output_path, "wb") as f:
                f.write(audio_data)

            print(f"[volc-v3] 合成成功: {output_path} ({len(audio_data)} bytes, ~{len(audio_data)*8//128000:.1f}s)")
            return output_path

    except Exception as e:
        print(f"[volc-v3] 合成异常: {type(e).__name__}: {e}")
        return None


# ============== 声音复刻（上传参考音频 → 获得 S_xxx speaker_id）==============

async def clone_voice(
    audio_path: str,
    voice_name: str,
    reference_text: str = "",
) -> tuple[Optional[str], Optional[str]]:
    """
    上传参考音频到火山引擎声音复刻 2.0，获得克隆音色 speaker_id。

    Args:
        audio_path: 参考音频文件路径（wav/mp3/m4a/ogg）
        voice_name: 自定义音色名称（8-256 字符，英文开头，仅字母数字-_）
        reference_text: 参考音频对应的文本（可选，用于提升克隆质量）

    Returns:
        (speaker_id, error_msg) — 成功时 speaker_id 为 S_xxx 格式
    """
    token = VOLC_ACCESS_TOKEN
    if not token:
        return None, "VOLC_ACCESS_TOKEN 未设置"

    if not os.path.exists(audio_path):
        return None, f"参考音频文件不存在: {audio_path}"

    # 文件大小检查：最大 10MB
    file_size = os.path.getsize(audio_path)
    if file_size > 10 * 1024 * 1024:
        return None, f"参考音频过大（{file_size / 1024 / 1024:.1f}MB），请使用 10MB 以内的文件"

    # 读取并 Base64 编码
    try:
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        return None, f"读取参考音频失败: {e}"

    # 确保 voice_name 合规：仅字母数字-_，英文开头
    import re
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]{7,255}$', voice_name):
        # 自动修正：前缀 + 清洗
        safe = "my_" + re.sub(r'[^a-zA-Z0-9_-]', '', voice_name.replace(' ', '_'))[:60]
        if not re.match(r'^[a-zA-Z]', safe):
            safe = "voice_" + safe
        print(f"[volc-clone] voice_name 不合规，自动修正: {voice_name} → {safe}")
        voice_name = safe

    headers = {
        "Content-Type": "application/json",
        "X-Api-App-Id": VOLC_APP_ID,
        "X-Api-Access-Key": token,
        "X-Api-Request-Id": str(__import__("uuid").uuid4()),
    }

    # 区分预付费（S_xxx）和后付费（custom_speaker_id）模式
    is_prepaid = voice_name.startswith("S_")

    if is_prepaid:
        payload = {
            "speaker_id": voice_name,
            "audio": {
                "data": audio_b64,
            },
            "language": 0,
        }
    else:
        payload = {
            "speaker_id": "custom_speaker_id",
            "custom_speaker_id": voice_name,
            "audio": {
                "data": audio_b64,
            },
            "language": 0,
        }

    # 自动检测格式
    ext = os.path.splitext(audio_path)[1].lower().lstrip('.')
    if ext in ('wav', 'mp3', 'm4a', 'ogg', 'aac'):
        payload["audio"]["format"] = ext

    if reference_text:
        payload["extra_params"] = {"demo_text": reference_text[:300]}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(VOLC_CLONE_URL, json=payload, headers=headers)

            if resp.status_code == 200:
                result = resp.json()
                speaker_id = result.get("speaker_id", "")
                status = result.get("status", -1)

                if status == 2 or status == 4:  # Success 或 Active
                    print(f"[volc-clone] 克隆成功: {voice_name} → {speaker_id}")
                    return speaker_id, None
                elif status == 1:
                    print(f"[volc-clone] 训练中（异步），稍后可用: {voice_name}")
                    return speaker_id, None  # 返回 ID 但标注训练中
                else:
                    msg = f"克隆返回异常状态 status={status}: {resp.text[:200]}"
                    print(f"[volc-clone] {msg}")
                    return None, msg
            else:
                msg = f"克隆失败 {resp.status_code}: {resp.text[:300]}"
                print(f"[volc-clone] {msg}")
                return None, msg

    except Exception as e:
        msg = f"克隆异常: {type(e).__name__}: {e}"
        print(f"[volc-clone] {msg}")
        return None, msg


async def synthesize_clone(
    text: str,
    speaker_id: str,
    output_path: str,
) -> Optional[str]:
    """
    使用克隆音色（S_xxx）合成完整音频。
    不需要分段！一次请求合成全部文本。

    Args:
        text: 待合成文本（不限长度）
        speaker_id: 克隆返回的 S_xxx ID
        output_path: 输出路径

    Returns:
        output_path（成功）或 None（失败）
    """
    token = VOLC_ACCESS_TOKEN
    if not token:
        print("[volc-clone-tts] VOLC_ACCESS_TOKEN 未设置")
        return None

    if not speaker_id or not speaker_id.startswith("S_"):
        print(f"[volc-clone-tts] 无效的 speaker_id: {speaker_id}")
        return None

    headers = {
        "Content-Type": "application/json",
        "X-Api-App-Id": VOLC_APP_ID,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": VOLC_CLONE_RESOURCE_ID,
    }

    payload = {
        "user": {"uid": VOLC_UID},
        "req_params": {
            "text": text,
            "speaker": speaker_id,
            "audio_params": {"format": "mp3", "sample_rate": 24000},
        },
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(VOLC_TTS_URL, json=payload, headers=headers)

            if resp.status_code != 200:
                err_text = resp.text[:300]
                print(f"[volc-clone-tts] API 返回 {resp.status_code}: {err_text}")
                return None

            audio_data = bytearray()
            for line in resp.text.strip().split("\n"):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                code = chunk.get("header", {}).get("code", 0)
                if code == 0 and chunk.get("data"):
                    audio_data.extend(base64.b64decode(chunk["data"]))
                elif code == 20000000:
                    break
                elif code > 0:
                    msg = chunk.get("header", {}).get("message", "")
                    print(f"[volc-clone-tts] 服务端错误 code={code}: {msg}")

            if not audio_data:
                print("[volc-clone-tts] 未收到任何音频数据")
                return None

            with open(output_path, "wb") as f:
                f.write(audio_data)

            print(f"[volc-clone-tts] 合成成功: {output_path} ({len(audio_data)} bytes, ~{len(audio_data)*8//128000:.1f}s)")
            return output_path

    except Exception as e:
        print(f"[volc-clone-tts] 合成异常: {type(e).__name__}: {e}")
        return None


# ============== 本地音色库（复刻音色）==============

def _get_library_path() -> str:
    """本地音色库 JSON 路径"""
    from _resource import get_data_dir
    lib_dir = os.path.join(get_data_dir(), "voice_library")
    os.makedirs(lib_dir, exist_ok=True)
    return os.path.join(lib_dir, "voice_library.json")


def list_cloned_voices() -> list[dict]:
    """列出所有已存档的复刻音色"""
    path = _get_library_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_cloned_voice(
    voice_name: str,
    speaker_id: str,
    reference_audio_path: str,
    model: str = "seed-icl-2.0",
) -> bool:
    """存档复刻音色到本地音色库"""
    if not speaker_id or not speaker_id.startswith("S_"):
        print(f"[voice_library] 无效 speaker_id: {speaker_id}")
        return False

    library = list_cloned_voices()
    library = [v for v in library if v.get("voice_name") != voice_name]

    library.append({
        "voice_name": voice_name,
        "voice_uri": speaker_id,
        "source": "volcengine",
        "model": model,
        "reference_audio_path": reference_audio_path,
        "created_at": datetime.datetime.now().isoformat(),
    })

    try:
        with open(_get_library_path(), "w", encoding="utf-8") as f:
            json.dump(library, f, ensure_ascii=False, indent=2)
        print(f"[voice_library] 已存档复刻音色: {voice_name} → {speaker_id}")
        return True
    except Exception as e:
        print(f"[voice_library] 保存失败: {e}")
        return False


def remove_cloned_voice(voice_name: str) -> bool:
    """从本地音色库删除复刻音色"""
    library = list_cloned_voices()
    original_len = len(library)
    library = [v for v in library if v.get("voice_name") != voice_name]

    if len(library) == original_len:
        return False

    try:
        with open(_get_library_path(), "w", encoding="utf-8") as f:
            json.dump(library, f, ensure_ascii=False, indent=2)
        print(f"[voice_library] 已删除: {voice_name}")
        return True
    except Exception as e:
        print(f"[voice_library] 删除失败: {e}")
        return False
