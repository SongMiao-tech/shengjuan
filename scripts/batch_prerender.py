# -*- coding: utf-8 -*-
"""批量预生成睡前故事音频：本机跑（用 .env 密钥），产出 audio/{sid}.mp3 + {sid}.seg.json
跑前确认 web/stories/ 已由 build_story_lib.py 生成。
用法: python scripts/batch_prerender.py            # 全部缺音频的
      python scripts/batch_prerender.py s01 s02    # 指定"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
STORIES = ROOT / "web" / "stories"
AUDIO = ROOT / "web" / "audio"
AUDIO.mkdir(parents=True, exist_ok=True)
for line in (ROOT.parent / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

WORK = Path(tempfile.gettempdir()) / "audiobook_prerender"
WORK.mkdir(parents=True, exist_ok=True)
NARRATOR = "ttv-voice-2026082710331426-UpOQXpI8"   # 睡前故事姐姐（MiniMax 设计音色）
STYLE = "bedtime"
PAUSE = 0.8

sys.path.insert(0, str(ROOT / "cloudrun"))
import importlib.util
spec = importlib.util.spec_from_file_location("sj_app", ROOT / "cloudrun" / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
app.WORK = WORK    # Windows 路径重定向

def probe_dur(p: Path) -> float:
    try:
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip())
    except (ValueError, TypeError):
        return 0.0

def render_story(sid: str, story: dict) -> dict:
    d = WORK / f"pre_{sid}"
    d.mkdir(parents=True, exist_ok=True)
    paras = [p.strip() for p in story["text"].split("\n\n+") if p.strip()] if "\n\n+" in story["text"] \
        else [p.strip() for p in __import__("re").split(r"\n\n+", story["text"]) if p.strip()]
    parts, timeline, cursor = [], [], 0.0
    for i, p in enumerate(paras):
        seg_path = d / f"seg_{i:03d}.mp3"
        app.synth_dispatch(p, NARRATOR, seg_path, loudness=5)   # bedtime 响度
        parts.append(seg_path)
        time.sleep(3)   # MiniMax RPM 限流保护
        dur = probe_dur(seg_path)
        timeline.append({"idx": i, "start_ms": int(cursor * 1000), "dur_ms": int(dur * 1000), "text": p})
        cursor += dur + PAUSE
        print(f"    seg {i+1}/{len(paras)} ({dur:.1f}s)", flush=True)
    # 拼接（bedtime 混音参数）
    sil = d / "sil.mp3"
    if not sil.exists():
        app.ff(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(PAUSE), "-b:a", "128k", str(sil)])
    lst = d / "concat.txt"
    lines = []
    for p in parts:
        lines += [f"file '{p}'", f"file '{sil}'"]
    lst.write_text("\n".join(lines), encoding="utf-8")
    voice = d / "voice.mp3"
    app.ff(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(voice)])
    dur = probe_dur(voice)
    fade_out_bg = max(0.0, dur - 20)
    fade_out = max(0.0, dur - 25)
    out = d / "final.mp3"
    fc = (f"[1:a]atrim=0:{dur:.2f},asetpts=PTS-STARTPTS,volume=0.22,"
          f"afade=t=in:st=0:d=5,afade=t=out:st={fade_out_bg:.2f}:d=20[bg];"
          f"[bg][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=80:release=600[ducked];"
          f"[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
          f"loudnorm=I=-18:TP=-2:LRA=9,"
          f"afade=t=in:st=0:d=2,afade=t=out:st={fade_out:.2f}:d=25[out]")
    app.ff(["-i", str(voice), "-stream_loop", "-1", "-i", str(ROOT / "assets" / "bgm" / "calm.mp3"),
            "-filter_complex", fc, "-map", "[out]", "-b:a", "128k", str(out)])
    (AUDIO / f"{sid}.mp3").write_bytes(out.read_bytes())
    (STORIES / f"{sid}.seg.json").write_text(
        json.dumps({"story_id": sid, "audio": f"audio/{sid}.mp3", "duration_s": round(dur, 1),
                    "segments": timeline}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"duration_s": round(dur, 1), "segments": len(timeline)}

def main():
    only = set(sys.argv[1:])
    results = {}
    for f in sorted(STORIES.glob("s??.json")):   # 精确匹配两位编号，排除 .seg.json
        sid = f.stem
        if only and sid not in only:
            continue
        if (AUDIO / f"{sid}.mp3").exists():
            print(f"[skip] {sid} 音频已存在")
            continue
        story = json.loads(f.read_text(encoding="utf-8"))
        print(f"[render] {sid} {story['title']} ({story['chars']} 字)...", flush=True)
        t0 = time.time()
        try:
            r = render_story(sid, story)
            results[sid] = r
            print(f"    done {r['duration_s']}s / {r['segments']} 段 / {time.time()-t0:.0f}s", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"    FAILED: {str(e)[:150]}", flush=True)
    print("\n批量预生成完成:", json.dumps(results, ensure_ascii=False))

if __name__ == "__main__":
    main()
