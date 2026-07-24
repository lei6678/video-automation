"""
SiliconFlow 音色克隆端到端验证脚本
测试两步流程：1) 上传参考音频获取 voice_uri  2) 用音色合成语音
"""
import asyncio
import os
import sys

sys.path.insert(0, ".")
os.chdir("E:/video-automation/backend")

from dotenv import load_dotenv
load_dotenv()

from services.siliconflow_tts_service import (
    upload_reference_audio,
    synthesize,
    list_voices,
    TTS_MODEL,
)

# 用一个真实的小音频片段作为参考
REF_AUDIO = "E:/video-automation/test_short_ref.mp3"
TEST_TEXT = "今天天气真好，我们一起出去走走吧。"
OUTPUT_PATH = "E:/video-automation/test_sf_clone_output.mp3"
UNIQUE_NAME = f"test_voice_{os.getpid()}"


async def main():
    print(f"=" * 60)
    print(f"SiliconFlow 音色克隆端到端测试")
    print(f"模型: {TTS_MODEL}")
    print(f"=" * 60)

    # Step 0: 确认测试音频存在
    if not os.path.exists(REF_AUDIO):
        print(f"[ERROR] 测试音频不存在: {REF_AUDIO}")
        return
    size = os.path.getsize(REF_AUDIO)
    print(f"[OK] 测试音频: {REF_AUDIO} ({size} bytes)")

    # Step 1: 列出已有音色
    print(f"\n--- Step 1: 列出已有音色 ---")
    voices = await list_voices()
    print(f"已有音色数量: {len(voices)}")
    for v in voices[:5]:
        print(f"  - {v.get('uri', 'N/A')} | {v.get('customName', 'N/A')}")

    # Step 2: 上传参考音频
    print(f"\n--- Step 2: 上传参考音频，克隆音色 ---")
    print(f"参考音频: {REF_AUDIO}")
    print(f"音色名称: {UNIQUE_NAME}")

    voice_uri, err = await upload_reference_audio(
        audio_path=REF_AUDIO,
        custom_name=UNIQUE_NAME,
        reference_text="",
    )

    if not voice_uri:
        print(f"[ERROR] 音色克隆失败: {err}")
        return

    print(f"[OK] 音色克隆成功!")
    print(f"  voice_uri: {voice_uri}")

    # Step 3: 用克隆音色合成
    print(f"\n--- Step 3: 用克隆音色合成语音 ---")
    print(f"待合成文本: {TEST_TEXT}")

    result = await synthesize(
        text=TEST_TEXT,
        voice_uri=voice_uri,
        output_path=OUTPUT_PATH,
    )

    if result and os.path.exists(result):
        final_size = os.path.getsize(result)
        print(f"[OK] 合成成功!")
        print(f"  输出文件: {result}")
        print(f"  文件大小: {final_size} bytes ({final_size / 1024:.1f} KB)")
        if final_size < 1000:
            print(f"[WARN] 文件异常小，可能是空音频或 API 返回了错误")
        else:
            print(f"[PASS] 完整流程验证通过!")
    else:
        print(f"[ERROR] 合成失败，返回值: {result}")
        return

    print(f"\n{'=' * 60}")
    print(f"✅ SiliconFlow 音色克隆全流程验证通过!")
    print(f"=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
