# NutritionBot - Бот-нутрициолог для Telegram

NutritionBot - это мощный Telegram-бот для анализа питания, который помогает пользователям отслеживать их пищевые привычки, получать детальный анализ блюд и профессиональные рекомендации по питанию.

## Возможности

- **Анализ фотографий еды**: загрузите фото вашего блюда и получите подробный анализ его пищевой ценности, включая калории, БЖУ и микроэлементы
- **Ответы на вопросы о питании**: задавайте любые вопросы о питании и получайте научно обоснованные ответы
- **Персонализированные планы питания**: бот создает индивидуальные планы питания на основе ваших предпочтений и целей
- **Отслеживание приемов пищи**: бот сохраняет историю ваших приемов пищи и предоставляет статистику
- **Установка целей питания**: укажите свои цели (снижение веса, набор массы или поддержание) и получайте соответствующие рекомендации
- **Аналитические отчеты**: получайте подробные отчеты о вашем питании за день, неделю или месяц

## Технологии

- **Python 3.9+**
- **Aiogram 3.2+**: современный фреймворк для создания Telegram-ботов
- **Anthropic API (Claude 3.5 Haiku)**: для анализа изображений и ответов на вопросы
- **SQLAlchemy**: ORM для работы с базой данных
- **SQLite**: легкая база данных для хранения информации о пользователях и их питании

## Установка и запуск

1. Клонируйте репозиторий:
```bash
git clone https://github.com/yourusername/nutrition-bot.git
cd nutrition-bot
```

2. Создайте виртуальное окружение и установите зависимости:
```bash
python -m venv venv
source venv/bin/activate  # На Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Создайте файл `.env` с необходимыми переменными окружения:
```
TELEGRAM_BOT_TOKEN=ваш_токен_бота_telegram
ANTHROPIC_API_KEY=ваш_ключ_api_anthropic
DATABASE_URL=sqlite+aiosqlite:///./bot_database.db
```

4. Запустите бота:
```bash
python bot.py
```

## Структура проекта

```
nutrition_bot/
├── bot.py                  # Основной файл бота
├── config/
│   └── config.py           # Конфигурация
├── database/
│   ├── connection.py       # Подключение к БД
│   └── repository.py       # Репозитории для работы с сущностями
├── handlers/
│   ├── callback_handlers.py # Обработчики inline-кнопок
│   ├── command_handlers.py  # Обработчики команд
│   └── message_handlers.py  # Обработчики сообщений
├── models/
│   └── database.py         # Модели базы данных
├── services/
│   └── ai_service.py       # Сервис для работы с Anthropic API
├── utils/
│   └── image_utils.py      # Утилиты для работы с изображениями
├── images/                 # Директория для хранения изображений
├── requirements.txt        # Зависимости проекта
└── .env                    # Файл с переменными окружения
```

## Использование

1. Найдите бота в Telegram по имени `@your_nutrition_bot`
2. Отправьте команду `/start` для начала работы
3. Используйте одну из следующих функций:
   - Отправьте фотографию еды для получения анализа
   - Задайте вопрос о питании
   - Используйте команду `/plan` для создания плана питания
   - Используйте команду `/goals` для установки целей
   - Используйте команду `/report` для получения отчета о питании

## Команды бота

- `/start` - Начало работы с ботом
- `/help` - Показать справку
- `/clear` - Очистить историю диалога
- `/plan` - Создать персональный план питания
- `/goals` - Установить цели по питанию
- `/prefs` - Указать предпочтения в питании
- `/report` - Получить отчет о питании
- `/stats` - Показать вашу статистику

## Лицензия

Этот проект распространяется под лицензией MIT.

## Автор

Информация об авторе

## Благодарности

- Anthropic за предоставление API Claude для анализа изображений и обработки текста
- Разработчикам Aiogram за отличный фреймворк для создания Telegram-ботов
