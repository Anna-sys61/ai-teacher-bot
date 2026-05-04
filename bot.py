@dp.message()
async def handle_message(message: types.Message):
    student = await get_student(message.from_user.id)
    if not student:
        await message.answer("Сначала нажми /start")
        return
    
    # Если это команда — не обрабатываем здесь
    if message.text and message.text.startswith("/"):
        return
    
    # Если ждём домашку
    if student[4] == 1:
        content = message.text or message.caption or ""
        
        # Проверяем, не вопрос ли это
        question_words = ["как", "почему", "что", "какой", "где", "когда", "кто", 
                         "объясни", "подскажи", "расскажи", "помоги", "не понимаю", 
                         "не понял", "что такое", "посоветуешь", "посоветуйте"]
        is_question = any(
            content.lower().strip().startswith(word) or 
            content.lower().strip().endswith("?") 
            for word in question_words
        )
        
        if is_question:
            context = await get_memory_context(message.from_user.id, message.text)
            response = ask_teacher([{"role": "user", "content": message.text}], student_context=context)
            await save_memory(message.from_user.id, f"Вопрос: {message.text[:100]}")
            await message.answer(response)
            return
        
        # Иначе проверяем как домашку
        await message.answer("🔍 Проверяю твою работу... Это займёт несколько секунд.")
        
        try:
            result = evaluate_submission("text", content, CRITERIA_DEFAULT)
            total_score = result.get("total_score", 0)
            feedback = result.get("feedback", "")
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
            await update_progress(message.from_user.id, mod, les + 1)
            await message.answer("✅ Прогресс обновлён! Напиши /lesson чтобы перейти к следующему уроку.")
            
        except Exception as e:
            await message.answer(f"❌ Ошибка при проверке: {e}")
    
    else:
        # Обычный диалог
        context = await get_memory_context(message.from_user.id, message.text)
        response = ask_teacher([{"role": "user", "content": message.text}], student_context=context)
        await save_memory(message.from_user.id, f"Диалог: {message.text[:100]}")
        await message.answer(response)
