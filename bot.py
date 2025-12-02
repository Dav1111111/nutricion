import os
import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import config
from database.connection import db_connection
from handlers.command_handlers import register_command_handlers
from handlers.registration_handlers import register_registration_handlers
from handlers.message_handlers import register_message_handlers
from handlers.callback_handlers import register_callback_handlers
from services.ai_service import ai_service
from services.payment_service import payment_service
from services.subscription_renewal_service import subscription_renewal_service
from database.subscription_repository import subscription_repository

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Создание сессии и бота
session = AiohttpSession()
bot = Bot(token=config.TELEGRAM_BOT_TOKEN, session=session)

# Создание диспетчера
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Регистрация обработчиков
register_command_handlers(dp)
register_registration_handlers(dp)
register_message_handlers(dp)
register_callback_handlers(dp)

# Функция для передачи сессии БД в обработчики
async def db_session_middleware(handler, event, data):
    """Миддлвар для передачи сессии БД в обработчики"""
    async with db_connection.async_session() as session:
        data["db"] = session
        return await handler(event, data)

# Установка миддлвара
dp.update.middleware(db_session_middleware)

async def main():
    """Основная функция запуска бота"""
    try:
        # Инициализация базы данных
        await db_connection.init_db()
        logger.info("База данных инициализирована")

        # Создание директории для изображений, если не существует
        os.makedirs(config.IMAGES_DIR, exist_ok=True)

        # Устанавливаем список команд, чтобы они появились в системном синем меню Telegram
        commands = [
            ("anketa", "📝 Анкета"),
            ("calories", "🎯 Задать цель"),
            ("day_calories", "📊 Калории за день"),
            ("today_meals", "📋 Что я ел сегодня"),
            ("reset_today", "♻️ Сбросить данные"),
            ("subscription", "💳 Подписка"),
            ("feedback", "Отправить обратную связь")
        ]

        await bot.set_my_commands([
            types.BotCommand(command=c[0], description=c[1]) for c in commands
        ])
        
        # Передаём экземпляр бота в сервис автопродления чтобы избежать циклических импортов
        subscription_renewal_service.set_bot(bot)
        renewal_task = asyncio.create_task(subscription_renewal_service.start())

        # Запуск бота
        logger.info("Запуск бота (OpenAI)...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {str(e)}")
    finally:
        # Остановка сервиса автопродления
        await subscription_renewal_service.stop()
        if 'renewal_task' in locals():
            renewal_task.cancel()
            try:
                await renewal_task
            except asyncio.CancelledError:
                pass
        # Закрытие сессии бота
        await bot.session.close()

if __name__ == '__main__':
    # Запуск асинхронной функции main
    asyncio.run(main())
