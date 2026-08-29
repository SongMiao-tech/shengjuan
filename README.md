# 声卷 · 个性化有声读物智能生成系统

> 情绪曲线驱动的有声书生成工作台。上传文本 → AI 标注段落情绪/角色 → 多角色多情绪语音合成 → BGM 智能匹配 → 可增量调整的一键成品。
> 全云 API 架构（豆包语音合成 2.0 / MiniMax / GLM-4-Flash / CloudBase），本地零模型部署。

## 文档

- [PRD.md](PRD.md) — 产品需求文档（已确认）
- [docs/技术方案.md](docs/技术方案.md) — 完整技术方案（v2.0 纯 API 版）

## 目录结构

```
shengjuan/
├── PRD.md                  产品需求文档
├── README.md               本文件
├── db/                     SQLite 数据库
│   ├── schema.sql          建表脚本（users/voices/tasks/works）
│   ├── seed.sql            测试数据
│   ├── init_db.py          初始化脚本（幂等）
│   └── shengjuan.db        数据库文件（init 后生成）
├── app/                    数据访问层
│   ├── models.py           实体类（User/Voice/Task/Work）
│   └── dao.py              CRUD 封装（python -m app.dao 可自检）
├── cloudbase/migrations/   CloudBase PG 建表迁移（users / user_voices，版本化）
├── cloudrun/               CloudBase 云托管服务（后端 API，容器部署）
│   ├── app.py              流水线 + 账号系统（/tasks /voices/* /auth/* /me/voice）
│   ├── Dockerfile          python3.11-slim + ffmpeg
│   └── assets/bgm/         情绪曲库
├── web/                    前端
│   ├── index.html          正式工作台（已部署公网）
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

# 2. 初始化数据库（建表 + 测试数据，幂等）
cd shengjuan
python db/init_db.py          # 或 python -m app.dao

# 3. 配置密钥：复制 .env.example 为 .env 填入
#    VOLC_API_KEY / GLM_API_KEY / MINIMAX_API_KEY

# 4. 一键生成（本地 CLI）
python scripts/pipeline.py --input story.txt -o final.mp3 --narrator S_xxxxx

# 5. 前端：直接打开 web/index.html，或访问已部署版本
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
| `VOLC_API_KEY` / `GLM_API_KEY` / `MINIMAX_API_KEY` | 合成 / 情感分析 / 音色设计 |
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
| `user_voices` | uid(PK) / speaker_id / name / source / dialect / created_at |

`user_voices` 主键为 uid，天然实现「每用户 1 条、复制即覆盖」。RLS policy 用
`auth.uid()` 做行级隔离；后端走 `CB_SERVICE_KEY`（service_role）访问，
用户隔离由后端 token → uid 保证。建表 SQL 见 `cloudbase/migrations/`。

**已知限制**：录音克隆复用共享槽位 `S_7PtM1phd2`，多用户克隆会互相覆盖，正式版需为每用户分配独立 speaker_id。

## 功能特性

- **账号系统**：注册 / 登录，登录后可跨设备保存「我的音色」。走自建 users 表（CloudBase Auth 不支持用户名密码自助注册）+ PBKDF2 密码哈希 + HMAC token（7 天有效）
- **我的音色**：每账号 1 条覆盖式绑定，来源可以是预置音色池 / 录音克隆 / AI 设计；支持试听、设为旁白、删除
- **情绪曲线编辑器**：段落级情绪强度可拖拽调整，增量重合成单段后重混音整篇
- **多角色分饰**：GLM 标注角色 + 性别 → 声池自动分配，同角色全篇锁定同一音色
- **引号兼容**：弯引号 “” / 直角引号 「」 / 嵌套 『』 全兼容；旁白段内嵌「X道：」台词自动救援拆出
- **自定义音色**：MiniMax Voice Design（文本描述造音色）+ 豆包声音复刻 2.0（录音克隆）
- **方言通道**：豆包四大多方言母音色 × explicit_dialect，支持川/粤/东北/京/沪等 8 方言
- **内置书库**：13 部公版古籍（西游记全本 100 回 / 论语 / 庄子 / 诗经 / 韩非子…，CC0 协议，简体，国内 CDN 直连）
- **一键多版本**：正常 / 慢速 / 双语（中英交替）/ 预告片（情绪拉满 + 强制紧张配乐）
- **长文支持**：单次上限 10000 字，分块分析（1200 字/块，跨块同名角色声线一致）
- **BGM 智能匹配**：程序化合成八音盒风格曲库（neutral/calm/sad/happy/tense），ducking 混音 + 响度归一

## 测试

```bash
# 「」直角引号拆分单元测试（16 用例，含众猴道/玉帝曰/诗曰/嵌套『』等边界）
python scripts/test_corner_quotes.py

# 真实 GLM 端到端测试（西游记第一回节选，需 .env 配 GLM_API_KEY）
python scripts/test_xyj_glm.py
```

## 数据库

四表：`users`（用户）、`voices`（音色库：克隆/设计/预置）、`tasks`（生成任务）、`works`（作品）。
实体类见 `app/models.py`，CRUD 见 `app/dao.py`，表结构见 `db/schema.sql`。

## 适用性说明（对照开发任务清单）

- 爬虫：不适用——本项目文本输入来自用户上传，无需爬取外部数据
- 图像识别：不适用——纯音频文本管线
- 游戏开发：不适用

## 合规

音色克隆仅限本人或已授权声音；合成文本前置安全过滤；成品含 AI 生成标识。
