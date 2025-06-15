import os
import yaml
import aiosqlite
from datetime import datetime

DATABASE_PATH = os.getenv("DATABASE_PATH", "telegram_bot.db")

with open("vars.yaml", encoding="utf-8") as f:
    SQL = yaml.load(f, Loader=yaml.FullLoader)["queries"]

async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(SQL["create_table_q"])
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reddit_posts(
              post_id TEXT PRIMARY KEY,
              processed_at DATETIME
            );
        """)
        await db.commit()

async def is_reddit_processed(post_id: str) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute("SELECT 1 FROM reddit_posts WHERE post_id=?", (post_id,))
        return bool(await cur.fetchone())

async def mark_reddit_processed(post_id: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO reddit_posts(post_id, processed_at) VALUES(?,?)",
            (post_id, datetime.now().isoformat())
        )
        await db.commit()

async def save_post_to_db(**kwargs) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cols = ", ".join(kwargs.keys())
        qmarks = ", ".join("?" for _ in kwargs)
        vals = list(kwargs.values())
        cur = await db.execute(f"INSERT INTO post_logs ({cols}) VALUES ({qmarks})", vals)
        await db.commit()
        return cur.lastrowid
