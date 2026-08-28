# -*- coding: utf-8 -*-
"""初始化数据库：建表 + 插入测试数据
用法: python db/init_db.py [--db shengjuan.db]
"""
import argparse
import sqlite3
import sys
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_DIR / "shengjuan.db"))
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        conn.executescript((DB_DIR / "schema.sql").read_text(encoding="utf-8"))
        # 幂等：测试数据仅在空表时插入
        n = conn.execute("SELECT COUNT(*) FROM voices").fetchone()[0]
        if n == 0:
            conn.executescript((DB_DIR / "seed.sql").read_text(encoding="utf-8"))
            print("已插入测试数据")
        else:
            print("表已有数据，跳过 seed")
        conn.commit()
        for table in ("users", "voices", "tasks", "works"):
            cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {cnt} 行")
        print(f"数据库就绪: {args.db}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
