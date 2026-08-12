import asyncio
import hashlib
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from database import init_db
import aiosqlite

# ID администратора (узнайте свой ID через @userinfobot)
ADMIN_ID = 7055472251  # ← ПОМЕНЯЙТЕ НА СВОЙ ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def get_ref_code(user_id):
    return hashlib.md5(str(user_id).encode()).hexdigest()[:8]

# Состояния для создания анкеты
class ProfileForm(StatesGroup):
    name = State()
    age = State()
    city = State()
    gender = State()
    photo = State()

# Состояние для чата
class ChatState(StatesGroup):
    active_chat = State()

# ======================= СТАРТ =======================
@dp.message(CommandStart())
async def start(message: types.Message, command: CommandObject, state: FSMContext):
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
        await state.clear()
        await show_menu(message)

async def show_menu(message: types.Message):
    kb = types.ReplyKeyboardMarkup(keyboard=[
        [types.KeyboardButton(text="👤 Моя анкета")],
        [types.KeyboardButton(text="🔍 Дивитись анкети"), types.KeyboardButton(text="💰 Донат")],
        [types.KeyboardButton(text="🔗 Моє реферальне посилання")],
        [types.KeyboardButton(text="⚙️ Фільтри"), types.KeyboardButton(text="💬 Мої чати")]
    ], resize_keyboard=True)
    await message.answer("Головне меню:", reply_markup=kb)

# ======================= АНКЕТА =======================
@dp.message(F.text == "👤 Моя анкета")
async def start_profile(message: types.Message, state: FSMContext):
    await state.set_state(ProfileForm.name)
    await message.answer("Як вас звати?")

@dp.message(ProfileForm.name)
async def profile_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(ProfileForm.age)
    await message.answer("Скільки вам років? (число)")

@dp.message(ProfileForm.age)
async def profile_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Будь ласка, введіть число.")
        return
    await state.update_data(age=int(message.text))
    await state.set_state(ProfileForm.city)
    await message.answer("З якого ви міста?")

@dp.message(ProfileForm.city)
async def profile_city(message: types.Message, state: FSMContext):
    await state.update_data(city=message.text)
    await state.set_state(ProfileForm.gender)
    kb = types.ReplyKeyboardMarkup(keyboard=[
        [types.KeyboardButton(text="Чоловік")],
        [types.KeyboardButton(text="Жінка")]
    ], resize_keyboard=True)
    await message.answer("Ваша стать?", reply_markup=kb)

@dp.message(ProfileForm.gender)
async def profile_gender(message: types.Message, state: FSMContext):
    if message.text not in ("Чоловік", "Жінка"):
        await message.answer("Будь ласка, оберіть з клавіатури.")
        return
    await state.update_data(gender=message.text)
    await state.set_state(ProfileForm.photo)
    await message.answer("Тепер надішліть ваше фото (або натисніть /skip)", reply_markup=types.ReplyKeyboardRemove())

@dp.message(ProfileForm.photo, F.photo)
async def profile_photo(message: types.Message, state: FSMContext):
    # Берем file_id самого большого размера
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    uid = message.from_user.id
    async with aiosqlite.connect("dating.db") as db:
        await db.execute("""UPDATE users SET name=?, age=?, city=?, gender=?, photo_id=? WHERE user_id=?""",
                         (data["name"], data["age"], data["city"], data["gender"], photo_id, uid))
        await db.commit()
    await state.clear()
    await message.answer("✅ Анкету збережено з фото!")
    await show_menu(message)

@dp.message(ProfileForm.photo, Command("skip"))
async def profile_photo_skip(message: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = message.from_user.id
    async with aiosqlite.connect("dating.db") as db:
        await db.execute("""UPDATE users SET name=?, age=?, city=?, gender=?, photo_id=NULL WHERE user_id=?""",
                         (data["name"], data["age"], data["city"], data["gender"], uid))
        await db.commit()
    await state.clear()
    await message.answer("✅ Анкету збережено без фото.")
    await show_menu(message)

# ======================= ФИЛЬТРЫ =======================
@dp.message(F.text == "⚙️ Фільтри")
async def filter_menu(message: types.Message):
    uid = message.from_user.id
    async with aiosqlite.connect("dating.db") as db:
        cur = await db.execute("SELECT * FROM filters WHERE user_id=?", (uid,))
        filt = await cur.fetchone()
    if filt:
        text = (f"Ваші фільтри:\n"
                f"Стать: {filt[1] or 'будь-яка'}\n"
                f"Вік: {filt[2] or 'немає'} - {filt[3] or 'немає'}\n"
                f"Місто: {filt[4] or 'будь-яке'}\n")
    else:
        text = "Фільтри не встановлені."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Встановити стать", callback_data="set_gender")],
        [InlineKeyboardButton(text="Встановити вік", callback_data="set_age")],
        [InlineKeyboardButton(text="Встановити місто", callback_data="set_city")],
        [InlineKeyboardButton(text="Скинути всі фільтри", callback_data="reset_filters")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "reset_filters")
async def reset_filters(call: types.CallbackQuery):
    uid = call.from_user.id
    async with aiosqlite.connect("dating.db") as db:
        await db.execute("DELETE FROM filters WHERE user_id=?", (uid,))
        await db.commit()
    await call.message.answer("Фільтри скинуто.")
    await call.answer()

# Обработка установки пола
@dp.callback_query(F.data == "set_gender")
async def set_gender_start(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Чоловік", callback_data="gender_male")],
        [InlineKeyboardButton(text="Жінка", callback_data="gender_female")],
        [InlineKeyboardButton(text="Будь-яка", callback_data="gender_any")]
    ])
    await call.message.answer("Оберіть бажану стать:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("gender_"))
async def set_gender(call: types.CallbackQuery):
    val = call.data.split("_")[1]
    uid = call.from_user.id
    async with aiosqlite.connect("dating.db") as db:
        await db.execute("""INSERT INTO filters (user_id, preferred_gender) VALUES (?,?)
                            ON CONFLICT(user_id) DO UPDATE SET preferred_gender=?""",
                         (uid, val, val))
        await db.commit()
    await call.message.answer(f"Стать фільтру: {val}")
    await call.answer()

# Аналогично для возраста и города (для краткости приведу упрощённо)
@dp.callback_query(F.data == "set_age")
async def set_age_start(call: types.CallbackQuery):
    await call.message.answer("Введіть мінімальний і максимальний вік у форматі: мін-макс (наприклад, 18-25)")
    await call.answer()

@dp.message(lambda msg: msg.text and '-' in msg.text and msg.reply_to_message is not None)
async def set_age(message: types.Message):
    try:
        mn, mx = map(int, message.text.split('-'))
    except:
        await message.answer("Невірний формат. Приклад: 18-25")
        return
    uid = message.from_user.id
    async with aiosqlite.connect("dating.db") as db:
        await db.execute("""INSERT INTO filters (user_id, min_age, max_age) VALUES (?,?,?)
                            ON CONFLICT(user_id) DO UPDATE SET min_age=?, max_age=?""",
                         (uid, mn, mx, mn, mx))
        await db.commit()
    await message.answer(f"Віковий фільтр: {mn}-{mx}")

@dp.callback_query(F.data == "set_city")
async def set_city_start(call: types.CallbackQuery):
    await call.message.answer("Введіть місто для пошуку:")
    await call.answer()

@dp.message(lambda msg: msg.reply_to_message is not None and msg.text)
async def set_city(message: types.Message):
    uid = message.from_user.id
    city = message.text.strip()
    async with aiosqlite.connect("dating.db") as db:
        await db.execute("""INSERT INTO filters (user_id, city) VALUES (?,?)
                            ON CONFLICT(user_id) DO UPDATE SET city=?""",
                         (uid, city, city))
        await db.commit()
    await message.answer(f"Місто для пошуку: {city}")

# ======================= ПОИСК АНКЕТ =======================
@dp.message(F.text == "🔍 Дивитись анкети")
async def search(message: types.Message):
    uid = message.from_user.id
    async with aiosqlite.connect("dating.db") as db:
        # Получаем фильтры
        filt = await db.execute("SELECT * FROM filters WHERE user_id=?", (uid,))
        filt = await filt.fetchone()
        preferred_gender = filt[1] if filt else None
        min_age = filt[2] if filt else None
        max_age = filt[3] if filt else None
        city = filt[4] if filt else None

        query = """
            SELECT user_id, name, age, city, photo_id FROM users
            WHERE user_id != ? AND user_id NOT IN
                (SELECT to_user FROM likes WHERE from_user = ?)
        """
        params = [uid, uid]
        if preferred_gender and preferred_gender != 'any':
            query += " AND gender = ?"
            params.append(preferred_gender)
        if min_age:
            query += " AND age >= ?"
            params.append(min_age)
        if max_age:
            query += " AND age <= ?"
            params.append(max_age)
        if city:
            query += " AND city LIKE ?"
            params.append(f"%{city}%")

        query += " ORDER BY RANDOM() LIMIT 1"
        cur = await db.execute(query, tuple(params))
        row = await cur.fetchone()
        if not row:
            await message.answer("😔 Поки немає анкет за вашими фільтрами.")
            return
        target_id, name, age, city, photo_id = row
        text = f"{name}, {age}, {city}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❤️", callback_data=f"like_{target_id}"),
             InlineKeyboardButton(text="👎", callback_data="skip")]
        ])
        if photo_id:
            await message.answer_photo(photo_id, caption=text, reply_markup=kb)
        else:
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
            # Взаимный лайк - создаём матч
            user1, user2 = min(uid, target), max(uid, target)
            await db.execute("INSERT OR IGNORE INTO matches (user1, user2) VALUES (?,?)", (user1, user2))
            await db.commit()
            match_id = f"{user1}_{user2}"
            await call.message.answer("💞 Взаємний лайк! Тепер ви можете спілкуватися у чаті.")
            # Уведомляем обоих
            try:
                await bot.send_message(target, f"💞 У вас новий матч з користувачем {call.from_user.full_name}! Перейдіть у '💬 Мої чати'.")
            except:
                pass
        else:
            await call.message.answer("Лайк відправлено! Чекайте на відповідь.")
    await call.message.delete()
    await search(call.message)

@dp.callback_query(F.data == "skip")
async def skip(call: types.CallbackQuery):
    await call.message.delete()
    await search(call.message)

# ======================= ЧАТЫ =======================
@dp.message(F.text == "💬 Мої чати")
async def my_chats(message: types.Message):
    uid = message.from_user.id
    async with aiosqlite.connect("dating.db") as db:
        cur = await db.execute("""
            SELECT user1, user2 FROM matches
            WHERE user1=? OR user2=?
        """, (uid, uid))
        matches = await cur.fetchall()
    if not matches:
        await message.answer("У вас поки немає матчів.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for u1, u2 in matches:
        other = u1 if u2 == uid else u2
        # Получаем имя собеседника
        async with aiosqlite.connect("dating.db") as db:
            cur = await db.execute("SELECT name FROM users WHERE user_id=?", (other,))
            name = await cur.fetchone()
            name = name[0] if name else "Користувач"
        kb.inline_keyboard.append([InlineKeyboardButton(text=name, callback_data=f"chat_{other}")])
    await message.answer("Оберіть співрозмовника:", reply_markup=kb)

@dp.callback_query(F.data.startswith("chat_"))
async def start_chat(call: types.CallbackQuery, state: FSMContext):
    other_id = int(call.data.split("_")[1])
    uid = call.from_user.id
    # Сохраняем активного собеседника в FSM
    await state.update_data(chat_with=other_id)
    await state.set_state(ChatState.active_chat)
    await call.message.answer(f"Чат з користувачем відкрито. Напишіть повідомлення або /exit для виходу.", reply_markup=types.ReplyKeyboardRemove())
    await call.answer()

@dp.message(ChatState.active_chat, Command("exit"))
async def exit_chat(message: types.Message, state: FSMContext):
    await state.clear()
    await show_menu(message)

@dp.message(ChatState.active_chat, F.text)
async def chat_message(message: types.Message, state: FSMContext):
    data = await state.get_data()
    other_id = data.get("chat_with")
    if not other_id:
        await message.answer("Помилка, вийдіть з чату.")
        await state.clear()
        await show_menu(message)
        return
    # Отправляем сообщение собеседнику
    try:
        await bot.send_message(other_id, f"💬 Повідомлення від співрозмовника:\n{message.text}")
        # Сохраняем в историю (опционально)
        async with aiosqlite.connect("dating.db") as db:
            match_id = f"{min(message.from_user.id, other_id)}_{max(message.from_user.id, other_id)}"
            await db.execute("INSERT INTO messages (match_id, sender_id, text) VALUES (?,?,?)",
                             (match_id, message.from_user.id, message.text))
            await db.commit()
    except Exception as e:
        await message.answer(f"Не вдалося надіслати повідомлення: {e}")

# ======================= ДОНАТ =======================
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

# ======================= РЕФЕРАЛЬНА СИСТЕМА =======================
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

# ======================= АДМИН-ПАНЕЛЬ =======================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Немає доступу.")
        return
    async with aiosqlite.connect("dating.db") as db:
        users = await db.execute("SELECT COUNT(*) FROM users")
        users = (await users.fetchone())[0]
        matches = await db.execute("SELECT COUNT(*) FROM matches")
        matches = (await matches.fetchone())[0]
        reports = await db.execute("SELECT COUNT(*) FROM reports")
        reports = (await reports.fetchone())[0]
        # Последние 5 регистраций
        recent = await db.execute("SELECT name, age, city FROM users ORDER BY created_at DESC LIMIT 5")
        recent = await recent.fetchall()
        text = f"📊 Статистика:\n"
        text += f"👥 Користувачів: {users}\n"
        text += f"💞 Матчів: {matches}\n"
        text += f"⚠️ Скарг: {reports}\n\n"
        if recent:
            text += "Останні реєстрації:\n"
            for r in recent:
                text += f"- {r[0]}, {r[1]}, {r[2]}\n"
    await message.answer(text)

# ======================= ОБРАБОТКА ЖАЛОБ (можно добавить кнопку "Поскаржитись") =======================
# Для простоты добавим команду /report
@dp.message(Command("report"))
async def report(message: types.Message):
    # Заглушка: просто покажем сообщение
    await message.answer("Щоб поскаржитись на користувача, напишіть /report ID_користувача причина")

# ======================= ЗАПУСК =======================
async def main():
    await init_db()
    print("Бот запущено...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())