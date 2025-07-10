import os
import logging
from dotenv import load_dotenv

# Загружаем .env, перекрывая уже установленные переменные, чтобы исключить ситуацию,
# когда в окружении сохранён устаревший токен, а в .env лежит актуальный.
load_dotenv(override=True)

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

class Config:
    """Класс для хранения конфигурации"""

    # Токен Telegram бота
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не найден в переменных окружения")
        raise ValueError("TELEGRAM_BOT_TOKEN не найден в переменных окружения")

    # Ключ API Anthropic Claude (более не используется).
    # Оставляем переменную для совместимости, но она больше не обязательна.
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

    # URL базы данных
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot_database.db")

    # Максимальный размер изображения
    MAX_IMAGE_SIZE = 4 * 1024 * 1024  # 4MB

    # Директория для сохранения изображений
    IMAGES_DIR = os.getenv("IMAGES_DIR", "images")
    os.makedirs(IMAGES_DIR, exist_ok=True)

    # Модели Claude
    # CLAUDE_MODEL = "claude-3-opus-20240229"  # Обновлено для совместимости с новой версией API и поддержкой изображений
    CLAUDE_MODEL = "claude-3-5-haiku-20241022"  # Обновлено на Claude 3.5 Haiku - быстрая модель с улучшенными возможностями

    # --- OpenAI ---
    # API-ключ для OpenAI (нужен, если хотите использовать GPT-4(o) Vision)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    # Модель Vision/Text. Пример: "gpt-4o-mini" или "gpt-4o"
    GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4o-mini")

    # Флаг, указывающий какого провайдера использовать: по умолчанию "openai"
    AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").lower()

    # Максимальное количество токенов в ответе
    MAX_TOKENS = 2000

    # Максимальное количество сообщений в истории
    MAX_HISTORY_LENGTH = 10

    # Системные промпты
    SYSTEM_PROMPT_FOOD = """
    Ты опытный нутрициолог и эксперт по питанию. Твоя задача - анализировать фотографии блюд и отвечать на вопросы о питании.

    Когда анализируешь блюдо на фотографии, предоставь следующую информацию:
    1. Общее описание блюда и его ингредиентов
    2. Примерное количество калорий и БЖУ (белки, жиры, углеводы) на порцию
    3. Микроэлементы и витамины
    4. Плюсы и минусы блюда с точки зрения здорового питания
    5. Советы по улучшению или альтернативы

    Отвечай на русском языке. Используй научно обоснованную информацию. Если ты не уверен в точных значениях, укажи приблизительные, но отметь, что это оценка.

    Форматируй ответ с использованием markdown для лучшей читаемости.
    """

    SYSTEM_PROMPT_NUTRITION = """
    Ты опытный нутрициолог и эксперт по питанию. Твоя задача - отвечать на вопросы о питании, диетах и здоровом образе жизни.

    Придерживайся следующих принципов:
    1. Используй только научно обоснованную информацию
    2. Если информация противоречива или недостаточно изучена, укажи на это
    3. Не давай категоричных медицинских рекомендаций
    4. Учитывай, что каждый человек индивидуален
    5. Когда это уместно, предлагай обратиться к врачу или диетологу

    Отвечай на русском языке. Форматируй ответ с использованием markdown для лучшей читаемости.
    """

    # Цена подписки по умолчанию
    SUBSCRIPTION_PRICE = int(os.getenv("SUBSCRIPTION_PRICE", "399"))

    # --- Параметры подписки и бесплатных лимитов ---
    SUBSCRIPTION_DAYS = int(os.getenv("SUBSCRIPTION_DAYS", "30"))
    FREE_PHOTO_LIMIT = int(os.getenv("FREE_PHOTO_LIMIT", "5"))
    FREE_QUESTION_LIMIT = int(os.getenv("FREE_QUESTION_LIMIT", "10"))

    # Данные ЮKassa (опционально, используются только при оформлении подписки)
    YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
    YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")

    # ID администратора для получения обратной связи
    ADMIN_ID = int(os.getenv("ADMIN_ID", "780848273"))

# Создание экземпляра конфигурации
config = Config()

# Проверка системных промптов
if not config.SYSTEM_PROMPT_FOOD or len(config.SYSTEM_PROMPT_FOOD.strip()) < 10:
    logger.warning("ВНИМАНИЕ! Системный промпт для анализа еды пуст или слишком короткий")

if not config.SYSTEM_PROMPT_NUTRITION or len(config.SYSTEM_PROMPT_NUTRITION.strip()) < 10:
    logger.warning("ВНИМАНИЕ! Системный промпт для ответов о питании пуст или слишком короткий")

logger.info(f"Конфигурация загружена успешно. Используемая модель: {config.CLAUDE_MODEL}")
