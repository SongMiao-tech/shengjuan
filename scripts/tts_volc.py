# -*- coding: utf-8 -*-
"""
豆包语音合成 2.0 调用脚本（V3 HTTP 单向流式）
用法示例:
  python scripts/tts_volc.py --text "你好，世界" --speaker zh_female_yingtaowanzi_uranus_bigtts -o outputs/m0/test.mp3
  python scripts/tts_volc.py --text "你凭什么这样对我？" --emotion angry --speaker zh_male_silang_uranus_bigtts -o outputs/m0/angry.mp3
凭证从项目根目录 .env 读取（新版控制台 VOLC_API_KEY，X-Api-Key 鉴权），不打印密钥。
"""
import argparse
import base64
import json
import sys
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
RESOURCE_ID = "seed-tts-2.0"  # 豆包语音合成模型 2.0


def load_env() -> dict:
    """极简 .env 解析（不依赖 python-dotenv）"""
    env = {}
    if not ENV_PATH.exists():
        print(f"[错误] 未找到 {ENV_PATH}，请先复制 .env.example 为 .env 并填入密钥", file=sys.stderr)
        sys.exit(1)
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def synthesize(
    text: str,
    speaker: str,
    out_path: str,
    emotion: str | None = None,
    emotion_scale: int = 4,
    speech_rate: int = 0,
    loudness_rate: int = 0,
    format_: str = "mp3",
    sample_rate: int = 24000,
    uid: str = "audio-book-demo",
    resource_id: str = RESOURCE_ID,
) -> tuple[bool, str]:
    env = load_env()
    api_key = env.get("VOLC_API_KEY", "")
    if not api_key:
        print("[错误] .env 中缺少 VOLC_API_KEY（新版控制台 API Key）", file=sys.stderr)
        return False, "missing_credentials"

    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": str(uuid.uuid4()),
    }

    req_params = {
        "text": text,
        "speaker": speaker,
        "audio_params": {
            "format": format_,
            "sample_rate": sample_rate,
            "speech_rate": speech_rate,
            "loudness_rate": loudness_rate,
        },
    }
    if emotion:
        req_params["audio_params"]["emotion"] = emotion
        req_params["audio_params"]["emotion_scale"] = emotion_scale

    payload = {"user": {"uid": uid}, "req_params": req_params}

    audio = b""
    t0 = time.time()
    try:
        with requests.Session() as session:
            resp = session.post(TTS_URL, headers=headers, json=payload, stream=True, timeout=60)
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("data"):
                    audio += base64.b64decode(obj["data"])
                if obj.get("code") == 20000000:
                    usage = obj.get("usage", {})
                    print(f"  完成 | 耗时 {time.time()-t0:.1f}s | 用量(字): {usage.get('text_words', '?')}")
                    break
                if obj.get("code") != 0 and obj.get("code") is not None:
                    return False, f"code={obj.get('code')} msg={obj.get('message', '')}"
    except Exception as e:  # noqa: BLE001
        return False, f"请求异常: {e}"

    if not audio:
        return False, "未收到音频数据"

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    secs = len(audio) / (sample_rate * 2)  # 粗略估计（mp3 不精确，仅供参考）
    print(f"  已保存: {out} ({len(audio)/1024:.0f} KB, 约 {secs:.1f}s)")
    return True, "ok"


def main():
    parser = argparse.ArgumentParser(description="豆包语音合成 2.0 调用")
    parser.add_argument("--text", required=True, help="合成文本")
    parser.add_argument("--speaker", required=True, help="音色 ID，如 zh_female_yingtaowanzi_uranus_bigtts")
    parser.add_argument("-o", "--out", default="outputs/m0/out.mp3", help="输出音频路径")
    parser.add_argument("--emotion", default=None, help="情感（部分音色支持）：angry/happy/sad 等")
    parser.add_argument("--scale", type=int, default=4, help="情绪值 1~5，默认 4")
    parser.add_argument("--rate", type=int, default=0, help="语速 [-50,100]，100=2 倍速")
    parser.add_argument("--loudness", type=int, default=0, help="音量 [-50,100]")
    parser.add_argument("--resource", default="seed-tts-2.0",
                        help="资源版本: seed-tts-2.0(大模型合成) / seed-icl-2.0(声音复刻音色)")
    args = parser.parse_args()

    ok, msg = synthesize(
        args.text,
        args.speaker,
        args.out,
        emotion=args.emotion,
        emotion_scale=args.scale,
        speech_rate=args.rate,
        loudness_rate=args.loudness,
        resource_id=args.resource,
    )
    if not ok:
        print(f"[失败] {msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
