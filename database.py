import asyncpg
import os

DATABASE_URL = os.getenv("postgresql://postgres:QLgvunyttkJeXGEgJMjqzNIHgqihIjnO@postgres.railway.internal:5432/railway")  # Railway видасть це значення

async def get_db():
    return await asyncpg.connect(DATABASE_URL)

async def init_db():
    conn = await get_db()
    await conn.execute('''CREATE TABLE IF NOT EXISTS users (...)''')
    # ... створення інших таблиць
    await conn.close()