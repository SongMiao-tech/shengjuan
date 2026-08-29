# -*- coding: utf-8 -*-
"""用旧版 mega_tts 接口探测声音复刻训练（旧版凭证 + Resource-Id 组合）"""
import base64
import json
import sys
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
env = {}
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env[k.strip()] = v.strip()

APP_ID = env["VOLC_APP_ID"]          # api-key-20260827100210
TOKEN = env["VOLC_ACCESS_TOKEN"]     # baf345aa-...
AUDIO = Path(r"C:/Users/37584/Downloads/标准录音 3.mp3")
TEXT = "床前明月光，疑是地上霜。举头望明月，低头思故乡"
SPEAKER = "S_7PtM1phd2"

b64 = base64.b64encode(AUDIO.read_bytes()).decode("ascii")
body = {
    "appid": APP_ID,
    "speaker_id": SPEAKER,
    "audios": [{"audio_bytes": b64, "text": TEXT, "audio_format": "mp3"}],
    "source": 2,
}

URL = "https://openspeech.bytedance.com/api/v1/mega_tts/audio/upload"

for rid in ["seed-icl-2.0", "seed-icl-1.0"]:
    for auth in [f"Bearer; {TOKEN}", f"Bearer;{TOKEN}"]:
        headers = {
            "Authorization": auth,
            "Resource-Id": rid,
            "Content-Type": "application/json",
            "X-Api-Resource-Id": rid,
        }
        try:
            r = requests.post(URL, headers=headers, json=body, timeout=120)
            print(f"[{rid}] auth='{auth[:12]}...' -> HTTP {r.status_code} | {r.text[:200]}")
            if r.status_code == 200 and '"StatusCode":0' in r.text.replace(" ", ""):
                print(">>> 成功！")
                sys.exit(0)
        except Exception as e:  # noqa: BLE001
            print(f"[{rid}] 异常: {e}")
