# -*- coding: utf-8 -*-
"""
探测火山引擎豆包语音的鉴权组合（M0-B 排查用）
依次尝试 V3 HTTP 接口的 新旧控制台鉴权组合 与 V1 接口，打印各组合返回码。
"""
import json
import sys
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

TTS_V3 = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
TTS_V1 = "https://openspeech.bytedance.com/api/v1/tts"

TEXT = "测试"


def load_env() -> dict:
    env = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def try_v3(label: str, headers: dict) -> None:
    payload = {
        "user": {"uid": "probe"},
        "req_params": {
            "text": TEXT,
            "speaker": "zh_female_yingtaowanzi_uranus_bigtts",
            "audio_params": {"format": "mp3", "sample_rate": 24000},
        },
    }
    try:
        r = requests.post(TTS_V3, headers=headers, json=payload, timeout=20)
        body = r.text[:200].replace("\n", " ")
        print(f"[V3] {label} -> HTTP {r.status_code} | {body}")
    except Exception as e:  # noqa: BLE001
        print(f"[V3] {label} -> 异常 {e}")


def try_v1(label: str, headers: dict, body: dict) -> None:
    try:
        r = requests.post(TTS_V1, headers=headers, json=body, timeout=20)
        body_txt = r.text[:200].replace("\n", " ")
        print(f"[V1] {label} -> HTTP {r.status_code} | {body_txt}")
    except Exception as e:  # noqa: BLE001
        print(f"[V1] {label} -> 异常 {e}")


def main():
    env = load_env()
    a = env.get("VOLC_APP_ID", "")
    t = env.get("VOLC_ACCESS_TOKEN", "")
    print(f"AppID 变量: {a}")
    print(f"Token 变量: {t[:12]}...({len(t)} 字符)")
    print("---")

    rid = "seed-tts-2.0"
    common = {"X-Api-Resource-Id": rid, "X-Api-Request-Id": str(uuid.uuid4())}

    # V3 旧版控制台: X-Api-App-Id + X-Api-Access-Key
    try_v3("旧版 AppId=api-key / AccessKey=UUID", {**common, "X-Api-App-Id": a, "X-Api-Access-Key": t})
    try_v3("旧版 AppId=UUID / AccessKey=api-key", {**common, "X-Api-App-Id": t, "X-Api-Access-Key": a})
    # V3 新版控制台: X-Api-Key
    try_v3("新版 Key=api-key", {**common, "X-Api-Key": a})
    try_v3("新版 Key=UUID", {**common, "X-Api-Key": t})

    # V1 HTTP: Authorization Bearer + body 内 appid
    v1_body = {
        "app": {"appid": a, "token": "any", "cluster": "volcano_tts"},
        "user": {"uid": "probe"},
        "audio": {"voice_type": "zh_female_yingtaowanzi_uranus_bigtts", "encoding": "mp3"},
        "request": {"reqid": str(uuid.uuid4()), "text": TEXT, "operation": "query"},
    }
    try_v1("V1 Bearer=UUID", {"Authorization": f"Bearer; {t}"}, v1_body)
    v1_body2 = {**v1_body, "app": {"appid": t, "token": "any", "cluster": "volcano_tts"}}
    try_v1("V1 Bearer=api-key", {"Authorization": f"Bearer; {a}"}, v1_body2)


if __name__ == "__main__":
    main()
