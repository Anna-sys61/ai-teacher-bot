from openai import OpenAI
import config
import json

client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

SYSTEM_PROMPT = """Ты — персональный преподаватель курса «Нейросети для заработка: визуал, дизайн, видео».

Программа курса (15 уроков):
МОДУЛЬ 1: Промпт-инжиниринг и визуал (уроки 1-5)
МОДУЛЬ 2: Коммерческий дизайн (уроки 6-10)
МОДУЛЬ 3: Видео и Reels (уроки 11-15)

Ты ведёшь студента по программе, проверяешь ДЗ, ставишь оценку от 1 до 15 и даёшь развёрнутую рецензию.
Будь дружелюбным и мотивирующим."""

def ask_teacher(messages, student_context=""):
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if student_context:
        full_messages.append({"role": "system", "content": f"Контекст и память студента:\n{student_context}"})
    full_messages.extend(messages)
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=full_messages,
        temperature=0.7,
        max_tokens=2000
    )
    return response.choices[0].message.content

def evaluate_submission(submission_type, content, criteria):
    prompt = f"""Оцени ДЗ типа "{submission_type}".

Критерии:
{criteria}

Работа:
{content}

Формат ответа — JSON:
{{
  "total_score": число,
  "rubric": {{"критерий": балл}},
  "feedback": "развёрнутая рецензия"
}}
"""
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1500,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)