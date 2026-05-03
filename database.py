import aiosqlite
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from openai import OpenAI
import config
import uuid
import time

DATABASE = "students.db"

# Qdrant клиент
qdrant_client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)
COLLECTION_NAME = "student_memory"

# DeepSeek клиент для эмбеддингов
deepseek_client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

def init_qdrant():
    collections = qdrant_client.get_collections().collections
    if not any(c.name == COLLECTION_NAME for c in collections):
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
        )

def get_embedding(text):
    response = deepseek_client.embeddings.create(
        model="deepseek-chat",
        input=text
    )
    return response.data[0].embedding

def add_memory_qdrant(student_id, text):
    embedding = get_embedding(text)
    point = PointStruct(
        id=str(uuid.uuid4()),
        vector=embedding,
        payload={"student_id": student_id, "text": text, "timestamp": time.time()}
    )
    qdrant_client.upsert(collection_name=COLLECTION_NAME, points=[point])

def search_memory_qdrant(student_id, query_text, limit=5):
    query_embedding = get_embedding(query_text)
    results = qdrant_client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_embedding,
        query_filter={"must": [{"key": "student_id", "match": {"value": student_id}}]},
        limit=limit,
        with_payload=True
    )
    return [r.payload["text"] for r in results]

# SQLite функции остаются как есть
async def init_db():
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS students (
                telegram_id INTEGER PRIMARY KEY,
                name TEXT,
                current_module INTEGER DEFAULT 1,
                current_lesson INTEGER DEFAULT 1,
                awaiting_submission BOOLEAN DEFAULT 0,
                assignment_type TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                module INTEGER,
                lesson INTEGER,
                type TEXT,
                content TEXT,
                score REAL,
                feedback TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()
    init_qdrant()

async def get_student(telegram_id):
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute("SELECT * FROM students WHERE telegram_id=?", (telegram_id,)) as cursor:
            return await cursor.fetchone()

async def add_student(telegram_id, name):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("INSERT OR IGNORE INTO students (telegram_id, name) VALUES (?, ?)", (telegram_id, name))
        await db.commit()

async def update_progress(telegram_id, module, lesson):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE students SET current_module=?, current_lesson=? WHERE telegram_id=?", (module, lesson, telegram_id))
        await db.commit()

async def set_awaiting_submission(telegram_id, status, assignment_type=None):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE students SET awaiting_submission=?, assignment_type=? WHERE telegram_id=?", (status, assignment_type, telegram_id))
        await db.commit()

async def add_submission(telegram_id, module, lesson, sub_type, content, score, feedback):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("INSERT INTO submissions (telegram_id, module, lesson, type, content, score, feedback) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (telegram_id, module, lesson, sub_type, content, score, feedback))
        await db.commit()

async def get_memory_context(telegram_id, query_text, limit=3):
    """Получает релевантные воспоминания из Qdrant"""
    try:
        memories = search_memory_qdrant(telegram_id, query_text, limit)
        return "\n".join(memories) if memories else ""
    except:
        return ""

async def save_memory(telegram_id, text):
    """Сохраняет событие и в Qdrant, и в SQLite"""
   # add_memory_qdrant(telegram_id, text)
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("INSERT INTO memory (telegram_id, text) VALUES (?, ?)", (telegram_id, text))
        await db.commit()
