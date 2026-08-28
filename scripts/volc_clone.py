# -*- coding: utf-8 -*-
"""
火山引擎豆包声音复刻（音色训练 HTTP /api/v3/tts/voice_clone）
用法:
  python scripts/volc_clone.py train --audio "路径.mp3" --text "录音原文" \
      --speaker S_xxxxx --demo-text "试听文本" -o outputs/m0
响应里 status=2(Success)/4(Active) 即可合成，demo_audio 为试听链接（1 小时有效）。
"""
import argparse
import base64
import json
import sys
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

TRAIN_URL = "https://openspeech.bytedance.com/api/v3/tts/voice_clone"


def load_env() -> dict:
    env = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def main():
    parser = argparse.ArgumentParser(description="豆包声音复刻训练")
    parser.add_argument("cmd", choices=["train"])
    parser.add_argument("--audio", required=True, help="参考音频路径（wav/mp3/ogg/m4a/aac）")
    parser.add_argument("--text", required=True, help="录音对应的精确原文")
    parser.add_argument("--speaker", required=True, help="控制台获取的音色槽位 ID，如 S_xxx")
    parser.add_argument("--demo-text", default="你好呀，我是你的专属克隆声音，以后可以用我来为你朗读故事啦。")
    parser.add_argument("--denoise", action="store_true", help="开启降噪（手机录音建议开）")
    parser.add_argument("--resource", default="seed-icl-2.0", help="复刻资源版本: seed-icl-2.0 / seed-icl-1.0")
    parser.add_argument("--custom-id", default=None,
                        help="自定义音色代号（后付费，免控制台槽位）。提供时 --speaker 必须传固定值 custom_speaker_id")
    parser.add_argument("-o", "--out", default="outputs/m0")
    args = parser.parse_args()

    env = load_env()
    api_key = env.get("VOLC_API_KEY")
    if not api_key:
        print("[错误] .env 缺少 VOLC_API_KEY", file=sys.stderr)
        sys.exit(1)

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"[错误] 音频不存在: {audio_path}", file=sys.stderr)
        sys.exit(1)
    audio_b64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")

    body = {
        "speaker_id": args.speaker,
        "audio": {
            "data": audio_b64,
            "format": audio_path.suffix.lstrip(".").lower(),
        },
        "text": args.text,
        "language": 0,
        "extra_params": {
            "demo_text": args.demo_text,
            "enable_audio_denoise": bool(args.denoise),
        },
    }
    if args.custom_id:
        body["custom_speaker_id"] = args.custom_id
    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Resource-Id": args.resource,
    }

    print(f"上传 {audio_path.name} ({audio_path.stat().st_size/1024:.0f} KB)，开始训练...")
    r = requests.post(TRAIN_URL, headers=headers, json=body, timeout=300)
    if r.status_code != 200:
        print(f"[失败] HTTP {r.status_code} | {r.text[:400]}", file=sys.stderr)
        sys.exit(1)

    obj = r.json()
    status = obj.get("status")
    status_name = {0: "NotFound", 1: "Training", 2: "Success", 3: "Failed", 4: "Active"}.get(status, str(status))
    print(f"[训练] status={status}({status_name}) | speaker={obj.get('speaker_id')} | 剩余训练次数={obj.get('available_training_times', '?')}")
    if obj.get("message"):
        print(f"  message: {obj['message']}")

    demo_url = obj.get("demo_audio")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "clone_voice_meta.json").write_text(
        json.dumps({"speaker_id": args.speaker, "status": status_name,
                    "reference_text": args.text, "audio": str(audio_path)}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    if demo_url:
        try:
            demo = requests.get(demo_url, timeout=60).content
            p = out_dir / f"07_clone_demo_{args.speaker}.mp3"
            p.write_bytes(demo)
            print(f"[试听已保存] {p} ({len(demo)/1024:.0f} KB)  ← 训练自动生成的试听")
        except Exception as e:  # noqa: BLE001
            print(f"[下载试听失败] {e} | URL: {demo_url}")

    if status == 3:
        print("[注意] 训练失败，检查原文与音频是否一致、音频是否清晰", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
