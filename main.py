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
from database import init_db, DATABASE_URL
import asyncpg

ADMIN_ID = 7055472251  # ← ЗАМІНІТЬ на свій Telegram ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def get_ref_code(user_id):
    return hashlib.md5(str(user_id).encode()).hexdigest()[:8]

# ---------- Стани ----------
class ProfileForm(StatesGroup):
    name = State()
    age = State()
    city = State()
    gender = State()
    photo = State()

class ChatState(StatesGroup):
    active_chat = State()

class FilterForm(StatesGroup):
    waiting_for_min_age = State()
    waiting_for_max_age = State()
    waiting_for_city = State()

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

# ---------- Старт і реєстрація ----------
@dp.message(CommandStart())
async def start(message: types.Message, command: CommandObject, state: FSMContext):
    user_id = message.from_user.id
    ref = command.args
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT user_id FROM users WHERE user_id=$1", user_id)
            if not user:
                code = get_ref_code(user_id)
                invited_by = None
                if ref:
                    inv = await conn.fetchrow("SELECT user_id FROM users WHERE ref_code=$1", ref)
                    if inv:
                        invited_by = inv['user_id']
                await conn.execute(
                    "INSERT INTO users (user_id, username, ref_code, referred_by, balance) VALUES ($1,$2,$3,$4,$5)",
                    user_id, message.from_user.username, code, invited_by, 5
                )
                if invited_by:
                    await conn.execute("INSERT INTO referrals (inviter_id, invited_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", invited_by, user_id)
                    await conn.execute("UPDATE users SET balance = balance + 3 WHERE user_id=$1", invited_by)
                    await conn.execute("UPDATE users SET balance = balance + 3 WHERE user_id=$1", user_id)
                    await message.answer("🎉 Вас запросив друг! Ви обоє отримали +3 безкоштовні лайки.")
        await state.clear()
        await show_menu(message)

# ---------- Анкета ----------
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
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT user_id FROM users WHERE user_id=$1", uid)
            if user:
                await conn.execute(
                    "UPDATE users SET name=$1, age=$2, city=$3, gender=$4, photo_id=$5 WHERE user_id=$6",
                    data["name"], data["age"], data["city"], data["gender"], photo_id, uid
                )
            else:
                code = get_ref_code(uid)
                await conn.execute(
                    "INSERT INTO users (user_id, username, name, age, city, gender, photo_id, ref_code, balance) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                    uid, message.from_user.username, data["name"], data["age"], data["city"], data["gender"], photo_id, code, 5
                )
    await state.clear()
    await message.answer("✅ Анкету збережено з фото!")
    await show_menu(message)

# ---------- Пошук анкет ----------
@dp.message(F.text == "🔍 Дивитись анкети")
async def search(message: types.Message):
    uid = message.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            # Фільтри
            filt = await conn.fetchrow("SELECT * FROM filters WHERE user_id=$1", uid)
            preferred_gender = filt['preferred_gender'] if filt else None
            min_age = filt['min_age'] if filt else None
            max_age = filt['max_age'] if filt else None
            city = filt['city'] if filt else None

            query = """
                SELECT user_id, name, age, city, photo_id FROM users
                WHERE user_id != $1 AND user_id NOT IN
                    (SELECT to_user FROM likes WHERE from_user = $1)
            """
            params = [uid]
            if preferred_gender and preferred_gender != 'any':
                query += " AND gender = $2"
                params.append(preferred_gender)
            if min_age:
                query += f" AND age >= ${len(params)+1}"
                params.append(min_age)
            if max_age:
                query += f" AND age <= ${len(params)+1}"
                params.append(max_age)
            if city:
                query += f" AND city ILIKE ${len(params)+1}"
                params.append(f"%{city}%")

            query += " ORDER BY RANDOM() LIMIT 1"
            row = await conn.fetchrow(query, *params)
            if not row:
                await message.answer("😔 Поки немає анкет за вашими фільтрами.")
                return
            target_id, name, age, city, photo_id = row['user_id'], row['name'], row['age'], row['city'], row['photo_id']
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
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO likes (from_user, to_user) VALUES ($1,$2) ON CONFLICT DO NOTHING", uid, target)
            mutual = await conn.fetchrow("SELECT * FROM likes WHERE from_user=$1 AND to_user=$2", target, uid)
            if mutual:
                user1, user2 = min(uid, target), max(uid, target)
                await conn.execute("INSERT INTO matches (user1, user2) VALUES ($1,$2) ON CONFLICT DO NOTHING", user1, user2)
                # Імена для сповіщення
                name_uid = await conn.fetchval("SELECT name FROM users WHERE user_id=$1", uid)
                name_target = await conn.fetchval("SELECT name FROM users WHERE user_id=$1", target)
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

# ---------- Фільтри ----------
@dp.message(F.text == "⚙️ Фільтри")
async def filter_menu(message: types.Message):
    uid = message.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            filt = await conn.fetchrow("SELECT * FROM filters WHERE user_id=$1", uid)
    if filt:
        text = (
            f"Ваші фільтри:\n"
            f"Стать: {filt['preferred_gender'] or 'будь-яка'}\n"
            f"Вік: {filt['min_age'] or 'немає'} - {filt['max_age'] or 'немає'}\n"
            f"Місто: {filt['city'] or 'будь-яке'}\n"
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
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM filters WHERE user_id=$1", uid)
    await call.message.answer("Фільтри скинуто.")
    await call.answer()

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
    val = call.data.split("_")[1]
    uid = call.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO filters (user_id, preferred_gender) VALUES ($1,$2)
                ON CONFLICT (user_id) DO UPDATE SET preferred_gender=$2
            """, uid, val)
    await call.message.answer(f"Стать фільтру: {val}")
    await call.answer()

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
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO filters (user_id, min_age, max_age) VALUES ($1,$2,$3)
                ON CONFLICT (user_id) DO UPDATE SET min_age=$2, max_age=$3
            """, uid, mn, mx)
    await state.clear()
    await message.answer(f"Віковий фільтр встановлено: {mn}-{mx}")

@dp.callback_query(F.data == "filter_city")
async def filter_city_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(FilterForm.waiting_for_city)
    await call.message.answer("Введіть місто для пошуку:")
    await call.answer()

@dp.message(FilterForm.waiting_for_city)
async def filter_city_set(message: types.Message, state: FSMContext):
    city = message.text.strip()
    uid = message.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO filters (user_id, city) VALUES ($1,$2)
                ON CONFLICT (user_id) DO UPDATE SET city=$2
            """, uid, city)
    await state.clear()
    await message.answer(f"Місто для пошуку: {city}")

# ---------- Чати ----------
@dp.message(F.text == "💬 Мої чати")
async def my_chats(message: types.Message):
    uid = message.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            matches = await conn.fetch("""
                SELECT user1, user2 FROM matches
                WHERE user1=$1 OR user2=$1
            """, uid)
    if not matches:
        await message.answer("У вас поки немає матчів.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for m in matches:
        other = m['user1'] if m['user2'] == uid else m['user2']
        async with asyncpg.create_pool(DATABASE_URL) as pool:
            async with pool.acquire() as conn:
                name = await conn.fetchval("SELECT name FROM users WHERE user_id=$1", other)
        kb.inline_keyboard.append([InlineKeyboardButton(text=name or "Користувач", callback_data=f"chat_{other}")])
    await message.answer("Оберіть співрозмовника:", reply_markup=kb)

@dp.callback_query(F.data.startswith("chat_"))
async def start_chat(call: types.CallbackQuery, state: FSMContext):
    other_id = int(call.data.split("_")[1])
    uid = call.from_user.id
    await state.update_data(chat_with=other_id)
    await state.set_state(ChatState.active_chat)

    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            other_name = await conn.fetchval("SELECT name FROM users WHERE user_id=$1", other_id)

    exit_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚪 Вийти з чату")]],
        resize_keyboard=True
    )
    await call.message.answer(
        f"Ви спілкуєтесь з {other_name or 'Співрозмовник'}.\nНапишіть повідомлення або натисніть кнопку для виходу.",
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

    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            sender_name = await conn.fetchval("SELECT name FROM users WHERE user_id=$1", message.from_user.id)
    try:
        await bot.send_message(other_id, f"💬 {sender_name or 'Користувач'}: {message.text}")
    except Exception as e:
        await message.answer(f"Не вдалося надіслати повідомлення: {e}")
        return

    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            match_id = f"{min(message.from_user.id, other_id)}_{max(message.from_user.id, other_id)}"
            await conn.execute(
                "INSERT INTO messages (match_id, sender_id, text) VALUES ($1,$2,$3)",
                match_id, message.from_user.id, message.text
            )

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
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET balance = balance + 5 WHERE user_id=$1", uid)
    await message.answer("✅ Дякуємо! Ви отримали +5 лайків.")

# ---------- Реферальна система ----------
@dp.message(F.text == "🔗 Моє реферальне посилання")
async def my_ref(message: types.Message):
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            code = await conn.fetchval("SELECT ref_code FROM users WHERE user_id=$1", message.from_user.id)
    if code:
        bot_info = await bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={code}"
        await message.answer(
            f"Ваше реферальне посилання:\n{link}\nЗа кожного друга ви отримуєте +3 лайки."
        )
    else:
        await message.answer("Спочатку створіть анкету через кнопку '👤 Моя анкета'.")

# ---------- Адмін-панель ----------
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Немає доступу.")
        return
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            users = await conn.fetchval("SELECT COUNT(*) FROM users")
            matches = await conn.fetchval("SELECT COUNT(*) FROM matches")
            reports = await conn.fetchval("SELECT COUNT(*) FROM reports")
            recent = await conn.fetch("SELECT name, age, city FROM users ORDER BY created_at DESC LIMIT 5")
    text = f"📊 Статистика:\n"
    text += f"👥 Користувачів: {users}\n"
    text += f"💞 Матчів: {matches}\n"
    text += f"⚠️ Скарг: {reports}\n\n"
    if recent:
        text += "Останні реєстрації:\n"
        for r in recent:
            text += f"- {r['name']}, {r['age']}, {r['city']}\n"
    await message.answer(text)

# ---------- Запуск ----------
async def main():
    await init_db()
    print("Бот запущено...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())