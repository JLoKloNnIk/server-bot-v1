import asyncio, hashlib
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import LabeledPrice, PreCheckoutQuery
from config import BOT_TOKEN
from database import init_db
import aiosqlite

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def get_ref_code(user_id):
    return hashlib.md5(str(user_id).encode()).hexdigest()[:8]

# --- СТАРТ і реферальна система ---
@dp.message(CommandStart())
async def start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    ref = command.args
    async with aiosqlite.connect("dating.db") as db:
        user = await db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if not await user.fetchone():
            code = get_ref_code(user_id)
            invited_by = None
            if ref:
                inv = await db.execute("SELECT user_id FROM users WHERE ref_code=?", (ref,))
                inv = await inv.fetchone()
                if inv:
                    invited_by = inv[0]
            await db.execute("INSERT INTO users (user_id, username, ref_code, referred_by, balance) VALUES (?,?,?,?,?)",
                             (user_id, message.from_user.username, code, invited_by, 5))
            await db.commit()
            if invited_by:
                await db.execute("INSERT OR IGNORE INTO referrals VALUES (?,?)", (invited_by, user_id))
                await db.execute("UPDATE users SET balance=balance+3 WHERE user_id=?", (invited_by,))
                await db.execute("UPDATE users SET balance=balance+3 WHERE user_id=?", (user_id,))
                await db.commit()
                await message.answer("🎉 Вас запросив друг! Ви обоє отримали +3 безкоштовні лайки.")
        await show_menu(message)

async def show_menu(msg: types.Message):
    kb = types.ReplyKeyboardMarkup(keyboard=[
        [types.KeyboardButton(text="👤 Моя анкета")],
        [types.KeyboardButton(text="🔍 Дивитись анкети"), types.KeyboardButton(text="💰 Донат")],
        [types.KeyboardButton(text="🔗 Моє реферальне посилання")]
    ], resize_keyboard=True)
    await msg.answer("Головне меню:", reply_markup=kb)

# --- Створення/редагування анкети ---
user_data = {}

@dp.message(F.text == "👤 Моя анкета")
async def ask_name(message: types.Message):
    await message.answer("Як вас звати?")
    user_data[message.from_user.id] = {}

@dp.message(lambda msg: msg.from_user.id in user_data and "name" not in user_data[msg.from_user.id])
async def get_name(message: types.Message):
    user_data[message.from_user.id]["name"] = message.text
    await message.answer("Скільки вам років? (число)")

@dp.message(lambda msg: msg.from_user.id in user_data and "age" not in user_data[msg.from_user.id])
async def get_age(message: types.Message):
    if not message.text.isdigit():
        await message.answer("Будь ласка, введіть число.")
        return
    user_data[message.from_user.id]["age"] = int(message.text)
    await message.answer("З якого ви міста?")

@dp.message(lambda msg: msg.from_user.id in user_data and "city" not in user_data[msg.from_user.id])
async def get_city(message: types.Message):
    uid = message.from_user.id
    data = user_data[uid]
    data["city"] = message.text
    async with aiosqlite.connect("dating.db") as db:
        await db.execute("UPDATE users SET name=?, age=?, city=?, gender='не вказано' WHERE user_id=?",
                         (data["name"], data["age"], data["city"], uid))
        await db.commit()
    del user_data[uid]
    await message.answer("✅ Анкету збережено!", reply_markup=types.ReplyKeyboardRemove())
    await show_menu(message)

# --- Перегляд анкет і лайки ---
@dp.message(F.text == "🔍 Дивитись анкети")
async def search(message: types.Message):
    uid = message.from_user.id
    async with aiosqlite.connect("dating.db") as db:
        cur = await db.execute("""
            SELECT user_id, name, age, city FROM users
            WHERE user_id != ? AND user_id NOT IN
                (SELECT to_user FROM likes WHERE from_user = ?)
            ORDER BY RANDOM() LIMIT 1
        """, (uid, uid))
        row = await cur.fetchone()
        if not row:
            await message.answer("😔 Поки немає нових анкет.")
            return
        target_id, name, age, city = row
        text = f"{name}, {age}, {city}\n❤️ Лайкнути?"
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="❤️", callback_data=f"like_{target_id}"),
             types.InlineKeyboardButton(text="👎", callback_data="skip")]
        ])
        await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("like_"))
async def like(call: types.CallbackQuery):
    target = int(call.data.split("_")[1])
    uid = call.from_user.id
    async with aiosqlite.connect("dating.db") as db:
        await db.execute("INSERT OR IGNORE INTO likes VALUES (?,?)", (uid, target))
        await db.commit()
        cur = await db.execute("SELECT * FROM likes WHERE from_user=? AND to_user=?", (target, uid))
        if await cur.fetchone():
            await call.message.answer("💞 Взаємний лайк! Починайте спілкування.")
        else:
            await call.message.answer("Лайк відправлено! Чекайте на відповідь.")
    await call.message.delete()
    await search(call.message)

@dp.callback_query(F.data == "skip")
async def skip(call: types.CallbackQuery):
    await call.message.delete()
    await search(call.message)

# --- Донат через Telegram Stars ---
@dp.message(F.text == "💰 Донат")
async def donate(message: types.Message):
    prices = [LabeledPrice(label="5 додаткових лайків", amount=50)]
    await message.answer_invoice(
        title="Більше лайків",
        description="Отримайте 5 лайків для пошуку",
        payload="buy_likes",
        provider_token="",
        currency="XTR",
        prices=prices,
        start_parameter="start"
    )

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    uid = message.from_user.id
    async with aiosqlite.connect("dating.db") as db:
        await db.execute("UPDATE users SET balance = balance + 5 WHERE user_id = ?", (uid,))
        await db.commit()
    await message.answer("✅ Дякуємо! Ви отримали +5 лайків.")

# --- Реферальне посилання ---
@dp.message(F.text == "🔗 Моє реферальне посилання")
async def my_ref(message: types.Message):
    async with aiosqlite.connect("dating.db") as db:
        cur = await db.execute("SELECT ref_code FROM users WHERE user_id=?", (message.from_user.id,))
        code = await cur.fetchone()
        if code:
            link = f"https://t.me/{(await bot.get_me()).username}?start={code[0]}"
            await message.answer(f"Ваше реферальне посилання:\n{link}\nЗа кожного друга ви отримуєте +3 лайки.")
        else:
            await message.answer("Спочатку створіть анкету через кнопку '👤 Моя анкета'.")

# --- Запуск ---
async def main():
    await init_db()
    print("Бот запущено...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())