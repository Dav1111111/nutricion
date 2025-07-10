import logging
from typing import Dict, List, Optional, Any
from aiogram import types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from services.ai_service import ai_service, debug_api_calls
from database.repository import user_repository, message_repository, meal_log_repository
from database.repository import nutritional_goal_repository, user_preference_repository
from utils.image_utils import image_utils
from config.config import config
from utils.inline_keyboards import main_inline_menu
from aiogram.types import ReplyKeyboardRemove
from database.subscription_repository import subscription_repository, usage_repository
from services.payment_service import payment_service

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния FSM
class UserStates(StatesGroup):
    awaiting_feedback = State()
    awaiting_question = State()
    awaiting_meal_type = State()
    awaiting_preferences = State()
    awaiting_goal_type = State()
    awaiting_calories = State()
    awaiting_meal_plan_confirmation = State()
    awaiting_report_period = State()
    awaiting_feedback_message = State()  # Состояние для обратной связи
    awaiting_meal_edit = State()  # Новое: редактирование КБЖУ блюда
    awaiting_meal_edit_description = State()  # пользователь описывает блюдо

class CommandHandlers:
    """Обработчики команд бота"""

    @staticmethod
    async def start_command(message: types.Message, state: FSMContext, db: AsyncSession):
        """Обработчик команды /start"""
        try:
            # Создание или получение пользователя
            await user_repository.get_or_create_user(
                db,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )

            # Сброс состояния пользователя
            await state.clear()

            # Формирование приветственного сообщения
            welcome_message = (
                "👋🏻 Начнём наше знакомство.\n\n"
                "В первую очередь я рассчитываю калорийность и БЖУ по фото, поэтому можешь отправить фото блюда и я рассчитаю примерные КБЖУ.\n\n"
                "Так же можешь задать вопрос о питании, еде и ЗОЖ.\n\n"
                "Нажав на кнопку Меню ты увидишь остальные возможности бота:\n\n"
                "/calories — тут ты можешь задать цель по калориям за день.\n\n"
                "/day_calories — узнаешь сколько КБЖУ накопилось за день. Данные берутся с фотографий, которые ты скидываешь боту.\n\n"
                "/today_meals — список блюд с калориями съеденные за сегодня.\n\n"
                "/reset_today — сбросить данные и начать сначала.\n\n"
                "/subscription — твоя подписка.\n\n"
                "/feedback — отправить обратную связь или связаться с поддержкой.\n\n"
                "Доступно бесплатно:\n"
                " • 5 распознаваний КБЖУ по фото\n"
                " • 10 вопросов ИИ нутрициологу\n\n"
                "Помни: советы носят информационный характер и не заменяют консультацию врача."
            )

            # Убираем любую клавиатуру под полем ввода
            await message.answer(welcome_message, reply_markup=ReplyKeyboardRemove())

        except Exception as e:
            logger.error(f"Ошибка при обработке команды /start: {str(e)}")
            await message.answer("Произошла ошибка при обработке команды. Пожалуйста, попробуйте снова.")

    @staticmethod
    async def help_command(message: types.Message):
        """Обработчик команды /help"""
        help_text = (
            "🤖 ИИ Нутрициолог - твой помощник по питанию\n\n"
            "Список команд:\n"
            "/start - Начать работу с ботом\n"
            "/help - Показать это сообщение\n"
            "/question - Задать вопрос о питании\n"
            "/report - Сформировать отчет о питании\n"
            "/prefs - Указать предпочтения в питании\n"
            "/calories - Указать целевое количество калорий\n\n"
            "Также вы можете:\n"
            "- Отправить фотографию блюда для анализа\n"
            "- Задать вопрос о питании, диетах или здоровом образе жизни\n\n"
            "Если у вас возникли проблемы, пожалуйста, напишите /start, чтобы перезапустить бота."
        )
        await message.answer(help_text)
        
    @staticmethod
    async def test_prompt_command(message: types.Message):
        """Обработчик команды /test_prompt для проверки работы системного промпта"""
        await message.answer("Тестирую системный промпт... Подождите несколько секунд.")
        
        # Вызов отладочной функции
        result = await debug_api_calls()
        
        # Отправка результата
        await message.answer(f"Результат тестирования системного промпта:\n\n{result}")
        
        # Дополнительная информация
        await message.answer(
            "Если ответ начинается с фразы 'Как нутрициолог...', значит системные промпты работают правильно. "
            "Если нет, проверьте настройки API и конфигурацию бота."
        )

    @staticmethod
    async def cmd_clear(message: types.Message, db: AsyncSession):
        """Обработчик команды /clear для очистки истории диалога"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, message.from_user.id)

            if not user:
                await message.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return

            # Очистка истории
            deleted_count = await message_repository.clear_user_history(db, user.id)

            await message.answer(f"🗑️ История диалога очищена. Удалено {deleted_count} сообщений.")

            # Добавление нового системного сообщения
            await message_repository.create(
                db,
                user_id=user.id,
                role="system",
                content="История диалога очищена"
            )

        except Exception as e:
            logger.error(f"Ошибка в обработчике /clear: {str(e)}")
            await message.answer("😔 Произошла ошибка при очистке истории. Пожалуйста, попробуйте позже.")

    @staticmethod
    async def cmd_plan(message: types.Message, state: FSMContext, db: AsyncSession):
        """Обработчик команды /plan для создания плана питания"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, message.from_user.id)

            if not user:
                await message.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return

            # Получение целей и предпочтений пользователя
            goals = await nutritional_goal_repository.get_active_goal(db, user.id)
            preferences = await user_preference_repository.get_by_user_id(db, user.id)

            # Если нет предпочтений или целей, запрашиваем их
            if not preferences:
                await message.answer(
                    "📋 Для создания плана питания мне нужно знать ваши предпочтения.\n\n"
                    "Пожалуйста, укажите:\n"
                    "• Тип диеты (обычная, вегетарианская, веганская, кето и т.д.)\n"
                    "• Аллергии или непереносимость продуктов\n"
                    "• Продукты, которые вы не любите\n"
                    "• Предпочитаемую кухню (если есть)\n\n"
                    "Пример: \"Обычная диета, аллергия на орехи, не люблю баклажаны, предпочитаю средиземноморскую кухню\""
                )
                await state.set_state(UserStates.awaiting_preferences)
                return

            if not goals:
                await message.answer(
                    "🎯 Для создания плана питания мне нужно знать ваши цели.\n\n"
                    "Выберите тип цели:",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text="🔽 Снижение веса", callback_data="goal_weight_loss")],
                            [types.InlineKeyboardButton(text="🔼 Набор массы", callback_data="goal_weight_gain")],
                            [types.InlineKeyboardButton(text="➡️ Поддержание веса", callback_data="goal_maintenance")]
                        ]
                    )
                )
                await state.set_state(UserStates.awaiting_goal_type)
                return

            # Если есть и предпочтения, и цели, создаем план питания
            await CommandHandlers._generate_meal_plan(message, state, db, user.id)

        except Exception as e:
            logger.error(f"Ошибка в обработчике /plan: {str(e)}")
            await message.answer("😔 Произошла ошибка при создании плана питания. Пожалуйста, попробуйте позже.")

    @staticmethod
    async def _generate_meal_plan(message: types.Message, state: FSMContext, db: AsyncSession, user_id: int):
        """Генерация плана питания на основе предпочтений и целей пользователя"""
        try:
            # Получение целей и предпочтений пользователя
            goals = await nutritional_goal_repository.get_active_goal(db, user_id)
            preferences = await user_preference_repository.get_by_user_id(db, user_id)

            if not goals or not preferences:
                await message.answer("⚠️ Не хватает информации о целях или предпочтениях. Используйте /goals и /prefs.")
                return

            # Подготовка данных для генерации плана
            user_prefs = {
                "diet_type": preferences.diet_type or "обычная",
                "allergies": preferences.allergies or "нет",
                "disliked_foods": preferences.disliked_foods or "нет",
                "preferred_cuisine": preferences.preferred_cuisine or "любая"
            }

            nutrition_goals = {
                "goal_type": goals.goal_type,
                "target_calories": goals.target_calories,
                "target_proteins": goals.target_proteins,
                "target_fats": goals.target_fats,
                "target_carbs": goals.target_carbs
            }

            # Отправка сообщения о начале генерации
            await message.answer("🧪 Генерирую персональный план питания на основе ваших данных. Это может занять около минуты...")

            # Генерация плана питания
            meal_plan = await ai_service.generate_meal_plan(user_prefs, nutrition_goals)

            # Разбиение плана на части, если он слишком большой
            if len(meal_plan) > 4000:
                parts = [meal_plan[i:i+4000] for i in range(0, len(meal_plan), 4000)]
                for i, part in enumerate(parts):
                    await message.answer(f"📋 План питания (часть {i+1}/{len(parts)}):\n\n{part}", parse_mode="Markdown")
            else:
                await message.answer(f"📋 Ваш персональный план питания:\n\n{meal_plan}", parse_mode="Markdown")

            # Сохранение в историю
            user = await user_repository.get_by_id(db, user_id)
            await message_repository.create(
                db,
                user_id=user_id,
                role="user",
                content="Запрос на генерацию плана питания"
            )

            await message_repository.create(
                db,
                user_id=user_id,
                role="assistant",
                content=meal_plan
            )

            # Очистка состояния
            await state.clear()

        except Exception as e:
            logger.error(f"Ошибка при генерации плана питания: {str(e)}")
            await message.answer("😔 Произошла ошибка при генерации плана питания. Пожалуйста, попробуйте позже.")

    @staticmethod
    async def cmd_goals(message: types.Message, state: FSMContext, db: AsyncSession):
        """Обработчик команды /goals для установки целей по питанию"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, message.from_user.id)

            if not user:
                await message.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return

            # Получение текущих целей
            current_goal = await nutritional_goal_repository.get_active_goal(db, user.id)

            if current_goal:
                goal_info = (
                    f"🎯 *Ваши текущие цели:*\n\n"
                    f"Тип цели: {current_goal.goal_type}\n"
                    f"Целевые калории: {current_goal.target_calories} ккал/день\n"
                    f"Целевой белок: {current_goal.target_proteins} г/день\n"
                    f"Целевые жиры: {current_goal.target_fats} г/день\n"
                    f"Целевые углеводы: {current_goal.target_carbs} г/день\n\n"
                    f"Хотите изменить цели?"
                )

                await message.answer(
                    goal_info,
                    parse_mode="Markdown",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text="✅ Да, изменить", callback_data="change_goals")],
                            [types.InlineKeyboardButton(text="❌ Нет, оставить", callback_data="keep_goals")]
                        ]
                    )
                )
            else:
                await message.answer(
                    "🎯 У вас пока нет целей по питанию. Хотите их указать?",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text="✏️ Указать цели", callback_data="change_goals")],
                            [types.InlineKeyboardButton(text="⏭️ Пропустить", callback_data="keep_goals")]
                        ]
                    )
                )
                await state.set_state(UserStates.awaiting_goal_type)

        except Exception as e:
            logger.error(f"Ошибка в обработчике /goals: {str(e)}")
            await message.answer("😔 Произошла ошибка при установке целей. Пожалуйста, попробуйте позже.")

    @staticmethod
    async def cmd_prefs(message: types.Message, state: FSMContext, db: AsyncSession):
        """Обработчик команды /prefs для указания предпочтений в питании"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, message.from_user.id)

            if not user:
                await message.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return

            # Получение текущих предпочтений
            preferences = await user_preference_repository.get_by_user_id(db, user.id)

            if preferences:
                pref_info = (
                    f"🍽️ *Ваши текущие предпочтения:*\n\n"
                    f"Тип диеты: {preferences.diet_type or 'Не указано'}\n"
                    f"Аллергии: {preferences.allergies or 'Не указано'}\n"
                    f"Нелюбимые продукты: {preferences.disliked_foods or 'Не указано'}\n"
                    f"Предпочитаемая кухня: {preferences.preferred_cuisine or 'Не указано'}\n\n"
                    f"Хотите изменить предпочтения?"
                )

                await message.answer(
                    pref_info,
                    parse_mode="Markdown",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text="✏️ Изменить", callback_data="change_prefs")],
                            [types.InlineKeyboardButton(text="✅ Оставить как есть", callback_data="keep_prefs")]
                        ]
                    )
                )
            else:
                await message.answer(
                    "🍽️ У вас пока нет предпочтений в питании. Хотите их указать?",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text="✏️ Указать предпочтения", callback_data="change_prefs")],
                            [types.InlineKeyboardButton(text="⏭️ Пропустить", callback_data="keep_prefs")]
                        ]
                    )
                )
                await state.set_state(UserStates.awaiting_preferences)

        except Exception as e:
            logger.error(f"Ошибка в обработчике /prefs: {str(e)}")
            await message.answer("😔 Произошла ошибка при указании предпочтений. Пожалуйста, попробуйте позже.")

    @staticmethod
    async def cmd_report(message: types.Message, state: FSMContext, db: AsyncSession):
        """Обработчик команды /report для получения отчета о питании"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, message.from_user.id)

            if not user:
                await message.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return

            # Запрос периода для отчета
            await message.answer(
                "📊 За какой период вы хотите получить отчет о питании?",
                reply_markup=types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(text="📅 За сегодня", callback_data="report_today")],
                        [types.InlineKeyboardButton(text="📅 За неделю", callback_data="report_week")],
                        [types.InlineKeyboardButton(text="📅 За месяц", callback_data="report_month")]
                    ]
                )
            )
            await state.set_state(UserStates.awaiting_report_period)

        except Exception as e:
            logger.error(f"Ошибка в обработчике /report: {str(e)}")
            await message.answer("😔 Произошла ошибка при получении отчета. Пожалуйста, попробуйте позже.")

    @staticmethod
    async def cmd_stats(message: types.Message, db: AsyncSession):
        """Обработчик команды /stats для отображения статистики пользователя"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, message.from_user.id)

            if not user:
                await message.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return

            # Получение данных для статистики
            messages_count = await message_repository.count(db)
            meals_count = await meal_log_repository.count(db)

            # Формирование статистики
            stats_message = (
                f"📊 *Ваша статистика:*\n\n"
                f"Дата регистрации: {user.registration_date.strftime('%d.%m.%Y')}\n"
                f"Количество сообщений: {messages_count}\n"
                f"Количество записей о питании: {meals_count}\n"
            )

            await message.answer(stats_message, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Ошибка в обработчике /stats: {str(e)}")
            await message.answer("😔 Произошла ошибка при получении статистики. Пожалуйста, попробуйте позже.")

    @staticmethod
    async def reset_command(message: types.Message, db: AsyncSession):
        """Обработчик команды /reset для сброса настроек бота и проверки модели"""
        try:
            # Отправка сообщения о начале проверки
            await message.answer("🔄 Начинаю проверку и сброс настроек бота...")

            # Проверка доступности API
            api_result = await debug_api_calls()
            
            # Логирование информации о модели
            logger.info(f"Используемая модель: {config.CLAUDE_MODEL}")
            logger.info(f"Системный промпт для пищи (первые 50 символов): {config.SYSTEM_PROMPT_FOOD[:50]}...")
            logger.info(f"Системный промпт для вопросов (первые 50 символов): {config.SYSTEM_PROMPT_NUTRITION[:50]}...")
            
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, message.from_user.id)
            if user:
                # Сохранение сообщения о сбросе в историю
                await message_repository.create(
                    db,
                    user_id=user.id,
                    role="system",
                    content="Сброс настроек бота"
                )
            
            # Отправка результатов
            await message.answer(f"✅ Проверка API Claude завершена:\n\n{api_result}")
            
            # Добавление информации о модели Claude 3.5 Haiku
            await message.answer(
                "ℹ️ О модели Claude 3.5 Haiku:\n\n"
                "Claude 3.5 Haiku - это самая быстрая модель Anthropic с улучшенными возможностями для анализа "
                "пищи, кодирования и обработки данных. Она оптимизирована для интерактивного общения и "
                "быстрого анализа изображений. По сравнению с предыдущими версиями, она обеспечивает значительно "
                "более качественные результаты при сохранении высокой скорости работы."
            )
            
            await message.answer(f"ℹ️ Информация о настройках бота:\n\n"
                                f"• Модель: {config.CLAUDE_MODEL}\n"
                                f"• Максимальное количество токенов: {config.MAX_TOKENS}\n"
                                f"• Максимальная длина истории: {config.MAX_HISTORY_LENGTH} сообщений\n"
                                f"• Температура генерации: 0.2 (оптимизирована для точности)")
            
            await message.answer("✅ Сброс завершен. Бот использует Claude 3.5 Haiku и должен корректно использовать системные промпты.")
            
        except Exception as e:
            logger.error(f"Ошибка при сбросе настроек: {str(e)}")
            await message.answer(f"❌ Произошла ошибка при сбросе: {str(e)}")

    @staticmethod
    async def force_prompt_command(message: types.Message, db: AsyncSession):
        """Обработчик команды /force_prompt для принудительного добавления префикса нутрициолога"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, message.from_user.id)
            
            if not user:
                await message.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return
                
            await message.answer(
                "🔧 Активирована принудительная вставка фразы \"Как нутрициолог...\" в ответы бота.\n\n"
                "Теперь все ответы будут содержать эту фразу в начале, даже если модель Claude не следует системному промпту."
            )
            
            # Сохранение сообщения о режиме
            await message_repository.create(
                db,
                user_id=user.id,
                role="system",
                content="Активирован режим принудительного добавления фразы 'Как нутрициолог...'"
            )
            
            # Тестируем работу с принудительным добавлением
            test_response = await ai_service.answer_nutrition_question("Что такое правильное питание?")
            
            await message.answer(
                f"Пример ответа с принудительным добавлением фразы:\n\n{test_response[:200]}...\n\n"
                "Для выключения этого режима перезапустите бота командой /start"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при активации принудительного префикса: {str(e)}")
            await message.answer(f"❌ Произошла ошибка: {str(e)}")

    @staticmethod
    async def cmd_calories(message: types.Message, state: FSMContext, db: AsyncSession):
        """Запросить у пользователя суточную калорийность напрямую."""
        try:
            # Сброс предыдущих состояний
            await state.clear()

            # Получаем текущую активную цель
            user = await user_repository.get_by_telegram_id(db, message.from_user.id)

            current_goal = None
            if user:
                current_goal = await nutritional_goal_repository.get_active_goal(db, user.id)

            if current_goal and current_goal.target_calories:
                # Есть сохранённая цель – предлагаем изменить
                await message.answer(
                    f"🎯 Ваша текущая цель: {current_goal.target_calories:.0f} ккал/день\n\nХотите изменить её?",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text="✏️ Изменить", callback_data="change_calories")],
                            [types.InlineKeyboardButton(text="✅ Оставить как есть", callback_data="keep_calories")]
                        ]
                    )
                )
            else:
                # Цели ещё нет – запрашиваем значение
                await message.answer("Укажите желаемое количество калорий в день (например, 2000):")
                await state.set_state(UserStates.awaiting_calories)
        except Exception as e:
            logger.error(f"Ошибка в обработчике /calories: {str(e)}")
            await message.answer("Произошла ошибка, попробуйте позже.")

    @staticmethod
    async def cmd_day_calories(message: types.Message, db: AsyncSession):
        """Показывает потреблённые за сегодня калории и макроэлементы."""
        try:
            user = await user_repository.get_by_telegram_id(db, message.from_user.id)

            if not user:
                await message.answer("Пользователь не найден. Используйте /start.")
                return

            from datetime import datetime

            now = datetime.utcnow()
            date_from = datetime(now.year, now.month, now.day)
            meals = await meal_log_repository.get_meals_by_date(db, user.id, date_from, now)

            total_cal = sum(m.calories or 0 for m in meals)
            total_prot = sum(m.proteins or 0 for m in meals)
            total_fat = sum(m.fats or 0 for m in meals)
            total_carb = sum(m.carbs or 0 for m in meals)

            # Получаем цель пользователя
            goal = await nutritional_goal_repository.get_active_goal(db, user.id)

            msg = (
                f"📊 *Статистика за сегодня*\n\n"
                f"Калории: {total_cal:.0f} ккал\n"
                f"Белки: {total_prot:.1f} г\n"
                f"Жиры: {total_fat:.1f} г\n"
                f"Углеводы: {total_carb:.1f} г\n"
            )

            if goal and goal.target_calories:
                msg += f"🎯 Ваша цель: {goal.target_calories:.0f} ккал\n\n"
                diff = total_cal - goal.target_calories

                if abs(diff) <= 50:
                    msg += "✅ *Цель достигнута!* Отличная работа!"
                elif diff > 50:
                    msg += f"❌ *Цель превышена* на {diff:.0f} ккал."
                else:
                    msg += f"⏳ *Осталось до цели:* {abs(diff):.0f} ккал."

            await message.answer(msg, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Ошибка в /day_calories: {str(e)}")
            await message.answer("Не удалось получить данные. Попробуйте позже.")

    # ---------- Новый: список блюд за сегодня ----------
    @staticmethod
    async def cmd_today_meals(message: types.Message, db: AsyncSession):
        """Показывает список блюд за текущий день."""
        try:
            user = await user_repository.get_by_telegram_id(db, message.from_user.id)
            if not user:
                await message.answer("Пользователь не найден. Используйте /start.")
                return

            from datetime import datetime
            now = datetime.utcnow()
            date_from = datetime(now.year, now.month, now.day)

            meals = await meal_log_repository.get_meals_by_date(db, user.id, date_from, now)

            if not meals:
                await message.answer("За сегодня ещё нет записей о приёмах пищи.")
                return

            text_lines = ["📋 *Список блюд за сегодня:*\n"]
            total_cal = 0
            for i, m in enumerate(meals, 1):
                # Отображаем время в локальной тайзоне сервера, а не в UTC
                from datetime import timezone
                local_dt = m.date
                if m.date.tzinfo is None or m.date.tzinfo == timezone.utc:
                    # Если дата в UTC/naive, конвертируем в локальное время
                    local_dt = m.date.replace(tzinfo=timezone.utc).astimezone()

                time_str = local_dt.strftime('%H:%M')
                name = m.meal_name or 'Блюдо'
                cal = m.calories or 0
                total_cal += cal
                text_lines.append(f"{i}. {name} — {cal:.0f} ккал ({time_str})")

            text_lines.append(f"\nИтого: {total_cal:.0f} ккал")
            await message.answer("\n".join(text_lines), parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Ошибка в /today_meals: {str(e)}")
            await message.answer("Не удалось получить список блюд. Попробуйте позже.")

    # ---------- Новый: сброс данных за сегодня ----------
    @staticmethod
    async def cmd_reset_today(message: types.Message, db: AsyncSession):
        """Удаляет записи MealLog за сегодня."""
        try:
            user = await user_repository.get_by_telegram_id(db, message.from_user.id)
            if not user:
                await message.answer("Пользователь не найден. Используйте /start.")
                return

            from datetime import datetime
            now = datetime.utcnow()
            date_from = datetime(now.year, now.month, now.day)

            meals = await meal_log_repository.get_meals_by_date(db, user.id, date_from, now)
            deleted = 0
            for m in meals:
                ok = await meal_log_repository.delete(db, m.id)
                if ok:
                    deleted += 1

            await message.answer(f"♻️ Сброс завершён. Удалено записей: {deleted}.")

        except Exception as e:
            logger.error(f"Ошибка в /reset_today: {str(e)}")
            await message.answer("Не удалось очистить данные. Попробуйте позже.")

    @staticmethod
    async def cmd_feedback(message: types.Message, state: FSMContext):
        """Команда для отправки обратной связи администратору"""
        await message.answer("💬 Пожалуйста, напишите ваше сообщение. Я передам его администратору.")
        await state.set_state(UserStates.awaiting_feedback_message)

    @staticmethod
    async def cmd_subscription(message: types.Message, db: AsyncSession):
        """Обработчик команды /subscription для оформления или проверки подписки"""
        try:
            # Получаем пользователя или создаём
            user = await user_repository.get_or_create_user(
                db,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )

            # Проверяем активную подписку
            active_sub = await subscription_repository.get_active_subscription(db, user.id)
            if active_sub:
                end_date = active_sub.end_date.strftime("%d.%m.%Y")
                
                keyboard = types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(
                            text="❌ Отменить подписку",
                            callback_data="cancel_subscription"
                        )]
                    ]
                )
                
                await message.answer(
                    f"✅ У вас есть активная подписка до {end_date}\n\n"
                    "Вы можете использовать все функции без ограничений!",
                    reply_markup=keyboard
                )
                return

            # Текущие лимиты
            usage = await usage_repository.get_or_create_usage(db, user.id)
            remaining_photos = max(0, config.FREE_PHOTO_LIMIT - usage.photos_used)
            remaining_questions = max(0, config.FREE_QUESTION_LIMIT - usage.questions_used)

            # Формируем ссылку возврата
            return_url = f"https://t.me/{(await message.bot.get_me()).username}"
            payment_info = await payment_service.create_payment(
                amount=config.SUBSCRIPTION_PRICE,
                description=f"Подписка на ИИ Нутрициолог на {config.SUBSCRIPTION_DAYS} дней",
                return_url=return_url,
                metadata={"user_id": user.id, "telegram_id": user.telegram_id}
            )

            if payment_info:
                # Определяем текст кнопки в зависимости от предыдущей подписки
                last_sub = await subscription_repository.get_last_subscription(db, user.id)
                first_btn_text = "💳 Подписаться" if last_sub is None else "💳 Возобновить подписку"

                # Сохраняем информацию о платеже
                await subscription_repository.create_subscription(
                    db,
                    user_id=user.id,
                    payment_id=payment_info["id"],
                    amount=payment_info["amount"]
                )

                await message.answer(
                    f"💳 *Подписка ИИ Нутрициолог*\n\n"
                    f"Бесплатные лимиты: {remaining_photos} распознаваний КБЖУ по фото / {remaining_questions} вопросов ИИ нутрициологу\n"
                    f"Стоимость: {config.SUBSCRIPTION_PRICE} ₽ на {config.SUBSCRIPTION_DAYS} дней\n\n"
                    f"После оплаты вы получите:\n"
                    f"✅ Безлимитный анализ фото\n"
                    f"✅ Безлимитные вопросы\n\n"
                    "Нажмите кнопку ниже для перехода к оплате:",
                    parse_mode="Markdown",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text=first_btn_text, url=payment_info["confirmation_url"])],
                            [types.InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_payment_{payment_info['id']}")],
                            [types.InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_payment_{payment_info['id']}")]
                        ]
                    )
                )
            else:
                await message.answer("😔 Не удалось создать платеж. Попробуйте позже или обратитесь в поддержку.")

        except Exception as e:
            logger.error(f"Ошибка в обработчике /subscription: {str(e)}")
            await message.answer("😔 Произошла ошибка при оформлении подписки. Попробуйте позже.")

# Регистрация обработчиков команд
def register_command_handlers(dp):
    """Регистрация обработчиков команд"""
    # Регистрация обработчиков команд для aiogram 3.x
    dp.message.register(CommandHandlers.start_command, Command("start"))
    dp.message.register(CommandHandlers.help_command, Command("help"))
    dp.message.register(CommandHandlers.cmd_clear, Command("clear"))
    dp.message.register(CommandHandlers.cmd_goals, Command("goals"))
    dp.message.register(CommandHandlers.cmd_report, Command("report"))
    dp.message.register(CommandHandlers.cmd_stats, Command("stats"))
    dp.message.register(CommandHandlers.test_prompt_command, Command("test_prompt"))
    dp.message.register(CommandHandlers.reset_command, Command("reset"))
    dp.message.register(CommandHandlers.force_prompt_command, Command("force_prompt"))
    dp.message.register(CommandHandlers.cmd_calories, Command("calories"))
    dp.message.register(CommandHandlers.cmd_day_calories, Command("day_calories"))
    dp.message.register(CommandHandlers.cmd_today_meals, Command("today_meals"))
    dp.message.register(CommandHandlers.cmd_reset_today, Command("reset_today"))
    dp.message.register(CommandHandlers.cmd_prefs, Command("prefs"))
    dp.message.register(CommandHandlers.cmd_feedback, Command("feedback"))
    dp.message.register(CommandHandlers.cmd_subscription, Command("subscription"))
