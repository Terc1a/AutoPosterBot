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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              post_id TEXT NOT NULL,
              title TEXT,
              media_type TEXT,
              media_data BLOB,
              caption TEXT,
              scheduled_time DATETIME NOT NULL,
              status TEXT DEFAULT 'pending',
              source TEXT DEFAULT 'reddit',
              error_message TEXT,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              sent_at DATETIME,
              message_id INTEGER
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

async def get_marked_posts() -> list:
    """Получает все помеченные посты для использования в качестве негативных примеров"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute(
            "SELECT description FROM post_logs WHERE marked = 1 AND description IS NOT NULL ORDER BY created_at DESC LIMIT 10"
        )
        rows = await cur.fetchall()
        return [row[0] for row in rows]

async def save_scheduled_post(post_id: str, title: str, media_type: str, media_data: bytes, 
                              caption: str, scheduled_time: datetime, source: str = 'reddit') -> int:
    """Сохраняет отложенный пост в БД"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute("""
            INSERT INTO scheduled_posts (post_id, title, media_type, media_data, caption, 
                                       scheduled_time, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (post_id, title, media_type, media_data, caption, scheduled_time.isoformat(), source))
        await db.commit()
        return cur.lastrowid

async def get_pending_scheduled_posts() -> list:
    """Получает все отложенные посты, которые готовы к отправке"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute("""
            SELECT id, post_id, title, media_type, media_data, caption, scheduled_time, source
            FROM scheduled_posts
            WHERE status = 'pending' AND datetime(scheduled_time) <= datetime('now', 'localtime')
            ORDER BY scheduled_time ASC
        """)
        rows = await cur.fetchall()
        return [dict(zip([col[0] for col in cur.description], row)) for row in rows]

async def mark_scheduled_post_sent(post_id: int, message_id: int):
    """Помечает отложенный пост как отправленный"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            UPDATE scheduled_posts 
            SET status = 'sent', sent_at = datetime('now', 'localtime'), message_id = ?
            WHERE id = ?
        """, (message_id, post_id))
        await db.commit()

async def mark_scheduled_post_failed(post_id: int, error_message: str):
    """Помечает отложенный пост как не отправленный"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            UPDATE scheduled_posts 
            SET status = 'failed', error_message = ?
            WHERE id = ?
        """, (error_message, post_id))
        await db.commit()

async def get_scheduled_posts_stats() -> dict:
    """Получает статистику отложенных постов"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as sent,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM scheduled_posts
        """)
        row = await cur.fetchone()
        return dict(zip([col[0] for col in cur.description], row)) if row else {}

async def get_all_scheduled_posts() -> list:
    """Получает все отложенные посты для отображения в dashboard"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute("""
            SELECT id, post_id, title, media_type, caption, scheduled_time, status, 
                   source, error_message, created_at, sent_at, message_id
            FROM scheduled_posts
            ORDER BY scheduled_time DESC
        """)
        rows = await cur.fetchall()
        return [dict(zip([col[0] for col in cur.description], row)) for row in rows]


async def get_pending_scheduled_posts() -> list:
    """Получает посты, которые нужно опубликовать (время публикации прошло)"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute("""
            SELECT id, post_id, title, media_type, media_data, caption, scheduled_time, source
            FROM scheduled_posts
            WHERE status = 'pending' AND scheduled_time <= datetime('now')
            ORDER BY scheduled_time ASC
        """)
        rows = await cur.fetchall()
        return [dict(zip([col[0] for col in cur.description], row)) for row in rows]
