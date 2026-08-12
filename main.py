import asyncio
import hashlib
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import LabeledPrice, PreCheckoutQuery
from aiohttp import web
from database import init_db
import aiosqlite

BOT_TOKEN = os.getenv("BOT_TOKEN")  # токен беремо з змінних середовища Render
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Всі обробники (копіюємо з попереднього коду) ---
# ...

# --- Налаштування вебхука ---
async def on_startup():
    await init_db()
    webhook_url = os.getenv("WEBHOOK_URL")  # наприклад, https://your-app.onrender.com/webhook
    await bot.set_webhook(webhook_url)
    print("Webhook встановлено")

async def on_shutdown():
    await bot.delete_webhook()
    await bot.session.close()

async def handle_webhook(request):
    url = str(request.url)
    index = url.rfind('/')
    token = url[index+1:]
    if token == bot.token:
        update = await request.json()
        await dp.feed_update(bot, update)
        return web.Response()
    else:
        return web.Response(status=403)

async def main():
    await on_startup()
    app = web.Application()
    app.router.add_post('/webhook', handle_webhook)
    app.router.add_get('/webhook', handle_webhook)  # для перевірки
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8000)))
    await site.start()
    print("Веб-сервер запущено")
    await asyncio.Event().wait()  # тримаємо сервер

if __name__ == "__main__":
    asyncio.run(main())