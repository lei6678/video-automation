"""
index-tts2 本地 TTS 服务
常驻端口 7860，提供 HTTP 接口供主服务调用。

启动方式:
    cd workers/index_tts2
    pip install -r requirements.txt
    python server.py

接口说明:
    POST /tts          - 合成语音，返回音频字节
    GET  /voices       - 返回可用音色列表
    GET  /health       - 健康检查
"""
import io
import sys
import logging
import asyncio
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="[index-tts2] %(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("index-tts2")

# ============== 启动检查：尝试加载 index-tts2 ==============

TTS_ENGINE: Optional[object] = None
USE_FALLBACK = False

def _try_load_index_tts2():
    """尝试加载 index-tts2 官方包，失败则降级到 TTS(Python_audio)"""
    global TTS_ENGINE, USE_FALLBACK

    # 方案 1: 尝试官方的 index-tts2
    try:
        from index_tts import IndexTTS
        TTS_ENGINE = IndexTTS()
        logger.info("✅ index-tts2 官方引擎加载成功")
        return
    except ImportError:
        logger.warning("⚠️ index-tts2 官方包未安装，尝试其他方案...")
    except Exception as e:
        logger.warning(f"⚠️ index-tts2 加载失败: {e}，尝试其他方案...")

    # 方案 2: GPT-SoVITS（主流开源中文TTS）
    try:
        from TTS.api import TTS
        # 尝试加载一个中文模型，如果失败则继续降级
        TTS_ENGINE = TTS(model_name="tts_models/zh-CN/baker/tacotron2_GST糙GST", progressbar=False)
        USE_FALLBACK = True
        logger.info("✅ TTS (Coqui) 降级引擎加载成功")
        return
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"⚠️ Coqui TTS 加载失败: {e}，继续降级...")

    # 方案 3: 纯 Edge TTS 本地代理（最稳的降级）
    try:
        import edge_tts
        TTS_ENGINE = "edge_tts"
        USE_FALLBACK = True
        logger.info("✅ Edge TTS 降级引擎加载成功（本地模式）")
        return
    except ImportError:
        pass

    logger.error("❌ 所有 TTS 引擎均不可用，请运行: pip install edge-tts")
    TTS_ENGINE = None


# ============== 音色定义 ==============

# index-tts2 官方音色（如果用官方引擎）
OFFICIAL_VOICES = [
    {"id": "af_bella", "name": "Bella (女声-活泼)", "language": "en"},
    {"id": "af_sarah", "name": "Sarah (女声-沉稳)", "language": "en"},
    {"id": "am_adam", "name": "Adam (男声)", "language": "en"},
    {"id": "af_nicole", "name": "Nicole (女声-磁性)", "language": "en"},
    {"id": "zf_xiaobei", "name": "xiaobei (中文女声)", "language": "zh"},
    {"id": "zf_xiaoni", "name": "xiaoni (中文女声-轻柔)", "language": "zh"},
    {"id": "zf_xiaoyan", "name": "xiaoyan (中文女声-标准)", "language": "zh"},
    {"id": "zf_xiaoyun", "name": "xiaoyun (中文女声-温柔)", "language": "zh"},
]

# Edge TTS 降级音色映射
EDGE_TTS_VOICES = {
    # Worker 自有 ID
    "zf_xiaobei": "zh-CN-XiaoxiaoNeural",
    "zf_xiaoni": "zh-CN-XiaoyiNeural",
    "zf_xiaoyan": "zh-CN-YunxiNeural",
    "zf_xiaoyun": "zh-CN-YunyangNeural",
    # 主服务音色 ID（跨兼容）
    "zf_yunxi":    "zh-CN-YunxiNeural",
    "zf_yunjian":  "zh-CN-YunjianNeural",
    "zf_yunxia":   "zh-CN-YunxiaNeural",
    "zf_yunyang":  "zh-CN-YunyangNeural",
    "zf_xiaoxiao": "zh-CN-XiaoxiaoNeural",
    "zf_xiaoyi":   "zh-CN-XiaoyiNeural",
    "zf_hsiaochen":"zh-TW-HsiaoChenNeural",
    "zf_hsiaoyu":  "zh-TW-HsiaoYuNeural",
    "default":     "zh-CN-YunxiNeural",
}


# ============== 核心合成函数 ==============

async def synthesize(text: str, voice: str = "zf_xiaobei") -> bytes:
    """
    合成语音，返回 WAV/MP3 字节流。
    优先使用 index-tts2 官方引擎，失败则降级到 Edge TTS。
    """
    if TTS_ENGINE is None:
        raise RuntimeError("没有任何可用的 TTS 引擎，请安装 edge-tts: pip install edge-tts")

    # ---- 官方 index-tts2 ----
    if hasattr(TTS_ENGINE, "tts") and not USE_FALLBACK:
        return await _synthesize_index_tts(text, voice)

    # ---- Edge TTS 降级 ----
    return await _synthesize_edge_tts(text, voice)


async def _synthesize_index_tts(text: str, voice: str) -> bytes:
    """index-tts2 官方引擎合成"""
    loop = asyncio.get_event_loop()
    wav_bytes = await loop.run_in_executor(
        None,
        lambda: TTS_ENGINE.tts(text, speaker=voice)
    )
    # index-tts2 返回的可能是 numpy 数组或字节
    if hasattr(wav_bytes, "tobytes"):
        return wav_bytes.tobytes()
    return bytes(wav_bytes)


async def _synthesize_edge_tts(text: str, voice: str) -> bytes:
    """Edge TTS 降级引擎（最稳的本地方案）"""
    import edge_tts
    import tempfile
    import os

    # 映射到 Edge TTS 音色
    edge_voice = EDGE_TTS_VOICES.get(voice, EDGE_TTS_VOICES["default"])

    # 直接传纯文本，不使用 SSML（edge-tts 版本兼容性问题会导致空音频）
    # 停顿控制通过 Communicate 的 rate 参数实现，不靠 SSML break 标签
    communicate = edge_tts.Communicate(text, voice=edge_voice)

    # edge-tts 的 save() 只接受文件路径字符串，不接受 BytesIO
    # 因此写临时文件再读回内存
    fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        await communicate.save(tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def _build_ssml(text: str, voice: str) -> str:
    """将文本转换为带停顿标注的 SSML"""
    import re
    # 中文标点替换为 break 标签
    text = re.sub(r'，', r'， <break time="300ms"/>', text)
    text = re.sub(r'。', r'。 <break time="800ms"/>', text)
    text = re.sub(r'、', r'、 <break time="300ms"/>', text)
    text = re.sub(r'；', r'； <break time="400ms"/>', text)
    text = re.sub(r'：', r'： <break time="400ms"/>', text)
    text = re.sub(r'！', r'！ <break time="600ms"/>', text)
    text = re.sub(r'？', r'？ <break time="600ms"/>', text)
    # 转义 & 和 "
    text = text.replace("&", "&amp;").replace('"', "&quot;")
    return (
        f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'>"
        f"<voice name='{voice}'>"
        f"<prosody pitch='+0Hz' rate='+0%' volume='+0%'>"
        f"{text}"
        f"</prosody>"
        f"</voice>"
        f"</speak>"
    )


# ============== FastAPI 服务 ==============

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(title="index-tts2 Local TTS Server", version="1.0.0")


class TTSRequest(BaseModel):
    text: str
    voice: str = "zf_xiaobei"


class VoicesResponse(BaseModel):
    voices: list[dict]


@app.get("/health")
async def health():
    engine_type = "index-tts2" if (TTS_ENGINE and not USE_FALLBACK) else ("edge-tts" if TTS_ENGINE == "edge_tts" else "none")
    return {
        "status": "ok" if TTS_ENGINE else "error",
        "engine": engine_type,
        "fallback": USE_FALLBACK,
    }


@app.get("/voices", response_model=VoicesResponse)
async def list_voices():
    """返回可用音色列表"""
    return VoicesResponse(voices=OFFICIAL_VOICES)


@app.post("/tts")
async def tts(request: TTSRequest):
    """
    合成语音，返回音频字节流。
    Content-Type: audio/wav 或 audio/mp3
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="text 不能为空")

    logger.info(f"合成请求: voice={request.voice}, text_len={len(request.text)}")

    try:
        audio_bytes = await synthesize(request.text, request.voice)
        logger.info(f"合成完成: {len(audio_bytes)} bytes")
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={"Content-Disposition": "inline"},
        )
    except Exception as e:
        logger.error(f"合成失败: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"合成失败: {str(e)}")


# ============== 启动 ==============

@app.on_event("startup")
async def startup():
    logger.info("🚀 index-tts2 服务启动中...")
    _try_load_index_tts2()
    if TTS_ENGINE is None:
        logger.error("没有可用 TTS 引擎，服务将以 limited 模式运行")
        logger.error("请安装 edge-tts: pip install edge-tts")
    else:
        logger.info(f"✅ 服务就绪，当前引擎: {'index-tts2' if not USE_FALLBACK else 'edge-tts (降级)'}")
        logger.info("📍 监听端口: 7860")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="info")
