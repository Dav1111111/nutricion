#!/usr/bin/env python
import os
import sys
import logging
import asyncio

"""
Скрипт для запуска бота
"""

if __name__ == "__main__":
    try:
        # Проверка наличия файла .env
        if not os.path.exists('.env'):
            print("[ВНИМАНИЕ] Файл .env не найден. Создайте его и укажите TELEGRAM_BOT_TOKEN и OPENAI_API_KEY.")
            print("Пример содержимого файла .env:")
            print("TELEGRAM_BOT_TOKEN=ваш_токен_бота_telegram")
            print("OPENAI_API_KEY=ваш_ключ_api_openai")
            print("DATABASE_URL=sqlite+aiosqlite:///./bot_database.db")
            sys.exit(1)
            
        # Проверка системных промптов
        print("\033[1;32m[ИНФОРМАЦИЯ] Проверка системных промптов:\033[0m")
        from config.config import config
        print(f"Используемая модель: \033[1;36m{config.GPT_MODEL}\033[0m")
        
        food_prompt_ok = isinstance(config.SYSTEM_PROMPT_FOOD, str) and len(config.SYSTEM_PROMPT_FOOD.strip()) > 10
        nutrition_prompt_ok = isinstance(config.SYSTEM_PROMPT_NUTRITION, str) and len(config.SYSTEM_PROMPT_NUTRITION.strip()) > 10
        
        if food_prompt_ok:
            print("\033[1;32m[✓] Системный промпт для анализа еды содержит нужную фразу\033[0m")
        else:
            print("\033[1;31m[✗] ВНИМАНИЕ! Системный промпт для анализа еды НЕ содержит нужную фразу\033[0m")
            
        if nutrition_prompt_ok:
            print("\033[1;32m[✓] Системный промпт для вопросов о питании содержит нужную фразу\033[0m")
        else:
            print("\033[1;31m[✗] ВНИМАНИЕ! Системный промпт для вопросов о питании НЕ содержит нужную фразу\033[0m")
            
        print("\033[1;36m[СОВЕТ] Для проверки работы системных промптов используйте команду /test_prompt или /reset\033[0m")

        # Запуск бота
        print("\n\033[1;32mЗапуск NutritionBot...\033[0m")
        from bot import main
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем.")
    except Exception as e:
        logging.error(f"Ошибка при запуске бота: {str(e)}")
        print(f"Произошла ошибка: {str(e)}")
        sys.exit(1)
