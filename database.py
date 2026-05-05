import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from openai import OpenAI
import config
import uuid
import time
import libsql_client

DATABASE_URL = config.TURSO_URL
DATABASE_TOKEN = config.TURSO_TOKEN

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

def get_client():
    return libsql_client.create_client(
        url=DATABASE_URL,
        auth_token=DATABASE_TOKEN
    )

async def init_db():
    client = get_client()
    try:
        await client.execute('''
            CREATE TABLE IF NOT EXISTS students (
                telegram_id INTEGER PRIMARY KEY,
                name TEXT,
                current_module INTEGER DEFAULT 1,
                current_lesson INTEGER DEFAULT 1,
                awaiting_submission BOOLEAN DEFAULT 0,
                assignment_type TEXT
            )
        ''')
        await client.execute('''
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
        await client.execute('''
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                text TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    finally:
        await client.close()
    init_qdrant()

async def get_student(telegram_id):
    client = get_client()
    try:
        result = await client.execute(
            "SELECT * FROM students WHERE telegram_id = ?",
            (telegram_id,)
        )
        rows = result.rows
        return rows[0] if rows else None
    finally:
        await client.close()

async def add_student(telegram_id, name):
    client = get_client()
    try:
        await client.execute(
            "INSERT OR IGNORE INTO students (telegram_id, name) VALUES (?, ?)",
            (telegram_id, name)
        )
    finally:
        await client.close()

async def update_progress(telegram_id, module, lesson):
    client = get_client()
    try:
        await client.execute(
            "UPDATE students SET current_module=?, current_lesson=? WHERE telegram_id=?",
            (module, lesson, telegram_id)
        )
    finally:
        await client.close()

async def set_awaiting_submission(telegram_id, status, assignment_type=None):
    client = get_client()
    try:
        await client.execute(
            "UPDATE students SET awaiting_submission=?, assignment_type=? WHERE telegram_id=?",
            (status, assignment_type, telegram_id)
        )
    finally:
        await client.close()

async def add_submission(telegram_id, module, lesson, sub_type, content, score, feedback):
    client = get_client()
    try:
        await client.execute(
            "INSERT INTO submissions (telegram_id, module, lesson, type, content, score, feedback) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (telegram_id, module, lesson, sub_type, content, score, feedback)
        )
    finally:
        await client.close()

async def save_memory(telegram_id, text):
    # add_memory_qdrant(telegram_id, text)
    client = get_client()
    try:
        await client.execute(
            "INSERT INTO memory (telegram_id, text) VALUES (?, ?)",
            (telegram_id, text)
        )
    finally:
        await client.close()

async def get_memory_context(telegram_id, query_text=None, limit=5):
    client = get_client()
    try:
        result = await client.execute(
            "SELECT text FROM memory WHERE telegram_id = ? ORDER BY timestamp DESC LIMIT ?",
            (telegram_id, limit)
        )
        texts = [row[0] for row in result.rows]
        return "\n".join(texts) if texts else ""
    finally:
        await client.close()
