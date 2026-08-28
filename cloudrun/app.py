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
import subprocess
import threading
import time
import uuid
from pathlib import Path

import requests
from flask import Flask, jsonify, request

APP = Flask(__name__)
WORK = Path("/tmp/audiobook")          # 容器内工作目录
BGM_DIR = Path(__file__).parent / "assets" / "bgm"

@APP.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
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


def assign_speakers(segments: list, narrator: str) -> dict:
    """按角色性别动态分配音色；旁白固定用 narrator；同一角色全篇锁定同一音色"""
    pools = {"male": list(MALE_POOL), "female": list(FEMALE_POOL)}
    role_map = {}
    for seg in segments:
        r = seg.get("role", "旁白")
        if r == "旁白":
            seg["speaker"] = narrator
            continue
        if r not in role_map:
            g = seg.get("gender", "unknown")
            pool = pools.get(g)
            if pool:                       # 按性别依次取池中音色，多角色自然错开
                role_map[r] = pool.pop(0)
            else:                          # unknown 跟随旁白，保证不违和
                role_map[r] = narrator
        seg["speaker"] = role_map[r]
    return role_map

TASKS: dict = {}   # task_id -> {"status","stage","segments","audio_base64","duration_s","error"}


def pick_resource(speaker: str) -> str:
    return "seed-icl-2.0" if speaker.startswith(("S_", "custom")) else "seed-tts-2.0"


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------- 确定性拆分兜底 ----------
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


# ---------- GLM 情感分析 ----------
def analyze(text: str):
    body = {"model": "glm-4-flash",
            "messages": [{"role": "user", "content": PROMPT.replace('__TEXT__', text)}],
            "temperature": 0.2}
    headers = {"Authorization": f"Bearer {os.environ['GLM_API_KEY']}", "Content-Type": "application/json"}
    content = None
    for attempt in range(3):
        try:
            r = requests.post(GLM_URL, headers=headers, json=body, timeout=150)
            if r.status_code != 200:
                raise RuntimeError(f"GLM HTTP {r.status_code}: {r.text[:200]}")
            content = r.json()["choices"][0]["message"]["content"]
            break
        except Exception as e:  # noqa: BLE001
            log(f"[glm retry {attempt+1}] {e}")
            time.sleep(2 * (attempt + 1))
    if content is None:
        raise RuntimeError("GLM 分析失败（重试耗尽）")
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
    return out


# ---------- 豆包 TTS ----------
def tts(text: str, speaker: str, out_path: Path, emotion=None, scale=4, speed=0):
    body = {"user": {"uid": "audiobook-cloud"},
            "req_params": {"text": text, "speaker": speaker,
                           "audio_params": {"format": "mp3", "sample_rate": 24000,
                                            "speech_rate": speed}}}
    if emotion:
        body["req_params"]["audio_params"]["emotion"] = emotion
        body["req_params"]["audio_params"]["emotion_scale"] = scale
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
    preview = minimax_tts_bytes(preview_text, voice_id)   # 激活并出试听
    return voice_id, base64.b64encode(preview).decode("ascii")


def minimax_tts_bytes(text: str, voice_id: str) -> bytes:
    body = {"model": "speech-2.8-turbo", "text": text, "stream": False,
            "output_format": "hex",
            "voice_setting": {"voice_id": voice_id, "speed": 1.0, "vol": 1.0, "pitch": 0},
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1}}
    r = requests.post(f"{MM_BASE}/v1/t2a_v2?GroupId={os.environ.get('MINIMAX_GROUP_ID', '')}",
                      headers=mm_headers(), json=body, timeout=120)
    obj = r.json()
    br = obj.get("base_resp", {})
    if r.status_code != 200 or br.get("status_code") != 0:
        raise RuntimeError(f"MiniMax 合成失败: {br.get('status_msg', '')}")
    return bytes.fromhex(obj["data"]["audio"])


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
def run_pipeline(task_id: str, text: str, narrator: str, use_bgm: bool):
    t = TASKS[task_id]
    d = WORK / task_id
    d.mkdir(parents=True, exist_ok=True)
    try:
        t["stage"] = "analyzing"
        segments = analyze(text)
        t["segments"] = segments
        log(f"[{task_id}] {len(segments)} 段")

        t["stage"] = "synthesizing"
        role_map = assign_speakers(segments, narrator)
        log(f"[{task_id}] role_map={role_map}")
        parts = []
        for i, seg in enumerate(segments):
            speaker = seg["speaker"]
            emo = EMOTION_MAP.get(seg["emotion"])
            if seg["emotion"] in ("neutral", "calm"):
                emo = None
            scale = max(1, min(5, round(1 + seg["intensity"] * 4)))
            seg_path = d / f"seg_{i:03d}.mp3"
            try:
                synth_dispatch(seg["text"], speaker, seg_path, emotion=emo, scale=scale, speed=seg["speed"])
            except Exception:  # 回退中性
                synth_dispatch(seg["text"], speaker, seg_path)
            parts.append(seg_path)
            t["progress"] = f"{i+1}/{len(segments)}"

        t["stage"] = "mixing"
        t["part_files"] = [str(p) for p in parts]     # 供段落级调整后重混音
        audio_b, dur = mix_task(d, parts, use_bgm)
        out = d / "final.mp3"
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


def mix_task(d: Path, parts: list, use_bgm: bool):
    """拼接段落 + BGM 匹配 ducking 混音 + 响度归一 -> (bytes, duration_s)"""
    sil = d / "sil.mp3"
    if not sil.exists():
        ff(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.28", "-b:a", "128k", str(sil)])
    lst = d / "concat.txt"
    lines = []
    for p in parts:
        lines += [f"file '{p}'", f"file '{sil}'"]
    lst.write_text("\n".join(lines), encoding="utf-8")
    voice = d / "voice.mp3"
    ff(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(voice)])
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(voice)], capture_output=True, text=True).stdout.strip())

    segments_meta = TASKS.get(d.name, {}).get("segments") if d.name in TASKS else None
    out = d / "final.mp3"
    bgm = pick_bgm(segments_meta) if (use_bgm and segments_meta) else ""
    if bgm:
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
    return jsonify({"ok": True, "service": "audiobook-api"})


@APP.post("/tasks")
def create_task():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    if len(text) > 5000:
        return jsonify({"error": "text too long (max 5000)"}), 400
    narrator = data.get("narrator") or DEFAULT_NARRATOR
    use_bgm = bool(data.get("bgm", True))
    task_id = uuid.uuid4().hex[:12]
    TASKS[task_id] = {"status": "running", "stage": "queued", "progress": "0",
                      "segments": None, "audio_base64": None, "error": None}
    threading.Thread(target=run_pipeline, args=(task_id, text, narrator, use_bgm), daemon=True).start()
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


def synth_dispatch(text: str, speaker: str, out_path: Path, emotion=None, scale=4, speed=0):
    """按音色类型分发：ttv-voice -> MiniMax；其余 -> 豆包"""
    if speaker.startswith("ttv-voice"):
        out_path.write_bytes(minimax_tts_bytes(text, speaker))
        return
    tts(text, speaker, out_path, emotion=emotion, scale=scale, speed=speed)


# ---------- 音色接口 ----------
PREVIEW_TEXT = "你好，我是你的朗读者，很高兴用声音为你讲述接下来的故事。"

@APP.post("/voices/preview")
def voice_preview():
    """任意音色试听：固定文案合成一句，自动按音色类型分发厂商"""
    data = request.get_json(force=True, silent=True) or {}
    speaker = (data.get("speaker_id") or "").strip()
    if not speaker:
        return jsonify({"error": "speaker_id required"}), 400
    d = WORK / f"preview-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        out = d / "preview.mp3"
        synth_dispatch(PREVIEW_TEXT, speaker, out)
        return jsonify({"audio_base64": base64.b64encode(out.read_bytes()).decode("ascii")})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:300]}), 502


@APP.post("/voices/design")
def voice_design():
    data = request.get_json(force=True, silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    preview = "你好，我是由声卷为你量身定制的声音，很高兴认识你，希望你喜欢我讲的故事。"
    try:
        voice_id, preview_b64 = minimax_design(prompt, preview)
        return jsonify({"voice_id": voice_id, "preview_base64": preview_b64,
                        "note": "设计费已在本次试听合成时收取"})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:300]}), 502


@APP.post("/voices/clone")
def voice_clone():
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
    try:
        try:
            synth_dispatch(seg["text"], seg["speaker"], tmp_new, emotion=emo,
                           scale=scale, speed=seg["speed"])
        except Exception:                            # 回退中性
            synth_dispatch(seg["text"], seg["speaker"], tmp_new)
        Path(part_files[index]).write_bytes(tmp_new.read_bytes())
        tmp_new.unlink(missing_ok=True)

        audio_b, dur = mix_task(d, [Path(p) for p in part_files], bool(t.get("use_bgm", True)))
        t["audio_base64"] = base64.b64encode(audio_b).decode("ascii")
        t["duration_s"] = round(dur, 1)
        return jsonify({"ok": True, "segments": t["segments"],
                        "duration_s": t["duration_s"],
                        "audio_base64": t["audio_base64"]})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:300]}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    APP.run(host="0.0.0.0", port=port, threaded=True)
