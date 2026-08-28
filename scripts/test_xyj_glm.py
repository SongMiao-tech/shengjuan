# -*- coding: utf-8 -*-
"""真实 GLM 端到端测试：西游记「」直角引号节选 -> analyze -> role 归属检查"""
import sys, os, json, re

WS = r"C:\Users\37584\.workbuddy\2026-08-27-09-34-01"
sys.path.insert(0, os.path.join(WS, "cloudrun", "audiobook-api"))

# 从 .env 读 key（不打印）
env = {}
for line in open(os.path.join(WS, ".env"), encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
os.environ.setdefault("GLM_API_KEY", env.get("GLM_API_KEY", ""))

from app import analyze  # noqa: E402

text = open(os.path.join(WS, "outputs", "m2", "xyj_corner_test.txt"), encoding="utf-8").read()
print(f"输入 {len(text)} 字，调用 GLM 分析中...\n")
segs = analyze(text)

# 保存结果供检查
out_path = os.path.join(WS, "outputs", "m2", "xyj_corner_result.json")
json.dump(segs, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

roles = {}
for s in segs:
    roles.setdefault(s["role"], 0)
    roles[s["role"]] += 1
print(f"共 {len(segs)} 段，角色分布: {roles}\n")

# 检查1: 不应有 unknown/空角色
bad_role = [s for s in segs if s["role"] in ("unknown", "")]
# 检查2: 引号开头且带说话动词上下文的段，不应是旁白（抽查打印）
quote_as_narr = [s for s in segs if s["role"] == "旁白" and s["text"].startswith("「") and len(s["text"]) > 6]

print("== 台词段抽样（前12条非旁白）==")
n = 0
for s in segs:
    if s["role"] != "旁白":
        print(f"  [{s['role']}|{s['gender']}] {s['text'][:42]}")
        n += 1
        if n >= 12:
            break

print("\n== 旁白段抽样（前8条）==")
n = 0
for s in segs:
    if s["role"] == "旁白":
        print(f"  [旁白] {s['text'][:42]}")
        n += 1
        if n >= 8:
            break

print(f"\n异常角色段: {len(bad_role)}；以「开头却归旁白的长段: {len(quote_as_narr)}")
if quote_as_narr:
    for s in quote_as_narr[:5]:
        print("  疑似漏判:", s["text"][:50])
