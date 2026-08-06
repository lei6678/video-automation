"""
ASR 语音识别服务 - 基于硅基流动 (SiliconFlow) API
使用 FunAudioLLM/SenseVoiceSmall 模型进行高精度中文语音识别
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from openai import AsyncOpenAI


# ============== SiliconFlow ASR 客户端初始化 =============

SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"

# 初始化异步客户端
_client = None


def get_asr_client() -> AsyncOpenAI:
    """获取或创建 ASR 客户端单例"""
    global _client
    if _client is None:
        if not SILICONFLOW_API_KEY:
            raise ValueError("SILICONFLOW_API_KEY 未设置，请检查 .env 配置")
        _client = AsyncOpenAI(
            api_key=SILICONFLOW_API_KEY,
            base_url=SILICONFLOW_BASE_URL,
        )
    return _client


# ============== 语音识别函数 =============

async def transcribe_media(file_path: str) -> str:
    """
    使用 SiliconFlow ASR API 对音视频文件进行语音识别

    Args:
        file_path: 本地音频/视频文件的绝对路径或相对路径

    Returns:
        识别出的纯文本内容（原始逐字稿）

    Raises:
        FileNotFoundError: 音频文件不存在
        ValueError: API Key 未配置
        Exception: 其他 ASR 调用错误
    """
    # 检查文件是否存在
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"[asr_service] 音频文件不存在: {file_path}")

    # 检查 API Key
    if not SILICONFLOW_API_KEY:
        raise ValueError("[asr_service] SILICONFLOW_API_KEY 未设置")

    client = get_asr_client()

    print(f"[asr_service] 开始 ASR 识别: {file_path}")
    print(f"[asr_service] 使用模型: FunAudioLLM/SenseVoiceSmall")

    try:
        with open(file_path, "rb") as audio_file:
            response = await client.audio.transcriptions.create(
                model="FunAudioLLM/SenseVoiceSmall",
                file=audio_file,
                response_format="text",
            )

        transcript = response.text if hasattr(response, "text") else str(response)

        print(f"[asr_service] ASR 识别完成! 文字长度: {len(transcript)} 字符")
        print(f"[asr_service] 识别结果预览: {transcript[:100]}...")

        return transcript

    except Exception as e:
        print(f"[asr_service] ASR 识别失败! 报错类型: {type(e).__name__}, 详情: {str(e)}")
        raise
