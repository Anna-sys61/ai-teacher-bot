import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from openai import OpenAI
from supabase import create_client, Client
import config
import uuid
import time

SUPABASE_URL = config.SUPABASE_URL
SUPABASE_KEY = config.SUPABASE_KEY

# Supabase клиент
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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

def create_tables():
    """Создаёт таблицы через SQL API Supabase."""
    import requests
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    # Создаём таблицы через REST API
    sql_queries = [
        """
        CREATE TABLE IF NOT EXISTS students (
            telegram_id BIGINT PRIMARY KEY,
            name TEXT,
            current_module INTEGER DEFAULT 1,
            current_lesson INTEGER DEFAULT 1,
            awaiting_submission BOOLEAN DEFAULT FALSE,
            assignment_type TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            module INTEGER,
            lesson INTEGER,
            type TEXT,
            content TEXT,
            score REAL,
            feedback TEXT,
            timestamp TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS memory (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            text TEXT,
            timestamp TIMESTAMPTZ DEFAULT NOW()
        )
        """
    ]
    for sql in sql_queries:
        try:
            response = requests.post(
                f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
                headers=headers,
                json={"query": sql}
            )
        except:
            pass

async def init_db():
    init_qdrant()
    create_tables()

async def get_student(telegram_id):
    try:
        result = supabase.table("students").select("*").eq("telegram_id", telegram_id).execute()
        rows = result.data
        if rows:
            row = rows[0]
            return (row["telegram_id"], row["name"], row["current_module"],
                    row["current_lesson"], row["awaiting_submission"], row.get("assignment_type"))
        return None
    except Exception as e:
        print(f"get_student error: {e}")
        return None

async def add_student(telegram_id, name):
    try:
        supabase.table("students").upsert({
            "telegram_id": telegram_id,
            "name": name
        }).execute()
    except Exception as e:
        print(f"add_student error: {e}")

async def update_progress(telegram_id, module, lesson):
    try:
        supabase.table("students").update({
            "current_module": module,
            "current_lesson": lesson
        }).eq("telegram_id", telegram_id).execute()
    except Exception as e:
        print(f"update_progress error: {e}")

async def set_awaiting_submission(telegram_id, status, assignment_type=None):
    try:
        supabase.table("students").update({
            "awaiting_submission": status,
            "assignment_type": assignment_type
        }).eq("telegram_id", telegram_id).execute()
    except Exception as e:
        print(f"set_awaiting_submission error: {e}")

async def add_submission(telegram_id, module, lesson, sub_type, content, score, feedback):
    try:
        supabase.table("submissions").insert({
            "telegram_id": telegram_id,
            "module": module,
            "lesson": lesson,
            "type": sub_type,
            "content": content,
            "score": score,
            "feedback": feedback
        }).execute()
    except Exception as e:
        print(f"add_submission error: {e}")

async def save_memory(telegram_id, text):
    try:
        supabase.table("memory").insert({
            "telegram_id": telegram_id,
            "text": text
        }).execute()
    except Exception as e:
        print(f"save_memory error: {e}")

async def get_memory_context(telegram_id, query_text=None, limit=5):
    try:
        result = supabase.table("memory").select("text").eq("telegram_id", telegram_id)\
            .order("timestamp", desc=True).limit(limit).execute()
        texts = [row["text"] for row in result.data]
        return "\n".join(texts) if texts else ""
    except Exception as e:
        print(f"get_memory_context error: {e}")
        return ""
