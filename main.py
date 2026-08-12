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

ADMIN_ID = 7055472251  # ← ЗАМЕНИТЕ на свой Telegram ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def get_ref_code(user_id):
    return hashlib.md5(str(user_id).encode()).hexdigest()[:8]

# ---------- Состояния ----------
class ProfileForm(StatesGroup):
    name = State()
    age = State()
    city = State()
    gender = State()
    photo = State()
    description = State()
    interests = State()

class ChatState(StatesGroup):
    active_chat = State()

class FilterForm(StatesGroup):
    waiting_for_min_age = State()
    waiting_for_max_age = State()
    waiting_for_city = State()

def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="✏️ Заполнить анкету")],
            [KeyboardButton(text="🔍 Смотреть анкеты"), KeyboardButton(text="💰 Донат")],
            [KeyboardButton(text="🔗 Моя реферальная ссылка")],
            [KeyboardButton(text="⚙️ Фильтры"), KeyboardButton(text="💬 Мои чаты")]
        ],
        resize_keyboard=True
    )

async def show_menu(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu_keyboard())

# ---------- Форматирование профиля ----------
def format_profile(row):
    if not row:
        return "Профиль не заполнен."
    text = (
        f"👤 <b>{row['name']}</b>, {row['age']}\n"
        f"📍 {row['city'] or 'Город не указан'}\n"
        f"🚻 {row['gender'] or 'Пол не указан'}"
    )
    if row.get('description'):
        text += f"\n📝 <b>О себе:</b> {row['description']}"
    if row.get('interests'):
        text += f"\n🎯 <b>Интересы:</b> {row['interests']}"
    return text

# ---------- Открытие чата ----------
async def open_chat(user_id, other_id, message: types.Message):
    """Открывает чат для пользователя (отправляет историю и клавиатуру)"""
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            other_name = await conn.fetchval("SELECT name FROM users WHERE user_id=$1", other_id)
            match_id = f"{min(user_id, other_id)}_{max(user_id, other_id)}"
            messages = await conn.fetch("""
                SELECT sender_id, text, timestamp FROM messages
                WHERE match_id = $1
                ORDER BY timestamp DESC LIMIT 10
            """, match_id)
            messages = messages[::-1]  # хронологический порядок

    history_text = "📜 Последние сообщения:\n\n" if messages else "Сообщений пока нет.\n"
    for msg in messages:
        sender = "Вы" if msg['sender_id'] == user_id else other_name or "Собеседник"
        history_text += f"{sender}: {msg['text']}\n"

    exit_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚪 Выйти из чата")]],
        resize_keyboard=True
    )
    await message.answer(
        f"💞 Чат с {other_name or 'Собеседник'} открыт.\n\n{history_text}\n"
        f"Напишите сообщение или нажмите кнопку для выхода.",
        reply_markup=exit_kb
    )

# ---------- Старт и регистрация ----------
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
                    await message.answer("🎉 Вас пригласил друг! Вы оба получили +3 бесплатных лайка.")
        await state.clear()
        await show_menu(message)

# ---------- Просмотр своего профиля ----------
@dp.message(F.text == "👤 Мой профиль")
async def my_profile(message: types.Message):
    uid = message.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", uid)
    if row:
        profile_text = format_profile(row)
        if row['photo_id']:
            await message.answer_photo(row['photo_id'], caption=profile_text, parse_mode="HTML")
        else:
            await message.answer(profile_text, parse_mode="HTML")
    else:
        await message.answer("Профиль ещё не создан. Нажмите '✏️ Заполнить анкету'.")

# ---------- Заполнение/редактирование анкеты ----------
@dp.message(F.text == "✏️ Заполнить анкету")
async def start_profile(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT name, age, city, gender, description, interests FROM users WHERE user_id=$1", uid)
    if user:
        await message.answer(
            "У вас уже есть анкета. При заполнении она будет перезаписана.\n"
            "Продолжить?"
        )
    await state.set_state(ProfileForm.name)
    await message.answer("Как вас зовут?")

@dp.message(ProfileForm.name)
async def profile_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(ProfileForm.age)
    await message.answer("Сколько вам лет? (число)")

@dp.message(ProfileForm.age)
async def profile_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите число.")
        return
    age = int(message.text)
    if age < 16 or age > 100:
        await message.answer("Возраст должен быть от 16 до 100 лет.")
        return
    await state.update_data(age=age)
    await state.set_state(ProfileForm.city)
    await message.answer("Из какого вы города?")

@dp.message(ProfileForm.city)
async def profile_city(message: types.Message, state: FSMContext):
    await state.update_data(city=message.text)
    await state.set_state(ProfileForm.gender)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Мужчина")], [KeyboardButton(text="Женщина")]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("Ваш пол?", reply_markup=kb)

@dp.message(ProfileForm.gender)
async def profile_gender(message: types.Message, state: FSMContext):
    if message.text not in ("Мужчина", "Женщина"):
        await message.answer("Пожалуйста, выберите из клавиатуры.")
        return
    await state.update_data(gender=message.text)
    await state.set_state(ProfileForm.photo)
    await message.answer("Теперь отправьте ваше фото (обязательно).", reply_markup=ReplyKeyboardRemove())

@dp.message(ProfileForm.photo, F.photo)
async def profile_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await state.set_state(ProfileForm.description)
    await message.answer("Расскажите о себе (или нажмите /skip, чтобы пропустить)")

@dp.message(ProfileForm.description, Command("skip"))
async def profile_description_skip(message: types.Message, state: FSMContext):
    await state.update_data(description=None)
    await state.set_state(ProfileForm.interests)
    await message.answer("Теперь укажите ваши интересы через запятую (например: спорт, музыка, кино). Или /skip.")

@dp.message(ProfileForm.description)
async def profile_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(ProfileForm.interests)
    await message.answer("Теперь укажите ваши интересы через запятую (например: спорт, музыка, кино). Или /skip.")

@dp.message(ProfileForm.interests, Command("skip"))
async def profile_interests_skip(message: types.Message, state: FSMContext):
    await state.update_data(interests=None)
    await save_profile(message, state)

@dp.message(ProfileForm.interests)
async def profile_interests(message: types.Message, state: FSMContext):
    await state.update_data(interests=message.text)
    await save_profile(message, state)

async def save_profile(message: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = message.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT user_id FROM users WHERE user_id=$1", uid)
            if user:
                await conn.execute(
                    "UPDATE users SET name=$1, age=$2, city=$3, gender=$4, photo_id=$5, description=$6, interests=$7 WHERE user_id=$8",
                    data["name"], data["age"], data["city"], data["gender"], data.get("photo_id"), data.get("description"), data.get("interests"), uid
                )
            else:
                code = get_ref_code(uid)
                await conn.execute(
                    "INSERT INTO users (user_id, username, name, age, city, gender, photo_id, description, interests, ref_code, balance) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                    uid, message.from_user.username, data["name"], data["age"], data["city"], data["gender"], data.get("photo_id"), data.get("description"), data.get("interests"), code, 5
                )
    await state.clear()
    await message.answer("✅ Анкета сохранена!")
    await show_menu(message)

# ---------- Поиск анкет ----------
@dp.message(F.text == "🔍 Смотреть анкеты")
async def search(message: types.Message):
    uid = message.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            # Фильтры
            filt = await conn.fetchrow("SELECT * FROM filters WHERE user_id=$1", uid)
            preferred_gender = filt['preferred_gender'] if filt else None
            min_age = filt['min_age'] if filt else None
            max_age = filt['max_age'] if filt else None
            city = filt['city'] if filt else None

            query = """
                SELECT user_id, name, age, city, photo_id, description, interests FROM users
                WHERE user_id != $1 AND user_id NOT IN
                    (SELECT to_user FROM likes WHERE from_user = $1)
                    AND user_id NOT IN (SELECT blocked_user_id FROM blocks WHERE user_id = $1)
                    AND user_id NOT IN (SELECT user_id FROM blocks WHERE blocked_user_id = $1)
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
                await message.answer("😔 Пока нет анкет по вашим фильтрам.")
                return
            target_id = row['user_id']
            caption = (
                f"👤 <b>{row['name']}</b>, {row['age']}\n"
                f"📍 {row['city'] or 'Город не указан'}"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="❤️", callback_data=f"like_{target_id}"),
                    InlineKeyboardButton(text="👎", callback_data="skip"),
                    InlineKeyboardButton(text="Подробнее", callback_data=f"details_{target_id}")
                ]
            ])
            if row['photo_id']:
                await message.answer_photo(row['photo_id'], caption=caption, parse_mode="HTML", reply_markup=kb)
            else:
                await message.answer(caption, parse_mode="HTML", reply_markup=kb)

# Обработчик кнопки "Подробнее"
@dp.callback_query(F.data.startswith("details_"))
async def show_details(call: types.CallbackQuery):
    target_id = int(call.data.split("_")[1])
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", target_id)
    if not user:
        await call.answer("Пользователь не найден.", show_alert=True)
        return

    text = format_profile(user)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❤️ Лайкнуть", callback_data=f"like_{target_id}"),
            InlineKeyboardButton(text="👎", callback_data="skip")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_search")]
    ])

    if user['photo_id']:
        await call.message.answer_photo(user['photo_id'], caption=text, parse_mode="HTML", reply_markup=kb)
    else:
        await call.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data == "back_to_search")
async def back_to_search(call: types.CallbackQuery):
    await call.message.delete()
    await search(call.message)

# Обработчик лайка
@dp.callback_query(F.data.startswith("like_"))
async def like(call: types.CallbackQuery, state: FSMContext):
    target = int(call.data.split("_")[1])
    uid = call.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            # Проверяем баланс
            balance = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1", uid)
            if balance is None:
                await call.answer("Сначала создайте анкету!", show_alert=True)
                return
            if balance <= 0:
                await call.answer("У вас закончились лайки! Пополните через 💰 Донат или пригласите друзей.", show_alert=True)
                return

            # Сохраняем лайк и уменьшаем баланс
            await conn.execute("INSERT INTO likes (from_user, to_user) VALUES ($1,$2) ON CONFLICT DO NOTHING", uid, target)
            await conn.execute("UPDATE users SET balance = balance - 1 WHERE user_id=$1", uid)

            # Проверяем взаимность
            mutual = await conn.fetchrow("SELECT * FROM likes WHERE from_user=$1 AND to_user=$2", target, uid)
            if mutual:
                # Создаём мэтч
                user1, user2 = min(uid, target), max(uid, target)
                await conn.execute("INSERT INTO matches (user1, user2) VALUES ($1,$2) ON CONFLICT DO NOTHING", user1, user2)
                name_uid = await conn.fetchval("SELECT name FROM users WHERE user_id=$1", uid)
                name_target = await conn.fetchval("SELECT name FROM users WHERE user_id=$1", target)

                # Открываем чат для текущего пользователя
                await state.update_data(chat_with=target)
                await state.set_state(ChatState.active_chat)
                await open_chat(uid, target, call.message)

                # Уведомляем второго пользователя с кнопкой "Открыть чат"
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Открыть чат", callback_data=f"chat_{uid}")]
                ])
                try:
                    await bot.send_message(
                        target,
                        f"💞 У вас новый мэтч с {name_uid}!",
                        reply_markup=kb
                    )
                except:
                    pass
            else:
                # Анонимное уведомление получателю
                try:
                    await bot.send_message(target, "❤️ Кто-то лайкнул вашу анкету! Зайдите в поиск, чтобы возможно ответить взаимностью.")
                except Exception:
                    pass
                await call.message.answer(f"Лайк отправлен! Осталось лайков: {balance-1}")

    await call.message.delete()
    await search(call.message)

@dp.callback_query(F.data == "skip")
async def skip(call: types.CallbackQuery):
    await call.message.delete()
    await search(call.message)

# ---------- Фильтры ----------
@dp.message(F.text == "⚙️ Фильтры")
async def filter_menu(message: types.Message):
    uid = message.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            filt = await conn.fetchrow("SELECT * FROM filters WHERE user_id=$1", uid)
    if filt:
        text = (
            f"Ваши фильтры:\n"
            f"Пол: {filt['preferred_gender'] or 'любой'}\n"
            f"Возраст: {filt['min_age'] or 'нет'} - {filt['max_age'] or 'нет'}\n"
            f"Город: {filt['city'] or 'любой'}\n"
        )
    else:
        text = "Фильтры не установлены."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пол", callback_data="filter_gender")],
        [InlineKeyboardButton(text="Возраст", callback_data="filter_age")],
        [InlineKeyboardButton(text="Город", callback_data="filter_city")],
        [InlineKeyboardButton(text="Сбросить все", callback_data="filter_reset")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "filter_reset")
async def reset_filters(call: types.CallbackQuery):
    uid = call.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM filters WHERE user_id=$1", uid)
    await call.message.answer("Фильтры сброшены.")
    await call.answer()

@dp.callback_query(F.data == "filter_gender")
async def filter_gender_start(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мужчина", callback_data="gender_male")],
        [InlineKeyboardButton(text="Женщина", callback_data="gender_female")],
        [InlineKeyboardButton(text="Любой", callback_data="gender_any")]
    ])
    await call.message.answer("Выберите желаемый пол:", reply_markup=kb)
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
    await call.message.answer(f"Фильтр по полу: {val}")
    await call.answer()

@dp.callback_query(F.data == "filter_age")
async def filter_age_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(FilterForm.waiting_for_min_age)
    await call.message.answer("Введите минимальный возраст (число):")
    await call.answer()

@dp.message(FilterForm.waiting_for_min_age)
async def filter_min_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите число.")
        return
    mn = int(message.text)
    await state.update_data(min_age=mn)
    await state.set_state(FilterForm.waiting_for_max_age)
    await message.answer("Теперь введите максимальный возраст (число):")

@dp.message(FilterForm.waiting_for_max_age)
async def filter_max_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите число.")
        return
    mx = int(message.text)
    data = await state.get_data()
    mn = data.get("min_age")
    if mn is None:
        await message.answer("Ошибка, начните заново.")
        await state.clear()
        return
    if mn > mx:
        await message.answer("Минимальный возраст не может быть больше максимального.")
        return
    uid = message.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO filters (user_id, min_age, max_age) VALUES ($1,$2,$3)
                ON CONFLICT (user_id) DO UPDATE SET min_age=$2, max_age=$3
            """, uid, mn, mx)
    await state.clear()
    await message.answer(f"Возрастной фильтр установлен: {mn}-{mx}")

@dp.callback_query(F.data == "filter_city")
async def filter_city_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(FilterForm.waiting_for_city)
    await call.message.answer("Введите город для поиска:")
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
    await message.answer(f"Город для поиска: {city}")

# ---------- Чаты ----------
@dp.message(F.text == "💬 Мои чаты")
async def my_chats(message: types.Message):
    uid = message.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            matches = await conn.fetch("""
                SELECT user1, user2 FROM matches
                WHERE user1=$1 OR user2=$1
            """, uid)
    if not matches:
        await message.answer("У вас пока нет мэтчей.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for m in matches:
        other = m['user1'] if m['user2'] == uid else m['user2']
        async with asyncpg.create_pool(DATABASE_URL) as pool:
            async with pool.acquire() as conn:
                name = await conn.fetchval("SELECT name FROM users WHERE user_id=$1", other)
        kb.inline_keyboard.append([InlineKeyboardButton(text=name or "Пользователь", callback_data=f"chat_{other}")])
    await message.answer("Выберите собеседника:", reply_markup=kb)

@dp.callback_query(F.data.startswith("chat_"))
async def start_chat(call: types.CallbackQuery, state: FSMContext):
    other_id = int(call.data.split("_")[1])
    uid = call.from_user.id
    # Проверяем, существует ли матч (чат не закрыт)
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            match_exists = await conn.fetchval(
                "SELECT 1 FROM matches WHERE (user1=$1 AND user2=$2) OR (user1=$2 AND user2=$1)",
                uid, other_id
            )
            if not match_exists:
                await call.answer("Чат закрыт, так как собеседник вышел.", show_alert=True)
                await call.message.delete()
                return

            blocked = await conn.fetchval("SELECT 1 FROM blocks WHERE user_id=$1 AND blocked_user_id=$2", uid, other_id)
            if blocked:
                await call.answer("Вы заблокировали этого пользователя.", show_alert=True)
                return

    await state.update_data(chat_with=other_id)
    await state.set_state(ChatState.active_chat)
    await open_chat(uid, other_id, call.message)
    await call.answer()

@dp.message(ChatState.active_chat, F.text == "🚪 Выйти из чата")
async def exit_chat_button(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    other_id = data.get("chat_with")
    await state.clear()
    await show_menu(message)

    if other_id:
        # Удаляем матч, чтобы закрыть комнату для обоих
        async with asyncpg.create_pool(DATABASE_URL) as pool:
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM matches WHERE (user1=$1 AND user2=$2) OR (user1=$2 AND user2=$1)",
                    uid, other_id
                )

        # Уведомляем второго пользователя
        try:
            await bot.send_message(
                other_id,
                "🚪 Собеседник вышел из чата. Комната закрыта."
            )
        except:
            pass

        # Предлагаем действия текущему пользователю
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"block_{other_id}"),
                InlineKeyboardButton(text="⚠️ Пожаловаться", callback_data=f"report_{other_id}")
            ]
        ])
        await message.answer("Вы вышли из чата. Что хотите сделать?", reply_markup=kb)

@dp.message(ChatState.active_chat, F.text)
async def chat_message(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    other_id = data.get("chat_with")
    if not other_id:
        await message.answer("Ошибка, выйдите из чата.")
        await state.clear()
        await show_menu(message)
        return

    # Проверяем, существует ли ещё матч (чат открыт)
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            match_exists = await conn.fetchval(
                "SELECT 1 FROM matches WHERE (user1=$1 AND user2=$2) OR (user1=$2 AND user2=$1)",
                uid, other_id
            )
    if not match_exists:
        await message.answer("Этот чат закрыт, так как собеседник вышел.")
        await state.clear()
        await show_menu(message)
        return

    # Получаем имя отправителя
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            sender_name = await conn.fetchval("SELECT name FROM users WHERE user_id=$1", uid)

    # Создаём клавиатуру с кнопкой "Ответить"
    reply_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"chat_{uid}")]
    ])

    try:
        await bot.send_message(other_id, f"💬 {sender_name or 'Пользователь'}: {message.text}", reply_markup=reply_kb)
    except Exception as e:
        await message.answer(f"Не удалось отправить сообщение: {e}")
        return

    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            match_id = f"{min(uid, other_id)}_{max(uid, other_id)}"
            await conn.execute(
                "INSERT INTO messages (match_id, sender_id, text) VALUES ($1,$2,$3)",
                match_id, uid, message.text
            )

# ---------- Блокировка и жалоба ----------
@dp.callback_query(F.data.startswith("block_"))
async def block_user(call: types.CallbackQuery):
    blocked_id = int(call.data.split("_")[1])
    uid = call.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO blocks (user_id, blocked_user_id) VALUES ($1,$2)
                ON CONFLICT DO NOTHING
            """, uid, blocked_id)
            # Удаляем лайки и мэтчи, чтобы они больше не видели друг друга
            await conn.execute("DELETE FROM likes WHERE from_user=$1 AND to_user=$2", uid, blocked_id)
            await conn.execute("DELETE FROM likes WHERE from_user=$1 AND to_user=$2", blocked_id, uid)
            await conn.execute("DELETE FROM matches WHERE (user1=$1 AND user2=$2) OR (user1=$2 AND user2=$1)", uid, blocked_id)
    await call.message.answer("🚫 Пользователь заблокирован. Он больше не появится в поиске.")
    await call.answer()

@dp.callback_query(F.data.startswith("report_"))
async def report_user(call: types.CallbackQuery):
    reported_id = int(call.data.split("_")[1])
    uid = call.from_user.id
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO reports (reporter_id, reported_id, reason)
                VALUES ($1, $2, $3)
            """, uid, reported_id, "Пожаловался из чата")
    await call.message.answer("⚠️ Жалоба отправлена администрации. Спасибо!")
    await call.answer()

# ---------- Донат ----------
@dp.message(F.text == "💰 Донат")
async def donate(message: types.Message):
    prices = [LabeledPrice(label="5 дополнительных лайков", amount=50)]
    await message.answer_invoice(
        title="Больше лайков",
        description="Получите 5 лайков для поиска",
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
    await message.answer("✅ Спасибо! Вы получили +5 лайков.")

# ---------- Реферальная система ----------
@dp.message(F.text == "🔗 Моя реферальная ссылка")
async def my_ref(message: types.Message):
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            code = await conn.fetchval("SELECT ref_code FROM users WHERE user_id=$1", message.from_user.id)
    if code:
        bot_info = await bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={code}"
        await message.answer(
            f"Ваша реферальная ссылка:\n{link}\nЗа каждого друга вы получаете +3 лайка."
        )
    else:
        await message.answer("Сначала создайте анкету через кнопку '✏️ Заполнить анкету'.")

# ---------- Админ-панель ----------
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        async with pool.acquire() as conn:
            users = await conn.fetchval("SELECT COUNT(*) FROM users")
            matches = await conn.fetchval("SELECT COUNT(*) FROM matches")
            reports = await conn.fetchval("SELECT COUNT(*) FROM reports")
            recent = await conn.fetch("SELECT name, age, city FROM users ORDER BY created_at DESC LIMIT 5")
    text = f"📊 Статистика:\n"
    text += f"👥 Пользователей: {users}\n"
    text += f"💞 Мэтчей: {matches}\n"
    text += f"⚠️ Жалоб: {reports}\n\n"
    if recent:
        text += "Последние регистрации:\n"
        for r in recent:
            text += f"- {r['name']}, {r['age']}, {r['city']}\n"
    await message.answer(text)

# ---------- Запуск ----------
async def main():
    await init_db()
    print("Бот запущен...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
