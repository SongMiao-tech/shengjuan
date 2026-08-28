# -*- coding: utf-8 -*-
"""
MiniMax 自定义音色链路（Voice Design + T2A 合成）
用法:
  # 设计新音色（返回 voice_id 并保存试听音频）
  python scripts/minimax_voice.py design --prompt "温柔的年轻女声,讲睡前故事的姐姐,语速缓慢亲切" \
      --preview "宝贝，今晚我们要讲一个关于星星的故事哦。" -o outputs/m0
  # 用已有 voice_id 合成任意文本
  python scripts/minimax_voice.py tts --voice-id ttv-voice-xxx --text "你好呀" -o outputs/m0/test.mp3

费用说明: Voice Design $3/音色（首次用它合成时收取）；试听文本约 $30/百万字符。
"""
import argparse
import base64
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

BASE = "https://api.minimax.chat"
DESIGN_URL = f"{BASE}/v1/voice_design"
TTS_URL = f"{BASE}/v1/t2a_v2"


def load_env() -> dict:
    env = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def save_audio(data: bytes, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    print(f"  已保存: {p} ({len(data)/1024:.0f} KB)")
    return p


def cmd_design(args) -> None:
    env = load_env()
    key, gid = env.get("MINIMAX_API_KEY"), env.get("MINIMAX_GROUP_ID")
    if not key or not gid:
        print("[错误] .env 缺少 MINIMAX_API_KEY / MINIMAX_GROUP_ID", file=sys.stderr)
        sys.exit(1)

    body = {
        "model": "minimax-voice-design",
        "prompt": args.prompt,
        "preview_text": args.preview,
        "output_format": "url",
    }
    t0 = time.time()
    r = requests.post(DESIGN_URL, headers=headers(key), json=body, timeout=60)
    obj = r.json()
    br = obj.get("base_resp", {})
    if r.status_code != 200 or br.get("status_code") != 0:
        print(f"[失败] HTTP {r.status_code} | {json.dumps(obj, ensure_ascii=False)[:400]}", file=sys.stderr)
        sys.exit(1)

    voice_id = obj["voice_id"]
    audio_url = obj.get("trial_audio") or obj.get("data", {}).get("audio")
    print(f"[设计成功] {time.time()-t0:.1f}s | voice_id={voice_id}")

    if isinstance(audio_url, str) and audio_url.startswith("http"):
        audio = requests.get(audio_url, timeout=60).content
        save_audio(audio, Path(args.out) / "designed_preview.mp3")

    meta = {
        "voice_id": voice_id,
        "prompt": args.prompt,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "group_id": gid,
    }
    meta_path = Path(args.out) / "designed_voice.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  音色档案已保存: {meta_path}")


def cmd_tts(args) -> None:
    env = load_env()
    key, gid = env.get("MINIMAX_API_KEY"), env.get("MINIMAX_GROUP_ID")
    body = {
        "model": args.model,
        "text": args.text,
        "stream": False,
        "output_format": "hex",
        "voice_setting": {
            "voice_id": args.voice_id,
            "speed": 1.0,
            "vol": 1.0,
            "pitch": 0,
        },
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
    }
    t0 = time.time()
    r = requests.post(TTS_URL, headers=headers(key), json=body, timeout=120)
    obj = r.json()
    br = obj.get("base_resp", {})
    if r.status_code != 200 or br.get("status_code") != 0:
        print(f"[失败] HTTP {r.status_code} | {json.dumps(obj, ensure_ascii=False)[:400]}", file=sys.stderr)
        sys.exit(1)

    audio_hex = obj.get("data", {}).get("audio")
    audio = bytes.fromhex(audio_hex)
    save_audio(audio, args.out)
    print(f"  [完成] {time.time()-t0:.1f}s | 该次合成为设计音色的首次使用时将收取设计费 $3")


def main():
    parser = argparse.ArgumentParser(description="MiniMax Voice Design / TTS")
    sub = parser.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("design", help="设计新音色")
    d.add_argument("--prompt", required=True, help="音色自然语言描述")
    d.add_argument("--preview", required=True, help="试听文本（≤500字）")
    d.add_argument("-o", "--out", default="outputs/m0")
    d.set_defaults(func=cmd_design)

    t = sub.add_parser("tts", help="用 voice_id 合成语音")
    t.add_argument("--voice-id", required=True)
    t.add_argument("--text", required=True)
    t.add_argument("-o", "--out", default="outputs/m0/designed_tts.mp3")
    t.add_argument("--model", default="speech-2.8-turbo")
    t.set_defaults(func=cmd_tts)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
