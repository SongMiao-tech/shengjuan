# -*- coding: utf-8 -*-
"""把对话确认的 20 篇故事数据（stories_data_a/b.py）写入 web/stories/*.json + index.json"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from stories_data_a import STORIES_A
from stories_data_b import STORIES_B

OUT = Path(__file__).resolve().parent.parent / "web" / "stories"
OUT.mkdir(parents=True, exist_ok=True)

ALL = STORIES_A + STORIES_B

def main():
    entries = []
    for s in ALL:
        s["chars"] = len(s["text"])
        (OUT / f"{s['id']}.json").write_text(
            json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        entries.append({"id": s["id"], "title": s["title"], "age_group": s["age_group"],
                        "series": s["series"], "episode": s["episode"],
                        "tags": s["tags"], "chars": s["chars"],
                        "summary": s["summary"], "source": s["source"]})
        print(f"{s['id']:4s} {s['title']:12s} {s['age_group']} {s['series']:6s} E{s['episode']} {s['chars']} 字")
    order = {s["id"]: i for i, s in enumerate(ALL)}
    entries.sort(key=lambda e: order[e["id"]])
    index = {"stories": entries,
             "generated_at": time.strftime("%Y-%m-%d %H:%M"),
             "source_policy": "全部改编自公版经典（格林童话/安徒生童话/伊索寓言/西游记/封神演义/中国神话/英国经典童话），贴合原著核心情节、人物性格与结局"}
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(e["chars"] for e in entries)
    print(f"\n共 {len(entries)} 篇，总字数 {total}，平均 {total // len(entries)} 字/篇")
    print(f"预计总时长 ≈ {total / 4.3 / 60:.0f} 分钟")

if __name__ == "__main__":
    main()
