# -*- coding: utf-8 -*-
"""把 oovm/api.ctext.org (CC0) 古籍 JSON 库加工成声卷书库：
   outputs/m2/lib/index.json  —— 书目目录（搜索用）
   outputs/m2/lib/{id}.json   —— 单书全量（title + chapters[{t, p[]}])，p 为简体段落
"""
import json
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / ".tmp_ctext"
OUT = Path(__file__).resolve().parent.parent / "outputs" / "m2" / "lib"
OUT.mkdir(parents=True, exist_ok=True)

def slugify(name: str) -> str:
    # 中文名转安全文件名：直接用原名（CloudBase 托管支持 UTF-8 路径），仅去掉路径风险字符
    return re.sub(r"[\\/:*?\"<>| ]", "", name)

books = []
# 标题级简繁映射（搜索时支持简体关键字）
Simplified_TITLE = {"論語": "论语", "詩經": "诗经", "莊子": "庄子", "楚辭": "楚辞",
                    "西遊記": "西游记", "韓非子": "韩非子", "孫子兵法": "孙子兵法",
                    "山海經": "山海经", "太玄經": "太玄经", "公孫龍子": "公孙龙子",
                    "尉繚子": "尉缭子"}
book_no = 0
for book_dir in sorted(SRC.iterdir()):
    if not book_dir.is_dir() or book_dir.name.startswith("."):
        continue
    data_file = book_dir / "data.json"
    if not data_file.exists():
        continue
    raw = json.loads(data_file.read_text(encoding="utf-8"))
    chapters = []
    total_chars = 0
    for ch in raw:
        if not isinstance(ch, dict):
            continue
        full_title = ch.get("Chapter", "")
        title = full_title.split("|")[-1].strip() or full_title
        paras = ch.get("Simplified") or ch.get("Traditional") or []
        paras = [p.strip() for p in paras if isinstance(p, str) and p.strip()]
        if not paras:
            continue
        chapters.append({"t": title, "p": paras})
        total_chars += sum(len(p) for p in paras)
    if not chapters:
        continue
    book_no += 1
    bid = f"book{book_no:02d}"          # ASCII 文件名：CloudBase 托管对 UTF-8 名返回空体
    out = {"title": book_dir.name, "chapters": chapters}
    (OUT / f"{bid}.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    books.append({"id": bid, "title": book_dir.name,
                  "s": Simplified_TITLE.get(book_dir.name, book_dir.name),
                  "chapters": len(chapters), "chars": total_chars})
    print(f"{book_dir.name:8s} {len(chapters):4d} 章 {total_chars:7d} 字 -> {bid}.json")

index = {"source": "oovm/api.ctext.org (CC0 1.0, ctext.org 公有领域文本)", "books": books}
(OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
print(f"\n共 {len(books)} 部书 -> {OUT}/index.json")
