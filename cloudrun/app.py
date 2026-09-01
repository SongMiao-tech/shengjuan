# -*- coding: utf-8 -*-
"""
个性化有声读物生成服务（CloudBase 云托管 · 容器版）
POST /tasks            {text, narrator?}       -> {"task_id"}  异步启动流水线
GET  /tasks/<task_id>                          -> 状态/进度/结果（done 时含 audio_base64）
GET  /health                                   -> {"ok": true}
密钥从环境变量读取：VOLC_API_KEY / GLM_API_KEY（不打印、不回显）
"""
import base64
import json
import os
import re
import secrets
import subprocess
import threading
import time
import uuid
from pathlib import Path

import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, request

APP = Flask(__name__)
WORK = Path("/tmp/audiobook")          # 容器内工作目录
BGM_DIR = Path(__file__).parent / "assets" / "bgm"

@APP.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp

TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

DEFAULT_NARRATOR = "zh_female_yingtaowanzi_uranus_bigtts"
# 角色音色按性别从声池自动分配（同角色锁定同一音色，保证前后一致）
MALE_POOL = ["zh_male_silang_uranus_bigtts", "zh_male_qingcang_uranus_bigtts"]
FEMALE_POOL = ["zh_female_yingtaowanzi_uranus_bigtts", "zh_female_popo_uranus_bigtts"]
EMOTION_MAP = {"happy": "happy", "excited": "happy", "sad": "sad",
               "angry": "angry", "fearful": "fearful", "surprised": "surprised"}
BGM_GROUP = {"neutral": "neutral", "calm": "calm", "sad": "sad",
             "happy": "happy", "excited": "happy",
             "tense": "tense", "angry": "tense", "fearful": "tense"}

PROMPT = """你是有声书情感分析师。分析下面的文本，把它切分为适合朗读的段落（每段不超过50个字，保持句子完整），并为每段标注朗读参数：
- text: 该段原文内容
- emotion: 情绪标签，只能从这些里选：neutral/happy/sad/angry/fearful/surprised/calm/tense/excited
- intensity: 情绪强度 0.0~1.0（中性段给0.3以下）
- speed: 语速调整建议，整数，范围-30~30（紧张时加速为正数，悲伤助眠时放慢为负数，正常为0）
- role: 该段的朗读归属，判定规则：
    * 台词段——角色亲口说的话（无论是否带引号），填该角色名；
    * 叙述段——作者的描写、动作、心理说明（如"林晚盯着屏幕……"、"她喃喃道，手指微微发抖"），一律填"旁白"，即使句中出现了角色名字；
    * 拟声词段——模拟环境声音的象声词（如"轰隆隆""哗啦啦""滴答""咔嚓""呼——"及其叠词/连用），不是任何角色说出口的话，纯拟声段一律填"旁白"、gender 填 unknown；但以拟声词开头、后面跟着实际说话内容的句子（如"哈哈，你好"）仍按台词处理；
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
引号类型：直角引号「」（古籍/繁体排版常见，如 石猴道：「大造化！」）与弯引号 “ ” 均可能出现，引号内的话都是台词，处理规则相同。「」内若再嵌套『』（如「他说：『花果山福地』」），引号内文字整体归角色，不必再拆。

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


# ── 拟声词识别：仅由拟声字构成的段落强制归旁白（GLM 偶发把"轰隆隆"等判成角色台词） ──
# 集合只收纯拟声字；叹词（啊/哦/嗯/哈/呜/呀/哇等角色发声）与普通词汇字符不在内，
# 因此"哈哈，你好"（含非拟声字）仍按台词分配，角色笑声/哭声也不被误改。
_ONOMATOPOEIA_CHARS = set(
    "轰哗啦叮滴答呼沙咔砰嗖咚噼啪嘟隆吱哞咩汪喵叽喳嘎咕呱嗡锵哐啷铛嘶潺淅沥簌嗒嗵嘣噗嚓咯咝乒乓唰笃咚欻哒哔噜啾呖铮嘚当"
)
_ONOMA_STRIP_RE = re.compile(r"[\s\u3000，。！？、；：…—～·「」『』“”‘’\"'!?,.:;()\-]+")


def _is_onomatopoeia(text: str) -> bool:
    """去掉标点/引号/空白后，剩余字符全部是拟声字 → 视为纯拟声段（应归旁白）。"""
    core = _ONOMA_STRIP_RE.sub("", text or "")
    return bool(core) and all(ch in _ONOMATOPOEIA_CHARS for ch in core)


def assign_speakers(segments: list, narrator: str) -> dict:
    """按角色性别分配音色；旁白固定用 narrator；同一角色全篇锁定同一音色。

    改进（睡前故事版）：
    - 分配改 hash 取模：同一角色名跨故事恒定映射同一音色（角色记忆一致性）
    - 池耗尽不再退化成旁白（撞声），改为复用该性别池音色 + speech_rate 偏移区分
    """
    # ── 拟声词兜底：纯象声词段落强制归旁白（GLM 偶发把"轰隆隆"等判成角色台词） ──
    for seg in segments:
        if _is_onomatopoeia(seg.get("text", "")):
            seg["role"] = "旁白"
            seg["gender"] = "unknown"

    pools = {"male": [s for s in MALE_POOL if s != narrator],       # 角色不用旁白音色，避免撞声
             "female": [s for s in FEMALE_POOL if s != narrator]}
    base = {"male": list(pools["male"]), "female": list(pools["female"])}
    role_map = {}      # role -> speaker_id
    shift_map = {}     # role -> speech_rate 偏移（池耗尽时用于区分撞声角色）
    for seg in segments:
        r = seg.get("role", "旁白")
        if r == "旁白":
            seg["speaker"] = narrator
            seg.setdefault("speed_shift", 0)
            continue
        if r not in role_map:
            g = seg.get("gender", "unknown")
            if g in pools and pools[g]:
                role_map[r] = pools[g].pop(0)
                shift_map[r] = 0
            elif g in base:                # 池耗尽：hash 取模复用 + 语速偏移区分
                spk = base[g][hash(r) % len(base[g])]
                role_map[r] = spk
                shift_map[r] = 10 if (hash(r) % 2 == 0) else -10
            else:                          # unknown 跟随旁白
                role_map[r] = narrator
                shift_map[r] = 0
        seg["speaker"] = role_map[r]
        seg["speed_shift"] = shift_map.get(r, 0)
    return role_map

TASKS: dict = {}   # task_id -> {"status","stage","segments","audio_base64","duration_s","error"}


def pick_resource(speaker: str) -> str:
    """按音色选 X-Api-Resource-Id（unidirectional V3 网关）：
    - 声音复刻（S_/custom 开头）-> seed-icl-2.0
    - 其余 -> seed-tts-2.0（可用 TTS_RESOURCE env 覆盖，排查账号 resource 授权用）"""
    if speaker.startswith(("S_", "custom")):
        return "seed-icl-2.0"
    return os.environ.get("TTS_RESOURCE", "").strip() or "seed-tts-2.0"


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------- 确定性拆分兜底 ----------
_QUOTE_SPLIT_RE = re.compile(r'(“[^”]*”|"[^"]*"|「[^」]*」|『[^』]*』)')
_SAY_RE = re.compile(r'[曰道][：:]')   # 说话动词 + 冒号（X道：/X曰：）
# 邻接名后可剥离的动词/修饰尾字（笑道/问道/回报道/呵呵道…的动词部分）
_TAIL_STRIP = set('都等皆齐们笑问答喝骂叹说叫唤呼吟诵念唱哭劝谏赞贺拜吩呏述回报奏禀启教命言云谈讲高声低厉连忙慌急拍呵哈拱躬叩抬低头转身前垂堕泪含陪堆喜恼愁动怒大礼首回')
# 说话人候选名中不允许出现的字（虚词/数词/动作字，用于排除叙述性主语）
_BLACK_CHARS = set('的了着那这只有是便即却又就但见忽且还再不没未无亦须少正因故乃果其之于与而则若如被把在去来到从望向对一五十百千万亿个位名次朝早晚新旧大小多少高低上下东西南北中内外前后左右自相或此最彼他她它你你们我乎者也矣焉哉飞落起坐立睡卧醒醉游跳走行出入看听想心喜垂背')
_WORD_BLACK = {'须臾', '少顷', '古云', '俗云', '常言', '古语', '正是', '忽然', '不觉', '当下',
               '次日', '一日', '当日', '却说', '且说', '话说', '但见', '只见', '只听', '原来',
               '自古', '心想', '暗想'}
_PUNCT = '，。！？；：、“”「」『』〈〉《》（）() \n'


def _valid_speaker(name):
    """候选说话人校验：2-3 个汉字（纯汉字）、不在黑名单（词级/字级）"""
    if name in _WORD_BLACK or not (2 <= len(name) <= 3):
        return None
    if not all('\u4e00' <= c <= '\u9fff' for c in name):
        return None
    if any(c in _BLACK_CHARS for c in name):
        return None
    return name


def _speaker_before(pre: str):
    """从引号前的叙述文本识别说话人（如「众猴把他围住，问道：」->众猴）；失败返回 None"""
    m = None
    for m in _SAY_RE.finditer(pre):
        pass                                     # 取最后一个 道：/曰：
    if m is None:
        return None
    head = pre[:m.start()]
    # a) 邻接名：动词前紧贴的 2-3 字，剥离动词复合尾字，且前面须是标点/边界
    tail = head.rstrip('，。！？；：、 \n')
    while tail and tail[-1] in _TAIL_STRIP:
        tail = tail[:-1]
    for L in (3, 2):
        if len(tail) >= L:
            cand, rest = tail[-L:], tail[:-L]
            if not rest or rest[-1] in _PUNCT:
                v = _valid_speaker(cand)
                if v:
                    return v
    # b) 回溯主语：动句所在子句及上一句的子句，从后向前找首个合法的 2-3 字开头
    cands = []
    sents = [s for s in re.split(r'[。！？；]', head) if s.strip()]
    if sents:
        for sent in [sents[-1]] + sents[-2:-1]:
            for c in reversed([x for x in re.split(r'[，、：]', sent) if x.strip()]):
                for L in (3, 2):
                    lead = re.match(r'[\u4e00-\u9fa5]{%d}' % L, c.strip())
                    if lead:
                        cands.append(lead.group(0))
    for cand in cands:
        v = _valid_speaker(cand)
        if v:
            return v
    return None


def _merge_adjacent(segments: list) -> list:
    """相邻同角色段合并（含相邻旁白）"""
    merged = []
    for s in segments:
        if merged and merged[-1]["role"] == s["role"]:
            merged[-1]["text"] += s["text"]
        else:
            merged.append(dict(s))
    return merged


def split_mixed_dialogue(segments: list) -> list:
    """
    确定性兜底（三层）：
    1) 非旁白段若含引号，按引号边界机械拆分——引号内归角色，引号外叙述归旁白；
    2) 旁白段内嵌的「X道：/X曰：+引号台词」按说话人救援拆出（识别不到可靠说话人则保持旁白，
       诗曰/赋曰/古云等引经据典不会被误判）；
    3) 非旁白段无引号、无强烈语气标点（！？…）且较长（>=12字）——判定为第三人称叙述回退旁白。
    引号类型兼容 弯引号“”/直角引号「」『』/英文双引号。
    """
    result = []
    for seg in segments:
        text = seg["text"]
        if seg["role"] == "旁白":
            # 旁白段：仅当内嵌「道：/曰：+引号」台词时救援拆分
            pieces = _QUOTE_SPLIT_RE.split(text) if any(q in text for q in '「」“”"') else [text]
            if len(pieces) == 1:
                result.append(seg)
                continue
            pre_acc = ""
            for p in pieces:
                p = p.strip()
                if not p:
                    continue
                if _QUOTE_SPLIT_RE.fullmatch(p):
                    speaker = _speaker_before(pre_acc)
                    if speaker:
                        result.append({**seg, "text": p, "role": speaker,
                                       "gender": "male", "_rescued": True})
                    else:
                        result.append({**seg, "text": p})
                else:
                    pre_acc += p
                    result.append({**seg, "text": p})
            continue
        if seg["role"] in ("unknown", ""):
            seg = {**seg, "role": "旁白", "gender": "unknown"}
        if not any(q in text for q in '“”"「」『』'):
            if not any(p in text for p in '！？…') and len(text) >= 12:
                result.append({**seg, "role": "旁白", "gender": "unknown"})
            else:
                result.append(seg)
            continue
        parts = _QUOTE_SPLIT_RE.split(text)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if _QUOTE_SPLIT_RE.fullmatch(p):
                result.append({**seg, "text": p})
            else:
                result.append({**seg, "text": p, "role": "旁白", "gender": "unknown"})
    # 同角色性别统一：LLM 标注优先，救援段回退（默认 male，古典文本主体为男性角色）
    gmap = {}
    for s in result:
        if s["role"] != "旁白" and s.get("gender") in ("male", "female"):
            gmap.setdefault(s["role"], s["gender"])
    # 儿童故事性别关键词兜底：小动物/女性称谓多为 female，避免全判 male
    _FEMALE_HINTS = ("妈", "娘", "姐", "妹", "婆", "姨", "奶", "婶", "姑", "公主", "女王",
                     "女孩", "姑娘", "小姐", "兔", "猫", "鸟", "蝶", "鹅", "鸭", "鹿",
                     "狐狸", "仙女", "奶奶", "婆婆", "阿姨")
    def _guess_gender(role: str) -> str:
        if any(w in role for w in _FEMALE_HINTS):
            return "female"
        return "male"
    for s in result:
        if s.pop("_rescued", None) and s["gender"] not in ("male", "female"):
            s["gender"] = gmap.get(s["role"], _guess_gender(s["role"]))
    return _merge_adjacent(result)


# ---------- GLM 情感分析 ----------
USAGE_FILE = Path("/tmp/audiobook_usage.json")   # 单实例部署：计数落盘防重启丢失

def _load_usage() -> dict:
    base = {"tasks": 0, "chars_tts": 0, "llm_calls": 0, "cache_hits": 0,
            "clones": 0, "designs": 0, "previews": 0}
    try:
        base.update(json.loads(USAGE_FILE.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    return base

USAGE = _load_usage()

def bump(key: str, n: int = 1):
    USAGE[key] = USAGE.get(key, 0) + n
    try:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        USAGE_FILE.write_text(json.dumps(USAGE), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

ANALYSIS_CACHE = {}        # sha256(text) -> segments（同文本缓存，命中跳过 GLM 调用）

# GLM 免费降级链：主模型失效（key 重置/限流）时自动切换，防生产中断
GLM_MODELS = ["glm-4-flash", "glm-4-flash-250414", "glm-4.5-air"]

def _glm_chat(body: dict) -> str:
    """带模型降级链的 GLM 调用：3 个免费模型轮换，单模型失败即换下一个"""
    headers = {"Authorization": f"Bearer {os.environ['GLM_API_KEY']}", "Content-Type": "application/json"}
    last_err = None
    for model in GLM_MODELS:
        body["model"] = model
        try:
            r = requests.post(GLM_URL, headers=headers, json=body, timeout=300)
            if r.status_code != 200:
                raise RuntimeError(f"GLM HTTP {r.status_code}: {r.text[:160]}")
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            last_err = e
            log(f"[glm] {model} 失败，降级下一模型: {str(e)[:120]}")
            time.sleep(1)
    raise RuntimeError(f"GLM 全模型链失败: {last_err}")


def analyze(text: str):
    import hashlib
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if key in ANALYSIS_CACHE:
        bump("cache_hits")
        log("[glm] 同文本缓存命中，跳过 LLM 调用")
        return json.loads(json.dumps(ANALYSIS_CACHE[key], ensure_ascii=False))   # 深拷贝
    bump("llm_calls")
    body = {"messages": [{"role": "user", "content": PROMPT.replace('__TEXT__', text)}],
            "temperature": 0.2}
    content = _glm_chat(body)
    import re
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if not m:
        raise RuntimeError(f"GLM 返回非 JSON: {content[:200]}")
    segments = json.loads(m.group(0))
    valid = {"neutral", "happy", "sad", "angry", "fearful", "surprised", "calm", "tense", "excited"}
    out = []
    for seg in segments:
        if not isinstance(seg, dict) or "text" not in seg:
            continue
        emo = seg.get("emotion", "neutral")
        out.append({"text": str(seg["text"]).strip(),
                    "emotion": emo if emo in valid else "neutral",
                    "intensity": max(0.0, min(1.0, float(seg.get("intensity", 0.5)))),
                    "speed": int(max(-30, min(30, seg.get("speed", 0)))),
                    "role": (str(seg.get("role", "旁白")).strip() or "旁白"),
                    "gender": str(seg.get("gender", "unknown")).strip()})
    if not out:
        raise RuntimeError("GLM 解析为空")
    for seg in out:                                   # unknown 角色归旁白
        if seg["role"] in ("unknown", ""):
            seg["role"] = "旁白"
            seg["gender"] = "unknown"
    out = split_mixed_dialogue(out)
    for seg in out:                                   # 拟声词兜底：引号救援拆出的纯拟声段归旁白
        if _is_onomatopoeia(seg.get("text", "")):
            seg["role"] = "旁白"
            seg["gender"] = "unknown"
    if len(ANALYSIS_CACHE) > 200:               # 简单上限防内存膨胀
        ANALYSIS_CACHE.clear()
    ANALYSIS_CACHE[key] = out
    return out


TRANS_PROMPT = """你是有声书中英双语译配师。把下面的中文段落数组逐段翻译成适合朗读的英文（简洁、口语化、保留原文语气）。
输入是一个 JSON 字符串数组。只输出等长的 JSON 字符串数组（每元素为对应段落的英文翻译），不要任何解释、markdown 标记或其他文字。
重要：JSON 字符串内部一律使用单引号 ' 表示对话引号，绝对不要输出未转义的双引号。
段落数组：
__TEXT__

"""

TRANS_ONE_PROMPT = """把下面的中文翻译成适合朗读的英文（简洁、口语化、保留原文语气）。
只输出译文本身，不要任何解释或引号。对话引号一律用单引号 ' 。
中文：
__TEXT__
"""

def split_chunks(text: str, limit: int = 1200) -> list:
    """按段落边界切分长文本，每块 <= limit 字；单段超限时按句号硬切。
    块越小 GLM 输出 JSON 越短越稳（长输出会超时/截断）。"""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for p in text.split("\n\n"):
        if cur and len(cur) + len(p) + 2 > limit:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
        while len(cur) > limit:                    # 单段超限兜底
            cut = cur.rfind("。", 0, limit)
            cut = cut + 1 if cut > 0 else limit
            chunks.append(cur[:cut])
            cur = cur[cut:]
    if cur.strip():
        chunks.append(cur)
    return chunks


def analyze_long(text: str):
    """长文分块分析：每块独立过 GLM（分块缓存生效），合并结果。
    角色音色在合并后统一分配，跨块的同名角色声线保持一致。"""
    if len(text) <= 1200:
        return analyze(text)
    chunks = split_chunks(text)
    log(f"[glm] 长文分块：{len(text)} 字 -> {len(chunks)} 块")
    out = []
    for i, c in enumerate(chunks):
        log(f"[glm] 分析块 {i+1}/{len(chunks)}（{len(c)} 字）")
        out.extend(analyze(c))
    return out

TRANS_BATCH_SEGMENTS = 4    # 每批最多段落数
TRANS_BATCH_CHARS = 700     # 每批最多总字数（控制 GLM 单次输出长度，防超时/JSON 截断）

def _batch_texts(texts: list) -> list:
    """把段落列表按批分组：批内 <= TRANS_BATCH_SEGMENTS 段且总字数 <= TRANS_BATCH_CHARS。
    批越小 GLM 输出 JSON 越短越稳，批间独立降级互不影响。"""
    batches, cur, cur_chars = [], [], 0
    for t in texts:
        if cur and (len(cur) >= TRANS_BATCH_SEGMENTS or cur_chars + len(t) > TRANS_BATCH_CHARS):
            batches.append(cur)
            cur, cur_chars = [], 0
        cur.append(t)
        cur_chars += len(t)
    if cur:
        batches.append(cur)
    return batches

def _translate_batch(texts: list) -> list:
    """单批翻译：成功返回英文列表；失败重试 1 次（间隔 3s，抗 GLM 免费档限流），
    仍失败返回 [None]*n（该批降级保留中文）"""
    body = {"messages": [{"role": "user", "content": TRANS_PROMPT.replace("__TEXT__", json.dumps(texts, ensure_ascii=False))}],
            "temperature": 0.3}
    for attempt in (1, 2):
        try:
            content = _glm_chat(body)
        except Exception as e:  # noqa: BLE001
            log(f"[translate] 批翻译失败（第 {attempt} 次尝试，全模型链），{len(texts)} 段: {str(e)[:100]}")
        else:
            m = _re.search(r"\[.*\]", content, _re.DOTALL)
            if m:
                try:
                    en = json.loads(m.group(0))
                except Exception:  # noqa: BLE001
                    en = None
                if isinstance(en, list) and len(en) == len(texts):
                    return [str(x).strip() if x else None for x in en]
            log(f"[translate] 批翻译响应解析失败（第 {attempt} 次尝试），{len(texts)} 段"
                f"{'，转逐段翻译' if attempt == 2 else ''}")
        if attempt == 1:
            time.sleep(3)
    # 批 JSON 两连败兜底：逐段纯文本翻译（不经 JSON，无转义问题，单段必成功）
    log(f"[translate] 批 JSON 翻译失败，{len(texts)} 段转逐段纯文本翻译")
    return [_translate_one(t) for t in texts]

def _translate_one(text: str) -> str | None:
    """单段纯文本翻译兜底：不经 JSON，避免引号转义炸解析；失败返回 None 降级中文"""
    body = {"messages": [{"role": "user", "content": TRANS_ONE_PROMPT.replace("__TEXT__", text)}],
            "temperature": 0.3}
    try:
        content = _glm_chat(body).strip()
    except Exception as e:  # noqa: BLE001
        log(f"[translate] 单段翻译失败，该段降级保留中文: {str(e)[:100]}")
        return None
    # 去掉模型可能加的包裹引号/前缀
    content = content.strip().strip('"').strip("'").strip()
    if not content or len(content) > len(text) * 8 + 200:
        return None
    return content

def translate_segments(segments: list) -> tuple:
    """GLM 分批翻译为英文（每批 <=4 段且 <=700 字）。
    批间独立降级——单批失败只影响该批段落，不再整篇降级。
    返回 (en_list, failed_n)：failed_n 为翻译失败降级保留中文的段落数（供任务状态透出）。"""
    texts = [s["text"] for s in segments]
    en_list, idx, failed = [None] * len(texts), 0, 0
    for batch in _batch_texts(texts):
        res = _translate_batch(batch)
        for j, en in enumerate(res):
            if en:
                en_list[idx + j] = en
            else:
                failed += 1
        idx += len(batch)
    if failed:
        log(f"[translate] 共 {failed}/{len(texts)} 段翻译失败，英语版降级保留中文")
    return en_list, failed


# ---------- 豆包 TTS ----------
def tts(text: str, speaker: str, out_path: Path, emotion=None, scale=4, speed=0,
        dialect: str | None = None, loudness: int = 0):
    """loudness_rate：响度偏移 [-50,100]（厂商口径），儿童/睡前场景用正值提清晰度"""
    audio_params = {"format": "mp3", "sample_rate": 24000, "speech_rate": speed}
    if loudness:
        audio_params["loudness_rate"] = max(-50, min(100, int(loudness)))
    body = {"user": {"uid": "audiobook-cloud"},
            "req_params": {"text": text, "speaker": speaker, "audio_params": audio_params}}
    if emotion:
        body["req_params"]["audio_params"]["emotion"] = emotion
        body["req_params"]["audio_params"]["emotion_scale"] = scale
    if dialect:   # 方言通道：仅支持方言的音色（vv/小何/云舟/小天）生效；additions 须为 JSON 字符串
        body["req_params"]["additions"] = json.dumps({"explicit_dialect": dialect})
    headers = {"X-Api-Key": os.environ["VOLC_API_KEY"],
               "X-Api-Resource-Id": pick_resource(speaker),
               "X-Api-Request-Id": str(uuid.uuid4())}
    r = requests.post(TTS_URL, headers=headers, json=body, timeout=60, stream=True)
    if r.status_code != 200:
        raise RuntimeError(f"TTS HTTP {r.status_code}: {r.text[:200]}")
    audio = b""
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("data"):
            audio += base64.b64decode(obj["data"])
        if obj.get("code") == 20000000:
            break
        if obj.get("code") not in (0, None):
            raise RuntimeError(f"TTS code={obj.get('code')} {obj.get('message', '')}")
    if not audio:
        raise RuntimeError("TTS 无音频返回")
    out_path.write_bytes(audio)


# ---------- MiniMax（音色设计 + ttv 音色合成） ----------
MM_BASE = "https://api.minimax.chat"

def mm_headers():
    return {"Authorization": f"Bearer {os.environ['MINIMAX_API_KEY']}", "Content-Type": "application/json"}


def minimax_design(prompt: str, preview_text: str):
    """文本描述 -> 新音色。返回 (voice_id, preview_audio_b64)。首次合成会收取音色设计费。"""
    r = requests.post(f"{MM_BASE}/v1/voice_design", headers=mm_headers(),
                      json={"model": "minimax-voice-design", "prompt": prompt,
                            "preview_text": preview_text, "output_format": "url"}, timeout=90)
    obj = r.json()
    br = obj.get("base_resp", {})
    if r.status_code != 200 or br.get("status_code") != 0:
        raise RuntimeError(f"音色设计失败: {br.get('status_msg', 'HTTP ' + str(r.status_code))}")
    voice_id = obj.get("voice_id")
    if not voice_id:
        raise RuntimeError("设计接口未返回 voice_id")
    bump("designs")
    preview = minimax_tts_bytes(preview_text, voice_id)   # 激活并出试听
    return voice_id, base64.b64encode(preview).decode("ascii")


def minimax_tts_bytes(text: str, voice_id: str) -> bytes:
    body = {"model": "speech-2.8-turbo", "text": text, "stream": False,
            "output_format": "hex",
            "voice_setting": {"voice_id": voice_id, "speed": 1.0, "vol": 1.0, "pitch": 0},
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1}}
    # 实测：带 GroupId 会报 1004 token not match group，不带则成功（key 单独可用）
    r = requests.post(f"{MM_BASE}/v1/t2a_v2",
                      headers=mm_headers(), json=body, timeout=120)
    obj = r.json()
    br = obj.get("base_resp", {})
    if r.status_code != 200 or br.get("status_code") != 0:
        raise RuntimeError(f"MiniMax 合成失败: {br.get('status_msg', '')}")
    return bytes.fromhex(obj["data"]["audio"])


# ---------- 阿里云百炼 CosyVoice（可选通道：设计免费 + 合成更便宜） ----------
# 配置 DASHSCOPE_API_KEY 后启用；未配置时音色设计自动回落 MiniMax，现有逻辑零影响。
# 设计接口：POST /services/audio/tts/customization（model=voice-enrollment, action=create_voice）
# 合成接口：POST /services/audio/tts/SpeechSynthesizer（纯 HTTP，非流式返 output.audio.url）
COSY_TARGET_MODEL = "cosyvoice-v3.5-plus"   # 设计音色的目标模型；voice_id 前缀即合成模型

def cosy_enabled() -> bool:
    return bool((os.environ.get("DASHSCOPE_API_KEY") or "").strip())


def design_provider() -> str:
    return "cosyvoice" if cosy_enabled() else "minimax"


def cosy_base() -> str:
    """默认工作空间走 dashscope 域名；配置了业务空间 ID 则走 maas 域名（仅北京地域）"""
    ws = (os.environ.get("DASHSCOPE_WORKSPACE_ID") or "").strip()
    if ws:
        return f"https://{ws}.cn-beijing.maas.aliyuncs.com/api/v1"
    return "https://dashscope.aliyuncs.com/api/v1"


def cosy_design(prompt: str, preview_text: str):
    """CosyVoice 声音设计（创建免费）。返回 (voice_id, preview_audio_b64)"""
    body = {"model": "voice-enrollment",
            "input": {"action": "create_voice", "target_model": COSY_TARGET_MODEL,
                      "voice_prompt": prompt[:500], "preview_text": preview_text[:200],
                      "prefix": "shengjuan", "language_hints": ["zh"]},
            "parameters": {"sample_rate": 24000, "response_format": "wav"}}
    r = requests.post(f"{cosy_base()}/services/audio/tts/customization",
                      headers={"Authorization": f"Bearer {os.environ['DASHSCOPE_API_KEY']}",
                               "Content-Type": "application/json"},
                      json=body, timeout=90)
    obj = r.json()
    if r.status_code != 200 or obj.get("code"):
        raise RuntimeError(f"CosyVoice 设计失败: {obj.get('message') or 'HTTP ' + str(r.status_code)}")
    voice_id = (obj.get("output") or {}).get("voice_id")
    if not voice_id:
        raise RuntimeError("CosyVoice 设计接口未返回 voice_id")
    bump("designs")
    # 新音色可能仍在部署（DEPLOYING），预览统一走合成拿 mp3，失败重试一次
    preview_b64 = None
    for attempt in range(2):
        try:
            preview_b64 = base64.b64encode(cosy_tts_bytes(preview_text, voice_id)).decode("ascii")
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 0:
                log(f"[cosy-design] 预览合成失败（音色可能部署中），4 秒后重试: {e}")
                time.sleep(4)
            else:
                raise
    return voice_id, preview_b64


def cosy_tts_bytes(text: str, voice_id: str) -> bytes:
    """CosyVoice 合成：模型名取自 voice_id 前缀（{model}-vd-{prefix}-{uid}）"""
    model = voice_id.split("-vd-")[0] or COSY_TARGET_MODEL
    body = {"model": model,
            "input": {"text": text, "voice": voice_id, "format": "mp3",
                      "sample_rate": 24000, "volume": 50, "rate": 1.0, "pitch": 1.0,
                      "language_hints": ["zh"]}}
    r = requests.post(f"{cosy_base()}/services/audio/tts/SpeechSynthesizer",
                      headers={"Authorization": f"Bearer {os.environ['DASHSCOPE_API_KEY']}",
                               "Content-Type": "application/json"},
                      json=body, timeout=120)
    obj = r.json()
    if r.status_code != 200 or obj.get("code"):
        raise RuntimeError(f"CosyVoice 合成失败: {obj.get('message') or 'HTTP ' + str(r.status_code)}")
    url = ((obj.get("output") or {}).get("audio") or {}).get("url")
    if not url:
        raise RuntimeError("CosyVoice 合成未返回音频地址")
    au = requests.get(url, timeout=60)
    if au.status_code != 200:
        raise RuntimeError(f"CosyVoice 音频下载失败 HTTP {au.status_code}")
    return au.content


def custom_tts_bytes(text: str, voice_id: str) -> bytes:
    """自定义音色（设计类）合成分发：按 voice_id 前缀选厂商"""
    if voice_id.startswith("cosyvoice"):
        return cosy_tts_bytes(text, voice_id)
    return minimax_tts_bytes(text, voice_id)


# ---------- 音色设计缓存（按描述哈希，避免为同一句描述重复付设计费） ----------
# MiniMax 音色设计按次计费（约 ¥21.6/个），同描述重复调用纯属浪费。
# 缓存全局共享（跨用户），PG 不可用时优雅降级为不缓存，不阻塞主流程。

def design_cache_key(prompt: str) -> str:
    """描述归一化后取 sha256 前 32 位：忽略空白与大小写差异"""
    norm = _re.sub(r"\s+", "", prompt).lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


def design_cache_get(key: str, provider: str):
    """命中返回 voice_id（仅限当前通道的音色），未命中或 PG 不可用返回 None"""
    if not CB_SERVICE_KEY:
        return None
    try:
        r = _pg_request("GET", "voice_design_cache",
                        params={"prompt_hash": f"eq.{key}", "provider": f"eq.{provider}",
                                "select": "voice_id,use_count"})
        if r.status_code != 200:
            return None
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            return None
        voice_id = (rows[0] or {}).get("voice_id")
        if not voice_id:
            return None
        _pg_request("PATCH", "voice_design_cache", params={"prompt_hash": f"eq.{key}"},
                    json_body={"use_count": int(rows[0].get("use_count") or 1) + 1})
        return voice_id
    except Exception as e:  # noqa: BLE001
        log(f"[design-cache] 查询失败，跳过缓存: {e}")
        return None


def design_cache_put(key: str, prompt: str, voice_id: str, provider: str = "minimax") -> None:
    if not CB_SERVICE_KEY:
        return
    try:
        _pg_request("POST", "voice_design_cache", upsert=True,
                    json_body={"prompt_hash": key, "prompt": prompt[:500],
                               "voice_id": voice_id, "provider": provider})
    except Exception as e:  # noqa: BLE001
        log(f"[design-cache] 写入失败，忽略: {e}")


# ---------- 豆包声音复刻训练 ----------
CLONE_URL = "https://openspeech.bytedance.com/api/v3/tts/voice_clone"
DEFAULT_CLONE_SPEAKER = "S_7PtM1phd2"

def volc_clone_train(audio_bytes: bytes, fmt: str, text: str, speaker_id: str, demo_text: str):
    body = {"speaker_id": speaker_id,
            "audio": {"data": base64.b64encode(audio_bytes).decode(), "format": fmt},
            "text": text, "language": 0,
            "extra_params": {"demo_text": demo_text[:100], "enable_audio_denoise": True}}
    headers = {"Content-Type": "application/json",
               "X-Api-Key": os.environ["VOLC_API_KEY"],
               "X-Api-Request-Id": str(uuid.uuid4()),
               "X-Api-Resource-Id": "seed-icl-2.0"}
    r = requests.post(CLONE_URL, headers=headers, json=body, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"克隆训练 HTTP {r.status_code}: {r.text[:300]}")
    resp = r.json()
    status = resp.get("status")
    if status == 3:
        raise RuntimeError("训练失败：录音与原文差异过大或录音无效，请重录")
    return {"speaker_id": resp.get("speaker_id"),
            "status": {0: "NotFound", 1: "Training", 2: "Success", 3: "Failed", 4: "Active"}.get(status, str(status)),
            "remaining_trainings": resp.get("available_training_times")}


# ---------- ffmpeg ----------
def ff(args):
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg: {r.stderr[-300:]}")


def pick_bgm(segments) -> str:
    score = {}
    for seg in segments:
        g = BGM_GROUP.get(seg["emotion"], "neutral")
        score[g] = score.get(g, 0.0) + 0.3 + seg["intensity"]
    for g, _ in sorted(score.items(), key=lambda kv: -kv[1]):
        if (BGM_DIR / f"{g}.mp3").exists():
            return f"{g}.mp3"
    return ""


# ---------- 流水线 ----------
def run_pipeline(task_id: str, text: str, narrator: str, use_bgm: bool, dialect: str | None = None, style: str = "normal"):
    t = TASKS[task_id]
    t["dialect"] = dialect or ""
    t["style"] = style
    d = WORK / task_id
    d.mkdir(parents=True, exist_ok=True)
    pause = 0.28          # 段间停顿
    force_bgm = None      # 强制配乐（预告片版用）
    try:
        t["stage"] = "analyzing"
        segments = analyze_long(text)

        # ---- 风格变换（一键多版本输出的核心差异） ----
        if style == "slow":                       # 慢速版：降语速 + 拉长停顿
            for seg in segments:
                seg["speed"] = max(-30, seg["speed"] - 20)
            pause = 0.55
        elif style == "bedtime":                  # 睡前版：更缓语速 + 长留白 + 强制 calm + 响度收紧
            for seg in segments:
                seg["speed"] = max(-30, seg["speed"] - 15)
                seg["intensity"] = min(seg["intensity"], 0.7)   # 情绪不过冲（scale 上限≈3.8）
            pause = 0.8
            force_bgm = "calm.mp3"
        elif style == "trailer":                  # 预告片版：情绪拉满 + 加速 + 强制紧张配乐
            for seg in segments:
                seg["intensity"] = max(seg["intensity"], 0.85)
                seg["speed"] = min(30, seg["speed"] + 10)
            pause = 0.45
            force_bgm = "tense.mp3"
        elif style == "english":                  # 英语版：整篇替换为英文朗读（分批翻译，失败段降级保留中文）
            t["stage"] = "translating"
            en_list, failed_n = translate_segments(segments)
            inter = []
            for seg, en in zip(segments, en_list):
                if en:
                    inter.append({"text": en, "emotion": seg["emotion"],
                                  "intensity": seg["intensity"],
                                  "speed": 0, "role": "English", "gender": "unknown", "en": True})
                else:
                    inter.append(seg)
            segments = inter
            if failed_n:                          # 降级情况透出到任务状态，前端可见
                t["note"] = f"有 {failed_n} 段英文翻译失败，这些段落将保留中文朗读"
                log(f"[{task_id}] {t['note']}")

        t["segments"] = segments
        log(f"[{task_id}] {len(segments)} 段 dialect={dialect} style={style}")

        t["stage"] = "synthesizing"
        role_map = assign_speakers(segments, narrator)
        log(f"[{task_id}] role_map={role_map}")
        en_voice = os.environ.get("EN_TTS_VOICE", "").strip() or "en_male_tim_uranus_bigtts"
        loudness = 5 if style == "bedtime" else 0    # 睡前版响度略提（孩子入睡后环境噪声大）
        parts = []
        cursor_s = 0.0                                # 段落时间轴游标（秒）
        for i, seg in enumerate(segments):
            if seg.get("en"):
                speaker = en_voice                # 英文段落用英语母声音色
                emo = None
                scale = 3
                seg_speed = 0
            else:
                speaker = seg["speaker"]
                emo = EMOTION_MAP.get(seg["emotion"])
                if seg["emotion"] in ("neutral", "calm"):
                    emo = None
                scale = max(1, min(5, round(1 + seg["intensity"] * 4)))
                seg_speed = max(-30, min(30, seg["speed"] + seg.get("speed_shift", 0)))
            seg_path = d / f"seg_{i:03d}.mp3"
            try:
                synth_dispatch(seg["text"], speaker, seg_path, emotion=emo, scale=scale,
                               speed=seg_speed, dialect=dialect, loudness=loudness)
            except Exception:  # 回退中性
                synth_dispatch(seg["text"], speaker, seg_path, dialect=dialect)
            parts.append(seg_path)
            # 段落时间轴：实际时长 ffprobe 累加（跟读高亮/生字定位的前置数据）
            seg_dur = _probe_duration(seg_path)
            seg["start_ms"] = int(cursor_s * 1000)
            seg["dur_ms"] = int(seg_dur * 1000)
            cursor_s += seg_dur + pause
            bump("chars_tts", len(seg["text"]))
            t["progress"] = f"{i+1}/{len(segments)}"

        t["stage"] = "mixing"
        t["part_files"] = [str(p) for p in parts]     # 供段落级调整后重混音
        audio_b, dur = mix_task(d, parts, use_bgm, pause=pause,
                                force_bgm=force_bgm, bedtime=(style == "bedtime"))
        out = d / "final.mp3"
        if style == "bedtime":
            bgm = "calm.mp3" if use_bgm else ""
        elif style == "trailer":
            bgm = "tense.mp3" if use_bgm else ""
        else:
            bgm = pick_bgm(segments) if use_bgm else ""
        out.write_bytes(audio_b)

        t["status"] = "done"
        t["audio_base64"] = base64.b64encode(audio_b).decode("ascii")
        t["duration_s"] = round(dur, 1)
        t["bgm"] = bgm or "无"
        log(f"[{task_id}] done {dur:.1f}s bgm={bgm}")
    except Exception as e:  # noqa: BLE001
        t["status"] = "failed"
        t["error"] = str(e)[:500]
        log(f"[{task_id}] FAILED: {e}")


def _probe_duration(path: Path) -> float:
    """取单个音频文件实际时长（秒）——段落时间轴的数据源"""
    try:
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "csv=p=0", str(path)],
                                    capture_output=True, text=True).stdout.strip())
    except (ValueError, TypeError):
        return 0.0


def mix_task(d: Path, parts: list, use_bgm: bool, pause: float = 0.28,
             force_bgm: str | None = None, bedtime: bool = False):
    """拼接段落 + BGM 匹配 ducking 混音 + 响度归一 -> (bytes, duration_s)

    bedtime=True：BGM 音量 0.22（默认 0.32）、更安静的响度目标（I=-18）、
                  BGM 首 5s 淡入尾 20s 淡出、整体首 2s 淡入尾 25s 淡出（入睡渐弱）
    """
    sil = d / f"sil_{pause}.mp3"
    if not sil.exists():
        ff(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(pause), "-b:a", "128k", str(sil)])
    lst = d / "concat.txt"
    lines = []
    for p in parts:
        lines += [f"file '{p}'", f"file '{sil}'"]
    lst.write_text("\n".join(lines), encoding="utf-8")
    voice = d / "voice.mp3"
    ff(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(voice)])
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(voice)], capture_output=True, text=True).stdout.strip())

    if bedtime:
        bgm = force_bgm or "calm.mp3"
        if not (BGM_DIR / bgm).exists():
            bgm = pick_bgm(TASKS.get(d.name, {}).get("segments")) if use_bgm else ""
    else:
        segments_meta = TASKS.get(d.name, {}).get("segments") if d.name in TASKS else None
        bgm = force_bgm or (pick_bgm(segments_meta) if (use_bgm and segments_meta) else "")
    if use_bgm and not bgm:
        bgm = ""
    out = d / "final.mp3"
    if bedtime:
        # 睡前混音：BGM 0.22 + 首尾淡入淡出 + 更安静的响度 + 整体 25s 长淡出
        fade_out_bg_start = max(0.0, dur - 20)
        fade_out_start = max(0.0, dur - 25)
        if bgm:
            fc = (f"[1:a]atrim=0:{dur:.2f},asetpts=PTS-STARTPTS,volume=0.22,"
                  f"afade=t=in:st=0:d=5,afade=t=out:st={fade_out_bg_start:.2f}:d=20[bg];"
                  f"[bg][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=80:release=600[ducked];"
                  f"[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
                  f"loudnorm=I=-18:TP=-2:LRA=9,"
                  f"afade=t=in:st=0:d=2,afade=t=out:st={fade_out_start:.2f}:d=25[out]")
            ff(["-i", str(voice), "-stream_loop", "-1", "-i", str(BGM_DIR / bgm),
                "-filter_complex", fc, "-map", "[out]", "-b:a", "128k", str(out)])
        else:
            ff(["-i", str(voice), "-af",
                f"loudnorm=I=-18:TP=-2:LRA=9,afade=t=in:st=0:d=2,afade=t=out:st={fade_out_start:.2f}:d=25",
                "-b:a", "128k", str(out)])
    elif bgm:
        fc = (f"[1:a]atrim=0:{dur:.2f},asetpts=PTS-STARTPTS,volume=0.32[bg];"
              f"[bg][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=80:release=600[ducked];"
              f"[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
              f"loudnorm=I=-16:TP=-1.5:LRA=11[out]")
        ff(["-i", str(voice), "-stream_loop", "-1", "-i", str(BGM_DIR / bgm),
            "-filter_complex", fc, "-map", "[out]", "-b:a", "192k", str(out)])
    else:
        ff(["-i", str(voice), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-b:a", "192k", str(out)])
    return out.read_bytes(), dur


# ---------- 路由 ----------
@APP.get("/health")
def health():
    return jsonify({"ok": True, "service": "audiobook-api", "usage": USAGE})


# ---------- 公版书导入（维基文库中转） ----------
import html as _html
import re as _re
import urllib.parse
import urllib.request

WIKI_API = "https://zh.wikisource.org/w/api.php"


def _fetch_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ShengJuan-Audiobook/1.0 (public-domain reader demo)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", errors="replace")
    # jina Reader 会在 JSON 前加 Markdown 头，从第一个 { 截取
    return json.loads(body[body.index("{"):])


def _wiki_get(params: dict):
    """维基文库 API 请求，镜像链依次尝试，返回 (data, via)。国内云直连维基媒体被墙，
    优先走可达的公共镜像/代理。corsproxy.io 需在环境变量 CORSPROXY_KEY 配置 key（国内云唯一可达）。"""
    qs = urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    target = f"{WIKI_API}?{qs}"
    qe = urllib.parse.quote(target, safe="")
    chain = []
    cp_key = os.environ.get("CORSPROXY_KEY", "").strip()
    if cp_key:
        chain.append(("corsproxy", f"https://corsproxy.io/?url={qe}&key={cp_key}", 15))
    chain += [
        ("jina",    f"https://r.jina.ai/{target}",            20),
        ("codetabs", f"https://api.codetabs.com/v1/proxy?quest={qe}", 10),
        ("allorigins", f"https://api.allorigins.win/raw?url={qe}", 15),
        ("direct",  target, 6),
    ]
    last_err = None
    for via, url, to in chain:
        try:
            return _fetch_json(url, to), via
        except Exception as e:  # noqa: BLE001
            last_err = f"{via}: {e}"
            continue
    raise RuntimeError(f"全部镜像通道失败（{last_err}）")


def _clean_wiki_html(raw: str) -> str:
    """维基文库页面 HTML -> 纯文本段落"""
    raw = _re.sub(r"<(style|script)[^>]*>.*?</\1>", "", raw, flags=_re.DOTALL)
    raw = _re.sub(r"<(table|sup)[^>]*>.*?</(table|sup)>", "", raw, flags=_re.DOTALL)  # 版式横幅/脚注
    raw = _re.sub(r"</(p|div|li|h[1-6]|br)>", "\n", raw)
    raw = _re.sub(r"<br\s*/?>", "\n", raw)
    raw = _re.sub(r"<[^>]+>", "", raw)
    raw = _html.unescape(raw)
    paras = [p.strip() for p in raw.split("\n")]
    paras = [p for p in paras if p and not _re.fullmatch(r"[\s·|()\[\]（）「」←→-]+", p)]
    return "\n\n".join(paras)


@APP.get("/books/diag")
def books_diag():
    """诊断模式一（默认）：逐条探测维基文库镜像链。
    诊断模式二（?probe=hosts）：普查国内可达的公版文本源站。"""
    if request.args.get("probe") == "hosts":
        hosts = [
            ("gushiwen", "https://so.gushiwen.cn/search.aspx?type=title&value=%E8%B5%A4%E5%A3%81%E8%B3%A6"),
            ("zdic", "https://www.zdic.net/"),
            ("ctext_api", "https://api.ctext.org/gettext?urn=ctp:analects/xue-er"),
            ("ctext_www", "https://ctext.org/"),
            ("gitee", "https://gitee.com/explore"),
            ("gitee_raw", "https://gitee.com/explore/raw/master/README.md"),
            ("npmmirror", "https://registry.npmmirror.com/chinese-poetry/latest"),
            ("hf_mirror", "https://hf-mirror.com/"),
            ("jsdelivr", "https://cdn.jsdelivr.net/"),
            ("wikisource", "https://zh.wikisource.org/w/api.php?action=query&meta=siteinfo&format=json"),
        ]
        out = []
        for via, url in hosts:
            t0 = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ShengJuan/1.0"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    status = r.status
                out.append({"via": via, "ok": 200 <= status < 400, "ms": int((time.time() - t0) * 1000),
                            "status": status})
            except urllib.error.HTTPError as e:
                out.append({"via": via, "ok": False, "ms": int((time.time() - t0) * 1000), "status": e.code})
            except Exception as e:  # noqa: BLE001
                out.append({"via": via, "ok": False, "ms": int((time.time() - t0) * 1000),
                            "err": str(e)[:60]})
        return jsonify({"probe": "hosts", "diag": out})

    # 默认：维基文库镜像链探测
    probe = {"action": "query", "meta": "siteinfo", "srlimit": 1}
    qs = urllib.parse.urlencode({**probe, "format": "json", "formatversion": 2})
    target = f"{WIKI_API}?{qs}"
    qe = urllib.parse.quote(target, safe="")
    chain = []
    cp_key = os.environ.get("CORSPROXY_KEY", "").strip()
    if cp_key:
        chain.append(("corsproxy", f"https://corsproxy.io/?url={qe}&key={cp_key}"))
    chain += [
        ("jina", f"https://r.jina.ai/{target}"),
        ("codetabs", f"https://api.codetabs.com/v1/proxy?quest={qe}"),
        ("allorigins", f"https://api.allorigins.win/raw?url={qe}"),
        ("direct", target),
    ]
    out = []
    for via, url in chain:
        t0 = time.time()
        try:
            _fetch_json(url, 6)
            out.append({"via": via, "ok": True, "ms": int((time.time() - t0) * 1000)})
        except Exception as e:  # noqa: BLE001
            out.append({"via": via, "ok": False, "ms": int((time.time() - t0) * 1000),
                        "err": str(e)[:80]})
    return jsonify({"diag": out})


@APP.get("/books/search")
def books_search():
    """维基文库全文检索（公有领域文本源）"""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "q required"}), 400
    try:
        data, via = _wiki_get({"action": "query", "list": "search", "srsearch": q,
                               "srlimit": 8, "srprop": "snippet|wordcount"})
        hits = [{"title": it["title"],
                 "snippet": _re.sub(r"<[^>]+>", "", it.get("snippet", "")),
                 "words": it.get("wordcount", 0)}
                for it in data.get("query", {}).get("search", [])]
        return jsonify({"results": hits, "via": via})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"文库检索失败: {e}"}), 502


@APP.get("/books/fetch")
def books_fetch():
    """按页面标题拉取维基文库正文，清洗为纯文本"""
    title = (request.args.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    try:
        data, via = _wiki_get({"action": "parse", "page": title, "prop": "text"})
        page = data.get("parse", {})
        text = _clean_wiki_html(page.get("text", ""))
        if len(text) < 100:
            return jsonify({"error": "该页面疑似目录页或内容过短，请尝试具体章节页（如「三國演義/第一回」）"}), 422
        return jsonify({"title": page.get("title", title), "text": text, "chars": len(text), "via": via})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"正文拉取失败: {e}"}), 502


@APP.get("/books/ctext/search")
def ctext_search():
    """ctext（中国哲学书电子化计划）搜书——官方 API，内容公有领域，腾讯云直连可达。
    searchtexts 免 key；remap=gb 输出简体。"""
    title = (request.args.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    try:
        qs = urllib.parse.urlencode({"if": "zh", "remap": "gb", "title": title})
        req = urllib.request.Request(f"https://api.ctext.org/searchtexts?{qs}",
                                     headers={"User-Agent": "ShengJuan-Audiobook/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        results = [{"title": b.get("title", ""), "urn": b.get("urn", "")}
                   for b in data.get("books", []) if b.get("urn")]
        return jsonify({"results": results})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"ctext 检索失败: {e}"}), 502


@APP.get("/books/ctext/fetch")
def ctext_fetch():
    """按 urn 拉取 ctext 正文（gettext 需 API key：环境变量 CTEXT_API_KEY）"""
    urn = (request.args.get("urn") or "").strip()
    if not urn:
        return jsonify({"error": "urn required"}), 400
    key = os.environ.get("CTEXT_API_KEY", "").strip()
    if not key:
        return jsonify({"error": "KEY_REQUIRED"}), 428
    try:
        qs = urllib.parse.urlencode({"if": "zh", "remap": "gb", "urn": urn, "apikey": key})
        req = urllib.request.Request(f"https://api.ctext.org/gettext?{qs}",
                                     headers={"User-Agent": "ShengJuan-Audiobook/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        if "error" in data:
            code = data["error"].get("code", "")
            msg = {"ERR_REQUIRES_AUTHENTICATION": "ctext key 无效或额度用尽",
                   "ERR_NON_EXISTING_URN": "urn 不存在"}.get(code, data["error"].get("description", code))
            return jsonify({"error": msg}), 502
        # gettext 返回结构兼容多种字段
        passages = data.get("passages") or []
        parts = []
        for p in passages:
            if isinstance(p, dict):
                t = p.get("utf8") or p.get("text") or ""
            else:
                t = str(p)
            t = t.strip()
            if t:
                parts.append(t)
        text = "\n\n".join(parts) if parts else (data.get("fulltext") or "").strip()
        if len(text) < 10:
            return jsonify({"error": "该 urn 内容为空或为目录层级，请选择具体章节"}), 422
        return jsonify({"title": data.get("title", urn), "text": text, "chars": len(text)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"ctext 拉取失败: {e}"}), 502


@APP.post("/tasks")
def create_task():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    if len(text) > 10000:
        return jsonify({"error": "text too long (max 10000)"}), 400
    narrator = data.get("narrator") or DEFAULT_NARRATOR
    use_bgm = bool(data.get("bgm", True))
    dialect = (data.get("dialect") or "").strip() or None   # 方言通道：sichuan/yue/dongbei/beijing/shanghai/henan/shaanxi/tianjin
    style = (data.get("style") or "normal").strip().lower()
    if style not in ("normal", "slow", "trailer", "english", "bedtime"):
        style = "normal"
    task_id = uuid.uuid4().hex[:12]
    TASKS[task_id] = {"status": "running", "stage": "queued", "progress": "0",
                      "segments": None, "audio_base64": None, "error": None,
                      "narrator": narrator}
    bump("tasks")
    # 登录用户自动记会话历史（匿名任务不记）
    try:
        uid = _require_uid()
        _add_history(uid, "generate", f"有声化《{(data.get('title') or text[:12])}》",
                     {"task_id": task_id, "chars": len(text), "style": style, "narrator": narrator})
    except ValueError:
        pass
    except Exception as e:  # noqa: BLE001
        log(f"[history] tasks 钩子失败: {e}")
    threading.Thread(target=run_pipeline, args=(task_id, text, narrator, use_bgm, dialect, style), daemon=True).start()
    return jsonify({"task_id": task_id})


@APP.get("/tasks/<task_id>")
def get_task(task_id: str):
    t = TASKS.get(task_id)
    if not t:
        return jsonify({"error": "not found"}), 404
    resp = {k: v for k, v in t.items() if k != "audio_base64"}
    resp["has_audio"] = t.get("audio_base64") is not None
    if request.args.get("audio") == "1" and t.get("audio_base64"):
        resp["audio_base64"] = t["audio_base64"]
    return jsonify(resp)


def synth_dispatch(text: str, speaker: str, out_path: Path, emotion=None, scale=4, speed=0,
                   dialect: str | None = None, loudness: int = 0):
    """按音色类型分发：cosyvoice-vd -> CosyVoice；ttv-voice -> MiniMax；其余 -> 豆包（可带方言参数）"""
    if speaker.startswith("cosyvoice"):
        out_path.write_bytes(cosy_tts_bytes(text, speaker))
        return
    if speaker.startswith("ttv-voice"):
        out_path.write_bytes(minimax_tts_bytes(text, speaker))
        return
    tts(text, speaker, out_path, emotion=emotion, scale=scale, speed=speed,
        dialect=dialect, loudness=loudness)


# ---------- 音色接口 ----------
PREVIEW_TEXT = "你好，我是你的朗读者，很高兴用声音为你讲述接下来的故事。"
PREVIEW_TEXT_EN = "Hello, I am your narrator. It is a pleasure to read the next story for you."

@APP.post("/voices/preview")
def voice_preview():
    """任意音色试听：固定文案合成一句，自动按音色类型分发厂商（可带方言）。
    英文音色用英文文案（豆包英文音色遇纯中文输入会静默不合成）"""
    data = request.get_json(force=True, silent=True) or {}
    speaker = (data.get("speaker_id") or "").strip()
    dialect = (data.get("dialect") or "").strip() or None
    if not speaker:
        return jsonify({"error": "speaker_id required"}), 400
    bump("previews")
    d = WORK / f"preview-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        out = d / "preview.mp3"
        preview_text = PREVIEW_TEXT_EN if speaker.startswith("en_") else PREVIEW_TEXT
        synth_dispatch(preview_text, speaker, out, dialect=dialect)
        return jsonify({"audio_base64": base64.b64encode(out.read_bytes()).decode("ascii")})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:300]}), 502


@APP.get("/voices/design/info")
def voice_design_info():
    """设计通道与费用提示，供前端确认弹窗动态展示"""
    provider = design_provider()
    if provider == "cosyvoice":
        return jsonify({"provider": provider, "free": True,
                        "fee_text": "当前通道：阿里云 CosyVoice，<b>音色设计免费</b>（合成约 ¥1.5/万字符，为 MiniMax 的 1/3）。"})
    return jsonify({"provider": provider, "free": False,
                    "fee_text": "音色设计按次计费，本次将产生约 <b>¥21.6</b> 费用。"})


@APP.post("/voices/design")
def voice_design():
    data = request.get_json(force=True, silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    preview = "你好，我是由声卷为你量身定制的声音，很高兴认识你，希望你喜欢我讲的故事。"
    provider = design_provider()
    ckey = design_cache_key(prompt)
    cached_id = design_cache_get(ckey, provider)
    if cached_id:
        log(f"[design] 命中缓存 {ckey} -> {cached_id}，不重复收取设计费")
        try:
            preview_b64 = base64.b64encode(custom_tts_bytes(preview, cached_id)).decode("ascii")
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": str(e)[:300]}), 502
        return jsonify({"voice_id": cached_id, "preview_base64": preview_b64,
                        "cached": True, "provider": provider,
                        "note": "已复用相同描述的历史音色，本次不产生设计费"})
    try:
        if provider == "cosyvoice":
            voice_id, preview_b64 = cosy_design(prompt, preview)
            note = "CosyVoice 通道：音色设计免费，相同描述后续自动复用"
        else:
            voice_id, preview_b64 = minimax_design(prompt, preview)
            note = "设计费已在本次试听合成时收取（约 ¥21.6），相同描述后续将自动复用"
        design_cache_put(ckey, prompt, voice_id, provider)
        return jsonify({"voice_id": voice_id, "preview_base64": preview_b64,
                        "cached": False, "provider": provider, "note": note})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:300]}), 502


@APP.post("/voices/clone")
def voice_clone():
    bump("clones")
    data = request.get_json(force=True, silent=True) or {}
    audio_b64 = data.get("audio_base64") or ""
    fmt = data.get("format", "mp3").lower()
    text = (data.get("text") or "").strip()
    speaker = data.get("speaker_id") or DEFAULT_CLONE_SPEAKER
    name_hint = (data.get("demo_text") or "").strip()
    if len(audio_b64) < 1000:
        return jsonify({"error": "录音数据无效或过短"}), 400
    if not text:
        return jsonify({"error": "缺少录音原文（text）"}), 400
    d = WORK / f"clone-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    raw = d / f"raw.{fmt}"
    try:
        raw.write_bytes(base64.b64decode(audio_b64))
        mp3 = d / "audio.mp3"
        # 浏览器 MediaRecorder 产出 webm/ogg 等，统一转 mp3 保证火山兼容
        ff(["-i", str(raw), "-ar", "44100", "-ac", "1", "-b:a", "128k", str(mp3)])
        result = volc_clone_train(mp3.read_bytes(), "mp3", text, speaker,
                                  demo_text=name_hint or "你好，我是你的专属克隆声音。")
        return jsonify(result)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:300]}), 502


@APP.post("/tasks/<task_id>/adjust")
def adjust_segment(task_id: str):
    """段落级增量重合成：修改指定段的情绪强度 -> 只重合成该段 -> 重拼混音整篇"""
    t = TASKS.get(task_id)
    if not t or t.get("status") != "done":
        return jsonify({"error": "task not ready"}), 404
    part_files = t.get("part_files") or []
    data = request.get_json(force=True, silent=True) or {}
    try:
        index = int(data.get("index", -1))
        intensity = float(data.get("intensity", 0.5))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid index/intensity"}), 400
    if not (0 <= index < len(part_files)) or len(part_files) != len(t["segments"]):
        return jsonify({"error": "index out of range"}), 400
    intensity = max(0.05, min(1.0, intensity))

    seg = t["segments"][index]
    seg["intensity"] = round(intensity, 2)          # 更新曲线数据
    emo = EMOTION_MAP.get(seg["emotion"])
    if seg["emotion"] in ("neutral", "calm"):
        emo = None
    scale = max(1, min(5, round(1 + intensity * 4)))

    d = WORK / task_id
    tmp_new = d / f"seg_{index:03d}_new.mp3"
    task_dialect = t.get("dialect") or None
    try:
        try:
            synth_dispatch(seg["text"], seg["speaker"], tmp_new, emotion=emo,
                           scale=scale, speed=seg["speed"], dialect=task_dialect)
        except Exception:                            # 回退中性
            synth_dispatch(seg["text"], seg["speaker"], tmp_new, dialect=task_dialect)
        Path(part_files[index]).write_bytes(tmp_new.read_bytes())
        tmp_new.unlink(missing_ok=True)

        task_style = t.get("style") or "normal"
        style_pause = {"slow": 0.55, "trailer": 0.45, "bedtime": 0.8}.get(task_style, 0.28)
        audio_b, dur = mix_task(d, [Path(p) for p in part_files], bool(t.get("use_bgm", True)),
                                pause=style_pause, bedtime=(task_style == "bedtime"))
        t["audio_base64"] = base64.b64encode(audio_b).decode("ascii")
        t["duration_s"] = round(dur, 1)
        return jsonify({"ok": True, "segments": t["segments"],
                        "duration_s": t["duration_s"],
                        "audio_base64": t["audio_base64"]})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:300]}), 502


# ---------- 用户系统（自建：users 表 + HMAC token + PBKDF2 密码哈希） ----------
# 说明：CloudBase Auth 不支持用户名+密码自助注册（官方文档明确），故自建用户表。
# 前端 /auth/register /auth/login 换取 token，/me/* 接口带 Bearer token。
# 后端持 CB_SERVICE_KEY（service_role 绕过 RLS），uid 隔离由后端代码保证。
import hashlib
import hmac as _hmac

CB_ENV_ID = os.environ.get("CB_ENV_ID", "sm-20252354-d0gugy5fq52b8b895")
PG_REST_BASE = f"https://{CB_ENV_ID}.api.tcloudbasegateway.com/v1/rdb/rest"
CB_SERVICE_KEY = os.environ.get("CB_SERVICE_KEY", "")          # service_role，仅后端使用
CB_AUTH_SECRET = os.environ.get("CB_AUTH_SECRET", "")          # token 签名密钥
TOKEN_TTL_S = 7 * 24 * 3600                                    # token 有效期 7 天
PBKDF2_ITER = 100_000


def _pg_request(method, table, params=None, json_body=None, upsert=False):
    """service_role 调 PG HTTP API（绕过 RLS，后端自己做 uid 隔离）"""
    url = f"{PG_REST_BASE}/{table}"
    headers = {"Authorization": f"Bearer {CB_SERVICE_KEY}", "Content-Type": "application/json"}
    if json_body is not None:
        headers["Prefer"] = "return=representation" + (",resolution=merge-duplicates" if upsert else "")
    return requests.request(method, url, headers=headers, params=params or {}, json=json_body, timeout=15)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign_token(uid: str) -> str:
    payload = _b64url(json.dumps({"uid": uid, "exp": int(time.time()) + TOKEN_TTL_S}).encode())
    sig = _b64url(_hmac.new(CB_AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def _check_token(token: str):
    """验证 token，返回 uid 或 None"""
    if not token or "." not in token:
        return None
    try:
        payload, sig = token.rsplit(".", 1)
        expect = _b64url(_hmac.new(CB_AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
        if not _hmac.compare_digest(sig, expect):
            return None
        obj = json.loads(_b64url_decode(payload))
        if int(obj.get("exp", 0)) < time.time():
            return None
        return obj.get("uid")
    except Exception:  # noqa: BLE001
        return None


def _require_uid():
    """从请求头验证 token，返回 uid；失败时已带 401 响应（用异常流简化）"""
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    uid = _check_token(token)
    if not uid:
        raise ValueError("UNAUTHORIZED")
    return uid


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITER)
    return f"{salt}${dk.hex()}"


def _check_password(password: str, stored: str) -> bool:
    try:
        salt, dk_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITER)
        return _hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:  # noqa: BLE001
        return False


@APP.post("/auth/register")
def auth_register():
    if not CB_SERVICE_KEY or not CB_AUTH_SECRET:
        return jsonify({"error": "服务端用户系统未配置"}), 503
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"error": "用户名和密码必填"}), 400
    if not re.fullmatch(r"[\w\u4e00-\u9fa5]{3,20}", username):
        return jsonify({"error": "用户名 3-20 位，仅限中英文/数字/下划线"}), 400
    if len(password) < 6 or len(password) > 64:
        return jsonify({"error": "密码 6-64 位"}), 400
    # 查重
    try:
        r = _pg_request("GET", "users", params={"username": f"eq.{username}", "select": "uid"})
        if r.status_code == 200 and r.json():
            return jsonify({"error": "用户名已被占用"}), 409
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"注册失败: {e}"}), 502
    uid = uuid.uuid4().hex
    try:
        r = _pg_request("POST", "users", json_body={
            "uid": uid, "username": username, "password_hash": _hash_password(password)})
        if r.status_code not in (200, 201):
            return jsonify({"error": f"注册失败: {r.text[:200]}"}), 502
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"注册失败: {e}"}), 502
    return jsonify({"ok": True, "username": username, "token": _sign_token(uid)})


@APP.post("/auth/login")
def auth_login():
    if not CB_SERVICE_KEY or not CB_AUTH_SECRET:
        return jsonify({"error": "服务端用户系统未配置"}), 503
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"error": "用户名和密码必填"}), 400
    try:
        r = _pg_request("GET", "users",
                        params={"username": f"eq.{username}", "select": "uid,password_hash"})
        rows = r.json() if r.status_code == 200 else []
        if not isinstance(rows, list) or not rows or not _check_password(password, rows[0].get("password_hash", "")):
            return jsonify({"error": "用户名或密码错误"}), 401
        return jsonify({"ok": True, "username": username, "token": _sign_token(rows[0]["uid"])})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"登录失败: {e}"}), 502


@APP.get("/me/voice")
def me_voice_get():
    """查询当前用户的「我的音色」（1 条，覆盖式）；新用户返回 voice=null"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    try:
        r = _pg_request("GET", "user_voices", params={"uid": f"eq.{uid}", "select": "*"})
        if r.status_code == 200:
            rows = r.json()
            return jsonify({"voice": rows[0] if isinstance(rows, list) and rows else None})
        return jsonify({"error": f"查询失败: {r.text[:200]}"}), r.status_code
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502


@APP.put("/me/voice")
def me_voice_put():
    """复制/覆盖「我的音色」：每用户 1 条（PK=uid），新音色覆盖旧的。
    body: {speaker_id, name, source, dialect?}"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    data = request.get_json(force=True, silent=True) or {}
    speaker_id = (data.get("speaker_id") or "").strip()
    name = (data.get("name") or "").strip()
    source = (data.get("source") or "preset").strip()
    dialect = (data.get("dialect") or "").strip() or None
    if not speaker_id or not name:
        return jsonify({"error": "speaker_id 和 name 必填"}), 400
    body = {"uid": uid, "speaker_id": speaker_id, "name": name, "source": source}
    if dialect:
        body["dialect"] = dialect
    try:
        r = _pg_request("POST", "user_voices", json_body=body, upsert=True,
                        params={"on_conflict": "uid"})    # UPSERT：PK 冲突即覆盖
        if r.status_code in (200, 201):
            rows = r.json()
            return jsonify(rows[0] if isinstance(rows, list) and rows else {"ok": True})
        return jsonify({"error": f"保存失败: {r.text[:200]}"}), r.status_code
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502


@APP.delete("/me/voice")
def me_voice_delete():
    """删除当前用户的「我的音色」"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    try:
        r = _pg_request("DELETE", "user_voices", params={"uid": f"eq.{uid}"})
        return jsonify({"ok": True})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502


# ---------- 个人书架与会话历史（账号级隔离） ----------
BOOK_MAX_CHARS = 30000

@APP.get("/me/books")
def me_books_list():
    """我的书架：当前账号上传过的全部读本"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    try:
        r = _pg_request("GET", "user_books",
                        params={"uid": f"eq.{uid}", "select": "id,title,chars,created_at",
                                "order": "created_at.desc"})
        rows = r.json() if r.status_code == 200 else []
        return jsonify({"books": rows})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502


@APP.post("/me/books")
def me_books_create():
    """上传读本到个人书架（title + content，超长自动截断）"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()[:80]
    content = (data.get("content") or "").strip()
    if not title or not content:
        return jsonify({"error": "title 和 content 必填"}), 400
    truncated = len(content) > BOOK_MAX_CHARS
    if truncated:
        content = content[:BOOK_MAX_CHARS]
    book_id = uuid.uuid4().hex[:16]
    try:
        r = _pg_request("POST", "user_books", json_body={
            "id": book_id, "uid": uid, "title": title,
            "content": content, "chars": len(content)})
        if r.status_code not in (200, 201):
            return jsonify({"error": f"保存失败: {r.text[:200]}"}), 502
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502
    # 自动记历史
    _add_history(uid, "upload", f"上传读本《{title}》", {"book_id": book_id, "chars": len(content)})
    return jsonify({"ok": True, "book_id": book_id, "chars": len(content), "truncated": truncated})


@APP.get("/me/books/<book_id>")
def me_books_get(book_id: str):
    """取读本正文（仅本人）"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    try:
        r = _pg_request("GET", "user_books",
                        params={"id": f"eq.{book_id}", "uid": f"eq.{uid}", "select": "*"})
        rows = r.json() if r.status_code == 200 else []
        if not rows:
            return jsonify({"error": "读本不存在或无权访问"}), 404
        return jsonify({"book": rows[0]})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502


@APP.delete("/me/books/<book_id>")
def me_books_delete(book_id: str):
    """删除书架读本（仅本人）"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    try:
        r = _pg_request("DELETE", "user_books", params={"id": f"eq.{book_id}", "uid": f"eq.{uid}"})
        return jsonify({"ok": True})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502


# ───────── 成品有声书书架（工作台生成 → 保存 → 双端共享收听） ─────────
AUDIO_B64_MAX = 60 * 1024 * 1024    # base64 上限 ≈ 45MB 音频


@APP.post("/me/audiobooks")
def me_audiobooks_create():
    """把已完成任务的成品音频存入书架（body: {task_id, title}）"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    data = request.get_json(force=True, silent=True) or {}
    task_id = (data.get("task_id") or "").strip()
    title = (data.get("title") or "").strip()[:80]
    if not task_id or not title:
        return jsonify({"error": "task_id 和 title 必填"}), 400
    t = TASKS.get(task_id)
    if not t or t.get("status") != "done" or not t.get("audio_base64"):
        return jsonify({"error": "任务不存在或尚未完成"}), 404
    b64 = t["audio_base64"]
    if len(b64) > AUDIO_B64_MAX:
        return jsonify({"error": "音频过大，暂无法保存到书架"}), 413
    book_id = uuid.uuid4().hex[:16]
    try:
        r = _pg_request("POST", "user_audiobooks", json_body={
            "id": book_id, "uid": uid, "title": title,
            "narrator": t.get("narrator", ""),
            "dur_s": t.get("duration_s", 0),
            "size_bytes": len(b64) * 3 // 4,
            "audio_b64": b64})
        if r.status_code not in (200, 201):
            return jsonify({"error": f"保存失败: {r.text[:200]}"}), 502
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502
    _add_history(uid, "render", f"保存有声书《{title}》", {"shelf_id": book_id})
    return jsonify({"ok": True, "id": book_id, "dur_s": t.get("duration_s", 0)})


@APP.get("/me/audiobooks")
def me_audiobooks_list():
    """书架列表（元数据，不含音频体）"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    try:
        r = _pg_request("GET", "user_audiobooks",
                        params={"uid": f"eq.{uid}",
                                "select": "id,title,narrator,dur_s,size_bytes,created_at",
                                "order": "created_at.desc"})
        rows = r.json() if r.status_code == 200 else []
        return jsonify({"books": rows})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502


@APP.get("/me/audiobooks/<book_id>/audio")
def me_audiobooks_audio(book_id: str):
    """流式取成品音频（不鉴权：id 为 16 位随机串难枚举；支持 Range 供拖拽 seek）"""
    try:
        r = _pg_request("GET", "user_audiobooks",
                        params={"id": f"eq.{book_id}", "select": "audio_b64"})
        rows = r.json() if r.status_code == 200 else []
        if not rows:
            return jsonify({"error": "not found"}), 404
        audio_bytes = base64.b64decode(rows[0]["audio_b64"])
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502

    total = len(audio_bytes)
    rng = request.headers.get("Range", "")
    m = re.match(r"bytes=(\d*)-(\d*)", rng)
    if m and (m.group(1) or m.group(2)):
        start = int(m.group(1)) if m.group(1) else max(0, total - int(m.group(2)))
        end = int(m.group(2)) if m.group(2) else min(start + 512 * 1024, total - 1)
        end = min(end, total - 1)
        if start > end or start >= total:
            return APP.response_class(status=416, headers={"Content-Range": f"bytes */{total}"})
        chunk = audio_bytes[start:end + 1]
        resp = APP.response_class(chunk, 206, mimetype="audio/mpeg")
        resp.headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        resp.headers["Accept-Ranges"] = "bytes"
        return resp
    resp = APP.response_class(audio_bytes, 200, mimetype="audio/mpeg")
    resp.headers["Accept-Ranges"] = "bytes"
    return resp


@APP.delete("/me/audiobooks/<book_id>")
def me_audiobooks_delete(book_id: str):
    """删除书架有声书（仅本人）"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    try:
        r = _pg_request("DELETE", "user_audiobooks",
                        params={"id": f"eq.{book_id}", "uid": f"eq.{uid}"})
        return jsonify({"ok": True})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502


def _add_history(uid: str, kind: str, title: str, detail: dict | None = None):
    """写会话历史（尽力而为，失败不阻塞主流程）"""
    try:
        _pg_request("POST", "user_history", json_body={
            "uid": uid, "kind": kind, "title": title[:120],
            "detail": detail or {}})
    except Exception as e:  # noqa: BLE001
        log(f"[history] 写入失败: {e}")


@APP.get("/me/history")
def me_history_list():
    """会话历史：当前账号最近操作"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    limit = min(int(request.args.get("limit", 50) or 50), 100)
    try:
        r = _pg_request("GET", "user_history",
                        params={"uid": f"eq.{uid}", "select": "id,kind,title,detail,created_at",
                                "order": "created_at.desc", "limit": str(limit)})
        rows = r.json() if r.status_code == 200 else []
        return jsonify({"history": rows})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502


@APP.post("/me/history")
def me_history_add():
    """手动补记一条历史（前端关键操作后调用）"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    data = request.get_json(force=True, silent=True) or {}
    kind = (data.get("kind") or "").strip()
    title = (data.get("title") or "").strip()
    if not kind or not title:
        return jsonify({"error": "kind 和 title 必填"}), 400
    _add_history(uid, kind, title, data.get("detail"))
    return jsonify({"ok": True})


# ---------- 收听报告（listen_logs：家长端数据源） ----------
LISTEN_DAYS_MAX = 60

@APP.post("/me/listen")
def me_listen_add():
    """上报一段收听（前端按 30s 增量批量上报，尽力而为不阻塞播放）"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    data = request.get_json(force=True, silent=True) or {}
    story_id = (data.get("story_id") or "").strip()[:64]
    title = (data.get("title") or "").strip()[:80]
    listen_date = (data.get("date") or "").strip()[:10]
    duration_s = int(data.get("duration_s") or 0)
    if not story_id or not listen_date or duration_s <= 0:
        return jsonify({"error": "story_id / date / duration_s 必填"}), 400
    duration_s = min(duration_s, 3600)
    row = {"uid": uid, "story_id": story_id, "title": title,
           "listen_date": listen_date, "duration_s": duration_s,
           "completed": bool(data.get("completed")),
           "tags": [str(t)[:16] for t in (data.get("tags") or [])][:8],
           "age_group": (data.get("age_group") or "").strip()[:8]}
    try:
        r = _pg_request("POST", "user_listen_logs", json_body=row)
        if r.status_code not in (200, 201):
            return jsonify({"error": f"写入失败: {r.text[:200]}"}), 502
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502
    return jsonify({"ok": True})


@APP.get("/me/listen")
def me_listen_list():
    """查询收听记录（days 天内，供家长端聚合报告）"""
    try:
        uid = _require_uid()
    except ValueError:
        return jsonify({"error": "未登录或登录已过期"}), 401
    days = min(max(int(request.args.get("days", 14) or 14), 1), LISTEN_DAYS_MAX)
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    try:
        r = _pg_request("GET", "user_listen_logs",
                        params={"uid": f"eq.{uid}", "listen_date": f"gte.{since}",
                                "select": "story_id,title,listen_date,duration_s,completed,tags,age_group",
                                "order": "listen_date.desc", "limit": "500"})
        rows = r.json() if r.status_code == 200 else []
        return jsonify({"logs": rows, "days": days})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    APP.run(host="0.0.0.0", port=port, threaded=True)
