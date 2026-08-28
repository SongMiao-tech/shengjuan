# -*- coding: utf-8 -*-
"""实体类：与 db/schema.sql 表结构一一对应"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class User:
    id: Optional[int]
    username: str
    display_name: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class Voice:
    id: Optional[int]
    speaker_id: str          # 火山 S_xxx / custom_xxx / 大模型音色 ID / MiniMax ttv-voice-xxx
    name: str                # 显示名
    type: str                # clone / design / preset
    provider: str = "volc"   # volc / minimax
    gender: str = "unknown"
    note: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class Task:
    id: Optional[int]
    task_id: str             # 云端任务 UUID
    text_len: int
    narrator: str
    use_bgm: bool = True
    status: str = "running"  # running / done / failed
    segments_json: Optional[str] = None   # 情感分析 JSON 数组
    duration_s: Optional[float] = None
    error: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class Work:
    id: Optional[int]
    task_id: str
    title: str
    audio_path: str
    duration_s: Optional[float] = None
    bgm_name: Optional[str] = None
    created_at: Optional[str] = None
