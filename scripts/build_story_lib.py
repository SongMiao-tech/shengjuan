# -*- coding: utf-8 -*-
"""睡前故事内容生成（v2 公版改编版，分步生成：正文→元数据）：
全部改编自公版经典，贴合原著核心情节/人物性格/结局，不魔改；长篇分集。
输出 shengjuan/web/stories/{story_id}.json + stories/index.json
用法: python scripts/build_story_lib.py
      python scripts/build_story_lib.py s01 s02   # 只生成指定 ID"""
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

# 字段: (id, 标题, 故事架, 系列, 集数, 来源[原著/作者], 情节要求)
CATALOG = [
    ("s01", "龟兔赛跑", "3-5", "单篇", 0, "伊索寓言《龟兔赛跑》/伊索",
     "兔子嘲笑乌龟慢，两人赛跑；兔子半路睡大觉，乌龟坚持爬到终点获胜。忠实原著：兔子的骄傲、乌龟的不放弃、兔子醒来追悔莫及。结尾：兔子向乌龟道贺，明白虚心与坚持的道理，森林归于宁静"),
    ("s02", "狮子和老鼠", "3-5", "单篇", 0, "伊索寓言《狮子和报恩的老鼠》/伊索",
     "狮子放过小老鼠；后来狮子被猎人网住，老鼠咬破网救了狮子。忠实原著：狮子起初的不屑、老鼠的报恩、网中呼救与撕网相救。结尾：狮子道谢，两兽成为朋友，草原归于安宁"),
    ("s03", "北风和太阳", "3-5", "单篇", 0, "伊索寓言《北风和太阳》/伊索",
     "北风和太阳比赛谁能让旅人脱下外套；北风越吹旅人裹越紧，太阳温暖照耀旅人自己脱下。忠实原著寓意：温和胜于强逼。结尾：太阳微笑，旅人哼着歌走远，天空安宁"),
    ("s04", "蚂蚁和蚱蜢", "3-5", "单篇", 0, "伊索寓言《蚂蚁和蚱蜢》/伊索",
     "夏天蚂蚁忙着储粮，蚱蜢只顾唱歌；冬天蚱蜢挨饿，蚂蚁分它粮食并教它早早准备。忠实原著：勤劳与懒惰的对比；改编结尾温和化——蚂蚁分享粮食，蚱蜢学会勤劳，来年两只一起储粮，洞穴里安稳过冬"),
    ("s05", "狼和七只小羊", "3-5", "单篇", 0, "格林童话《狼和七只小羊》/格林兄弟",
     "羊妈妈出门叮嘱小羊提防大灰狼（认声音看爪子）；狼骗开门吞下六只小羊；羊妈妈回来剪开狼肚皮救出小羊，缝进石头；狼喝水坠井。忠实原著情节与结局。结尾：小羊们平安，狼再不能作恶，羊家安稳入睡"),
    ("s06", "青蛙王子", "3-5", "单篇", 0, "格林童话《青蛙王子》/格林兄弟",
     "小公主的金球掉进井里，青蛙帮她捡回，要求公主做它的好朋友；公主食言，国王教导守诺；公主与青蛙同桌吃饭，青蛙变回王子。忠实原著，暴力细节温和化。结尾：王子与公主成为好朋友，城堡烛光轻轻熄灭"),
    ("s07", "丑小鸭", "3-5", "单篇", 0, "安徒生童话《丑小鸭》/安徒生",
     "丑小鸭因长得与众不同被排挤，离开家四处流浪度过寒冬；春天它长成美丽的天鹅被大家赞美。忠实原著情节线与结局。结尾：天鹅在湖面照见自己，安然入睡"),
    ("s08", "三只小猪", "3-5", "单篇", 0, "英国经典童话《三只小猪》（公版）",
     "三只小猪分别盖草屋、木屋、砖屋；大灰狼吹倒草屋木屋，两只小猪逃到砖屋；狼从烟囱掉进热水锅逃走。忠实经典情节；温和化：狼烫伤后逃进森林再不敢来。结尾：三只小猪在结实的砖屋里安心睡觉"),
    ("s09", "拇指姑娘", "3-5", "单篇", 0, "安徒生童话《拇指姑娘》/安徒生",
     "拇指般小的姑娘从郁金香里出生，被癞蛤蟆抢走、金龟子丢弃；冬日受田鼠收留，救了冻僵的燕子；春天燕子带她飞到花之国遇见花王子。忠实原著主线与幸福结局。结尾：拇指姑娘在花瓣里安然入睡"),
    ("s10", "金发姑娘和三只熊", "3-5", "单篇", 0, "英国经典童话《金发姑娘和三只熊》（公版）",
     "金发姑娘闯进熊屋，尝了三碗粥、坐坏小椅子、睡了小熊的床；三只熊回家发现她，她惊醒逃跑。忠实经典情节；温和化结尾——金发姑娘后来登门道歉并帮忙修好小椅子，熊一家原谅了她，森林小屋恢复安宁"),
    ("s11", "石猴出世", "6-8", "大闹天宫", 1, "《西游记》第一回/吴承恩",
     "花果山山顶仙石迸裂石猴出世；与群猴玩耍，勇敢跳进瀑布发现水帘洞，被拜为美猴王。忠实原著：仙石感天地精华而裂、石猴目运金光、瀑布探险抢先进洞、群猴兑现承诺拜王。结尾：猴群在水帘洞安家，花果山夜晚宁静"),
    ("s12", "拜师学艺", "6-8", "大闹天宫", 2, "《西游记》第一至二回/吴承恩",
     "美猴王为求长生漂洋过海多年，找到灵台方寸山斜月三星洞菩提祖师，得名孙悟空；学言语礼节洒扫应对，后学七十二般变化与筋斗云；因变松树卖弄被逐出师门。忠实原著：祖师敲头三下的哑谜、半夜传艺、不许提师门名号。结尾：悟空驾筋斗云回到花果山与猴群重逢，山间明月高悬"),
    ("s13", "龙宫借宝", "6-8", "大闹天宫", 3, "《西游记》第三回/吴承恩",
     "悟空闯东海龙宫向龙王求兵器，试遍刀枪剑戟都不趁手，最后拿走定海神针如意金箍棒（重一万三千五百斤，可大可小）；又向其他龙王讨了披挂；后被地府勾魂，大闹森罗殿勾掉生死簿猴属名字。忠实原著。结尾：悟空回花果山，龙王与阎王上天庭告状为下一集埋线；花果山下海浪轻拍礁石"),
    ("s14", "官封弼马温", "6-8", "大闹天宫", 4, "《西游记》第三至四回/吴承恩",
     "太白金星招安，悟空上天做弼马温；得知官小是哄骗后打出南天门回花果山，竖起齐天大圣旗；天兵征讨失败，天庭再招安封齐天大圣管蟠桃园。忠实原著：弼马温官职真相、巨灵神哪吒败阵、金星二次招安。结尾：悟空接管蟠桃园，仙桃满园香，他暂时安稳下来"),
    ("s15", "偷桃盗丹", "6-8", "大闹天宫", 5, "《西游记》第五回/吴承恩",
     "悟空看管蟠桃园偷吃大仙桃；王母蟠桃会未请他，他变赤脚大仙混进瑶池，喝光仙酒吃光珍馐；醉闯兜率宫偷吃太上老君五壶金丹；怕罪逃回花果山。忠实原著：七仙女被定住、玉帝震怒。结尾：悟空与群猴分享仙酒，花果山月色温柔"),
    ("s16", "大战天兵", "6-8", "大闹天宫", 6, "《西游记》第五至七回/吴承恩",
     "玉帝派十万天兵布天罗地网；悟空战败九曜星、哪吒等；观音举荐二郎神，两人大战三百回合各显神通变法相斗（庙宇旗杆藏尾巴破绽被识）；老君暗掷金刚琢打中悟空被擒；刀砍斧剁雷劈火烧无损，投入八卦炉炼四十九天炼出火眼金睛。忠实原著。结尾温和收束：炉火渐熄，悟空双目如金灯静静立在炉中——好戏还在后头"),
    ("s17", "五行山下", "6-8", "大闹天宫", 7, "《西游记》第七回、第十四回/吴承恩",
     "悟空打出八卦炉大闹凌霄殿，与如来佛祖打赌：翻出五指掌心就赢；一个筋斗十万八千里却翻不出佛掌，被五指化作五行山压住；五百年后观音点化，唐僧路经揭起金字压帖救出悟空；悟空拜唐僧为师得名行者，踏上西天路。忠实原著与结局（被唐僧救出五行山为止）。结尾：师徒二人迎着朝阳西行，山间钟声悠悠——大闹天宫的故事讲完了，孙悟空的故事才刚刚开始"),
    ("s18", "哪吒闹海", "6-8", "单篇", 0, "《封神演义》第十二至十四回/许仲琳（改编）",
     "陈塘关李靖之子哪吒出生为肉球，太乙真人收徒赐乾坤圈混天绫；七岁时在东海边洗澡，混天绫搅动龙宫，夜叉来问罪被打死，龙王三太子敖丙兴师问罪被哪吒打杀；四海龙王水淹陈塘关要李靖交人，哪吒为不连累百姓父母削骨还父削肉还母；太乙真人以莲花荷叶为他重塑身躯复活。改编口径：保留核心冲突与舍身取义，结尾温和化——哪吒重生后与龙王讲和，立誓守护陈塘关百姓。结尾：风浪平息，哪吒脚踏风火轮巡视海面，月色如银"),
    ("s19", "后羿射日", "6-8", "单篇", 0, "中国神话《后羿射日》/《山海经》《淮南子》记载",
     "远古天帝的十个太阳儿子轮流值日，某天一起出现在天上，大地焦渴庄稼枯死怪兽出没；神射手后羿受命拯救人间，张弓搭箭射落九个太阳，留下一个温暖人间；又除掉为祸的怪兽。忠实神话记载（射九留一、万民欢庆）。结尾：最后一个太阳每天按时升起落下，人间四季分明，夜晚村庄安然入梦"),
    ("s20", "皇帝的新装", "6-8", "单篇", 0, "安徒生童话《皇帝的新装》/安徒生",
     "爱新装的皇帝被两个骗子裁缝欺骗，说愚蠢的人看不见这布料；大臣和皇帝谁都不敢说自己看不见，举行游行大典；一个小孩子喊出「他什么衣服也没穿呀」，百姓传开，皇帝硬撑着走完游行。忠实原著情节与结局；改编结尾温和化——皇帝回到宫里又羞又恼，但想到那孩子的诚实，决定以后做一位听真话的好皇帝。结尾：皇宫安静下来，夜色温柔"),
]

SYS = "你是儿童睡前故事作家，擅长把经典童话、神话与名著改编成适合朗读的睡前故事。"


def prompt_for(item):
    sid, title, age, series, ep, source, brief = item
    if age == "3-5":
        words, sentence = "1200~1350 字", "句子简短（一句不超过 15 字），多叠词和拟声词"
        kid = "3~5 岁"
    else:
        words, sentence = "1250~1350 字", "可以有少量复合句，情节要完整连贯"
        kid = "6~8 岁"
    series_note = ("这是《" + series + "》系列第 " + str(ep) + " 集，与前后的集连续讲述；"
                   "本集只讲本集情节，结尾为下一集留一点悬念但今晚也能安然入睡。") if series != "单篇" else ""
    head = ("把经典作品改编成 " + kid + " 孩子的睡前故事《" + title + "》"
            + ("（《" + series + "》第 " + str(ep) + " 集）" if series != "单篇" else "（单篇）"))
    return head + """

改编来源：""" + source + """

必须遵守（最重要的规则）：
1. **忠实改编原著**：核心情节、人物性格、结局都要贴合原著，不得凭空原创杜撰，不得魔改设定；只做语言适龄化和细节扩写（把原文简练处扩成画面与对话）
2. 正文 """ + words + """，""" + sentence + """；**这是硬性要求，不足 1150 字视为不合格**
3. 睡前铁律：开头安静引入；结尾必须安宁收束（安稳入睡/平静收场），惊险情节都放在中段
4. 语言纯净：无血腥恐怖描写（原著的冲突用孩子能接受的方式讲）
5. 对话用直角引号「」
""" + series_note + """
直接输出正文，不要输出任何其他内容（不要标题、不要 JSON、不要解释）：

正文："""


META_PROMPT = """以下是一篇 {age} 岁孩子的睡前故事《{title}》（改编自 {source}）。

请基于正文输出元数据 JSON（只输出 JSON，不要其他内容）：
{{"tags":["...","..."],
  "new_words":[{{"word":"...","hint":"组词例句"}}],
  "quiz":[{{"q":"...","a":"..."}}],
  "fact":"与故事相关的知识小卡片，50字内",
  "summary":"一句话摘要，20字内"}}

要求：
- tags：2~3 个主题词（勇气/友谊/坚持/诚实/分享/中国神话 等）
- new_words：{nw} 个适合 {age} 岁孩子学习的**名词或动词**生字词（不要拟声词/叠词），各附组词例句
- quiz：2 个理解提问（考情节与寓意）+ 参考答案

正文：
{body}"""


def glm(prompt: str, timeout: int = 240) -> str:
    r = requests.post("https://open.bigmodel.cn/api/paas/v4/chat/completions",
                      headers={"Authorization": f"Bearer {os.environ['GLM_API_KEY']}",
                               "Content-Type": "application/json"},
                      json={"model": "glm-4-flash", "temperature": 0.5,
                            "messages": [{"role": "system", "content": SYS},
                                         {"role": "user", "content": prompt}]},
                      timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def glm_text(prompt: str, min_len: int = 1100, attempts: int = 4) -> str:
    """正文生成：纯文本输出，字数不足自动重试"""
    last = ""
    for a in range(attempts):
        try:
            txt = glm(prompt).strip()
            txt = re.sub(r"^(正文：|```[a-z]*\n?|<story>)", "", txt, flags=re.S)
            txt = re.sub(r"(```|</story>)$", "", txt).strip()
            last = txt
            if len(txt) >= min_len:
                return txt
            print(f"       short({len(txt)}), retry {a + 1}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"       glm err: {str(e)[:80]}", flush=True)
            time.sleep(3)
    return last if len(last) >= 850 else ""


def parse_json(txt: str) -> dict:
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0), strict=False)


def gen_meta(item, body: str) -> dict:
    sid, title, age, series, ep, source, brief = item
    nw = 3 if age == "3-5" else 5
    prompt = META_PROMPT.replace("{age}", age).replace("{title}", title) \
                        .replace("{source}", source).replace("{nw}", str(nw)) \
                        .replace("{body}", body[:4000])
    for a in range(3):
        try:
            return parse_json(glm(prompt, timeout=120))
        except Exception as e:  # noqa: BLE001
            print(f"       meta retry {a + 1}: {str(e)[:70]}", flush=True)
            time.sleep(2)
    return {"tags": [], "new_words": [], "quiz": [], "fact": "", "summary": brief[:20]}


def main():
    only = {a for a in sys.argv[1:] if not a.startswith("--")}
    index_path = OUT / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"stories": []}
    for item in CATALOG:
        sid, title, age, series, ep, source, brief = item
        if only and sid not in only:
            continue
        out = OUT / f"{sid}.json"
        print(f"[gen ] {sid} {title} ({age}{' ' + series if series != '单篇' else ''} E{ep})...", flush=True)
        ok = False
        for attempt in range(2):
            try:
                body = glm_text(prompt_for(item))
                if not body:
                    raise ValueError("正文生成失败")
                meta = gen_meta(item, body)
                text = re.sub(r"\n{3,}", "\n\n", body)
                chars = len(text)
                obj = {"id": sid, "title": title, "age_group": age,
                       "series": series, "episode": ep if series != "单篇" else 0,
                       "chars": chars, "text": text,
                       "license": "public_domain_adaptation", "source": source,
                       "tags": meta.get("tags", []),
                       "new_words": meta.get("new_words", []),
                       "quiz": meta.get("quiz", []),
                       "fact": meta.get("fact", ""),
                       "summary": meta.get("summary", brief[:20])}
                out.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
                entry = {"id": sid, "title": title, "age_group": age,
                         "series": series, "episode": obj["episode"],
                         "tags": obj["tags"], "chars": chars,
                         "summary": obj["summary"], "source": source}
                index["stories"] = [x for x in index["stories"] if x["id"] != sid] + [entry]
                index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"       ok, {chars} 字, {len(obj['new_words'])} 生字", flush=True)
                ok = True
                break
            except Exception as e:  # noqa: BLE001
                print(f"       retry {attempt + 1}: {str(e)[:100]}", flush=True)
                time.sleep(3)
        if not ok:
            print(f"       FAILED: {sid}", flush=True)
    order = {c[0]: i for i, c in enumerate(CATALOG)}
    index["stories"].sort(key=lambda s: order.get(s["id"], 99))
    index["generated_at"] = time.strftime("%Y-%m-%d %H:%M")
    index["source_policy"] = "全部改编自公版经典（格林童话/安徒生童话/伊索寓言/西游记/中国神话等），贴合原著情节与结局"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    n_ok = sum(1 for f in OUT.glob("s*.json") if ".seg" not in f.name)
    print(f"完成，索引共 {len(index['stories'])} 篇，正文文件 {n_ok} 个")


if __name__ == "__main__":
    main()
