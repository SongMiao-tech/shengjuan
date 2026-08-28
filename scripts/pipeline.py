# -*- coding: utf-8 -*-
"""
个性化有声读物生成流水线（M1）
文本 -> GLM 情感曲线 -> 多角色多情绪 TTS -> BGM 情绪匹配 + ducking 混音 -> 响度归一 -> 成品

用法:
  python scripts/pipeline.py --input story.txt -o outputs/m1/final.mp3
  python scripts/pipeline.py --input story.txt --narrator S_xxxxx     # 用克隆音色读旁白
  python scripts/pipeline.py --input story.txt --no-bgm               # 纯人声版
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))
from llm_emotion import analyze  # noqa: E402
from tts_volc import synthesize  # noqa: E402

BGM_DIR = ROOT / "assets" / "bgm"
TMP_DIR = ROOT / "outputs" / "m1" / "segments"

DEFAULT_NARRATOR = "zh_female_yingtaowanzi_uranus_bigtts"   # 樱桃丸子
# 角色音色按性别从声池自动分配（同角色锁定同一音色）
MALE_POOL = ["zh_male_silang_uranus_bigtts", "zh_male_qingcang_uranus_bigtts"]
FEMALE_POOL = ["zh_female_yingtaowanzi_uranus_bigtts", "zh_female_popo_uranus_bigtts"]
EMOTION_MAP = {  # GLM 情绪 -> 豆包 emotion（不在表内的走默认）
    "happy": "happy", "excited": "happy",
    "sad": "sad", "angry": "angry",
    "fearful": "fearful", "surprised": "surprised",
}
BGM_GROUP = {  # 情绪 -> BGM 分组（选曲用）
    "neutral": "neutral", "calm": "calm", "sad": "sad",
    "happy": "happy", "excited": "happy",
    "tense": "tense", "angry": "tense", "fearful": "tense",
}


def assign_speakers(segments: list, narrator: str) -> dict:
    """按角色性别动态分配音色；旁白固定用 narrator；同一角色全篇锁定同一音色"""
    pools = {"male": list(MALE_POOL), "female": list(FEMALE_POOL)}
    role_map = {}
    for seg in segments:
        r = seg.get("role", "旁白")
        if r == "旁白":
            seg["speaker"] = narrator
            continue
        if r not in role_map:
            pool = pools.get(seg.get("gender", "unknown"))
            role_map[r] = pool.pop(0) if pool else narrator   # unknown 跟随旁白
        seg["speaker"] = role_map[r]
    return role_map


def pick_resource(speaker: str) -> str:
    """按音色类型选资源版本：S_/custom 开头=声音复刻（seed-icl-2.0），其余=大模型合成（seed-tts-2.0）"""
    return "seed-icl-2.0" if speaker.startswith(("S_", "custom")) else "seed-tts-2.0"


def pick_bgm(segments) -> Path | None:
    """按情绪强度加权投票选 BGM"""
    score: dict = {}
    for seg in segments:
        group = BGM_GROUP.get(seg["emotion"], "neutral")
        score[group] = score.get(group, 0.0) + 0.3 + seg["intensity"]
    ranked = sorted(score.items(), key=lambda kv: -kv[1])
    for group, _ in ranked:
        p = BGM_DIR / f"{group}.mp3"
        if p.exists():
            print(f"[BGM] 情绪投票 {ranked} -> 选用 {group}.mp3")
            return p
    return None


def run_ffmpeg(args: list) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg: {r.stderr[-400:]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="故事文本文件")
    parser.add_argument("-o", "--out", default="outputs/m1/final.mp3")
    parser.add_argument("--narrator", default=DEFAULT_NARRATOR, help="旁白音色（可传克隆音色 S_xxx）")
    parser.add_argument("--no-bgm", action="store_true", help="不加背景音乐")
    parser.add_argument("--bgm-volume", type=float, default=0.32, help="BGM 音量系数")
    args = parser.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"[错误] 文件不存在: {src}", file=sys.stderr)
        sys.exit(1)
    text = src.read_text(encoding="utf-8").strip()
    print(f"=== 流水线启动 | {len(text)} 字 ===")

    # 1. 情感分析
    print("[1/4] GLM 情感分析...")
    segments, msg = analyze(text)
    if segments is None:
        print(f"[失败] {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"  {len(segments)} 段 | 角色: {sorted({s['role'] for s in segments})}")

    # 2. 逐段合成
    print("[2/4] 分段合成...")
    role_map = assign_speakers(segments, args.narrator)
    print(f"  角色分配: {role_map}")
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    for f in TMP_DIR.glob("seg_*.mp3"):
        f.unlink()
    voice_parts = []
    for i, seg in enumerate(segments):
        speaker = seg["speaker"]
        emo = EMOTION_MAP.get(seg["emotion"])
        if seg["emotion"] in ("neutral", "calm"):
            emo = None
        scale = max(1, min(5, round(1 + seg["intensity"] * 4)))
        out_seg = TMP_DIR / f"seg_{i:03d}.mp3"
        print(f"  [{i+1}/{len(segments)}] {seg['role']}|{seg['emotion']} :: {seg['text'][:16]}...")
        ok, m = synthesize(seg["text"], speaker, str(out_seg), emotion=emo, emotion_scale=scale,
                           speech_rate=seg["speed"], resource_id=pick_resource(speaker))
        if not ok:
            ok, m = synthesize(seg["text"], speaker, str(out_seg), resource_id=pick_resource(speaker))  # 回退中性
        if not ok:
            print(f"    [跳过] {m}")
            continue
        voice_parts.append(out_seg)
    if not voice_parts:
        print("[失败] 无段落合成成功", file=sys.stderr)
        sys.exit(1)

    # 3. 拼接语音轨（段间 280ms 静音）
    print("[3/4] 拼接语音轨...")
    silence = TMP_DIR / "silence.mp3"
    run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.28", "-b:a", "128k", str(silence)])
    concat_list = TMP_DIR / "concat.txt"
    lines = []
    for p in voice_parts:
        lines.append(f"file '{p.as_posix()}'")
        lines.append(f"file '{silence.as_posix()}'")
    (TMP_DIR / "voice_concat.txt").write_text("\n".join(lines), encoding="utf-8")
    voice_track = TMP_DIR / "voice_full.mp3"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(TMP_DIR / "voice_concat.txt"), "-c", "copy", str(voice_track)])
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(voice_track)],
        capture_output=True, text=True).stdout.strip())
    print(f"  语音轨 {len(voice_parts)} 段 / {dur:.1f}s")

    # 4. BGM 匹配 + ducking 混音 + 响度归一
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bgm = None if args.no_bgm else pick_bgm(segments)
    print("[4/4] 混音（ducking + loudnorm）...")
    if bgm:
        fc = (
            f"[1:a]atrim=0:{dur:.2f},asetpts=PTS-STARTPTS,volume={args.bgm_volume}[bg];"
            f"[bg][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=80:release=600[ducked];"
            f"[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
            f"loudnorm=I=-16:TP=-1.5:LRA=11[out]"
        )
        run_ffmpeg(["-i", str(voice_track), "-stream_loop", "-1", "-i", str(bgm),
                    "-filter_complex", fc, "-map", "[out]", "-b:a", "192k", str(out)])
    else:
        run_ffmpeg(["-i", str(voice_track), "af" if False else "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-b:a", "192k", str(out)])

    size_kb = out.stat().st_size / 1024
    print(f"\n=== 完成 === {out} ({size_kb:.0f} KB / {dur:.1f}s | 段落 {len(voice_parts)}/{len(segments)} | BGM: {bgm.name if bgm else '无'})")


if __name__ == "__main__":
    main()
