# -*- coding: utf-8 -*-
"""
生成占位 BGM（情绪标签化曲库的临时替身）
用 ffmpeg 合成简单的和弦垫乐，按情绪区分。正式版替换为 CC0/授权曲库即可：
把 mp3 放进 assets/bgm/{emotion}.mp3 就行，文件名即情绪标签。
"""
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "bgm"
DUR = 60  # 每首 60 秒，混音时会自动循环/裁剪

# 情绪 -> (频率列表, tremolo频率, tremolo深度, 音量)
RECIPES = {
    "calm":    ([220.00, 261.63, 329.63], 0.3, 0.25, 0.28),   # A3+C4+E4 大三和弦，缓慢呼吸
    "neutral": ([196.00, 246.94, 293.66], 0.4, 0.20, 0.22),   # G3+B3+D4，中性温和
    "happy":   ([261.63, 329.63, 392.00], 2.0, 0.35, 0.30),   # C4+E4+G4 明亮，轻快脉动
    "tense":   ([110.00, 116.54, 220.00], 4.0, 0.45, 0.32),   # A2+A#2 不协和+快脉冲
    "sad":     ([174.61, 220.00, 261.63], 0.25, 0.30, 0.24),  # F3+A3+C4 小调暗淡
}


def make(name: str, freqs: list, trem_f: float, trem_d: float, vol: float) -> None:
    out = OUT_DIR / f"{name}.mp3"
    cmd = ["ffmpeg", "-y"]
    for f in freqs:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={f}:duration={DUR}"]
    n = len(freqs)
    fc = (
        f"amix=inputs={n}:duration=longest,"
        f"tremolo=f={trem_f}:d={trem_d},"
        f"lowpass=f=1200,"           # 柔化，像背景垫乐
        f"volume={vol},"
        f"aformat=sample_rates=44100:channel_layouts=stereo"
    )
    cmd += ["-filter_complex", fc, "-b:a", "128k", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[失败] {name}: {r.stderr[-200:]}", file=sys.stderr)
    else:
        print(f"[生成] {out.name} ({out.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for emotion, recipe in RECIPES.items():
        make(emotion, *recipe)
    print(f"\n占位 BGM 就绪: {OUT_DIR}")
