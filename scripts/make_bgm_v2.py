# -*- coding: utf-8 -*-
"""
程序化 BGM 作曲 v2（八音盒/音乐盒风格琶音，替代 v1 正弦垫乐）
numpy 合成：和弦进行 + 琶音模式 + ADSR 包络 + 低音持续 + 混响，ffmpeg 转 mp3
用法: python scripts/make_bgm_v2.py [-o assets/bgm] [--backup]
"""
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets" / "bgm"
SR = 44100

NOTE_FREQ = {}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
for octave in range(1, 7):
    for i, n in enumerate(NAMES):
        midi = 12 * (octave + 1) + i
        NOTE_FREQ[f"{n}{octave}"] = 440.0 * 2 ** ((midi - 69) / 12)


def tone(freq: float, dur: float, vol: float, timbre: str = "box") -> np.ndarray:
    """单个音符：八音盒音色 = 基频 + 弱二次谐波，快起音指数衰减"""
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    wave_f = np.sin(2 * np.pi * freq * t)
    if timbre == "box":
        wave_f += 0.35 * np.sin(2 * np.pi * freq * 2 * t) + 0.12 * np.sin(2 * np.pi * freq * 3 * t)
    env = np.exp(-3.2 * t / dur)                      # 指数衰减
    env[: int(0.008 * SR)] *= np.linspace(0, 1, int(0.008 * SR))   # 起音防爆音
    return wave_f * env * vol


def pad(freq: float, dur: float, vol: float) -> np.ndarray:
    """低音持续铺底：纯正弦，慢包络"""
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    env = np.minimum(t / 0.4, 1.0) * np.minimum((dur - t) / 0.6, 1.0)
    env = np.clip(env, 0, 1)
    return np.sin(2 * np.pi * freq * t) * env * vol


def place(buf: np.ndarray, sound: np.ndarray, at_sec: float):
    i = int(at_sec * SR)
    j = min(i + len(sound), len(buf))
    if i < len(buf):
        buf[i:j] += sound[: j - i]


def compose(chords: list, bpm: float, note_div: int, dur_total: float,
            arpeggio_vol: float = 0.55, bass_vol: float = 0.30,
            style: str = "updown", dissonance: list = None) -> np.ndarray:
    """
    chords: [[音名...], ...] 和弦进行，每个和弦 2 拍
    note_div: 每拍细分数（2=八分音符琶音）
    dissonance: 额外的不协和音符（tense 用），随机插入
    """
    beat = 60.0 / bpm
    buf = np.zeros(int(SR * dur_total))
    t = 0.0
    ci = 0
    while t < dur_total - beat:
        chord = chords[ci % len(chords)]
        # 低音：根音持续一个和弦周期
        place(buf, pad(NOTE_FREQ[chord[0]] / 2, beat * 2, bass_vol), t)
        # 琶音：和弦音符按 note_div 细分上行/上下行
        notes = chord + [chord[1]] if style == "updown" else chord
        seq = notes if style != "updown" else notes + notes[-2::-1]
        step = beat / note_div
        for k in range(note_div * 2):
            at = t + k * step
            if at >= dur_total:
                break
            f = NOTE_FREQ[seq[k % len(seq)]]
            place(buf, tone(f, step * 1.6, arpeggio_vol), at)
        # 不协和点缀（tense）
        if dissonance and ci % 2 == 1:
            at = t + beat * 0.5
            place(buf, tone(NOTE_FREQ[dissonance[ci % len(dissonance)]], beat, arpeggio_vol * 0.7), at)
        t += beat * 2
        ci += 1
    return buf


def save_mp3(buf: np.ndarray, out: Path):
    buf = buf / (np.abs(buf).max() + 1e-9) * 0.85
    wav_path = out.with_suffix(".wav")
    with wave.open(str(wav_path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((buf * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(wav_path), "-af",
                    "aecho=0.7:0.6:120:0.25,lowpass=f=4500,volume=0.9",
                    "-b:a", "128k", str(out.with_suffix(".mp3"))], check=True)
    wav_path.unlink()
    print(f"[生成] {out.name} ({out.with_suffix('.mp3').stat().st_size/1024:.0f} KB)")


SONGS = {
    "calm": lambda: compose(
        [["C4", "E4", "G4"], ["G3", "B3", "D4"], ["A3", "C4", "E4"], ["F3", "A3", "C4"]],
        bpm=56, note_div=2, dur_total=64, arpeggio_vol=0.5),
    "neutral": lambda: compose(
        [["C4", "E4", "G4"], ["A3", "C4", "E4"], ["F3", "A3", "C4"], ["G3", "B3", "D4"]],
        bpm=66, note_div=2, dur_total=64),
    "happy": lambda: compose(
        [["C4", "E4", "G4", "C5"], ["F3", "A3", "C4", "F4"], ["G3", "B3", "D4", "G4"], ["C4", "E4", "G4", "C5"]],
        bpm=100, note_div=2, dur_total=64, arpeggio_vol=0.6),
    "tense": lambda: compose(
        [["A2", "E3", "A3"], ["A2", "D#3", "E3"], ["A2", "E3", "A3"], ["G#2", "E3", "G#3"]],
        bpm=92, note_div=4, dur_total=64, arpeggio_vol=0.5,
        dissonance=["A#3", "D#4"]),
    "sad": lambda: compose(
        [["A3", "C4", "E4"], ["F3", "A3", "C4"], ["C4", "E4", "G4"], ["E3", "G3", "B3"]],
        bpm=48, note_div=2, dur_total=64, arpeggio_vol=0.45),
}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--out", default="assets/bgm")
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    backup = ROOT / "assets" / "bgm_placeholder"
    if args.backup and out_dir.exists():
        backup.mkdir(parents=True, exist_ok=True)
        for f in out_dir.glob("*.mp3"):
            (backup / f.name).write_bytes(f.read_bytes())
        print(f"旧曲已备份到 {backup}")

    for k, fn in SONGS.items():
        print(f"[{k}] 合成中…")
        save_mp3(fn(), out_dir / k)
    print(f"\n完成: {out_dir}")
