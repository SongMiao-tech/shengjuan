# -*- coding: utf-8 -*-
"""探测豆包可用音色：逐个候选 speaker_id 发小规模合成请求，验证可用性。
输出：可直接写入 app.py 音色池的可用清单。"""
import json
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
env = {}
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

TEXT = "夜深了，月亮升起来，小兔子揉揉眼睛，该睡觉啦。"

# 候选音色（豆包公开音色库常见 bigtts/mars 系列 ID + 已验证的 4 个）
CANDIDATES = [
    # --- 已在项目中使用/声明 ---
    ("zh_female_yingtaowanzi_uranus_bigtts", "樱桃丸子", "female"),
    ("zh_male_silang_uranus_bigtts",         "四郎",     "male"),
    ("zh_male_qingcang_uranus_bigtts",       "擎苍",     "male"),
    ("zh_female_popo_uranus_bigtts",         "婆婆",     "female"),
    # --- bigtts 通用系列候选 ---
    ("zh_female_cancan_mars_bigtts",         "灿灿",     "female"),
    ("zh_female_mengyao_mars_bigtts",        "梦瑶",     "female"),
    ("zh_female_tianmeixiaoyuan_mars_bigtts","甜美小원", "female"),
    ("zh_female_wanwanxiaoxingxing_mars_bigtts","弯弯小星星","female"),
    ("zh_female_ludi_mars_bigtts",           "鹿笛",     "female"),
    ("zh_female_xingmeng_mars_bigtts",       "星梦",     "female"),
    ("zh_male_beijingxiaoye_mars_bigtts",    "北京小爷", "male"),
    ("zh_male_wanqudashu_mars_bigtts",       "弯曲大叔", "male"),
    ("zh_male_changtianyi_mars_bigtts",      "长天一",   "male"),
    ("zh_male_ruishiniu_mars_bigtts",        "锐视牛",   "male"),
    ("zh_male_yuanboxiaohei_mars_bigtts",    "苑博小黑", "male"),
    ("zh_male_qingshuangnanzhu_mars_bigtts", "清爽男猪", "male"),
    ("zh_male_shaoergushi_mars_bigtts",      "少儿故事", "male"),
    ("zh_female_shaoergushi_mars_bigtts",    "少儿故事女","female"),
    ("zh_female_kawujiang_mars_bigtts",      "卡屋酱",   "female"),
    ("zh_male_jingqiankanbo_mars_bigtts",    "镜前侃伯", "male"),
]

def probe(speaker: str) -> dict:
    body = {"user": {"uid": "audiobook-probe"},
            "req_params": {"text": TEXT, "speaker": speaker,
                           "audio_params": {"format": "mp3", "sample_rate": 24000, "speech_rate": 0}}}
    headers = {"X-Api-Key": env["VOLC_API_KEY"], "X-Api-Resource-Id": "seed-tts-2.0",
               "X-Api-Request-Id": str(uuid.uuid4())}
    try:
        r = requests.post("https://openspeech.bytedance.com/api/v3/tts/unidirectional",
                          headers=headers, json=body, timeout=30, stream=True)
        ok, err, audio_len = False, "", 0
        if r.status_code == 200:
            for line in r.iter_lines():
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("code") not in (0, None) and obj.get("code") != 20000000:
                    err = str(obj.get("message", ""))[:80]
                data = obj.get("data")
                if data:
                    audio_len += len(data)
                if obj.get("code") == 20000000:
                    ok = True
        else:
            err = f"HTTP {r.status_code}"
        return {"ok": ok, "err": err, "bytes": audio_len // 4 * 3}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "err": str(e)[:80], "bytes": 0}

results = []
for sid, name, gender in CANDIDATES:
    res = probe(sid)
    mark = "✓" if res["ok"] else "✗"
    print(f"{mark} {name:6s} {gender:6s} {sid}  {res['err'] or f'{res[chr(98)+chr(121)+chr(116)+chr(101)+chr(115)]}B audio'}")
    if res["ok"]:
        results.append({"speaker_id": sid, "name": name, "gender": gender})

out = Path(__file__).parent / "volc_voices_available.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
males = [r for r in results if r["gender"] == "male"]
females = [r for r in results if r["gender"] == "female"]
print(f"\n可用: male {len(males)} 个, female {len(females)} 个 -> {out.name}")
