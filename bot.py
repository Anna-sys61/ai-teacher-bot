import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import config
from database import (init_db, get_student, add_student, set_awaiting_submission,
                      add_submission, save_memory, get_memory_context, update_progress)
from teacher import ask_teacher, evaluate_submission
from image_gen import generate_image
from lessons import LESSONS

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

# Критерии для оценки домашних заданий
CRITERIA_DEFAULT = """
- Понимание темы (1-5): насколько студент разобрался в материале
- Качество выполнения (1-5): насколько аккуратно и полно сделана работа
- Применимость для заработка (1-5): насколько результат можно продать реальному заказчику
"""

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    student = await get_student(message.from_user.id)
    if not student:
        await add_student(message.from_user.id, message.from_user.full_name)
        await message.answer(
            "👋 Привет! Я твой AI-преподаватель курса «Нейросети для заработка: визуал, дизайн, видео».\n\n"
            "За 15 уроков ты научишься создавать изображения, тексты и видео, которые можно продавать "
            "реальным заказчикам: блогерам, селлерам Wildberries, владельцам Telegram-каналов.\n\n"
            "📌 Каждый урок — это шаг к первой оплате.\n"
            "📌 Я проверяю домашние задания, ставлю оценку и даю развёрнутую рецензию.\n"
            "📌 Все уроки сохраняются — ты всегда можешь вернуться и перечитать.\n\n"
            "Напиши /lesson чтобы начать первый урок!"
        )
    else:
        mod, les = student[2], student[3]
        await message.answer(
            f"С возвращением! Ты остановился на модуле {mod}, уроке {les}.\n"
            f"Напиши /lesson чтобы продолжить."
        )

@dp.message(Command("lesson"))
async def cmd_lesson(message: types.Message):
    student = await get_student(message.from_user.id)
    if not student:
        await message.answer("Сначала нажми /start")
        return
    
    mod, les = student[2], student[3]
    lesson_text = LESSONS.get((mod, les))
    
    if not lesson_text:
        await message.answer("🎉 Урок пока не готов. Напиши /progress, чтобы узнать, что пройдено.")
        return
    
    await save_memory(message.from_user.id, f"Начат урок {mod}.{les}")
    
    # Разбиваем длинный текст на части по 4000 символов
    max_length = 4000
    if len(lesson_text) <= max_length:
        await message.answer(lesson_text)
    else:
        parts = []
        text = lesson_text
        while len(text) > max_length:
            split_index = text.rfind('\n', 0, max_length)
            if split_index == -1:
                split_index = max_length
            parts.append(text[:split_index])
            text = text[split_index:].lstrip()
        if text:
            parts.append(text)
        
        for part in parts:
            await message.answer(part)
    
    await set_awaiting_submission(message.from_user.id, True, "text")
@dp.message()
async def handle_message(message: types.Message):
    student = await get_student(message.from_user.id)
    if not student:
        await message.answer("Сначала нажми /start")
        return
    
    if student[4] == 1:  # awaiting_submission
    content = message.text or message.caption or ""
    
    # Проверяем, не похоже ли сообщение на вопрос (а не на домашку)
    question_words = ["как", "почему", "что", "какой", "где", "когда", "кто", "объясни", "подскажи", "расскажи", "помоги", "не понимаю", "не понял", "что такое"]
    is_question = any(content.lower().strip().startswith(word) or content.lower().strip().endswith("?") for word in question_words)
    
    if is_question:
        # Это вопрос преподавателю, а не домашнее задание
        context = await get_memory_context(message.from_user.id)
        response = ask_teacher([{"role": "user", "content": message.text}], student_context=context)
        await save_memory(message.from_user.id, f"Вопрос: {message.text[:100]}")
        await message.answer(response)
        return
    
    # Если это не вопрос — проверяем как домашнее задание
    await message.answer("🔍 Проверяю твою работу... Это займёт несколько секунд.")
        try:
            result = evaluate_submission("text", content, CRITERIA_DEFAULT)
            total_score = result.get("total_score", 0)
            feedback = result.get("feedback", "Оценка не получена, попробуй ещё раз.")
            rubric = result.get("rubric", {})
            
            rubric_text = "\n".join([f"• {k}: {v}/5" for k, v in rubric.items()])
            response = (
                f"📊 ОЦЕНКА: {total_score} из 15 баллов\n\n"
                f"📋 КРИТЕРИИ:\n{rubric_text}\n\n"
                f"📝 РЕЦЕНЗИЯ:\n{feedback}"
            )
            
            mod, les = student[2], student[3]
            await add_submission(message.from_user.id, mod, les, "text", content, total_score, feedback)
            await save_memory(message.from_user.id, f"ДЗ {mod}.{les}, оценка {total_score}/15")
            
            await message.answer(response)
            await set_awaiting_submission(message.from_user.id, False)
            
            # Двигаем прогресс
            await update_progress(message.from_user.id, mod, les + 1)
            await message.answer("✅ Прогресс обновлён! Напиши /lesson чтобы перейти к следующему уроку.")
            
        except Exception as e:
            await message.answer(f"❌ Ошибка при проверке: {e}")
            logging.error(f"Ошибка проверки ДЗ: {e}")
    
    else:
        # Обычный диалог
        context = await get_memory_context(message.from_user.id)
        response = ask_teacher([{"role": "user", "content": message.text}], student_context=context)
        await save_memory(message.from_user.id, f"Диалог: {message.text[:100]}")
        await message.answer(response)

@dp.message(Command("generate"))
async def cmd_generate(message: types.Message):
    prompt = message.text.replace("/generate", "").strip()
    if not prompt:
        await message.answer("Напиши промпт после команды, например: /generate кот в космосе")
        return
    
    await message.answer("🎨 Генерирую изображение...")
    try:
        url = await generate_image(prompt)
        if url:
            await message.answer_photo(url, caption=prompt)
        else:
            await message.answer("⚠️ Генерация изображений пока недоступна в тестовой версии. Но ты можешь использовать Kandinsky или Midjourney вручную!")
    except Exception as e:
        await message.answer(f"⚠️ Генерация изображений пока недоступна. Используй Kandinsky или Midjourney вручную!")

@dp.message(Command("progress"))
async def cmd_progress(message: types.Message):
    student = await get_student(message.from_user.id)
    if not student:
        await message.answer("Сначала нажми /start")
        return
    mod, les = student[2], student[3]
    await message.answer(f"📊 Твой прогресс:\n• Модуль: {mod} из 3\n• Урок: {les} из 15\n\nВсего пройдено: {(mod-1)*5 + (les-1)} уроков из 15")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
