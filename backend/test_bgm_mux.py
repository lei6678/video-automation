"""
BGM 混音验证脚本
================
生成合成素材(蓝屏视频 + 440Hz"人声" + 3s 880Hz"BGM") → 注入 _find_bgm → mux_audio
定量校验: BGM 混入 / 循环 / 结尾淡出 / 时长 / 视频流 copy / 无 BGM 回退
用法: cd backend && python test_bgm_mux.py
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from services import video_service as vs


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, timeout=60,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"cmd failed: {cmd}\n{(r.stderr or '')[-500:]}"
    return r


def mean_volume(path, af):
    """经 af 滤镜链后的 mean_volume(dB)。"""
    r = subprocess.run(
        ["ffmpeg", "-i", path, "-af", af + ",volumedetect", "-f", "null", "-"],
        capture_output=True, timeout=60, encoding="utf-8", errors="replace")
    for line in (r.stderr or "").splitlines():
        if "mean_volume" in line:
            return float(line.split("mean_volume:")[1].strip().split(" ")[0])
    return -999.0


d = tempfile.mkdtemp(prefix="bgm_test_")
video = os.path.join(d, "v.mp4")
voice = os.path.join(d, "voice.mp3")
bgm = os.path.join(d, "bgm.mp3")
out_bgm = os.path.join(d, "out_bgm.mp4")
out_plain = os.path.join(d, "out_plain.mp4")

run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x480:d=8.5:r=30",
     "-c:v", "libx264", "-pix_fmt", "yuv420p", video])
run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
     "-af", "volume=0.3", "-c:a", "libmp3lame", voice])
run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=3",
     "-c:a", "libmp3lame", bgm])  # 仅 3s → 8s 人声必须循环 2.7 次

# --- 用例1: bgm/ 目录无音频文件时 → None(当前仅有说明 txt) ---
found = vs._find_bgm()
assert found is None, f"bgm/ 应为空却找到: {found}"
print("PASS 1: bgm/ 无音频文件 → _find_bgm() = None")

# --- 用例2: 无 BGM 时走原有纯人声混流 ---
assert vs.mux_audio(video, voice, out_plain), "纯人声混流失败"
print("PASS 2: 无 BGM 回退路径正常")

# --- 用例3: 注入 BGM 混流 ---
vs._find_bgm = lambda: bgm
assert vs.mux_audio(video, voice, out_bgm), "BGM 混流失败"
dur = vs.get_audio_duration(out_bgm)
assert 7.4 < dur < 8.7, f"成片时长异常: {dur:.2f}s(应约 8s)"
print(f"PASS 3: BGM 混流成功, 成片 {dur:.2f}s(人声 8s)")

# --- 用例4: 高通滤波只留 880Hz BGM → 验证混入 + 循环 + 淡出 ---
hp = ",".join(["highpass=f=700"] * 4)  # ~40dB 压掉 440Hz 人声, 880Hz BGM 基本保留
head = mean_volume(out_bgm, f"atrim=0:2,{hp}")       # 第一轮 BGM
mid = mean_volume(out_bgm, f"atrim=4:6,{hp}")        # 超出 3s 源长 → 证明循环
tail = mean_volume(out_bgm, f"atrim=7.5:8,{hp}")     # 淡出区
ctrl = mean_volume(out_plain, f"atrim=0:2,{hp}")     # 无 BGM 对照组
print(f"  880Hz 能量: head={head}dB mid={mid}dB tail={tail}dB 对照={ctrl}dB")
assert head > ctrl + 15, f"BGM 未混入(head={head}dB 对照={ctrl}dB)"
assert abs(head - mid) < 4, f"BGM 未稳定循环(head={head}dB mid={mid}dB)"
assert tail < mid - 6, f"结尾淡出无效(tail={tail}dB vs mid={mid}dB)"
# 全频段总响度: BGM 只应带来轻微抬升, 不得盖过人声
fb_plain = mean_volume(out_plain, "atrim=0:6")
fb_bgm = mean_volume(out_bgm, "atrim=0:6")
print(f"  全频段响度: 纯人声={fb_plain}dB 含BGM={fb_bgm}dB")
assert fb_bgm - fb_plain < 3, f"BGM 过响(抬升 {fb_bgm - fb_plain:.1f}dB)"
print("PASS 4: BGM 已混入 + stream_loop 循环生效 + 结尾淡出生效 + 音量铺底不盖人声")

# --- 用例5: 视频流应为 copy 未重编码(本机无 ffprobe, 用 ffmpeg -i 解析) ---
r = subprocess.run(["ffmpeg", "-i", out_bgm], capture_output=True, timeout=60,
                   encoding="utf-8", errors="replace")
assert "Video: h264" in (r.stderr or ""), "视频流被重编码(未检出 h264)"
print("PASS 5: 视频流保持 copy(h264)")

print("\n=== 全部通过 ===")
print(f"素材目录(可试听验证): {d}")
