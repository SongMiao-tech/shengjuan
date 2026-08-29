# -*- coding: utf-8 -*-
"""睡前故事内容生成：GLM 按故事清单批量产出适龄正文 + 标签 + 生字 + 知识点。
输出 shengjuan/web/stories/{story_id}.json + stories/index.json
用法: python scripts/build_story_lib.py          # 生成全部
      python scripts/build_story_lib.py s01 s02  # 只生成指定 ID"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "stories"
OUT.mkdir(parents=True, exist_ok=True)
for line in (ROOT.parent / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

# 20 篇故事清单：中文公版（西游记/山海经/中国民间故事）+ 西方公版（格林/安徒生/伊索）
# age_group: '3-5' | '6-8'；每篇给出 IP 与核心情节，正文由 GLM 适龄改写
CATALOG = [
    ("s01", "小兔子的月亮灯", "原创", "3-5", ["友谊", "睡前"], "小兔子怕黑，朋友们送来会发光的月亮灯陪它入睡"),
    ("s02", "爱打哈欠的小刺猬", "原创", "3-5", ["睡前", "习惯"], "小刺猬总不肯睡，哈欠传染了全森林，大家约定一起早睡"),
    ("s03", "月亮婆婆的摇篮曲", "原创", "3-5", ["睡前", "自然"], "月亮婆婆每晚给森林里的动物们唱摇篮曲"),
    ("s04", "小熊的第一颗乳牙", "原创", "3-5", ["成长", "勇气"], "小熊乳牙掉了很害怕，妈妈告诉它这是长大的礼物"),
    ("s05", " Sharing is Caring 小松鼠分橡果", "原创", "3-5", ["分享", "友谊"], "小松鼠学会把橡果分给过冬的邻居们"),
    ("s06", "不爱洗澡的小猪", "原创", "3-5", ["习惯"], "小猪不爱洗澡，朋友们都不爱靠近它，最后爱上洗澡"),
    ("s07", "彩虹桥上的小鸭子", "原创", "3-5", ["勇气", "友谊"], "小鸭子害怕过桥，朋友们陪它一步步走过去"),
    ("s08", "小星星找妈妈", "原创", "3-5", ["亲情", "睡前"], "一颗小星星迷路了，月亮帮它找到回家的路"),
    ("s09", "龟兔赛跑新编", "伊索寓言", "3-5", ["坚持", "友谊"], "改编自伊索寓言：乌龟不放弃，兔子学会了认真"),
    ("s10", "拔萝卜", "俄罗斯民间", "3-5", ["合作"], "大家一起用力，大萝卜终于拔出来了"),
    ("s11", "小马过河", "中国民间", "3-5", ["思考", "勇气"], "小马亲自试过河，才知道河的深浅"),
    ("s12", "猴子捞月", "中国民间", "3-5", ["思考"], "猴子们捞水里的月亮，明白影子捞不起来"),
    ("s13", "狼来了", "伊索寓言", "3-5", ["诚实"], "放羊娃三次撒谎，最后没人信他了，他学会了诚实"),
    ("s14", "石头汤", "欧洲民间", "3-5", ["分享", "合作"], "一锅石头汤因为每人都添一点料变得美味"),
    ("s15", "西游记之石猴出世", "西游记", "6-8", ["勇气", "中国神话"], "花果山石头里蹦出石猴，被群猴拜为王"),
    ("s16", "西游记之龙宫借宝", "西游记", "6-8", ["中国神话"], "孙悟空去东海龙宫取如意金箍棒"),
    ("s17", "西游记之大闹天宫", "西游记", "6-8", ["中国神话"], "孙悟空不满弼马温官职，大闹天宫"),
    ("s18", "精卫填海", "山海经", "6-8", ["坚持", "中国神话"], "精卫鸟衔石填海，永不放弃"),
    ("s19", "愚公移山", "中国寓言", "6-8", ["坚持"], "愚公一家决心移走挡路的大山，感动天帝"),
    ("s20", "神笔马良", "中国民间", "6-8", ["善良"], "马良的神笔画什么有什么，他为穷苦人画画"),
]

SYS = "你是儿童睡前故事作家，文风温暖克制，句式简单，适合朗读。"

def prompt_for(sid, title, source, age, tags, brief):
    if age == "3-5":
        words, sentence = "500~750 字", "句子简短（一句不超过 15 字），多叠词和拟声词"
    else:
        words, sentence = "900~1300 字", "可以有少量复合句，情节更完整"
    return f"""请为 {age} 岁孩子创作睡前故事《{title}》。

故事原型（{source}）：{brief}

要求：
1. 正文 {words}，{sentence}；开头安静引入，结尾必须「入睡/安宁」收束（睡前故事铁律）
2. 语言纯净：无暴力恐怖、无死亡描写、无惊吓情节；冲突都要温柔化解
3. 对话用直角引号「」
4. tags 围绕：{ '、'.join(tags) }；可补充 1-2 个
5. new_words：{ '3' if age == '3-5' else '5' } 个适合该年龄段学的生字词（2 字词优先），附组词
6. quiz：2 个理解提问（不出现正文原句即可答）+ 参考答案
7. fact：1 个知识小卡片（从故事里自然引出的自然/生活常识，50 字内）

只输出 JSON：
{{"title":"...","age_group":"{age}","tags":["..."],"text":"正文（段落用\\n\\n分隔）","new_words":[{{"word":"...","hint":"...组词例句..."}}],"quiz":[{{"q":"...","a":"..."}}],"fact":"...","license":"...","source_note":"..."}}"""

def glm(prompt: str) -> str:
    r = requests.post("https://open.bigmodel.cn/api/paas/v4/chat/completions",
                      headers={"Authorization": f"Bearer {os.environ['GLM_API_KEY']}",
                               "Content-Type": "application/json"},
                      json={"model": "glm-4-flash", "temperature": 0.6,
                            "messages": [{"role": "system", "content": SYS},
                                         {"role": "user", "content": prompt}]},
                      timeout=180)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def parse_json(txt: str) -> dict:
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0), strict=False)   # GLM 偶发未转义换行，容忍控制字符

def main():
    only = set(sys.argv[1:])
    index_path = OUT / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"stories": []}
    known = {s["id"] for s in index["stories"]}
    for sid, title, source, age, tags, brief in CATALOG:
        if only and sid not in only:
            continue
        out = OUT / f"{sid}.json"
        if out.exists() and sid in known and not only:
            print(f"[skip] {sid} {title}")
            continue
        print(f"[gen ] {sid} {title} ({age})...", flush=True)
        for attempt in range(3):
            try:
                obj = parse_json(glm(prompt_for(sid, title, source, age, tags, brief)))
                obj.update({"id": sid, "source": source, "chars": len(obj.get("text", ""))})
                obj["text"] = obj["text"].strip()
                out.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
                entry = {"id": sid, "title": obj["title"], "age_group": age,
                         "tags": obj.get("tags", tags), "chars": obj["chars"],
                         "summary": brief}
                index["stories"] = [s for s in index["stories"] if s["id"] != sid] + [entry]
                index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"       ok, {obj['chars']} 字, {len(obj.get('new_words', []))} 生字", flush=True)
                break
            except Exception as e:  # noqa: BLE001
                print(f"       retry {attempt+1}: {str(e)[:100]}", flush=True)
                time.sleep(3 * (attempt + 1))
    print(f"完成，索引共 {len(index['stories'])} 篇")

if __name__ == "__main__":
    main()
