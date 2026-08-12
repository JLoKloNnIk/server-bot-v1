import asyncpg
import os

DATABASE_URL = os.getenv("DATABASE_URL")

async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Таблица пользователей
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                name TEXT,
                age INTEGER,
                city TEXT,
                gender TEXT,
                photo_id TEXT,
                description TEXT,
                interests TEXT,
                ref_code TEXT UNIQUE,
                referred_by BIGINT,
                balance INTEGER DEFAULT 5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Добавляем недостающие колонки (для старых баз)
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS description TEXT")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS interests TEXT")

        # Остальные таблицы без изменений
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS likes (
                from_user BIGINT,
                to_user BIGINT,
                PRIMARY KEY (from_user, to_user)
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS matches (
                user1 BIGINT,
                user2 BIGINT,
                matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user1, user2)
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                inviter_id BIGINT,
                invited_id BIGINT,
                PRIMARY KEY (inviter_id, invited_id)
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                match_id TEXT,
                sender_id BIGINT,
                text TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS filters (
                user_id BIGINT PRIMARY KEY,
                preferred_gender TEXT,
                min_age INTEGER,
                max_age INTEGER,
                city TEXT
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                reporter_id BIGINT,
                reported_id BIGINT,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    finally:
        await conn.close()