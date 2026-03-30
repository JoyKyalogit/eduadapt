
import os 
import asyncpg
from dotenv import load_dotenv

load_dotenv(override=False)



# TEMPORARY TEST - hardcoded to bypass Railway variable issues
DATABASE_URL = os.getenv("DATABASE_URL")

print(f"=== URL START === '{DATABASE_URL[:40]}'")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
DATABASE_URL = os.getenv("DATABASE_URL")



print(f"=== DATABASE_URL === '{DATABASE_URL}'")  # add this

# Railway/Heroku sometimes gives postgres:// — asyncpg needs postgresql://
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

class Database: 
    def __init__(self):
        self.pool = None

    async def connect(self):
        try:
            self.pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10, timeout=10)
            print("Database connected successfully")
        except Exception as e:
            print(f"Database connection failed: {e}")
            raise e

    async def close(self):
        if self.pool:
            await self.pool.close()
            print("Database connection closed")


db = Database()


async def create_tables():
    async with db.pool.acquire() as conn:

        # Students
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL DEFAULT '',
                class_name TEXT NOT NULL DEFAULT 'General',
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)    

        # Quiz Results
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_results (
                id SERIAL PRIMARY KEY,
                student_id INTEGER REFERENCES students(id),
                topic TEXT NOT NULL,
                question TEXT NOT NULL,
                student_answer TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                is_correct BOOLEAN NOT NULL,
                time_taken FLOAT,
                ai_feedback TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Performance History
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS performance_history (
                id SERIAL PRIMARY KEY,
                student_id INTEGER REFERENCES students(id),
                topic TEXT NOT NULL,
                total_attempts INTEGER DEFAULT 0,
                correct_attempts INTEGER DEFAULT 0,
                avg_score FLOAT DEFAULT 0.0,
                avg_time_taken FLOAT DEFAULT 0.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Teachers
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS teachers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Assignments
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                id SERIAL PRIMARY KEY,
                teacher_id INTEGER REFERENCES teachers(id),
                student_id INTEGER REFERENCES students(id),
                title TEXT NOT NULL DEFAULT 'Quiz',
                topic TEXT NOT NULL,
                difficulty TEXT NOT NULL DEFAULT 'medium',
                question TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                hint TEXT,
                class_name TEXT NOT NULL DEFAULT 'General',
                status TEXT NOT NULL DEFAULT 'pending',
                student_answer TEXT,
                is_correct BOOLEAN,
                ai_feedback TEXT,
                time_taken FLOAT,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );
        """)

        # Practice Results (self-practice only, not linked to assignments)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS practice_results (
                id SERIAL PRIMARY KEY,
                student_id INTEGER REFERENCES students(id),
                topic TEXT NOT NULL,
                difficulty TEXT NOT NULL DEFAULT 'medium',
                total_questions INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                score_pct FLOAT NOT NULL DEFAULT 0.0,
                taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    print("Tables created (or already exist)")

    # Migrations
    async with db.pool.acquire() as conn:
        await conn.execute("ALTER TABLE assignments ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT 'Quiz';")
        await conn.execute("ALTER TABLE assignments ADD COLUMN IF NOT EXISTS class_name TEXT NOT NULL DEFAULT 'General';")
        await conn.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS password_hash TEXT NOT NULL DEFAULT '';")
        await conn.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS class_name TEXT NOT NULL DEFAULT 'General';")
        await conn.execute("ALTER TABLE teachers ADD COLUMN IF NOT EXISTS password_hash TEXT NOT NULL DEFAULT '';")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS practice_results (
                id SERIAL PRIMARY KEY,
                student_id INTEGER REFERENCES students(id),
                topic TEXT NOT NULL,
                difficulty TEXT NOT NULL DEFAULT 'medium',
                total_questions INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                score_pct FLOAT NOT NULL DEFAULT 0.0,
                taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("ALTER TABLE assignments ADD COLUMN IF NOT EXISTS deadline TIMESTAMP;")
    print(" Migrations applied")