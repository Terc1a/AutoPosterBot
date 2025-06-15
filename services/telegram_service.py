import os
from telegram import Bot
from io import BytesIO

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
bot = Bot(token=BOT_TOKEN)

async def send_photo(image_bytes: bytes, caption: str = None):
    bio = BytesIO(image_bytes)
    bio.name = "image.png"
    bio.seek(0)
    await bot.send_photo(chat_id=CHANNEL_ID, photo=bio, caption=caption)

async def send_video(file_path: str):
    with open(file_path, "rb") as f:
        await bot.send_video(chat_id=CHANNEL_ID, video=f)
