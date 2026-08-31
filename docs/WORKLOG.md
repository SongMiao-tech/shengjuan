# 声卷项目 · 每日工作日志

> 文件用途：按日记录已完成的任务、工作进度、遇到的问题与解决办法，供复盘与持续维护使用。
> 维护约定：每日收工更新仓库时，须同步检查并补充本文件，确保与实际进度一致。

---

## 2026-08-27（周四）

### 已完成任务

1. **项目方案定稿**：产出《个性化有声读物智能生成项目方案.md》（v2.0 纯 API 版），明确 6 类用户画像、6 个创新功能点、4 大模块、技术选型、M0–M3 里程碑与 8 项风险应对。
2. **本机硬件实测**：确认 i7-13700H + 16GB RAM、无 NVIDIA 独显、无 CUDA；VoxCPM2 本地 CPU 推理 RTF≈18.4，仅适合短片段验证，长文批量不可行。
3. **技术路线转向**：由“本地开源 TTS + LLM API”改为**全云 API、本地零模型部署**，并同步更新方案文档。
4. **M0 四链路全部打通**：
   - 豆包语音合成 2.0：V3 HTTP 单向流式接口、情感控制、语速控制、多音色验证通过。
   - 豆包声音复刻 2.0：网页训练获得音色 `S_7PtM1phd2`，走 `seed-icl-2.0` 合成成功。
   - MiniMax Voice Design：设计“睡前故事姐姐”音色成功，t2a_v2 激活（首次合成收取 $3）。
   - GLM-4-Flash 情感 JSON：分段情绪/角色/重音标注可稳定输出。
5. **M1 一键成品流水线**：`scripts/pipeline.py` 完成 LLM 分析 → 多角色多情绪 TTS → 段间停顿 → ffmpeg 拼接 → BGM 情绪加权选曲 → sidechain ducking + loudnorm；858 字《信号》23/23 段成功，成品 208.6 s。
6. **CloudBase 云托管上线**：后端 `audiobook-api` 部署公网，Flask CORS 头修复，云端端到端验证成功。
7. **M2 前端 v1**：单文件 `outputs/m2/index.html`（后迁到 `shengjuan/web/index.html`）完成，含情绪曲线可视化、音色选择、BGM 开关、云端生成轮询、播放器、分段列表；已发布 CloudBase 静态托管。
8. **功能迭代 v1.2–v1.7**：角色性别自动分配、无引号对话识别、自定义音色双路径（MiniMax 设计 / 豆包克隆）、音色试听按钮。

### 当日进度

- 里程碑：M0 ✅、M1 ✅、M2 核心闭环 ✅。
- 剩余：真 BGM 曲库替换占位曲、演示文档、后续可选功能。

### 问题与解决

| 问题 | 解决方案 |
|---|---|
| 火山引擎旧版 AppID/AccessKey 鉴权 401 | 改用新版控制台 API Key（UUID）+ `X-Api-Resource-Id: seed-tts-2.0` |
| MiniMax t2a_v2 返回 1004 token not match group | 新版 API Key 不需要 GroupId query 参数，去掉后成功 |
| 克隆音色与普通大模型音色 resource id 不同 | `pick_resource()` 按 `S_/`custom` 前缀自动选择 `seed-icl-2.0` |
| Flask 默认无 CORS 头，浏览器跨域失败 | 后端加 `@APP.after_request` 注入 `Access-Control-Allow-Origin/Methods/Headers` |
| `/voices/design` 返回 bytes 导致 jsonify 崩溃 | 音频先 base64 编码为字符串再入 JSON |

---

## 2026-08-28（周五）

### 已完成任务

1. **前端修复 v1.8**：音色试听按钮导致选择高亮丢失，修复事件刷新链路。
2. **BGM 曲库升级 v1.9**：MiniMax Music API 对新用户关闭，改由 `make_bgm_v2.py` 程序化合成八音盒风格情绪曲库，替换占位曲。
3. **混合句拆分修复 v2.0**：针对“叙述+冒号/逗号+台词”混合句，补充 prompt 示例 + 机械拆分后处理 + 无引号短台词保护；本地/云端验证通过。
4. **工程化整理（学链任务清单）**：
   - 创建规范项目 `shengjuan/`，含 PRD.md、README.md、requirements.txt、.gitignore。
   - 本地 SQLite 四表（users/voices/tasks/works）、DAO、模型、初始化脚本。
   - 3 个功能原型页（情绪曲线编辑器/音色库管理/作品历史库）。
   - GitHub 仓库 `SongMiao-tech/shengjuan` 初始化并首次推送。
5. **M2 收尾**：同文本分析缓存、用量监控上线；云托管 MaxNum 由 3 降为 1，避免内存态跨实例不一致。
6. **方言通道 v2.1**：豆包 8 种方言（川/粤/东北/京/沪/河南/天津/陕西）参数链全通，前端方言分组、省点模式 `MinNum=0`；环境因资源点耗尽被隔离一次，充值后恢复。
7. **本地 TXT 导入 & 公版书在线导入**：实现 `web/index.html` 本地 TXT 拖拽导入（UTF-8/GBK 自动识别）；维基文库因上海出口 TLS 超时改浏览器直连；ctext 公版书源接入（search 免 key，fetch 待 key）。
8. **一键多版本输出 v2.2**：正常/慢速/双语/预告片四风格并行生成，云端 `style` 参数链完整，实测四风格全绿。
9. **内置书库落地 v2.3**：基于 GitHub `oovm/api.ctext.org` CC0 数据构建 13 部公版古籍 JSON 书库（西游记全本 100 回），部署到静态托管 `web/lib/`。
10. **长文上限 5000→10000 字**：分块分析（1200 字/块）+ 合并角色分配 + GLM 超时 300s；《西游记》第一回 7002 字实测成功。
11. **「」直角引号台词救援 v2.4**：拆分正则扩展支持「」『』，新增 `_speaker_before()` 救援“名+道：「台词」”型叙述段；16 单元用例 + GLM 端到端验证全过。
12. **GLM 升级尝试与回滚**：glm-5.3-flash/5.2/4.7 因余额/模型名/超时而不可行，回滚到 glm-4-flash；总结“换模型前小样本 probe”原则。
13. **仓库推送 commit e60ce62**：含 25 文件、+1764 行。

### 当日进度

- M2 全部关闭 ✅；M3 三场景（多角色/广播剧/方言）实质完成 3/3 ✅。
- 项目已具备完整产品化 Demo，可对外演示。

### 问题与解决

| 问题 | 解决方案 |
|---|---|
| 试听后音色选择无视觉反馈 | 修复 `onclick` 非自定义分支调 `renderVoices()` |
| 体验版 CloudBase 资源点两天烧光（MinNum=1） | `MinNum=0` 缩容到零，按需拉起；演示前提前预热 |
| 维基文库从上海云托管被墙 | 浏览器直连为主，云端 `/books/diag` 诊断通道备用 |
| ctext `additions` 对象导致 55000000 反序列化错误 | 将 `additions` 序列化为 JSON 字符串再传 |
| 书库 UTF-8 文件名在 CloudBase 静态托管返回空体 | 全部改用 ASCII 文件名（`bookNN.json`） |
| 长文 GLM 单块超时 | 分块 1200 字/块分析，跨块角色声线一致 |
| GLM coding plan key 模型名不认/余额不足/4.7 超时 | 回滚并建立 glm-4-flash → flash-250414 → 4.5-air 降级链 |
| `git push` 走代理时 GCM 弹窗挂起 | `GIT_TERMINAL_PROMPT=0 git -c http.proxy=... push` |

---

## 2026-08-29（周六）

### 已完成任务

1. **账号系统 +「我的音色」上线 v2.5**：
   - 自建 `users` 表 + PBKDF2 密码哈希 + HMAC-SHA256 token（7 天）。
   - `user_voices` 表每用户 1 条覆盖式绑定；新增 `/auth/register`、`/auth/login`、`/me/voice`。
   - 前端甩掉 CloudBase SDK，纯 fetch；CORS 放行 `Authorization` 头；API 端到端 12/12 通过。
2. **上线后补丁**：修复登录弹窗不关闭、沙箱 localStorage 报错、「我的声音」未克隆也显示、删除键失效等 bug。
3. **GLM key 失效应急**：原免费 key 401，切换 coding plan key 并重新部署；生产链路恢复。
4. **睡前故事有声化 MVP**：
   - 方案 `plans/quantum-cascade-tesla.md` 批准。
   - 后端新增 `style=bedtime`（语速-15、停顿 0.8 s、intensity≤0.7、 calm BGM、淡入淡出优化）。
   - 20 篇故事内容按公版经典改编（单篇实测 4:02~5:49），生成 `stories_data_a/b.py` 与 `web/stories/*.json`。
   - `web/story.html` 儿童向夜间播放器：进度拖拽、倍速、断点续听、定时停止、MediaSession。
   - 预渲染 20/20，静态托管部署。
5. **GLM 降级链**：`_glm_chat()` 三模型轮换（glm-4-flash → flash-250414 → 4.5-air）上线并验证。
6. **双端互联**：工作台 `index.html` 加“🌙 睡前故事”入口；`story.html` 家长音色代读直接复用同域“我的声音”。
7. **默认音色切换**：先切 MiniMax“睡前故事姐姐”，发现长句断句不稳后回退豆包女声樱桃丸子，并重渲全部 20 篇。
8. **功能移除 + 响应式优化**：删除 `story.html` 的“跟读识字”“生字卡片”；`index.html` 增加 900px/640px 断点，手机端无需手动缩放。
9. **熄屏播放修复**：通过 `userPaused` 标志、静音 wav 循环、visibilitychange、WeixinJSBridgeReady、pagehide、MediaSession 多管齐下，解决微信内置浏览器熄屏约 1 分钟停止的问题。
10. **自传读本 + 账号级书架/历史**：
    - PG migration `20260829224500_create_user_books_and_history.sql`。
    - 后端 `/me/books` CRUD、`/me/history`、任务完成后自动写入历史。
    - 前端 `story.html` 书架/历史 tabs、.txt 上传（UTF-8→GBK 回落）、超万字提示拆分。
    - API 隔离 10/10 验证通过。
11. **8.28 产物补齐进仓库 commit 2380fc6**：补齐 `scripts/probes/` 等探测脚本。

### 当日进度

- 睡前故事应用从 0 到完整闭环并部署；账号系统与书架/历史功能上线。
- 当前仓库最新 commit：`2380fc6`（main）。

### 问题与解决

| 问题 | 解决方案 |
|---|---|
| CloudBase Auth 不支持用户名密码自助注册 | 自建 users 表 + PBKDF2 + HMAC token |
| 前端插在中段的启动代码引用未初始化的 `const $/API` | 将 `$` 与 `API` 提到 script 最顶部 |
| 沙箱 iframe 无 `allow-same-origin` 导致 localStorage 报错 | 封装 `store` 对象，探测可用性后降级内存对象 |
| “我的音色”删除按钮点击无反应 | 复用 class `voice-copy-btn` 导致全局选择器覆盖 onclick；改独立 class 并收紧选择器作用域 |
| `/tasks/<id>` 默认不返回 audio_base64 | 轮询/拉取时显式加 `?audio=1` |
| 静态托管 CDN 缓存导致更新不生效 | 验证时用 `?v=N` cache-bust 或等待 update 生效 |
| `s*.json` 误匹配 `s01.seg.json` | glob 改为 `s??.json` |
| MiniMax 1004 token not match group | 新版 key 与 GroupId 不匹配，去掉 `?GroupId=` 拼接 |
| MiniMax“睡前故事姐姐”长句念不全 | 回退旁白到豆包樱桃丸子并全部重渲 |
| 微信内置浏览器熄屏约 1 分钟停止 | 多维度 keep-alive：userPaused 标志、静音循环、visibilitychange、WeixinJSBridgeReady、MediaSession、pagehide 进度保存 |
| `EnvParams` 传占位值会把真实 key 全部冲掉 | 每次 updateConfig 必须携带完整 EnvParams，禁止只传部分 |

---

## 2026-08-31（周一）

### 已完成任务

1. **公版书列表移动端溢出修复**（commit 96ff326）：`导入公版书` 章节列表的字数标签原用 `float: right`，长标题换行时溢出卡片边框、长标题折成两行；`.book-hit` 改 flex 基线布局——标题单行省略号截断、字数 `flex-shrink: 0` 贴右完整显示、搜索结果摘要行不受影响。390px 宽度实测通过，已部署线上。
2. **「多版本」按钮四列等宽重排**（commit bd268bf）：原 flex-wrap 在 244px 面板里放不下四个胶囊，「预告片」掉到第二行；改 4 列 grid（标签独占一行、chip 等宽居中）。几何断言：1440px 下 4×56px 同行落在 300px 面板内、390px 下 4×86px 同行无溢出。

### 学链任务清单对照（08-31）

| 清单项 | 状态 | 说明 |
|---|---|---|
| P0 功能开发、版本可运行 | ✅（存量满足） | 可运行版本 08-30 已具备（阶段 0-3 全上线）；今日修复公版书列表溢出，属初验体验缺陷 |
| 测试数据 + 功能测试 | ✅ | 公版书库 13 部 + 测试账号收听记录（listen_logs 3 条）为现成测试数据；上午完成布局真实验证（390px 几何断言） |
| 交互体验优化、UI 美化 | ✅ | 公版书列表溢出修复 + 多版本按钮四列等宽重排 |
| 游戏类 HUD / 数值调试 | — | 不适用（声卷非游戏项目） |
| 编写每日工作日志 | ✅ | 本条目即当日日志 |

### 遗留/建议

- 初验前建议再过一遍手机端全流程（登录 → 导入公版书 → 生成 → 播放），确认装饰素材与布局改动无回归。
- 阶段四（商业化与合规）按方案仍未启动。

---

## 2026-08-30（周日）

### 已完成任务

1. **学链任务清单第 4、5 条落地**（commit 4262d61 / a18db2c）：
   - `docs/WORKLOG.md`：补全 08-27 ~ 08-29 三天工作日志。
   - `docs/PROJECT_CHARTER.md`：项目宪章 + AI vibe coding 常见错误与规避方案（18 条）。
2. **睡前故事方案核查 + 教学功能规划移除**：核查 `plans/quantum-cascade-tesla.md` 阶段一/二完成情况并标注状态；移除跟读识字/生字本/知识点卡片全部教学功能规划（§3.4 整节、vocab_cards 表、F12/F13/F14、相关接口与文件描述）。
3. **「2.1 家长录音开场结尾」功能上线**（`web/story.html`，已部署静态托管）：
   - 音色来源固定「我的音色」：编辑页输入开场/结束语（各 ≤100 字）→ `/tasks`（bedtime 语感、无 BGM）实时合成 → base64 存本地。
   - 编辑页：试听、重录（文本修改后自动提示"需重录"）、重命名、删除、保存；未登录/无音色/未合成/合成失败均有明确提示。
   - 播放链：总开关（默认关）+ 开场/结尾细分开关，本地持久化；开启后按「开场语 → 故事正文 → 结尾语」顺序播放，缺失片段静默跳过；续听（>30s）不播开场；片段中暂停后恢复继续播该片段，片段播完处于暂停态则等用户按播放再接正文（chainPending）。
   - 定时停止渐弱对片段同样生效（activeMedia 统一寻址），片段结束后不再接续（clipChainStopped）。
   - 进度保存只记故事正文（片段播放中不写故事进度）；进度条/倍速/播放按钮/MediaSession 统一切换到当前媒体。

### 已完成任务（下午追加）

4. **阶段三「家长端 + 工程完善」全部上线**：
   - **收听报告**：PG 新表 `user_listen_logs`（migration 20260830100000）；后端 `POST/GET /me/listen`（uid 隔离，401/入库/查询实测通过）；前端按秒追踪正文播放（片段不计入）、30s 增量上报、听完/翻页/离页各补一次上报（pagehide 用 keepalive）。家长中心弹窗：近 7 天收听柱状图、总时长/段数、听完率、最爱标签、最常听故事；未登录降级本地数据并提示。
   - **时长控制**：每日上限（不限/15/30/45/60 分钟，默认 30），达到上限轻声渐停 + 播放键拦截 + 打开故事被门禁拦下；就寝时段（默认 20:00-21:00，支持跨零点），时段外打开故事需家长确认"仍要播放"；连续 20 分钟休息提醒。设置持久化 `sqParentCtrl`。
   - **内容安全过滤**：读本上传/有声化前敏感词表过滤（自伤/色情/毒品/赌博/暴力/邪教等 28 词），命中阻断并提示；GLM 改写与输出审核层留作生产化。
   - **离线下载**：Cache API（story-v1）——播放页「⤓ 离线」保存音频+正文，卡片"已离线"角标，断网时列表/正文/音频自动回落缓存，家长中心显示缓存篇数 + 一键清理。
   - **音箱投放引导**：系统级投放弹窗（蓝牙/AirPlay/安卓投屏/微信内指引），播放页与家长中心双入口。
   - 部署：后端 audiobook-api-042（EnvParams 完整保留）+ 前端 story.html 均已上线验证。
5. **20 张故事封面替换 emoji**（commit 09233a4）：AI 生图 2048px PNG → 512px WebP（保留透明通道，41MB→724KB）入库 `web/covers/s01-s20.webp`；story.html 卡片/播放页大封面/锁屏 MediaSession 三处改为读 `covers/{id}.webp`，加载失败回退 emoji，自传读本仍用 emoji；卡片图 lazy loading。本地+线上正式域名均验证 20/20 无 broken；确认 CloudBase 测试域名首次访问会弹"风险提醒"中间页（点"确定访问"放行，与代码无关）。
6. **列表页顶部工具栏重排**（commit 82daf16）：三行混乱按钮 → 两级语义分组（视图切换+右推家长工具 / 年龄筛选），新 `.tb` 统一按钮规格（36px/30px sm），新增「全部故事」主视图 tab，登录态按按钮级隐藏不再整行跳动。
7. **工作台 AI 装饰素材叠加**（commit 93a3e63 + 8cdf9f0）：按提示词生成琥珀光晕/音波绸带/纸页墨点 3 张素材（1.8MB PNG→94KB WebP）挂 `web/deco/`；header 右上光晕、main 标题区波带、aside 面板纸页；multiply 混合 + mask 羽化。修复右侧叠加冲突：波带 mask 改左锚点右渐隐消除接缝、光晕收进 header 条。
8. **睡前故事夜间装饰素材叠加**（commit 3c72c13 + a99dd4f）：月晕/星尘/夜云 3 张素材（1.3MB→60KB WebP）；列表右上月亮、播放页星尘带、列表底部夜云；**暗底用 screen 混合**（multiply 会吃掉发光素材）。夜云初版太暗不明显，透明度拉满 + 高度加至 480px 后达标。
9. **就寝门禁升级：家长密码解锁**（commit c63df34 + 5eb2860）：就寝时段外打开故事 → 密码弹窗走 `/auth/login` 真实校验家长账号密码，正确才进播放页；未登录引导登录。修复误判 bug：工作台 sqAuth 形状是 `{token, name}` 而 story.html 读 `username`，导致已登录用户被判未登录——4 处读取改为 `name || username` 双字段兼容。

### 当日进度

- 阶段 2、阶段 3 全部完成；封面全面替换为 AI 插画；工作台与睡前故事双端各叠加一组 AI 装饰素材；就寝门禁升级为密码验证。方案文件同步更新。

### 问题与解决

| 问题 | 解决方案 |
|---|---|
| 本地验证时故事"神秘重启"到 0s | 定位为本地 `python http.server` 不支持 Range 请求，seek 触发媒体错误后被熄屏保活自动恢复机制从 0 续播——生产 CDN 支持 Range，不受影响 |
| 片段播完时用户处于暂停态会强制开播正文 | 新增 chainPending 状态：等用户按播放再接正文 |
| 保存时文本已清空但音频残留 | 保存时文本为空则一并失效音频 |

### 测试遗留

- playwright-cli eval 的 CLI 调用延迟（1~2s/次）会让"采样断言"错过 4~7 秒的片段窗口——验证短时序必须把点击与采样放进同一个 eval；且 `$` 会被 bash 双引号插值，eval 代码里避免用 `$()`。

---

## 待办/下一步

- [ ] Gitee 镜像仓库（需用户提供 Gitee 账号）。
- [ ] 火山控制台开通训练服务 + 扩展音色资源授权。
- [ ] 正式演示文档 / 录屏素材。
6. **工作台 AI 装饰素材叠加**（commit 93a3e63）：用户按 A 组提示词生成 3 张素材（琥珀光晕/音波绸带/纸页墨点，1920px PNG 共 1.8MB）→ WebP 压缩（94KB）入库 `web/deco/`；index.html 三处挂载——header 右上光晕、main 标题区波带、aside 面板纸页，统一 multiply 混合 + radial/linear mask 羽化 + pointer-events:none，正文 `> *:not(.deco)` 提升 z-index；900px 断点收紧透明度与尺寸。修掉装饰负偏移导致的移动端 70px 横向溢出（负偏移改贴边+mask 羽化）。
7. **睡前故事夜间装饰素材叠加**（commit 3c72c13）：按夜间主题提示词生成月晕/星尘/夜云 3 张素材（1.3MB PNG→60KB WebP）→ `web/deco/`；story.html 挂载——列表右上月亮、播放页标题区星尘带、列表底部夜云；暗底用 **screen 混合**（区别于工作台的 multiply）+ mask 羽化 + 正文 z-index 提升；480px 断点收紧。线上 3 素材 200 + 代码 9 处命中。
10. **工作台「多版本」按钮四列等宽重排**（commit 后推）：原 flex-wrap 在 244px 面板里放不下，预告片掉到第二行；改 4 列 grid（标签独占一行、chip 等宽居中）。几何断言：1440px 下 4×56px 同行落在 300px 面板内、390px 下 4×86px 同行无溢出。
11. **拟声词误分类修复**（commit 后推）：GLM 偶发把纯拟声段（轰隆隆/哗啦啦）按"无引号对话"规则判成角色台词。双层修复——PROMPT 增加拟声词豁免规则（拟声词开头的对话仍归角色）；`assign_speakers` 增加确定性兜底：去标点后全由拟声字（约 60 字集合，不含叹词）构成的段强制归旁白。21 组单元用例全过，线上真实任务验证：拟声段=旁白、对话=小猴 ✓。后端 audiobook-api 重新部署。
