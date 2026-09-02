# 声卷 · 有声读物工作台 + 睡前故事播放器

> 「有声读物工作台 + 睡前故事播放器」双核心产品，聚焦亲子家庭。
> 生产端：上传文本 → AI 标注段落情绪/角色 → 多角色多情绪语音合成 → BGM 智能匹配 → 可增量调整的一键成品；
> 消费端：公版故事开箱即听 + 家长自制内容收听，配套迷你播放栏与家长中心管控。
> 两端经「书架」打通：工作台成品一键保存 → 睡前故事页同步收听，进度跨页跨设备一致。
> 全云 API 架构（豆包语音合成 2.0 / MiniMax / GLM-4-Flash / CloudBase），本地零模型部署。

## 产品定位

- **有声读物工作台**（面向家长）：把公版书或自选读本，快速做成有情绪、多角色、可用爸妈声音讲的有声书
- **睡前故事播放器**（面向孩子，特色功能）：经典故事开箱即听 + 专属自制故事收听 + 家长管控，是产品优先级最高、差异化最集中的界面
- **组合关系**：工作台是厨房，睡前故事是餐桌——成品经书架一键流转，生产与消费在一个产品内闭环

详见 [PRD.md](PRD.md)。

## 文档

- [PRD.md](PRD.md) — 产品需求文档 v2.0（定位调整版：双核心 + 亲子家庭聚焦）
- [docs/技术方案.md](docs/技术方案.md) — 完整技术方案（v2.0 纯 API 版）
- [docs/WORKLOG.md](docs/WORKLOG.md) — 每日工作日志（持续更新）
- [docs/PROJECT_CHARTER.md](docs/PROJECT_CHARTER.md) — 项目宪章与 AI vibe coding 开发经验

## 目录结构

```
shengjuan/
├── PRD.md                  产品需求文档（v2.0 双核心定位）
├── README.md               本文件
├── db/                     旧版本地 SQLite（未部署，仅开发参考）
│   ├── schema.sql          建表脚本（users/voices/tasks/works）
│   ├── seed.sql            测试数据
│   ├── init_db.py          初始化脚本（幂等）
│   └── shengjuan.db        数据库文件（init 后生成）
├── app/                    数据访问层
│   ├── models.py           实体类（User/Voice/Task/Work）
│   └── dao.py              CRUD 封装（python -m app.dao 可自检）
├── cloudbase/migrations/   CloudBase PG 建表迁移（users / user_voices / user_listen_logs / user_audiobooks，版本化）
├── cloudrun/               CloudBase 云托管服务（后端 API，容器部署）
│   ├── app.py              流水线 + 账号系统 + 书架（/tasks /voices/* /auth/* /me/voices /me/audiobooks）
│   ├── Dockerfile          python3.11-slim + ffmpeg
│   └── assets/bgm/         情绪曲库
├── web/                    前端
│   ├── index.html          有声读物工作台（已部署公网）
│   ├── story.html          睡前故事播放器（儿童播放器 + 迷你播放栏 + 家长中心）
│   ├── lib/                内置公版书库（13 部古籍，CC0，简体，~3.5MB）
│   └── prototypes/         功能原型页 ×3
├── assets/bgm/             情绪曲库（本地副本，程序化合成，make_bgm_v2.py 可重生）
├── scripts/                工具脚本（合成/分析/流水线/音色/书库构建/测试）
└── docs/                   技术方案
```

## 快速开始

```bash
# 1. 环境（Python 3.11+，依赖极少：requests / flask / numpy）
pip install requests flask numpy

# 2. 初始化数据库（建表 + 测试数据，幂等，旧版本地 SQLite）
cd shengjuan
python db/init_db.py          # 或 python -m app.dao

# 3. 配置密钥：复制 .env.example 为 .env 填入
#    VOLC_API_KEY / GLM_API_KEY / MINIMAX_API_KEY

# 4. 一键生成（本地 CLI）
python scripts/pipeline.py --input story.txt -o final.mp3 --narrator S_xxxxx

# 5. 前端：直接打开 web/index.html（工作台）与 web/story.html（睡前故事），或访问已部署版本
#    https://shengjuan-sm-20252354-d0gugy5fq52b8b895.webapps.tcloudbase.com
```

## 部署

| 组件 | 平台 | 地址 |
|---|---|---|
| 后端 API | CloudBase 云托管（容器 1C2G） | https://audiobook-api-303602-8-1421728968.sh.run.tcloudbase.com |
| 前端 | CloudBase 静态托管 | https://shengjuan-sm-20252354-d0gugy5fq52b8b895.webapps.tcloudbase.com |

云端环境变量（云托管 EnvParams，不入库不入镜像）：

| 变量 | 用途 |
|---|---|
| `VOLC_API_KEY` / `GLM_API_KEY` / `MINIMAX_API_KEY` / `DASHSCOPE_API_KEY` | 合成 / 情感分析 / 音色设计（备用）/ CosyVoice 设计+合成（主设计通道） |
| `CB_ENV_ID` | CloudBase 环境 ID，拼 PG REST 地址 |
| `CB_SERVICE_KEY` | service_role API Key，绕 RLS 供后端读写 PG |
| `CB_AUTH_SECRET` | token 签名密钥（泄露等于可伪造任意用户，务必保密） |

## 数据库

### 旧版本地 SQLite（未部署，仅本地开发参考）

四表：`users`（用户）、`voices`（音色库：克隆/设计/预置）、`tasks`（生成任务）、`works`（作品）。
实体类见 `app/models.py`，CRUD 见 `app/dao.py`，表结构见 `db/schema.sql`。

### 云端 CloudBase PostgreSQL（线上实际使用）

| 表 | 说明 |
|---|---|
| `users` | uid(PK) / username(UNIQUE) / password_hash / created_at |
| `user_voices` | 每用户 1 条覆盖式「我的音色」（旧机制，接口保留兼容） |
| `user_voice_library` | 音色库（PK=(uid,voice_id)，每账号上限 20 条，RLS 隔离，来源徽标） |
| `user_listen_logs` | 睡前故事收听记录（家长中心 7 天报告数据源） |
| `user_audiobooks` | 跨页书架（工作台保存的成品音频 base64，睡前故事页可听可下载） |
| `voice_design_cache` | 音色设计缓存（prompt 哈希主键，含 provider 字段，跨用户共享降费） |

`user_voices` 主键为 uid，天然实现「每用户 1 条、复制即覆盖」。RLS policy 用
`auth.uid()` 做行级隔离；后端走 `CB_SERVICE_KEY`（service_role）访问，
用户隔离由后端 token → uid 保证。建表 SQL 见 `cloudbase/migrations/`。

**已知限制**：录音克隆复用共享槽位 `S_7PtM1phd2`，多用户克隆会互相覆盖，正式版需为每用户分配独立 speaker_id。

## 功能特性

### 睡前故事播放器（特色功能，P0）

- **公版故事库**：20 篇经典改编（格林/安徒生童话、伊索寓言、西游记节选、神话故事），开箱即听
- **儿童播放器**：夜间友好 UI、大按钮大字、逐段播放、语速可调、家长音色代读
- **迷你播放栏**：故事列表页常驻，播放/暂停原地切换、点击进播放页、退出重进恢复篇目与进度；全面屏 safe-area 适配，内容不被系统手势条遮挡
- **跨页书架**：工作台成品一键「保存到书架」→ 睡前故事页同步可听；播放进度跨页跨设备一致（PG）；条目支持一键下载 MP3（⤓ → 下载百分比 → ✓ 状态机，两页同款）
- **家长中心**：近 7 天收听报告（柱状图/听完率/最爱标签，账号级跨设备同步）、每日收听上限、就寝时段控制、离线缓存管理
- **离线收听**：Cache API 缓存音频与正文，断网也能播放已保存的故事

### 有声读物工作台

- **情绪曲线编辑器**：段落级情绪强度可拖拽调整，增量重合成单段后重混音整篇
- **多角色分饰**：GLM 标注角色 + 性别 → 声池自动分配，同角色全篇锁定同一音色
- **引号兼容**：弯引号 "" / 直角引号「」/ 嵌套『』全兼容；旁白段内嵌「X道：」台词自动救援拆出
- **自定义音色**：阿里 CosyVoice 声音设计（免费，主通道）/ MiniMax Voice Design（备用）/ 豆包声音复刻 2.0（录音克隆爸妈的声音）/ 智能生成（一句话描述 → GLM 扩写专业设定 → 免费设计）
- **方言通道**：豆包四大多方言母音色 × explicit_dialect，支持川/粤/东北/京/沪等 8 方言（祖辈方言讲故事）
- **内置书库**：13 部公版古籍（西游记全本 100 回 / 论语 / 庄子 / 诗经 / 韩非子…，CC0 协议，简体，国内 CDN 直连）
- **一键多版本**：正常 / 慢速（哄睡专用）/ 英语（整篇英文朗读）/ 预告片（情绪拉满 + 强制紧张配乐）
- **长文支持**：单次上限 10000 字，分块分析（1200 字/块，跨块同名角色声线一致）
- **BGM 智能匹配**：程序化合成八音盒风格曲库（neutral/calm/sad/happy/tense），ducking 混音 + 响度归一
- **手机端适配**：窄屏堆叠布局、书架视图专用布局（隐藏音色侧栏直达书架）、触控目标放大、区块头部两行化

### 通用基础

- **账号系统**：注册 / 登录，登录后音色云端跨设备同步。走自建 users 表（CloudBase Auth 不支持用户名密码自助注册）+ PBKDF2 密码哈希 + HMAC token（7 天有效）
- **我的音色库**：每账号最多 20 条（克隆 / 设计 / 智能生成 / 预置收藏四来源，来源徽标区分），云端全量多设备同步、断网走本地缓存、登录自动迁移；支持试听、重命名、删除、一键设为旁白
- **内容安全**：读本上传 / 有声化前敏感词过滤；收听数据仅按 uid 隔离存储

## 测试

```bash
# 「」直角引号拆分单元测试（16 用例，含众猴道/玉帝曰/诗曰/嵌套『』等边界）
python scripts/test_corner_quotes.py

# 真实 GLM 端到端测试（西游记第一回节选，需 .env 配 GLM_API_KEY）
python scripts/test_xyj_glm.py
```

## 适用性说明（对照开发任务清单）

- 爬虫：不适用——本项目文本输入来自用户上传与公版书库，无需爬取外部数据
- 图像识别：不适用——纯音频文本管线
- 游戏开发：不适用

## 合规

音色克隆仅限本人或已授权声音；合成文本前置安全过滤；成品含 AI 生成标识。
