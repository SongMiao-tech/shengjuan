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
├── cloudrun/               CloudBase 云托管服务（后端 API，容器部署）
│   ├── app.py              流水线服务（/tasks /voices/* 接口）
│   ├── Dockerfile          python3.11-slim + ffmpeg
│   └── assets/bgm/         情绪曲库
├── web/                    前端
│   ├── index.html          正式工作台（已部署公网）
│   └── prototypes/         功能原型页 ×3
├── assets/bgm/             情绪曲库（本地副本）
├── scripts/                工具脚本（合成/分析/流水线/音色）
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

密钥通过云托管环境变量注入（VOLC_API_KEY / GLM_API_KEY / MINIMAX_API_KEY），不入库不入镜像。

## 数据库

四表：`users`（用户）、`voices`（音色库：克隆/设计/预置）、`tasks`（生成任务）、`works`（作品）。
实体类见 `app/models.py`，CRUD 见 `app/dao.py`，表结构见 `db/schema.sql`。

## 适用性说明（对照开发任务清单）

- 爬虫：不适用——本项目文本输入来自用户上传，无需爬取外部数据
- 图像识别：不适用——纯音频文本管线
- 游戏开发：不适用

## 合规

音色克隆仅限本人或已授权声音；合成文本前置安全过滤；成品含 AI 生成标识。
