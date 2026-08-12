import aiosqlite

DB_NAME = "dating.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Пользователи
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            age INTEGER,
            city TEXT,
            gender TEXT,
            photo_id TEXT,
            ref_code TEXT,
            referred_by INTEGER,
            balance INTEGER DEFAULT 5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Лайки
        await db.execute('''CREATE TABLE IF NOT EXISTS likes (
            from_user INTEGER,
            to_user INTEGER,
            PRIMARY KEY (from_user, to_user)
        )''')

        # Матчи (взаимные лайки)
        await db.execute('''CREATE TABLE IF NOT EXISTS matches (
            user1 INTEGER,
            user2 INTEGER,
            matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user1, user2)
        )''')

        # Рефералы
        await db.execute('''CREATE TABLE IF NOT EXISTS referrals (
            inviter_id INTEGER,
            invited_id INTEGER,
            PRIMARY KEY (inviter_id, invited_id)
        )''')

        # Сообщения чата
        await db.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,          -- "user1_user2"
            sender_id INTEGER,
            text TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Фильтры пользователя
        await db.execute('''CREATE TABLE IF NOT EXISTS filters (
            user_id INTEGER PRIMARY KEY,
            preferred_gender TEXT,
            min_age INTEGER,
            max_age INTEGER,
            city TEXT
        )''')

        # Жалобы
        await db.execute('''CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER,
            reported_id INTEGER,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        await db.commit()