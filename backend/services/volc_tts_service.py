"""
火山引擎 TTS 服务 - 参考音频音色克隆
官方文档: https://www.volcengine.com/docs/tts/1195622

认证方式：AK/SK → STS Token → TTS API
"""
import base64
import json
import hashlib
import hmac
import time
import httpx
import asyncio
from datetime import datetime, timezone
from typing import Optional


# ============== 凭证（从环境变量读取）==============
VOLC_ACCESS_KEY = ""  # 从环境变量设置
VOLC_SECRET_KEY = ""  # 从环境变量设置
VOLC_ACCOUNT_ID = ""  # 火山引擎账户 ID（从 IAM 设置获取）
VOLC_TTS_API = "https://openspeech.bytedance.com/api/v1/tts"
VOLC_STS_API = "https://open.volcengineapi.com/api/v1/sts/AssumeRole"


def set_credentials(ak: str, sk: str, account_id: str = ""):
    """设置火山引擎凭证（供外部调用）"""
    global VOLC_ACCESS_KEY, VOLC_SECRET_KEY, VOLC_ACCOUNT_ID
    VOLC_ACCESS_KEY = ak
    VOLC_SECRET_KEY = sk
    VOLC_ACCOUNT_ID = account_id


# ============== STS Token 获取 ==============

async def get_sts_token(role_arn: str = "") -> Optional[dict]:
    """
    使用 AK/SK 获取 STS Token
    role_arn 格式: acs:ram::${AccountID}:role/${RoleName}
    """
    if not VOLC_ACCESS_KEY or not VOLC_SECRET_KEY:
        print("[volc] 火山引擎凭证未设置")
        return None

    now = int(time.time())
    now_iso = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 签名方法 v1 - HMAC-SHA256
    def sign(secret, string_to_sign):
        return base64.b64encode(
            hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")

    # 构建签名字符串
    hashed_canonical_request = hashlib.sha256(
        f"GET\n/api/v1/sts/AssumeRole\nAccessKeyId={VOLC_ACCESS_KEY}&SignatureMethod=HMAC-SHA256&SignatureVersion=1.0&Timestamp={urllib.parse.quote(now_iso)}".encode("utf-8")
    ).hexdigest()

    string_to_sign = (
        f"HMAC-SHA256\n{now_iso}\n{hashed_canonical_request}"
    )

    signature = sign(VOLC_SECRET_KEY, string_to_sign)

    # STS 请求
    params = {
        "AccessKeyId": VOLC_ACCESS_KEY,
        "SignatureMethod": "HMAC-SHA256",
        "SignatureVersion": "1.0",
        "Timestamp": now_iso,
        "Signature": signature,
        "RoleArn": role_arn,
        "RoleSessionName": "tts_session",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(VOLC_STS_API, params=params)
            data = resp.json()
            if data.get("StatusCode") == 200:
                credentials = data.get("Result", {}).get("Credentials", {})
                return {
                    "AccessKeyId": credentials.get("AccessKeyId"),
                    "SecretAccessKey": credentials.get("SecretAccessKey"),
                    "SessionToken": credentials.get("SessionToken"),
                    "ExpiresAt": credentials.get("ExpiresAt"),
                }
            else:
                print(f"[volc] STS 获取失败: {data}")
                return None
    except Exception as e:
        print(f"[volc] STS 请求异常: {e}")
        return None


# ============== TTS 合成 ==============

async def synthesize(
    text: str,
    voice_id: str = "zh_female_shangning",
    speed: float = 1.0,
    pitch: float = 1.0,
    volume: float = 1.0,
    output_path: Optional[str] = None,
    reference_audio_path: Optional[str] = None,
) -> Optional[bytes]:
    """
    调用火山引擎 TTS API

    Args:
        text: 待合成文本（中文建议单次不超过 500 字）
        voice_id: 音色 ID，默认为 "zh_female_shangning"（女声）
        speed: 语速，0.5 ~ 2.0，默认 1.0
        pitch: 音调，0.5 ~ 2.0，默认 1.0
        volume: 音量，0.5 ~ 2.0，默认 1.0
        output_path: 保存路径（可选）
        reference_audio_path: 参考音频路径（用于音色克隆）

    Returns:
        bytes 音频数据，或 None（失败）
    """
    # 优先使用 STS Token（通过 AK/SK 获取）
    token_data = await _get_token_cached()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token_data['token']}" if token_data else "",
    }

    payload = {
        "appid": "test_appid",  # 火山引擎 App ID，需替换为真实值
        "text": text,
        "voice_id": voice_id,
        "speed_ratio": str(speed),
        "pitch_ratio": str(pitch),
        "volume_ratio": str(volume),
        "encoding": "mp3",
    }

    # 参考音频音色克隆（关键功能）
    if reference_audio_path:
        try:
            with open(reference_audio_path, "rb") as f:
                ref_audio_b64 = base64.b64encode(f.read()).decode("utf-8")
            payload["ref_audio"] = ref_audio_b64
            payload["operation"] = "submit"  # 克隆音色需要先提交
            print(f"[volc] 使用参考音频音色克隆: {reference_audio_path}")
        except Exception as e:
            print(f"[volc] 读取参考音频失败: {e}")
            return None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(VOLC_TTS_API, json=payload, headers=headers)
            print(f"[volc] TTS 响应状态: {resp.status_code}")

            if resp.status_code == 200:
                audio_data = resp.content
                if output_path and audio_data:
                    with open(output_path, "wb") as f:
                        f.write(audio_data)
                    print(f"[volc] 音频保存到: {output_path} ({len(audio_data)} bytes)")
                return audio_data
            else:
                print(f"[volc] TTS 请求失败 {resp.status_code}: {resp.text[:300]}")
                return None
    except Exception as e:
        print(f"[volc] TTS 请求异常: {e}")
        return None


# ============== Token 缓存（避免频繁获取）==============

_cached_token: Optional[dict] = None


async def _get_token_cached() -> Optional[dict]:
    """缓存 STS Token，过期前自动刷新"""
    global _cached_token
    if _cached_token:
        expires = _cached_token.get("ExpiresAt", 0)
        if time.time() < expires - 60:
            return _cached_token

    # 没有 role_arn 时，尝试匿名调用（部分 API 支持）
    # 有 ROLE_ARN 时走完整 STS 流程
    if VOLC_ACCOUNT_ID:
        role_arn = f"acs:ram::{VOLC_ACCOUNT_ID}:role/ttsrole"
        _cached_token = await get_sts_token(role_arn)
    else:
        # 没有 account_id，使用公开测试凭证模式
        # 火山引擎部分 TTS 接口支持 ACCESS_KEY 直接签名
        _cached_token = {
            "AccessKeyId": VOLC_ACCESS_KEY,
            "SecretAccessKey": VOLC_SECRET_KEY,
            "token": "",
        }

    return _cached_token
