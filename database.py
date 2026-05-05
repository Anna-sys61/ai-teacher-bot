import os
import sqlite3
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from openai import OpenAI
import config
import uuid
import time
import urllib.request
import json

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

def turso_query(sql, params=None):
    """Выполняет SQL-запрос к Turso через HTTP API."""
    url = f"{DATABASE_URL.replace('libsql://', 'https://')}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {DATABASE_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": params or []}}
        ]
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read())
        return result

def turso_query_sync(sql, params=None):
    """Синхронная обёртка для turso_query."""
    import asyncio
    return asyncio.run(turso_query(sql, params))

async def init_db():
    init_qdrant()
    try:
        turso_query_sync('''
            CREATE TABLE IF NOT EXISTS students (
                telegram_id INTEGER PRIMARY KEY,
                name TEXT,
                current_module INTEGER DEFAULT 1,
                current_lesson INTEGER DEFAULT 1,
                awaiting_submission BOOLEAN DEFAULT 0,
                assignment_type TEXT
            )
        ''')
        turso_query_sync('''
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
        turso_query_sync('''
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                text TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    except Exception as e:
        print(f"Warning: Could not create Turso tables: {e}")
        print("Falling back to SQLite for this session.")

async def get_student(telegram_id):
    try:
        result = turso_query_sync("SELECT * FROM students WHERE telegram_id = ?", (telegram_id,))
        results = result.get("results", [{}])[0].get("response", {}).get("result", {}).get("rows", [])
        return results[0] if results else None
    except:
        return None

async def add_student(telegram_id, name):
    try:
        turso_query_sync(
            "INSERT OR IGNORE INTO students (telegram_id, name) VALUES (?, ?)",
            (telegram_id, name)
        )
    except:
        pass

async def update_progress(telegram_id, module, lesson):
    try:
        turso_query_sync(
            "UPDATE students SET current_module=?, current_lesson=? WHERE telegram_id=?",
            (module, lesson, telegram_id)
        )
    except:
        pass

async def set_awaiting_submission(telegram_id, status, assignment_type=None):
    try:
        turso_query_sync(
            "UPDATE students SET awaiting_submission=?, assignment_type=? WHERE telegram_id=?",
            (status, assignment_type, telegram_id)
        )
    except:
        pass

async def add_submission(telegram_id, module, lesson, sub_type, content, score, feedback):
    try:
        turso_query_sync(
            "INSERT INTO submissions (telegram_id, module, lesson, type, content, score, feedback) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (telegram_id, module, lesson, sub_type, content, score, feedback)
        )
    except:
        pass

async def save_memory(telegram_id, text):
    # add_memory_qdrant(telegram_id, text)
    try:
        turso_query_sync(
            "INSERT INTO memory (telegram_id, text) VALUES (?, ?)",
            (telegram_id, text)
        )
    except:
        pass

async def get_memory_context(telegram_id, query_text=None, limit=5):
    try:
        result = turso_query_sync(
            "SELECT text FROM memory WHERE telegram_id = ? ORDER BY timestamp DESC LIMIT ?",
            (telegram_id, limit)
        )
        rows = result.get("results", [{}])[0].get("response", {}).get("result", {}).get("rows", [])
        texts = [row[0]["value"] for row in rows if row]
        return "\n".join(texts) if texts else ""
    except:
        return ""
