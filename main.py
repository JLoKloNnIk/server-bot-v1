import asyncio
import hashlib
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    LabeledPrice, PreCheckoutQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from config import BOT_TOKEN
from database import init_db
import aiosqlite

ADMIN_ID = 7055472251  # ← ЗАМЕНИТЕ на свой Telegram ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def get_ref_code(user_id):
    return hashlib.md5(str(user_id).encode()).hexdigest()[:8]

# ---------- Состояния профиля ----------
class ProfileForm(StatesGroup):
    name = State()
    age = State()
    city = State()
    gender = State()
    photo = State()

# ---------- Состояния чата ----------
class ChatState(StatesGroup):
    active_chat = State()

# ---------- Состояния фильтров ----------
class FilterForm(StatesGroup):
    waiting_for_min_age = State()
    waiting_for_max_age = State()
    waiting_for_city = State()

# ---------- Вспомогательные функции ----------
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Моя анкета")],
            [KeyboardButton(text="🔍 Дивитись анкети"), KeyboardButton(text="💰 Донат")],
            [KeyboardButton(text="🔗 Моє реферальне посилання")],
            [KeyboardButton(text="⚙️ Фільтри"), KeyboardButton(text="💬 Мої чати")]
        ],
        resize_keyboard=True
    )

async def show_menu(message: types.Message):
    await message.answer("Головне меню:", reply_markup=main_menu_keyboard())

# ---------- Старт и регистрация ----------
@dp.message(CommandStart())
async def start(message: types.Message, command: CommandObject, state: FSMContext):
    user_id = message.from_user.id
    ref = command.args
    async with aiosqlite.connect("asyncpg") as db:
        user = await db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if not await user.fetchone():
            code = get_ref_code(user_id)
            invited_by = None
            if ref:
                inv = await db.execute("SELECT user_id FROM users WHERE ref_code=?", (ref,))
                inv = await inv.fetchone()
                if inv:
                    invited_by = inv[0]
            await db.execute(
                "INSERT INTO users (user_id, username, ref_code, referred_by, balance) VALUES (?,?,?,?,?)",
                (user_id, message.from_user.username, code, invited_by, 5)
            )
            await db.commit()
            if invited_by:
                await db.execute("INSERT OR IGNORE INTO referrals VALUES (?,?)", (invited_by, user_id))
                await db.execute("UPDATE users SET balance=balance+3 WHERE user_id=?", (invited_by,))
                await db.execute("UPDATE users SET balance=balance+3 WHERE user_id=?", (user_id,))
                await db.commit()
                await message.answer("🎉 Вас запросив друг! Ви обоє отримали +3 безкоштовні лайки.")
        await state.clear()
        await show_menu(message)

# ---------- Создание анкеты ----------
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
    age = int(message.text)
    if age < 16 or age > 100:
        await message.answer("Вік має бути від 16 до 100 років.")
        return
    await state.update_data(age=age)
    await state.set_state(ProfileForm.city)
    await message.answer("З якого ви міста?")

@dp.message(ProfileForm.city)
async def profile_city(message: types.Message, state: FSMContext):
    await state.update_data(city=message.text)
    await state.set_state(ProfileForm.gender)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Чоловік")], [KeyboardButton(text="Жінка")]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("Ваша стать?", reply_markup=kb)

@dp.message(ProfileForm.gender)
async def profile_gender(message: types.Message, state: FSMContext):
    if message.text not in ("Чоловік", "Жінка"):
        await message.answer("Будь ласка, оберіть з клавіатури.")
        return
    await state.update_data(gender=message.text)
    await state.set_state(ProfileForm.photo)
    await message.answer("Тепер надішліть ваше фото (обов'язково).", reply_markup=ReplyKeyboardRemove())

@dp.message(ProfileForm.photo, F.photo)
async def profile_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    uid = message.from_user.id
    async with aiosqlite.connect("asyncpg") as db:
        # Проверяем, существует ли запись
        cur = await db.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
        if await cur.fetchone():
            await db.execute(
                "UPDATE users SET name=?, age=?, city=?, gender=?, photo_id=? WHERE user_id=?",
                (data["name"], data["age"], data["city"], data["gender"], photo_id, uid)
            )
        else:
            # Если вдруг нет (например, старый пользователь), создаём
            code = get_ref_code(uid)
            await db.execute(
                "INSERT INTO users (user_id, username, name, age, city, gender, photo_id, ref_code, balance) VALUES (?,?,?,?,?,?,?,?,?)",
                (uid, message.from_user.username, data["name"], data["age"], data["city"], data["gender"], photo_id, code, 5)
            )
        await db.commit()
    await state.clear()
    await message.answer("✅ Анкету збережено з фото!")
    await show_menu(message)

# ---------- Поиск анкет ----------
@dp.message(F.text == "🔍 Дивитись анкети")
async def search(message: types.Message):
    uid = message.from_user.id
    async with aiosqlite.connect("asyncpg") as db:
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
    async with aiosqlite.connect("asyncpg") as db:
        await db.execute("INSERT OR IGNORE INTO likes VALUES (?,?)", (uid, target))
        await db.commit()
        cur = await db.execute("SELECT * FROM likes WHERE from_user=? AND to_user=?", (target, uid))
        if await cur.fetchone():
            user1, user2 = min(uid, target), max(uid, target)
            await db.execute("INSERT OR IGNORE INTO matches (user1, user2) VALUES (?,?)", (user1, user2))
            await db.commit()
            # Получаем имена для уведомлений
            async with aiosqlite.connect("asyncpg") as db:
                cur2 = await db.execute("SELECT name FROM users WHERE user_id=?", (uid,))
                name_uid = (await cur2.fetchone())[0]
                cur2 = await db.execute("SELECT name FROM users WHERE user_id=?", (target,))
                name_target = (await cur2.fetchone())[0]
            await call.message.answer("💞 Взаємний лайк! Тепер ви можете спілкуватися у чаті.")
            try:
                await bot.send_message(target, f"💞 У вас новий матч з {name_uid}! Перейдіть у '💬 Мої чати'.")
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

# ---------- Фильтры ----------
@dp.message(F.text == "⚙️ Фільтри")
async def filter_menu(message: types.Message):
    uid = message.from_user.id
    async with aiosqlite.connect("asyncpg") as db:
        cur = await db.execute("SELECT * FROM filters WHERE user_id=?", (uid,))
        filt = await cur.fetchone()
    if filt:
        text = (
            f"Ваші фільтри:\n"
            f"Стать: {filt[1] or 'будь-яка'}\n"
            f"Вік: {filt[2] or 'немає'} - {filt[3] or 'немає'}\n"
            f"Місто: {filt[4] or 'будь-яке'}\n"
        )
    else:
        text = "Фільтри не встановлені."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Стать", callback_data="filter_gender")],
        [InlineKeyboardButton(text="Вік", callback_data="filter_age")],
        [InlineKeyboardButton(text="Місто", callback_data="filter_city")],
        [InlineKeyboardButton(text="Скинути всі", callback_data="filter_reset")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "filter_reset")
async def reset_filters(call: types.CallbackQuery):
    uid = call.from_user.id
    async with aiosqlite.connect("asyncpg") as db:
        await db.execute("DELETE FROM filters WHERE user_id=?", (uid,))
        await db.commit()
    await call.message.answer("Фільтри скинуто.")
    await call.answer()

# --- Настройка пола ---
@dp.callback_query(F.data == "filter_gender")
async def filter_gender_start(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Чоловік", callback_data="gender_male")],
        [InlineKeyboardButton(text="Жінка", callback_data="gender_female")],
        [InlineKeyboardButton(text="Будь-яка", callback_data="gender_any")]
    ])
    await call.message.answer("Оберіть бажану стать:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("gender_"))
async def filter_gender_set(call: types.CallbackQuery):
    val = call.data.split("_")[1]  # male, female, any
    uid = call.from_user.id
    async with aiosqlite.connect("asyncpg") as db:
        await db.execute("""
            INSERT INTO filters (user_id, preferred_gender) VALUES (?,?)
            ON CONFLICT(user_id) DO UPDATE SET preferred_gender=?
        """, (uid, val, val))
        await db.commit()
    await call.message.answer(f"Стать фільтру: {val}")
    await call.answer()

# --- Настройка возраста ---
@dp.callback_query(F.data == "filter_age")
async def filter_age_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(FilterForm.waiting_for_min_age)
    await call.message.answer("Введіть мінімальний вік (число):")
    await call.answer()

@dp.message(FilterForm.waiting_for_min_age)
async def filter_min_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Будь ласка, введіть число.")
        return
    mn = int(message.text)
    await state.update_data(min_age=mn)
    await state.set_state(FilterForm.waiting_for_max_age)
    await message.answer("Тепер введіть максимальний вік (число):")

@dp.message(FilterForm.waiting_for_max_age)
async def filter_max_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Будь ласка, введіть число.")
        return
    mx = int(message.text)
    data = await state.get_data()
    mn = data.get("min_age")
    if mn is None:
        await message.answer("Помилка, почніть заново.")
        await state.clear()
        return
    if mn > mx:
        await message.answer("Мінімальний вік не може бути більшим за максимальний.")
        return
    uid = message.from_user.id
    async with aiosqlite.connect("asyncpg") as db:
        await db.execute("""
            INSERT INTO filters (user_id, min_age, max_age) VALUES (?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET min_age=?, max_age=?
        """, (uid, mn, mx, mn, mx))
        await db.commit()
    await state.clear()
    await message.answer(f"Віковий фільтр встановлено: {mn}-{mx}")

# --- Настройка города ---
@dp.callback_query(F.data == "filter_city")
async def filter_city_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(FilterForm.waiting_for_city)
    await call.message.answer("Введіть місто для пошуку:")
    await call.answer()

@dp.message(FilterForm.waiting_for_city)
async def filter_city_set(message: types.Message, state: FSMContext):
    city = message.text.strip()
    uid = message.from_user.id
    async with aiosqlite.connect("asyncpg") as db:
        await db.execute("""
            INSERT INTO filters (user_id, city) VALUES (?,?)
            ON CONFLICT(user_id) DO UPDATE SET city=?
        """, (uid, city, city))
        await db.commit()
    await state.clear()
    await message.answer(f"Місто для пошуку: {city}")

# ---------- Чаты ----------
@dp.message(F.text == "💬 Мої чати")
async def my_chats(message: types.Message):
    uid = message.from_user.id
    async with aiosqlite.connect("asyncpg") as db:
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
        async with aiosqlite.connect("asyncpg") as db:
            cur = await db.execute("SELECT name FROM users WHERE user_id=?", (other,))
            row = await cur.fetchone()
            name = row[0] if row else "Користувач"
        kb.inline_keyboard.append([InlineKeyboardButton(text=name, callback_data=f"chat_{other}")])
    await message.answer("Оберіть співрозмовника:", reply_markup=kb)

@dp.callback_query(F.data.startswith("chat_"))
async def start_chat(call: types.CallbackQuery, state: FSMContext):
    other_id = int(call.data.split("_")[1])
    uid = call.from_user.id
    await state.update_data(chat_with=other_id)
    await state.set_state(ChatState.active_chat)

    # Получаем имя собеседника
    async with aiosqlite.connect("asyncpg") as db:
        cur = await db.execute("SELECT name FROM users WHERE user_id=?", (other_id,))
        row = await cur.fetchone()
        other_name = row[0] if row else "Співрозмовник"

    # Отправляем клавиатуру с кнопкой выхода
    exit_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚪 Вийти з чату")]],
        resize_keyboard=True
    )
    await call.message.answer(
        f"Ви спілкуєтесь з {other_name}.\nНапишіть повідомлення або натисніть кнопку для виходу.",
        reply_markup=exit_kb
    )
    await call.answer()

@dp.message(ChatState.active_chat, F.text == "🚪 Вийти з чату")
async def exit_chat_button(message: types.Message, state: FSMContext):
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

    # Получаем имя отправителя
    async with aiosqlite.connect("asyncpg") as db:
        cur = await db.execute("SELECT name FROM users WHERE user_id=?", (message.from_user.id,))
        row = await cur.fetchone()
        sender_name = row[0] if row else "Користувач"

    # Пересылаем сообщение собеседнику
    try:
        await bot.send_message(other_id, f"💬 {sender_name}: {message.text}")
    except Exception as e:
        await message.answer(f"Не вдалося надіслати повідомлення: {e}")
        return

    # Сохраняем в историю
    async with aiosqlite.connect("asyncpg") as db:
        match_id = f"{min(message.from_user.id, other_id)}_{max(message.from_user.id, other_id)}"
        await db.execute(
            "INSERT INTO messages (match_id, sender_id, text) VALUES (?,?,?)",
            (match_id, message.from_user.id, message.text)
        )
        await db.commit()

# ---------- Донат ----------
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
    async with aiosqlite.connect("asyncpg") as db:
        await db.execute("UPDATE users SET balance = balance + 5 WHERE user_id = ?", (uid,))
        await db.commit()
    await message.answer("✅ Дякуємо! Ви отримали +5 лайків.")

# ---------- Реферальная система ----------
@dp.message(F.text == "🔗 Моє реферальне посилання")
async def my_ref(message: types.Message):
    async with aiosqlite.connect("asyncpg") as db:
        cur = await db.execute("SELECT ref_code FROM users WHERE user_id=?", (message.from_user.id,))
        code = await cur.fetchone()
        if code:
            bot_info = await bot.get_me()
            link = f"https://t.me/{bot_info.username}?start={code[0]}"
            await message.answer(
                f"Ваше реферальне посилання:\n{link}\nЗа кожного друга ви отримуєте +3 лайки."
            )
        else:
            await message.answer("Спочатку створіть анкету через кнопку '👤 Моя анкета'.")

# ---------- Админ-панель ----------
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Немає доступу.")
        return
    async with aiosqlite.connect("asyncpg") as db:
        users = await db.execute("SELECT COUNT(*) FROM users")
        users = (await users.fetchone())[0]
        matches = await db.execute("SELECT COUNT(*) FROM matches")
        matches = (await matches.fetchone())[0]
        reports = await db.execute("SELECT COUNT(*) FROM reports")
        reports = (await reports.fetchone())[0]
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

# ---------- Запуск ----------
async def main():
    await init_db()
    print("Бот запущено...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())