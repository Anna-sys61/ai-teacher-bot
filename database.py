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

async def init_db():
    init_qdrant()
    try:
        supabase.table("students").select("*").limit(1).execute()
    except:
        # Таблицы ещё не созданы — создаём
        supabase.query("""
            CREATE TABLE IF NOT EXISTS students (
                telegram_id BIGINT PRIMARY KEY,
                name TEXT,
                current_module INTEGER DEFAULT 1,
                current_lesson INTEGER DEFAULT 1,
                awaiting_submission BOOLEAN DEFAULT FALSE,
                assignment_type TEXT
            )
        """).execute()
        supabase.query("""
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
        """).execute()
        supabase.query("""
            CREATE TABLE IF NOT EXISTS memory (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT,
                text TEXT,
                timestamp TIMESTAMPTZ DEFAULT NOW()
            )
        """).execute()

async def get_student(telegram_id):
    try:
        result = supabase.table("students").select("*").eq("telegram_id", telegram_id).execute()
        rows = result.data
        if rows:
            row = rows[0]
            return (row["telegram_id"], row["name"], row["current_module"],
                    row["current_lesson"], row["awaiting_submission"], row.get("assignment_type"))
        return None
    except:
        return None

async def add_student(telegram_id, name):
    try:
        supabase.table("students").upsert({
            "telegram_id": telegram_id,
            "name": name
        }).execute()
    except:
        pass

async def update_progress(telegram_id, module, lesson):
    try:
        supabase.table("students").update({
            "current_module": module,
            "current_lesson": lesson
        }).eq("telegram_id", telegram_id).execute()
    except:
        pass

async def set_awaiting_submission(telegram_id, status, assignment_type=None):
    try:
        supabase.table("students").update({
            "awaiting_submission": status,
            "assignment_type": assignment_type
        }).eq("telegram_id", telegram_id).execute()
    except:
        pass

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
    except:
        pass

async def save_memory(telegram_id, text):
    # add_memory_qdrant(telegram_id, text)
    try:
        supabase.table("memory").insert({
            "telegram_id": telegram_id,
            "text": text
        }).execute()
    except:
        pass

async def get_memory_context(telegram_id, query_text=None, limit=5):
    try:
        result = supabase.table("memory").select("text").eq("telegram_id", telegram_id)\
            .order("timestamp", desc=True).limit(limit).execute()
        texts = [row["text"] for row in result.data]
        return "\n".join(texts) if texts else ""
    except:
        return ""
