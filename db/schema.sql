-- 声卷 · 数据库设计（SQLite）
-- 设计原则：Demo 单机 SQLite；生产可平移至 CloudBase 云数据库（表结构与字段语义不变）

PRAGMA foreign_keys = ON;

-- 用户表（Demo 阶段单用户占位，预留多用户扩展）
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    display_name TEXT,
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 音色表：登记克隆音色 / 设计音色 / 预置音色
CREATE TABLE IF NOT EXISTS voices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    speaker_id  TEXT NOT NULL UNIQUE,          -- 火山 S_xxx / custom_xxx / 大模型音色 ID / MiniMax ttv-voice-xxx
    name        TEXT NOT NULL,                 -- 显示名（如"我的声音"）
    type        TEXT NOT NULL CHECK (type IN ('clone', 'design', 'preset')),
    provider    TEXT NOT NULL DEFAULT 'volc',  -- volc / minimax
    gender      TEXT DEFAULT 'unknown',        -- male / female / unknown
    note        TEXT,
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 生成任务表：记录一次流水线执行
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL UNIQUE,          -- 云端任务 UUID
    text_len    INTEGER NOT NULL,
    narrator    TEXT NOT NULL,                 -- 旁白音色 ID
    use_bgm     INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'running',  -- running/done/failed
    segments_json  TEXT,                       -- 情感分析结果（JSON 数组）
    duration_s  REAL,
    error       TEXT,
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 作品表：生成完成的成品音频
CREATE TABLE IF NOT EXISTS works (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    audio_path  TEXT NOT NULL,                 -- 本地/COS 路径
    duration_s  REAL,
    bgm_name    TEXT,                          -- 所用 BGM
    created_at  TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_works_created ON works(created_at DESC);
