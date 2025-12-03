import logging
from typing import Dict, List, Optional, Any
import json
from datetime import datetime

from aiogram import types, F
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

from handlers.command_handlers import UserStates
from services.ai_service import ai_service
from database.repository import (
    user_repository,
    message_repository,
    meal_log_repository,
    ingredient_repository,
    feedback_repository,
    nutritional_goal_repository,
    user_preference_repository,
)
from database.subscription_repository import subscription_repository, usage_repository
from utils.image_utils import image_utils
from config.config import config
from services.graspil_service import graspil_service

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from config.config import config
MAX_IMAGE_SIZE = config.MAX_IMAGE_SIZE

class MessageHandlers:
    """Обработчики сообщений бота"""

    # Ключевые слова/корни, указывающие, что вопрос связан с питанием
    _NUTRITION_KEYWORDS = [
        # русские - питание и нутрициология
        "калор", "ккал", "белк", "жир", "углевод", "витамин", "минера", "микроэлемент", "диет", "питани",
        "нутри", "еда", "бжу", "сахар", "клетчат", "гликем", "инсулин", "гидрата", "вода", "перекус", "рацион",
        "голод", "фастинг", "кишеч", "метабол", "ожирен", "ИМТ", "масса тела", "холестерин", "триглиц", "омега",
        # продукты
        "сметан", "фрукт", "овощ", "молок", "сыр", "йогурт", "творог", "рыб", "мяс", "куриц", "говядин", "свинин", "яиц",
        "хлеб", "круп", "каш", "рис", "гречк", "овсян", "макарон", "паст", "картоф", "картош",
        # рецепты и приготовление
        "рецепт", "приготов", "готов", "блюд", "завтрак", "обед", "ужин", "полдник",
        "суп", "салат", "соус", "запекан", "варен", "жарен", "тушен", "парово", "гриль",
        "смузи", "коктейл", "десерт", "выпечк", "торт", "пирог", "печень", "оладь", "блин",
        "бутерброд", "сэндвич", "пицц", "роллы", "суши",
        # похудение и фитнес питание
        "похуд", "сброс", "вес", "стройн", "худе", "набор массы", "сушк", "протеин", "пп ", " пп",
        # английские термины
        "calorie", "protein", "fat", "carb", "nutrition", "diet", "fiber", "sugar", "glycemic", "fasting", "meal",
        "cholesterol", "omega", "hydration", "recipe", "breakfast", "lunch", "dinner"
    ]

    @staticmethod
    def _is_nutrition_question(text: str) -> bool:
        """Проверка, связан ли вопрос с питанием по ключевым словам"""
        t = text.lower()
        return any(kw in t for kw in MessageHandlers._NUTRITION_KEYWORDS)

    @staticmethod
    async def process_photo(message: types.Message, state: FSMContext, db: AsyncSession):
        """Обработчик фотографий блюд"""
        processing_msg = None
        try:
            # Получение пользователя
            user = await user_repository.get_or_create_user(
                db,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )

            # Проверка лимитов
            can_use = await usage_repository.can_use_photo(db, user.id)
            if not can_use:
                usage = await usage_repository.get_or_create_usage(db, user.id)
                await message.answer(
                    f"❌ Вы исчерпали лимит бесплатных анализов фото ({config.FREE_PHOTO_LIMIT} шт.)\n\n"
                    f"Для продолжения оформите подписку за {config.SUBSCRIPTION_PRICE} руб./месяц",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text="💳 Оформить подписку", callback_data="subscribe")]
                        ]
                    )
                )
                return

            # Отправка уведомления о начале анализа
            processing_msg = await message.answer("🔍 Анализирую ваше блюдо... Это может занять до 30 секунд.")
            
            logger.info(f"Начат анализ фотографии блюда от пользователя {user.id}")

            # Проверка наличия фотографий
            if not message.photo or len(message.photo) == 0:
                await message.answer("⚠️ Фотография не найдена в сообщении. Пожалуйста, отправьте фотографию блюда.")
                if processing_msg and hasattr(processing_msg, 'message_id'):
                    await message.bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
                return

            # Получение фотографии самого высокого разрешения
            photo = message.photo[-1]
            file_info = await message.bot.get_file(photo.file_id)
            
            logger.info(f"Получена фотография размером {file_info.file_size} байт")

            # Проверка размера файла
            if file_info.file_size > MAX_IMAGE_SIZE:
                await message.answer("⚠️ Изображение слишком большое. Максимальный размер - 4MB.")
                await message.bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
                return

            # Загрузка файла
            file_content = await message.bot.download_file(file_info.file_path)
            file_bytes = file_content.read()

            # Оптимизация изображения
            optimized_image = image_utils.optimize_image(file_bytes)
            
            logger.info("Изображение успешно оптимизировано")

            # Сохранение изображения
            image_path = await image_utils.save_image(optimized_image, user.id)
            
            logger.info(f"Изображение сохранено по пути: {image_path}")

            # Получение истории сообщений
            history = await message_repository.get_conversation_history(db, user.id)

            # Получение текста сообщения или использование значения по умолчанию
            user_text = message.caption if message.caption else "Проанализируй детально это блюдо и предоставь полную информацию о БЖУ, калорийности и пищевой ценности. Укажи примерный вес порции."

            # Расширенный запрос для более подробного анализа
            user_message = (f"{user_text}\n\n"
                          f"Пожалуйста, проведите детальный анализ этого блюда, включая следующую информацию:\n"
                          f"1. Определите, что это за блюдо\n"
                          f"2. Укажите примерную калорийность (ккал)\n"
                          f"3. Предоставьте полный БЖУ анализ (белки, жиры, углеводы) в граммах\n"
                          f"4. Оцените содержание клетчатки и сахара, если возможно\n"
                          f"5. Перечислите основные ингредиенты\n"
                          f"6. Дайте оценку полезности блюда по шкале от 1 до 10")

            # Сохранение сообщения пользователя
            await message_repository.create(
                db,
                user_id=user.id,
                role="user",
                content=user_message,
                message_type="image",
                image_path=image_path
            )
            
            logger.info("Начинаю анализ изображения с помощью OpenAI Vision")

            # Анализ изображения с помощью AI
            analysis = await ai_service.analyze_food_image(optimized_image, user_message, history)
            
            logger.info("Анализ изображения успешно завершен")

            # Сохранение ответа ассистента
            ai_message = await message_repository.create(
                db,
                user_id=user.id,
                role="assistant",
                content=analysis
            )

            # Извлечение данных о питательной ценности
            logger.info("Извлекаю структурированные данные о питательной ценности")
            nutrition_data = await ai_service.extract_nutrition_data(analysis)
            
            # Логирование извлеченных данных
            logger.info(f"Извлеченные данные: Название: {nutrition_data.get('название_блюда')}, "
                        f"Калории: {nutrition_data.get('калории')}, "
                        f"Белки: {nutrition_data.get('белки')}г, "
                        f"Жиры: {nutrition_data.get('жиры')}г, "
                        f"Углеводы: {nutrition_data.get('углеводы')}г")

            # Создание записи о приеме пищи
            meal_log = await meal_log_repository.create(
                db,
                user_id=user.id,
                meal_type="unknown",  # будет обновлено позже
                meal_name=nutrition_data.get("название_блюда", "Неизвестное блюдо"),
                image_path=image_path,
                calories=nutrition_data.get("калории"),
                proteins=nutrition_data.get("белки"),
                fats=nutrition_data.get("жиры"),
                carbs=nutrition_data.get("углеводы"),
                fiber=nutrition_data.get("клетчатка"),
                sugar=nutrition_data.get("сахар")
            )

            # Добавление ингредиентов
            for ingredient_name in nutrition_data.get("основные_ингредиенты", []):
                await ingredient_repository.create(
                    db,
                    meal_log_id=meal_log.id,
                    name=ingredient_name
                )
            
            logger.info(f"Создана запись о приеме пищи: {meal_log.id}")

            # Удаление сообщения о обработке
            if processing_msg and hasattr(processing_msg, 'message_id'):
                try:
                    await message.bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
                except Exception as delete_error:
                    logger.warning(f"Не удалось удалить сообщение о обработке: {str(delete_error)}")

            # Формирование сводки о БЖУ с использованием нового метода
            nutrition_summary = await ai_service.format_nutrition_summary(nutrition_data)

            # Отправка результата анализа с красивой сводкой
            full_analysis = analysis
            if nutrition_summary:
                full_analysis = analysis + nutrition_summary

            # Отправка результата анализа
            feedback_kb = types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text="✏️ Исправить", callback_data=f"edit_meal_{meal_log.id}")]]
            )

            # Безопасная отправка: если Markdown ломается, отправляем обычным текстом
            try:
                sent_message = await message.answer(full_analysis, parse_mode="Markdown", reply_markup=feedback_kb)
            except TelegramBadRequest:
                sent_message = await message.answer(full_analysis, reply_markup=feedback_kb)

            # Проверяем, первое ли это фото
            usage = await usage_repository.get_or_create_usage(db, user.id)
            if usage.photos_used == 0:
                # Отправляем событие в Graspil: первое фото еды
                await graspil_service.send_first_photo_event(message.from_user.id)
            
            # Увеличиваем счетчик использования
            await usage_repository.increment_photos(db, user.id)

        except Exception as e:
            logger.exception(f"Ошибка при обработке фото: {str(e)}")
            await message.answer("😔 Произошла ошибка при анализе блюда. Пожалуйста, попробуйте снова.")

            # Удаление сообщения о обработке, если оно существует
            if processing_msg and hasattr(processing_msg, 'message_id'):
                try:
                    await message.bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
                except Exception:
                    pass

    @staticmethod
    async def process_text(message: types.Message, state: FSMContext, db: AsyncSession):
        """Обработчик текстовых сообщений"""
        # Игнорируем сообщения, начинающиеся с /, так как это команды
        if message.text.startswith('/'):
            return

        # Проверка текущего состояния для отладки
        current_state = await state.get_state()
        logger.info(f"Processing text: '{message.text}', State: {current_state}")
        
        # Если активно состояние регистрации, но мы попали сюда — значит что-то не так с роутингом.
        # Но чтобы не отвечать "Извините...", мы можем просто игнорировать сообщение или попробовать обработать его здесь (плохая практика).
        if current_state and "RegistrationStates" in str(current_state):
            logger.warning(f"Text caught in process_text during registration. State: {current_state}")
            # Можно попробовать перенаправить, но лучше просто вернуть return, чтобы бот не отвечал "Извините"
            return

        # ---- Новое: реагируем на приветствия без префикса "Как нутрициолог..." ----
        greetings = {
            "привет", "здравствуй", "здравствуйте", "добрый день", "добрый вечер",
            "доброе утро", "hello", "hi", "hey"
        }
        if message.text.lower().strip() in greetings:
            await message.answer("👋 Привет! Я готов помочь с вопросами о питании.")
            return
        # ------------------------------------------------------------------------

        try:
            # Проверка текущего состояния
            current_state = await state.get_state()

            # Получение пользователя
            user = await user_repository.get_or_create_user(
                db,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )

            # Отладочный вызов API
            if message.text.lower() == "тест промпта":
                from services.ai_service import debug_api_calls
                debug_result = await debug_api_calls()
                await message.answer(f"Результат тестового вызова API:\n\n{debug_result}")
                return

            # Если ждём описание блюда для исправления
            if current_state == UserStates.awaiting_meal_edit_description.state:
                await MessageHandlers._process_meal_edit_description(message, state, db, user.id)
                return

            # Обработка в зависимости от текущего состояния
            if current_state == UserStates.awaiting_preferences.state:
                await MessageHandlers._process_preferences(message, state, db, user.id)
            elif current_state == UserStates.awaiting_calories.state:
                await MessageHandlers._process_calories(message, state, db, user.id)
            elif current_state == UserStates.awaiting_feedback.state:
                await MessageHandlers._process_feedback(message, state, db, user.id)
            elif current_state == UserStates.awaiting_feedback_message.state:
                await MessageHandlers._process_general_feedback(message, state, db, user.id)
            else:
                # Стандартная обработка вопроса о питании
                await MessageHandlers._process_nutrition_question(message, db, user.id)

            # --- Обработка редактирования блюда (старый ручной ввод чисел удалён) ---

        except Exception as e:
            logger.error(f"Ошибка при обработке текста: {str(e)}")
            await message.answer("😔 Произошла ошибка при обработке вашего сообщения. Пожалуйста, попробуйте снова.")

    @staticmethod
    async def _process_preferences(message: types.Message, state: FSMContext, db: AsyncSession, user_id: int):
        """Обработка предпочтений пользователя"""
        try:
            # Парсинг предпочтений
            text = message.text.strip()

            # Поиск ключевых слов
            diet_type = None
            allergies = None
            disliked_foods = None
            preferred_cuisine = None

            # Простой алгоритм парсинга (можно улучшить с помощью NLP)
            text_lower = text.lower()

            # Определение типа диеты
            if "вегетарианск" in text_lower:
                diet_type = "вегетарианская"
            elif "веган" in text_lower:
                diet_type = "веганская"
            elif "кето" in text_lower:
                diet_type = "кето"
            elif "низкоуглеводн" in text_lower:
                diet_type = "низкоуглеводная"
            elif "палео" in text_lower:
                diet_type = "палео"
            elif "обычн" in text_lower:
                diet_type = "обычная"

            # Попытка найти аллергии
            if "аллерги" in text_lower:
                allergies_start = text_lower.find("аллерги")
                allergies_text = text[allergies_start:]
                allergies_end = allergies_text.find(",")
                if allergies_end > 0:
                    allergies = allergies_text[:allergies_end].replace("аллергия на ", "").replace("аллергии на ", "")
                else:
                    allergies = allergies_text.replace("аллергия на ", "").replace("аллергии на ", "")

            # Попытка найти нелюбимые продукты
            if "не люблю" in text_lower:
                disliked_start = text_lower.find("не люблю")
                disliked_text = text[disliked_start:]
                disliked_end = disliked_text.find(",")
                if disliked_end > 0:
                    disliked_foods = disliked_text[:disliked_end].replace("не люблю ", "")
                else:
                    disliked_foods = disliked_text.replace("не люблю ", "")

            # Попытка найти предпочитаемую кухню
            if "предпочитаю" in text_lower or "люблю" in text_lower:
                cuisine_start = text_lower.find("предпочитаю") if "предпочитаю" in text_lower else text_lower.find("люблю")
                cuisine_text = text[cuisine_start:]
                cuisine_end = cuisine_text.find(",")
                if cuisine_end > 0:
                    preferred_cuisine = cuisine_text[:cuisine_end].replace("предпочитаю ", "").replace("люблю ", "")
                else:
                    preferred_cuisine = cuisine_text.replace("предпочитаю ", "").replace("люблю ", "")

            # Сохранение предпочтений
            preferences = await user_preference_repository.get_by_user_id(db, user_id)

            if preferences:
                # Обновление существующих предпочтений
                if diet_type:
                    preferences.diet_type = diet_type
                if allergies:
                    preferences.allergies = allergies
                if disliked_foods:
                    preferences.disliked_foods = disliked_foods
                if preferred_cuisine:
                    preferences.preferred_cuisine = preferred_cuisine

                await db.commit()
                await db.refresh(preferences)
            else:
                # Создание новых предпочтений
                preferences = await user_preference_repository.create(
                    db,
                    user_id=user_id,
                    diet_type=diet_type,
                    allergies=allergies,
                    disliked_foods=disliked_foods,
                    preferred_cuisine=preferred_cuisine
                )

            # Формирование ответа
            response = (
                "✅ Ваши предпочтения сохранены:\n\n"
                f"Тип диеты: {preferences.diet_type or 'Не указано'}\n"
                f"Аллергии: {preferences.allergies or 'Не указано'}\n"
                f"Нелюбимые продукты: {preferences.disliked_foods or 'Не указано'}\n"
                f"Предпочитаемая кухня: {preferences.preferred_cuisine or 'Не указано'}"
            )

            await message.answer(response)

            # Очистка состояния
            await state.clear()

        except Exception as e:
            logger.error(f"Ошибка при обработке предпочтений: {str(e)}")
            await message.answer("😔 Произошла ошибка при сохранении предпочтений. Пожалуйста, попробуйте снова.")

    @staticmethod
    async def _process_calories(message: types.Message, state: FSMContext, db: AsyncSession, user_id: int):
        """Обработка целевых калорий"""
        try:
            # Парсинг калорий
            text = message.text.strip()

            # Извлечение числа
            import re
            calories_match = re.search(r'\d+', text)

            if not calories_match:
                await message.answer("⚠️ Не удалось распознать количество калорий. Пожалуйста, введите число, например: 2000")
                return

            calories = int(calories_match.group())

            # Проверка разумности значения
            if calories < 500 or calories > 5000:
                await message.answer("⚠️ Указанное количество калорий выглядит нереалистичным. Пожалуйста, введите значение от 500 до 5000 ккал.")
                return

            # Получение данных из состояния
            data = await state.get_data()
            goal_type = data.get("goal_type")

            if not goal_type:
                # Если тип цели не задан через /goals, используем "поддержание веса" по умолчанию.
                logger.warning("Тип цели не был найден в состоянии. Используется 'поддержание веса' по умолчанию.")
                goal_type = "поддержание веса"

            # Расчет БЖУ на основе калорий и типа цели
            if goal_type == "снижение веса":
                # Для снижения веса: больше белка, меньше жиров
                protein = calories * 0.30 / 4  # 30% от калорий - белки (4 ккал/г)
                fat = calories * 0.25 / 9      # 25% от калорий - жиры (9 ккал/г)
                carbs = calories * 0.45 / 4    # 45% от калорий - углеводы (4 ккал/г)
            elif goal_type == "набор массы":
                # Для набора массы: больше белка и углеводов
                protein = calories * 0.25 / 4  # 25% от калорий - белки
                fat = calories * 0.25 / 9      # 25% от калорий - жиры
                carbs = calories * 0.50 / 4    # 50% от калорий - углеводы
            else:  # поддержание веса
                # Для поддержания: сбалансированный подход
                protein = calories * 0.20 / 4  # 20% от калорий - белки
                fat = calories * 0.30 / 9      # 30% от калорий - жиры
                carbs = calories * 0.50 / 4    # 50% от калорий - углеводы

            # Округление значений
            protein = round(protein)
            fat = round(fat)
            carbs = round(carbs)

            # Создание или обновление цели
            current_goal = await nutritional_goal_repository.get_active_goal(db, user_id)

            if current_goal:
                # Деактивация текущей цели
                await nutritional_goal_repository.update(
                    db,
                    current_goal.id,
                    is_active=False,
                    end_date=datetime.utcnow()
                )

            # Создание новой цели
            new_goal = await nutritional_goal_repository.create(
                db,
                user_id=user_id,
                goal_type=goal_type,
                target_calories=calories,
                target_proteins=protein,
                target_fats=fat,
                target_carbs=carbs,
                is_active=True
            )

            # Короткое подтверждение
            await message.answer(f"✅ Цель {calories} ккал/день сохранена.")

            # Очистка состояния
            await state.clear()

        except Exception as e:
            logger.error(f"Ошибка при обработке калорий: {str(e)}")
            await message.answer("😔 Произошла ошибка при сохранении целей. Пожалуйста, попробуйте снова.")

    @staticmethod
    async def _process_feedback(message: types.Message, state: FSMContext, db: AsyncSession, user_id: int):
        """Обработка дополнительной обратной связи"""
        try:
            # Получение данных из состояния
            data = await state.get_data()
            feedback_id = data.get("feedback_id")

            if not feedback_id:
                await message.answer("⚠️ Не удалось определить ID обратной связи. Ваше сообщение обработано как обычный вопрос.")
                await state.clear()
                await MessageHandlers._process_nutrition_question(message, db, user_id)
                return

            # Обновление комментария к обратной связи
            feedback = await feedback_repository.get_by_id(db, feedback_id)

            if feedback:
                await feedback_repository.update(
                    db,
                    feedback_id,
                    comment=message.text
                )

                await message.answer("✅ Спасибо за дополнительную обратную связь! Мы используем её для улучшения качества анализа.")
            else:
                await message.answer("⚠️ Не удалось найти запись обратной связи. Ваше сообщение обработано как обычный вопрос.")
                await MessageHandlers._process_nutrition_question(message, db, user_id)

            # Очистка состояния
            await state.clear()

        except Exception as e:
            logger.error(f"Ошибка при обработке обратной связи: {str(e)}")
            await message.answer("😔 Произошла ошибка при сохранении обратной связи. Пожалуйста, попробуйте снова.")

    @staticmethod
    async def _process_general_feedback(message: types.Message, state: FSMContext, db: AsyncSession, user_id: int):
        """Получение комментария от пользователя и отправка администратору"""
        try:
            # Отправляем сообщение администратору
            admin_id = config.ADMIN_ID

            # Формируем текст, содержащий информацию о пользователе
            user_info = (
                f"👤 Пользователь: {message.from_user.full_name} (@{message.from_user.username or 'нет'})\n"
                f"ID: {message.from_user.id}\n"
                f"Сообщение:\n{message.text}"
            )

            try:
                await message.bot.send_message(chat_id=admin_id, text=user_info)
            except Exception as send_err:
                logger.error(f"Не удалось отправить сообщение админу: {send_err}")

            # Благодарим пользователя
            await message.answer("✅ Спасибо! Ваше сообщение отправлено администратору.")

            # Сбрасываем состояние
            await state.clear()

        except Exception as e:
            logger.error(f"Ошибка при сохранении обратной связи: {str(e)}")
            await message.answer("😔 Произошла ошибка при отправке обратной связи. Попробуйте позже.")

    @staticmethod
    async def _process_nutrition_question(message: types.Message, db: AsyncSession, user_id: int):
        """Обработка вопроса о питании"""
        processing_msg = None
        try:
            # Проверка лимитов
            can_use = await usage_repository.can_ask_question(db, user_id)
            if not can_use:
                usage = await usage_repository.get_or_create_usage(db, user_id)
                await message.answer(
                    f"❌ Вы исчерпали лимит бесплатных вопросов ({config.FREE_QUESTION_LIMIT} шт.)\n\n"
                    f"Для продолжения оформите подписку за {config.SUBSCRIPTION_PRICE} руб./месяц",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text="💳 Оформить подписку", callback_data="subscribe")]
                        ]
                    )
                )
                return

            # 1) Быстрая локальная проверка по ключевым словам.
            is_nutri = MessageHandlers._is_nutrition_question(message.text)

            # 2) Если ключевых слов нет, делаем дешёвую LLM-классификацию (1-2 токена)
            if not is_nutri:
                try:
                    # Формируем параметры вызова с учётом ограничений моделей gpt-5*
                    clf_params = {
                        "model": config.GPT_MODEL,
                        "messages": [
                            {"role": "system", "content": "Ответь одним словом: YES, если вопрос относится к питанию, еде, продуктам, рецептам, приготовлению блюд, диетам, нутриентам, похудению, набору веса, КБЖУ или здоровому образу жизни; иначе NO."},
                            {"role": "user", "content": message.text}
                        ],
                    }
                    # Корректный параметр лимита токенов для текущей модели
                    clf_params.update(ai_service._token_limit_param(1))
                    # Температура задаётся только если поддерживается моделью
                    if ai_service.supports_temperature:
                        clf_params["temperature"] = 0

                    clf_resp = await ai_service.client.chat.completions.create(**clf_params)
                    answer = clf_resp.choices[0].message.content.strip().lower()
                    is_nutri = answer.startswith("y") or answer.startswith("д")  # yes / да
                except Exception as _:
                    # В случае ошибки классификатора полагаемся на ключевые слова
                    pass

            # 3) Дополнительная эвристика: очень короткое сообщение (<= 20 символов)
            #    без спецсимволов считаем названием продукта и допускаем.
            if not is_nutri and len(message.text.strip()) <= 20 and message.text.isalpha():
                is_nutri = True

            # 4) Если предыдущий ответ ассистента был нутрициологическим, допускаем follow-up.
            if not is_nutri:
                history_short = await message_repository.get_conversation_history(db, user_id, limit=2)
                for h in reversed(history_short):  # просматриваем от последнего к первому
                    if h["role"] == "assistant" and "как нутрициолог" in h["content"].lower():
                        is_nutri = True
                        break

            if not is_nutri:
                await message.answer("🛑 Извините, я отвечаю только на вопросы о питании, диетах и здоровом образе жизни.")
                return

            # Отправка уведомления о начале обработки
            processing_msg = await message.answer("💭 Обрабатываю ваш вопрос...")

            # Получение истории сообщений
            history = await message_repository.get_conversation_history(db, user_id)

            # Сохранение вопроса пользователя
            await message_repository.create(
                db,
                user_id=user_id,
                role="user",
                content=message.text
            )

            # Получение ответа от AI
            response = await ai_service.answer_nutrition_question(message.text, history)

            # Удаление сообщения о обработке
            if processing_msg and hasattr(processing_msg, 'message_id'):
                try:
                    await message.bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
                except Exception as delete_error:
                    logger.warning(f"Не удалось удалить сообщение о обработке: {str(delete_error)}")

            # Проверяем ответ ПЕРЕД сохранением в историю
            is_valid_response = response and response.strip() and "Не удалось получить ответ" not in response
            
            # Сохраняем в историю ТОЛЬКО валидный ответ
            if is_valid_response:
                ai_message = await message_repository.create(
                    db,
                    user_id=user_id,
                    role="assistant",
                    content=response
                )

            # Отправка ответа без дополнительных кнопок
            safe_response = response if is_valid_response else "😔 Не удалось получить ответ. Пожалуйста, попробуйте снова."
            try:
                sent_message = await message.answer(safe_response, parse_mode="Markdown")
            except TelegramBadRequest:
                sent_message = await message.answer(safe_response)

            # Увеличиваем счетчик использования
            await usage_repository.increment_questions(db, user_id)

        except Exception as e:
            logger.error(f"Ошибка при ответе на вопрос: {str(e)}")

            # Удаление сообщения о обработке, если оно существует
            if processing_msg and hasattr(processing_msg, 'message_id'):
                try:
                    await message.bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
                except Exception:
                    pass

            await message.answer("😔 Произошла ошибка при обработке вашего вопроса. Пожалуйста, попробуйте снова.")

    @staticmethod
    async def _process_meal_edit(message: types.Message, state: FSMContext, db: AsyncSession, user_id: int):
        """Обрабатывает ввод пользователя с новыми значениями КБЖУ"""
        try:
            data = (await state.get_data()) or {}
            meal_id = data.get("edit_meal_id")
            if not meal_id:
                await message.answer("⚠️ Не найдено блюдо для редактирования. Попробуйте ещё раз.")
                await state.clear()
                return

            # Ожидаем ввод 4 чисел
            parts = message.text.strip().replace(',', '.').split()
            if len(parts) != 4 or not all(p.replace('.', '', 1).isdigit() for p in parts):
                await message.answer("Введите четыре числа через пробел: калории белки жиры углеводы")
                return

            cal, prot, fat, carb = map(float, parts)
            from database.repository import meal_log_repository
            await meal_log_repository.update(
                db,
                meal_id,
                calories=cal,
                proteins=prot,
                fats=fat,
                carbs=carb,
            )

            await message.answer("✅ Запись обновлена!")
            await state.clear()
        except Exception as e:
            logger.error(f"Ошибка при редактировании блюда: {e}")
            await message.answer("😔 Не удалось обновить данные. Попробуйте ещё раз.")

    @staticmethod
    async def _process_meal_edit_description(message: types.Message, state: FSMContext, db: AsyncSession, user_id: int):
        """Обрабатывает ввод пользователя с новым описанием блюда для исправления"""
        try:
            data = (await state.get_data()) or {}
            meal_id = data.get("edit_meal_id")
            if not meal_id:
                await message.answer("⚠️ Не найдено блюдо для редактирования. Попробуйте ещё раз.")
                await state.clear()
                return

            description = message.text.strip()

            # Сообщаем пользователю, что идёт обновление
            processing_msg = await message.answer("🔄 Обновляю информацию о блюде, подождите…")

            # Получаем текущие ингредиенты
            old_ingredients = await ingredient_repository.get_by_meal_id(db, meal_id)
            old_ing_names = [ing.name for ing in old_ingredients]

            # Определяем сценарий: добавление или замена
            text_lc = description.lower()
            addition_kw = ["ещё", "еще", "добав", "также", "плюс", "и "]
            replace_kw = ["замен", "вместо", "убер", "без", "исключ", "не "]

            is_addition = any(k in text_lc for k in addition_kw)
            is_replacement = any(k in text_lc for k in replace_kw)

            merge_ingredients = not is_replacement  # если явная замена — перезаписываем

            # Получаем текущую запись до использования
            current_log = await meal_log_repository.get_by_id(db, meal_id)
            existing_desc = ", ".join(old_ing_names) if old_ing_names else (current_log.meal_name if current_log else "")

            # Формируем расширенный запрос, учитывающий уже известные ингредиенты
            user_message = (
                f"Исходный состав блюда: {existing_desc}.\n"
                f"Пользователь уточнил: {description}.\n\n"
                f"Сформируй итоговый анализ блюда, учтя эти изменения, и предоставь информацию:\n"
                f"1. Краткое название блюда или список продуктов\n"
                f"2. Общая калорийность (ккал)\n"
                f"3. Полный анализ БЖУ (белки, жиры, углеводы) в граммах\n"
                f"4. При наличии — клетчатка и сахар\n"
                f"5. Полный список основных ингредиентов\n"
                f"6. Оценка полезности блюда по шкале 1–10"
            )

            # Запрашиваем модель для оценки калорий и БЖУ
            analysis_text = await ai_service.answer_nutrition_question(user_message)
            nutrition_data_new = await ai_service.extract_nutrition_data(analysis_text)

            # Текущая запись уже получена выше как current_log

            # Собираем старые данные
            nutrition_data_old = {
                "название_блюда": current_log.meal_name,
                "калории": current_log.calories,
                "белки": current_log.proteins,
                "жиры": current_log.fats,
                "углеводы": current_log.carbs,
                "клетчатка": getattr(current_log, "fiber", None),
                "сахар": getattr(current_log, "sugar", None),
            }

            # Мержим: новые значения имеют приоритет, если не None
            nutrition_data = nutrition_data_old.copy()
            for k, v in nutrition_data_new.items():
                if v is not None:
                    nutrition_data[k] = v

            # Обновляем запись в БД
            await meal_log_repository.update(
                db,
                meal_id,
                meal_name=nutrition_data.get("название_блюда", description[:50]),
                calories=nutrition_data.get("калории"),
                proteins=nutrition_data.get("белки"),
                fats=nutrition_data.get("жиры"),
                carbs=nutrition_data.get("углеводы")
            )

            # Обработка ингредиентов в зависимости от сценария
            if nutrition_data_new.get("основные_ингредиенты") is not None:
                new_ing_names = nutrition_data_new["основные_ингредиенты"] or []

                if merge_ingredients:
                    merged_ing_set = set(old_ing_names)
                    merged_ing_set.update(new_ing_names)
                else:
                    # замена – берём только новые, если они есть
                    merged_ing_set = set(new_ing_names) if new_ing_names else set(old_ing_names)

                if merged_ing_set != set(old_ing_names):
                    await ingredient_repository.delete_by_meal_log(db, meal_id)
                    for ing_name in merged_ing_set:
                        await ingredient_repository.create(db, meal_log_id=meal_id, name=ing_name)

            # Получаем обновлённую запись для подтверждения
            updated = await meal_log_repository.get_by_id(db, meal_id)
            summary = (
                "✅ Запись обновлена:\n\n"
                f"Название: {updated.meal_name}\n"
                f"Калории: {updated.calories or '—'}\n"
                f"Белки: {updated.proteins or '—'} г\n"
                f"Жиры: {updated.fats or '—'} г\n"
                f"Углеводы: {updated.carbs or '—'} г"
            )

            # Удаляем сообщение о процессе
            if processing_msg and hasattr(processing_msg, 'message_id'):
                try:
                    await message.bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
                except Exception:
                    pass

            await message.answer(summary)

            # Повторно формируем сводку по БЖУ на основе обновлённых данных
            nutrition_summary = await ai_service.format_nutrition_summary(nutrition_data)

            full_analysis = analysis_text
            if nutrition_summary:
                full_analysis += nutrition_summary

            # Безопасная отправка анализа (Markdown может упасть)
            try:
                await message.answer(full_analysis, parse_mode="Markdown")
            except TelegramBadRequest:
                await message.answer(full_analysis)

            await state.clear()
        except Exception as e:
            logger.error(f"Ошибка при редактировании описания блюда: {e}")
            # Удаляем сообщение о процессе, если оно есть
            try:
                if processing_msg and hasattr(processing_msg, 'message_id'):
                    await message.bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
            except Exception:
                pass

            await message.answer("😔 Не удалось обновить описание. Попробуйте ещё раз.")

# Регистрация обработчиков сообщений
def register_message_handlers(dp):
    """Регистрация обработчиков сообщений"""
    # Регистрация обработчиков сообщений для aiogram 3.x
    dp.message.register(MessageHandlers.process_photo, F.photo)
    dp.message.register(MessageHandlers.process_text, F.text)
