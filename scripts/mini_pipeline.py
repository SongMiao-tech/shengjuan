# -*- coding: utf-8 -*-
"""
最小闭环流水线（链路 D + B 串联）:
情感 JSON -> 按角色/情绪逐段 TTS 合成 -> ffmpeg 拼接成完整有声片段

用法: python scripts/mini_pipeline.py [-i outputs/m0/story_segments.json]
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))
from tts_volc import synthesize  # noqa: E402

# 角色 -> 音色映射（Demo 用，正式版做成配置表）
ROLE_SPEAKERS = {
    "旁白": "zh_female_yingtaowanzi_uranus_bigtts",
    "林晚": "zh_female_yingtaowanzi_uranus_bigtts",
    "陈默": "zh_male_silang_uranus_bigtts",
}

# GLM 情绪标签 -> 豆包 emotion 参数（不在表内的不传，走默认）
EMOTION_MAP = {
    "happy": "happy",
    "excited": "happy",
    "sad": "sad",
    "angry": "angry",
    "fearful": "fearful",
    "surprised": "surprised",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", default="outputs/m0/story_segments.json")
    parser.add_argument("--final", default="outputs/m0/final_story.mp3")
    args = parser.parse_args()

    seg_path = ROOT / args.input
    segments = json.loads(seg_path.read_text(encoding="utf-8"))
    out_dir = seg_path.parent / "pipeline"
    out_dir.mkdir(parents=True, exist_ok=True)

    parts = []
    for i, seg in enumerate(segments):
        speaker = ROLE_SPEAKERS.get(seg["role"], ROLE_SPEAKERS["旁白"])
        emo = EMOTION_MAP.get(seg["emotion"])
        if seg["emotion"] in ("neutral", "calm"):
            emo = None  # 中性段落用默认情感
        scale = max(1, min(5, round(1 + seg["intensity"] * 4)))
        out_path = out_dir / f"seg_{i:02d}_{seg['role']}_{seg['emotion']}.mp3"

        print(f"[{i+1}/{len(segments)}] {seg['role']} | {seg['emotion']} int={seg['intensity']} speed={seg['speed']} :: {seg['text'][:18]}...")
        ok, msg = synthesize(
            seg["text"], speaker, str(out_path),
            emotion=emo, emotion_scale=scale, speech_rate=seg["speed"],
        )
        if not ok:
            print(f"    带情绪失败({msg})，回退中性重试...")
            ok, msg = synthesize(seg["text"], speaker, str(out_path))
        if not ok:
            print(f"    [跳过] {msg}")
            continue
        parts.append(out_path)

    if not parts:
        print("[失败] 无任何段落合成成功", file=sys.stderr)
        sys.exit(1)

    # ffmpeg concat 拼接
    final = ROOT / args.final
    final.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_dir / "concat_list.txt"
    list_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(final)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[ffmpeg 失败] {r.stderr[-300:]}", file=sys.stderr)
        sys.exit(1)

    print(f"\n[完成] 成品: {final} | 段落 {len(parts)}/{len(segments)}")


if __name__ == "__main__":
    main()
