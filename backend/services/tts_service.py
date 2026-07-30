"""
TTS 配音服务 — 3 黄金音色，无降级。

接口（供 main.py 调用）:
    generate_audio(text, voice, output_path) -> str
    generate_audio_with_reference(text, reference_audio_path, output_path) -> None
    get_voices() -> list[dict]
"""
import os
import re
import asyncio
from dotenv import load_dotenv
load_dotenv()
from typing import Optional


# ============== 音色列表 ==============

def get_voices() -> list[dict]:
    """返回可用音色列表（豆包语音合成 V3）"""
    voices = []

    try:
        from services.volc_tts_v3_service import get_voices as _get_volc_voices
        voices.extend(_get_volc_voices())
    except ImportError:
        pass

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
        SF_FEMALE_VOICE_URI = "speech:voice_40_1783427531231:d8uv3ftsssvc73almr4g:rxcxjvoiekndkjtzyela"
        result = await sf_synthesize(text=text, voice_uri=SF_FEMALE_VOICE_URI, output_path=output_path)
        if result:
            return result
        raise RuntimeError(f"[tts] SiliconFlow 克隆女声合成失败，已中止（不降级）")

    # ---- vc_clone_wanglq: 火山引擎声音复刻 王立群 ----
    if voice == "vc_clone_wanglq":
        from services.volc_tts_v3_service import synthesize_clone as volc_clone_synth
        result = await volc_clone_synth(text=text, speaker_id="S_FqsgYzu92", output_path=output_path)
        if result:
            return result
        raise RuntimeError(f"[tts] 王立群音色合成失败，已中止（不降级）")

    # ---- 豆包语音 V3 路由（vc_shuangsisi 及其他 vc_*）----
    if voice.startswith("vc_"):
        from services.volc_tts_v3_service import synthesize as volc_synthesize
        result = await volc_synthesize(text=text, voice=voice, output_path=output_path)
        if result:
            return result
        raise RuntimeError(f"[tts] 豆包 V3 合成失败（voice={voice}），已中止（不降级）")

    # ---- 旧版 zf_* 路径：不支持，直接报错 ----
    raise RuntimeError(f"[tts] 不支持的音色: {voice}，已中止（不降级）")
