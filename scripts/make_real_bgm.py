# -*- coding: utf-8 -*-
"""
用 MiniMax music-1.5 生成情绪 BGM 曲库（替换 ffmpeg 合成的占位垫乐）
用法: python scripts/make_real_bgm.py [-o assets/bgm] [--only tense]
成本: 约 1 元/首。生成 90s 内音乐；歌词用极简哼唱词 + 提示词强调纯器乐。
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

# (prompt, lyrics) —— prompt 强调纯器乐无人声；lyrics 用哼唱词
SONGS = {
    "calm": {
        "prompt": "轻柔舒缓的纯音乐，无人声器乐曲，温暖的钢琴与柔和弦乐，慢节奏，平静安宁，适合夜晚睡前故事场景，氛围温柔治愈。",
        "lyrics": "[Intro]\n啦啦啦 呜\n\n[Verse]\n嗯——\n\n[Outro]\n啦啦… 呜…",
    },
    "neutral": {
        "prompt": "温暖自然的轻音乐，无人声器乐曲，原声吉他轻轻拨弦与轻柔打击乐，平和流畅，适合日常叙事场景，松弛自然。",
        "lyrics": "[Verse]\n嗯 嗯 嗯\n\n[Chorus]\n啦 啦 啦\n\n[Outro]\n嗯——",
    },
    "happy": {
        "prompt": "明亮欢快的轻音乐，无人声器乐曲，活泼的钢琴、尤克里里与口哨元素，充满阳光感，适合欢快的童话故事场景，轻快跳跃。",
        "lyrics": "[Intro]\n啦啦啦 啦啦啦\n\n[Verse]\n啦 啦 啦啦啦\n\n[Chorus]\n啦啦啦啦 嗯！\n\n[Outro]\n啦啦啦——",
    },
    "tense": {
        "prompt": "紧张压抑的纯音乐，无人声器乐曲，低音弦乐渐强与不协和音程，鼓点由缓渐急，营造悬疑紧张氛围，适合惊险故事高潮。",
        "lyrics": "[Intro]\n嗯… 嗯…\n\n[Verse]\n咚 咚 咚咚\n\n[Outro]\n嗯——",
    },
    "sad": {
        "prompt": "忧伤深情的纯音乐，无人声器乐曲，大提琴与钢琴对话，缓慢哀伤，适合离别与回忆场景，克制而动人。",
        "lyrics": "[Verse]\n呜—— 啦…\n\n[Chorus]\n嗯 嗯 呜\n\n[Outro]\n啦……",
    },
}


def load_env():
    env = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def generate_one(key: str, meta: dict, api_key: str) -> bytes | None:
    body = {"model": "music-1.5", "prompt": meta["prompt"], "lyrics": meta["lyrics"],
            "output_format": "hex",
            "audio_setting": {"sample_rate": 44100, "bitrate": 128000, "format": "mp3"}}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    # 文档域名优先，失败回退 t2a 同域
    for host in ("https://api.minimaxi.com", "https://api.minimax.chat"):
        try:
            t0 = time.time()
            r = requests.post(f"{host}/v1/music_generation", headers=headers, json=body, timeout=300)
            obj = r.json()
            br = obj.get("base_resp", {})
            if r.status_code != 200 or br.get("status_code") != 0:
                print(f"  [{host}] 失败: {br.get('status_code')} {br.get('status_msg', '')[:80]}")
                continue
            data = obj.get("data", {})
            status = data.get("status")
            if status != 2:
                print(f"  [{host}] 生成中(status={status})，等待…")
                time.sleep(8)
                continue
            audio = bytes.fromhex(data["audio"])
            print(f"  生成成功 {time.time()-t0:.0f}s, {len(audio)/1024:.0f} KB")
            return audio
        except Exception as e:  # noqa: BLE001
            print(f"  [{host}] 异常: {e}")
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--out", default="assets/bgm")
    parser.add_argument("--only", default=None, help="只生成指定情绪（默认全部）")
    parser.add_argument("--backup", action="store_true", help="备份旧曲到 assets/bgm_placeholder")
    args = parser.parse_args()

    env = load_env()
    api_key = env.get("MINIMAX_API_KEY")
    if not api_key:
        print("[错误] .env 缺少 MINIMAX_API_KEY", file=sys.stderr)
        sys.exit(1)

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    backup = ROOT / "assets" / "bgm_placeholder"
    if args.backup and out_dir.exists():
        backup.mkdir(parents=True, exist_ok=True)
        for f in out_dir.glob("*.mp3"):
            (backup / f.name).write_bytes(f.read_bytes())
        print(f"旧曲已备份到 {backup}")

    keys = [args.only] if args.only else list(SONGS)
    ok, fail = [], []
    for k in keys:
        if k not in SONGS:
            print(f"[跳过] 未知情绪 {k}")
            continue
        print(f"[{k}] 生成中…（约 30~90 秒）")
        audio = generate_one(k, SONGS[k], api_key)
        if audio:
            (out_dir / f"{k}.mp3").write_bytes(audio)
            ok.append(k)
        else:
            fail.append(k)
        time.sleep(2)

    print(f"\n完成：{len(ok)} 成功{('，失败: ' + ','.join(fail)) if fail else ''}")
    print("提醒：生成后请人工试听，若带明显人声可重新生成该情绪（重跑 --only 情绪名）")


if __name__ == "__main__":
    main()
