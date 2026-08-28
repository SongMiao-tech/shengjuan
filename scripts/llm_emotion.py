# -*- coding: utf-8 -*-
"""
GLM-4-Flash 文本情感分析（链路 D）
把小说文本切分为朗读段落，标注情绪/强度/语速/角色/重音词 → 结构化 JSON。
输出供 TTS 情绪驱动合成使用（情绪曲线的雏形）。

用法:
  python scripts/llm_emotion.py --file outputs/m0/story.txt -o outputs/m0/story_segments.json
  python scripts/llm_emotion.py --text "一段文字..."
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = "glm-4-flash"

VALID_EMOTIONS = {"neutral", "happy", "sad", "angry", "fearful", "surprised", "calm", "tense", "excited"}

PROMPT_TEMPLATE = """你是有声书情感分析师。分析下面的文本，把它切分为适合朗读的段落（每段不超过50个字，保持句子完整），并为每段标注朗读参数：
- text: 该段原文内容
- emotion: 情绪标签，只能从这些里选：neutral/happy/sad/angry/fearful/surprised/calm/tense/excited
- intensity: 情绪强度 0.0~1.0（中性段给0.3以下）
- speed: 语速调整建议，整数，范围-30~30（紧张时加速为正数，悲伤助眠时放慢为负数，正常为0）
- role: 该段的朗读归属，判定规则：
    * 台词段——角色亲口说的话（无论是否带引号），填该角色名；
    * 叙述段——作者的描写、动作、心理说明（如"林晚盯着屏幕……"、"她喃喃道，手指微微发抖"），一律填"旁白"，即使句中出现了角色名字；
    * 若一句中台词与叙述混杂（如：「"这不可能。"她说道。」），沿引号边界拆分为两段：台词单独一段填角色名，叙述单独一段填旁白；
    * 区分关键：看这段话是不是角色"说出口的内容"。有说话人动词（说道/吼道/喃喃道/低声问）紧邻的口语短句通常是台词；第三人称的描写是叙述。
- gender: 台词角色的性别，male/female/unknown（旁白与非台词段一律填unknown；同一角色各段必须一致，依据名字与上下文判断）
- emphasis: 需要重读的关键词数组（最多3个，没有则空数组）

切分与归属示例——
输入文本：警报响起。"关掉它！"陈默吼道。林晚的手停在键盘上。
正确输出片段：
[{"text":"警报响起。","emotion":"tense","intensity":0.7,"speed":10,"role":"旁白","gender":"unknown","emphasis":[]},
 {"text":"\"关掉它！\"","emotion":"angry","intensity":0.9,"speed":20,"role":"陈默","gender":"male","emphasis":["关掉"]},
 {"text":"林晚的手停在键盘上。","emotion":"fearful","intensity":0.5,"speed":0,"role":"旁白","gender":"unknown","emphasis":[]}]

注意：许多中文文本的对话不加引号（如「这不可能……林晚喃喃道」「快离开！陈默吼道」）。遇到这种无引号的口语对话句，同样要依据说话人动词（说道/吼道/喃喃道/低声说等）、语气和上下文识别出台词并标注角色，不要因为缺少引号就归为旁白；但纯粹的叙述描写句仍然填"旁白"。

更多拆分示例——
输入：「老周深深吸了一口气，对女孩说："到了。梧桐路，到了。慢点走。"」
正确输出：两段。第一段 text="老周深深吸了一口气，对女孩说：" role="旁白"；第二段 text=""到了。梧桐路，到了。慢点走。"" role="老周"。（叙述在前、冒号引出台词的混合句，必须拆）
输入：「"小姑娘，"老周压低了声音，"你上一次坐这班车，是哪一天？"」
正确输出：三段。text=""小姑娘，"" role="老周"；text="老周压低了声音，" role="旁白"；text=""你上一次坐这班车，是哪一天？"" role="老周"。（引号夹心句必须拆：引号内文字归角色，引号之间的叙述单独归旁白）
注意：紧邻台词的纯叙述句（如"阿婆笑了笑，没有回答，转身走进了雨里。"）即使主语是刚说过话的角色，也归"旁白"。

要求：只输出 JSON 数组，不要任何解释、markdown 代码块标记或其他文字。
文本：
__TEXT__


"""


def load_env() -> dict:
    env = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def extract_json_array(text: str) -> list | None:
    """容错提取 JSON 数组（模型偶尔会带 markdown 标记或前后缀）"""
    text = text.strip()
    # 去掉 ```json ... ``` 包裹
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def analyze(text: str) -> tuple[list | None, str]:
    env = load_env()
    api_key = env.get("GLM_API_KEY", "")
    if not api_key:
        return None, ".env 缺少 GLM_API_KEY"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT_TEMPLATE.replace('__TEXT__', text)}],
        "temperature": 0.2,
    }
    content = None
    last_err = ""
    for attempt in range(1, 4):  # 最多 3 次重试
        try:
            resp = requests.post(API_URL, headers=headers, json=body, timeout=150)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}: {resp.text[:300]}"
            content = resp.json()["choices"][0]["message"]["content"]
            break
        except Exception as e:  # noqa: BLE001
            last_err = f"请求异常(第{attempt}次): {e}"
            print(f"  [重试] {last_err}", file=sys.stderr)
            time.sleep(2 * attempt)
    if content is None:
        return None, last_err

    segments = extract_json_array(content)
    if segments is None:
        return None, f"JSON 解析失败，原始返回:\n{content[:500]}"

    # 校验与清洗
    cleaned = []
    for seg in segments:
        if not isinstance(seg, dict) or "text" not in seg:
            continue
        emo = seg.get("emotion", "neutral")
        if emo not in VALID_EMOTIONS:
            emo = "neutral"
        cleaned.append({
            "text": str(seg["text"]).strip(),
            "emotion": emo,
            "intensity": max(0.0, min(1.0, float(seg.get("intensity", 0.5)))),
            "speed": int(max(-30, min(30, seg.get("speed", 0)))),
            "role": str(seg.get("role", "旁白")).strip(),
            "gender": str(seg.get("gender", "unknown")).strip(),
            "emphasis": [str(w) for w in (seg.get("emphasis") or [])][:3],
        })
    if not cleaned:
        return None, "解析结果为空"
    return split_mixed_dialogue(cleaned), "ok"


def split_mixed_dialogue(segments: list) -> list:
    """
    确定性兜底：
    1) 非旁白段若含引号，按引号边界机械拆分——引号内归角色，引号外叙述归旁白，相邻同类合并；
    2) 非旁白段无引号、无强烈语气标点（！？…）且较长（>=12字）——判定为第三人称叙述，回退旁白。
    LLM 对「叙述+冒号台词」「引号夹心」句式偶尔偷懒不拆，此规则保证最终正确。
    """
    quotes = '“”"「」『』'
    result = []
    for seg in segments:
        text = seg["text"]
        if seg["role"] == "旁白":
            result.append(seg)
            continue
        if seg["role"] in ("unknown", ""):
            seg = {**seg, "role": "旁白", "gender": "unknown"}
        if not any(q in text for q in quotes):
            if not any(p in text for p in '！？…') and len(text) >= 12:
                result.append({**seg, "role": "旁白", "gender": "unknown"})
                continue
            result.append(seg)
            continue
        parts = re.split(r'(“[^”]*”|"[^"]*")', text)
        pieces = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if p[0] in '“"「' and p[-1] in '”"」':
                pieces.append({**seg, "text": p})
            else:
                pieces.append({**seg, "text": p, "role": "旁白", "gender": "unknown"})
        for s in pieces:                                    # 相邻同角色合并
            if result and result[-1]["role"] == s["role"] and s["role"] != "旁白":
                result[-1]["text"] += s["text"]
            elif result and result[-1]["role"] == "旁白" and s["role"] == "旁白":
                result[-1]["text"] += s["text"]
            else:
                result.append(dict(s))
    return result


def main():
    parser = argparse.ArgumentParser(description="GLM-4-Flash 情感分析")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="待分析文本")
    group.add_argument("--file", help="待分析文本文件路径")
    parser.add_argument("-o", "--out", default="outputs/m0/story_segments.json")
    args = parser.parse_args()

    if args.file:
        src = Path(args.file)
        if not src.exists():
            print(f"[错误] 文件不存在: {src}", file=sys.stderr)
            sys.exit(1)
        text = src.read_text(encoding="utf-8").strip()
    else:
        text = args.text.strip()

    print(f"输入 {len(text)} 字，正在调用 GLM-4-Flash 分析...")
    segments, msg = analyze(text)
    if segments is None:
        print(f"[失败] {msg}", file=sys.stderr)
        sys.exit(1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[成功] {len(segments)} 个段落 -> {out}")
    roles = sorted({s['role'] for s in segments})
    emos = {}
    for s in segments:
        emos[s['emotion']] = emos.get(s['emotion'], 0) + 1
    print(f"角色: {roles}")
    print(f"情绪分布: {emos}")


if __name__ == "__main__":
    main()
