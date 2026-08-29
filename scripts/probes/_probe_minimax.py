# -*- coding: utf-8 -*-
"""探测 MiniMax t2a_v2 的域名与 GroupId 组合"""
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

env = {}
for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env[k.strip()] = v.strip()

KEY = env["MINIMAX_API_KEY"]
GID = env["MINIMAX_GROUP_ID"]

# 先用一个最便宜的预置音色短文本测试鉴权组合
BODY = {
    "model": "speech-2.8-turbo",
    "text": "你好",
    "stream": False,
    "output_format": "hex",
    "voice_setting": {"voice_id": "female-shaonv", "speed": 1.0, "vol": 1.0, "pitch": 0},
    "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
}
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

CASES = [
    ("国内站 api.minimax.chat + GroupId", f"https://api.minimax.chat/v1/t2a_v2?GroupId={GID}"),
    ("国内站 不带 GroupId", "https://api.minimax.chat/v1/t2a_v2"),
    ("国际站 api.minimax.io + GroupId", f"https://api.minimax.io/v1/t2a_v2?GroupId={GID}"),
    ("国际站 不带 GroupId", "https://api.minimax.io/v1/t2a_v2"),
]

for label, url in CASES:
    try:
        r = requests.post(url, headers=H, json=BODY, timeout=30)
        obj = r.json()
        br = obj.get("base_resp", {})
        has_audio = bool(obj.get("data", {}).get("audio"))
        print(f"[{label}] HTTP {r.status_code} | status={br.get('status_code')} {br.get('status_msg')} | audio={has_audio}")
        if has_audio:
            print(">>> 鉴权成功组合找到！")
            break
    except Exception as e:  # noqa: BLE001
        print(f"[{label}] 异常: {e}")
