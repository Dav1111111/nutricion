import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from aiogram import types
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from handlers.command_handlers import UserStates
from services.ai_service import ai_service
from database.repository import user_repository, message_repository, meal_log_repository
from database.repository import nutritional_goal_repository, user_preference_repository, feedback_repository
from database.subscription_repository import subscription_repository, usage_repository
from services.payment_service import payment_service
from config.config import config

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CallbackHandlers:
    """Обработчики callback-запросов бота"""

    @staticmethod
    async def handle_feedback(callback: types.CallbackQuery, state: FSMContext, db: AsyncSession):
        """Обработчик обратной связи"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, callback.from_user.id)

            if not user:
                await callback.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return

            # Парсинг callback_data
            parts = callback.data.split("_")
            feedback_type = parts[1]  # "good" или "bad"
            message_id = int(parts[2])

            # Получение сообщения, к которому относится обратная связь
            message = await message_repository.get_by_id(db, message_id)

            if not message:
                await callback.answer("⚠️ Сообщение не найдено.")
                return

            # Добавление записи обратной связи
            feedback = await feedback_repository.create(
                db,
                message_id=message_id,
                rating=5 if feedback_type == "good" else 1
            )

            # Удаление кнопок из сообщения
            await callback.message.edit_reply_markup(reply_markup=None)

            if feedback_type == "good":
                await callback.answer("✅ Спасибо за положительную оценку!")
                await callback.message.edit_text("✅ Вы оценили ответ как полезный. Спасибо за обратную связь!")
            else:
                await callback.answer("✅ Спасибо за обратную связь!")
                await callback.message.edit_text("✅ Вы оценили ответ как неполезный. Можете написать, что можно улучшить:")

                # Сохраняем ID обратной связи в состоянии
                await state.set_state(UserStates.awaiting_feedback)
                await state.update_data(feedback_id=feedback.id)

        except Exception as e:
            logger.error(f"Ошибка в обработчике обратной связи: {str(e)}")
            await callback.answer("😔 Произошла ошибка при обработке обратной связи.")

    @staticmethod
    async def handle_meal_type(callback: types.CallbackQuery, db: AsyncSession):
        """Обработчик выбора типа приема пищи"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, callback.from_user.id)

            if not user:
                await callback.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return

            # Парсинг callback_data
            parts = callback.data.split("_")
            meal_type = parts[2]  # "breakfast", "lunch", "dinner", "snack"
            meal_log_id = int(parts[3])

            # Получение записи о приеме пищи
            meal_log = await meal_log_repository.get_by_id(db, meal_log_id)

            if not meal_log:
                await callback.answer("⚠️ Запись о приеме пищи не найдена.")
                return

            # Словарь для перевода типа приема пищи
            meal_types = {
                "breakfast": "завтрак",
                "lunch": "обед",
                "dinner": "ужин",
                "snack": "перекус"
            }

            # Обновление типа приема пищи
            await meal_log_repository.update(
                db,
                meal_log_id,
                meal_type=meal_types.get(meal_type, "unknown")
            )

            # Удаление кнопок из сообщения
            await callback.message.edit_reply_markup(reply_markup=None)

            await callback.answer(f"✅ Прием пищи записан как {meal_types.get(meal_type)}!")
            await callback.message.edit_text(f"✅ Прием пищи записан как: {meal_types.get(meal_type)}")

        except Exception as e:
            logger.error(f"Ошибка в обработчике типа приема пищи: {str(e)}")
            await callback.answer("😔 Произошла ошибка при сохранении типа приема пищи.")

    @staticmethod
    async def handle_goal_type(callback: types.CallbackQuery, state: FSMContext, db: AsyncSession):
        """Обработчик выбора типа цели по питанию"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, callback.from_user.id)

            if not user:
                await callback.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return

            # Парсинг callback_data
            parts = callback.data.split("_")
            goal_type = parts[1]  # "weight_loss", "weight_gain", "maintenance"

            # Словарь для перевода типа цели
            goal_types = {
                "weight_loss": "снижение веса",
                "weight_gain": "набор массы",
                "maintenance": "поддержание веса"
            }

            # Сохраняем тип цели в состоянии
            await state.update_data(goal_type=goal_types.get(goal_type))

            # Запрос калорий
            await callback.message.edit_text(
                f"🎯 Вы выбрали цель: {goal_types.get(goal_type)}.\n\n"
                f"Теперь укажите желаемое количество калорий в день (например, 2000):"
            )

            await state.set_state(UserStates.awaiting_calories)

            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в обработчике типа цели: {str(e)}")
            await callback.answer("😔 Произошла ошибка при сохранении типа цели.")

    @staticmethod
    async def handle_prefs_change(callback: types.CallbackQuery, state: FSMContext, db: AsyncSession):
        """Обработчик изменения предпочтений"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, callback.from_user.id)

            if not user:
                await callback.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return

            # Парсинг callback_data
            action = callback.data.split("_")[1]  # "change" или "keep"

            if action == "change":
                # Запрос новых предпочтений
                await callback.message.edit_text(
                    "🍽️ Укажите ваши новые предпочтения в питании:\n\n"
                    "• Тип диеты (обычная, вегетарианская, веганская, кето и т.д.)\n"
                    "• Аллергии или непереносимость продуктов\n"
                    "• Продукты, которые вы не любите\n"
                    "• Предпочитаемую кухню (если есть)\n\n"
                    "Пример: \"Обычная диета, аллергия на орехи, не люблю баклажаны, предпочитаю средиземноморскую кухню\""
                )

                await state.set_state(UserStates.awaiting_preferences)
            else:
                # Оставляем предпочтения без изменений
                await callback.message.edit_text("✅ Ваши предпочтения остаются без изменений.")

            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в обработчике изменения предпочтений: {str(e)}")
            await callback.answer("😔 Произошла ошибка при обработке запроса.")

    @staticmethod
    async def handle_goals_change(callback: types.CallbackQuery, state: FSMContext, db: AsyncSession):
        """Обработчик изменения целей"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, callback.from_user.id)

            if not user:
                await callback.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return

            # Парсинг callback_data
            action = callback.data.split("_")[1]  # "change" или "keep"

            if action == "change":
                # Запрос нового типа цели
                await callback.message.edit_text(
                    "🎯 Выберите новый тип вашей цели по питанию:",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(text="🔽 Снижение веса", callback_data="goal_weight_loss")],
                            [types.InlineKeyboardButton(text="🔼 Набор массы", callback_data="goal_weight_gain")],
                            [types.InlineKeyboardButton(text="➡️ Поддержание веса", callback_data="goal_maintenance")]
                        ]
                    )
                )

                await state.set_state(UserStates.awaiting_goal_type)
            else:
                # Оставляем цели без изменений
                await callback.message.edit_text("✅ Ваши цели по питанию остаются без изменений.")

            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в обработчике изменения целей: {str(e)}")
            await callback.answer("😔 Произошла ошибка при обработке запроса.")

    @staticmethod
    async def handle_report_period(callback: types.CallbackQuery, db: AsyncSession):
        """Обработчик выбора периода для отчета"""
        try:
            # Получение пользователя
            user = await user_repository.get_by_telegram_id(db, callback.from_user.id)

            if not user:
                await callback.answer("⚠️ Пользователь не найден. Пожалуйста, используйте /start для начала.")
                return

            # Парсинг callback_data
            parts = callback.data.split("_")
            period = parts[1]  # "today", "week", "month"

            # Определение временного интервала
            now = datetime.utcnow()
            if period == "today":
                date_from = datetime(now.year, now.month, now.day)
                date_to = now
                period_name = "сегодня"
            elif period == "week":
                date_from = now - timedelta(days=7)
                date_to = now
                period_name = "за последнюю неделю"
            else:  # month
                date_from = now - timedelta(days=30)
                date_to = now
                period_name = "за последний месяц"

            # Получение записей о приемах пищи за указанный период
            meals = await meal_log_repository.get_meals_by_date(db, user.id, date_from, date_to)

            if not meals:
                await callback.message.edit_text(f"⚠️ За выбранный период ({period_name}) не найдено записей о питании.")
                await callback.answer()
                return

            # Подготовка данных для анализа
            meals_data = []
            for meal in meals:
                meal_data = {
                    "тип": meal.meal_type,
                    "название": meal.meal_name,
                    "калории": meal.calories,
                    "белки": meal.proteins,
                    "жиры": meal.fats,
                    "углеводы": meal.carbs,
                    "дата": meal.date.strftime("%d.%m.%Y %H:%M")
                }
                meals_data.append(meal_data)

            # Получение целей пользователя
            goal = await nutritional_goal_repository.get_active_goal(db, user.id)

            if goal:
                goals_data = {
                    "тип_цели": goal.goal_type,
                    "целевые_калории": goal.target_calories,
                    "целевой_белок": goal.target_proteins,
                    "целевые_жиры": goal.target_fats,
                    "целевые_углеводы": goal.target_carbs
                }
            else:
                goals_data = {}

            # Ответ о начале генерации отчета
            await callback.message.edit_text(f"📊 Генерирую отчет о питании {period_name}...")

            # Анализ прогресса питания
            report = await ai_service.analyze_nutrition_progress(meals_data, goals_data)

            # Разбиение отчета на части, если он слишком большой
            if len(report) > 4000:
                parts = [report[i:i+4000] for i in range(0, len(report), 4000)]
                for i, part in enumerate(parts):
                    if i == 0:
                        await callback.message.edit_text(f"📊 Отчет о питании {period_name} (часть {i+1}/{len(parts)}):\n\n{part}", parse_mode="Markdown")
                    else:
                        await callback.message.answer(f"📊 Отчет о питании {period_name} (часть {i+1}/{len(parts)}):\n\n{part}", parse_mode="Markdown")
            else:
                await callback.message.edit_text(f"📊 Отчет о питании {period_name}:\n\n{report}", parse_mode="Markdown")

            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в обработчике периода отчета: {str(e)}")
            await callback.answer("😔 Произошла ошибка при генерации отчета.")
            await callback.message.edit_text("😔 Произошла ошибка при генерации отчета. Пожалуйста, попробуйте позже.")

    @staticmethod
    async def handle_calories_change(callback: types.CallbackQuery, state: FSMContext, db: AsyncSession):
        """Обработчик изменения целевых калорий"""
        try:
            user = await user_repository.get_by_telegram_id(db, callback.from_user.id)

            if not user:
                await callback.answer("⚠️ Пользователь не найден. Используйте /start.")
                return

            action = callback.data.split("_")[0]  # change или keep

            if action == "change":
                # Просим ввести новое значение
                await callback.message.edit_text("Введите новое количество калорий в день (например, 2000):")
                await state.set_state(UserStates.awaiting_calories)
            else:
                await callback.message.edit_text("✅ Цель по калориям остаётся без изменений.")

            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в обработчике изменения калорий: {str(e)}")
            await callback.answer("😔 Произошла ошибка.")

    @staticmethod
    async def handle_subscribe(callback: types.CallbackQuery, db: AsyncSession):
        """Обработчик кнопки подписки"""
        try:
            user = await user_repository.get_by_telegram_id(db, callback.from_user.id)
            if not user:
                await callback.answer("⚠️ Пользователь не найден. Используйте /start.")
                return
            
            # Проверяем активную подписку
            active_sub = await subscription_repository.get_active_subscription(db, user.id)
            if active_sub:
                end_date = active_sub.end_date.strftime("%d.%m.%Y")
                await callback.message.edit_text(
                    f"✅ У вас уже есть активная подписка до {end_date}\n\n"
                    "Вы можете использовать все функции без ограничений!"
                )
                await callback.answer()
                return
            
            # Получаем текущие лимиты использования
            usage = await usage_repository.get_or_create_usage(db, user.id)
            remaining_photos = max(0, config.FREE_PHOTO_LIMIT - usage.photos_used)
            remaining_questions = max(0, config.FREE_QUESTION_LIMIT - usage.questions_used)

            # Формируем URL, по которому пользователь вернётся после оплаты
            return_url = f"https://t.me/{(await callback.bot.get_me()).username}"
            payment_info = await payment_service.create_payment(
                amount=config.SUBSCRIPTION_PRICE,
                description=f"Подписка на ИИ Нутрициолог на {config.SUBSCRIPTION_DAYS} дней",
                return_url=return_url,
                metadata={"user_id": user.id, "telegram_id": user.telegram_id}
            )
            
            if payment_info:
                # Сохраняем информацию о платеже
                await subscription_repository.create_subscription(
                    db,
                    user_id=user.id,
                    payment_id=payment_info["id"],
                    amount=payment_info["amount"]
                )

                last_sub = await subscription_repository.get_last_subscription(db, user.id)
                first_btn_text = "💳 Подписаться" if last_sub is None else "💳 Возобновить подписку"
                
                await callback.message.edit_text(
                    f"💳 *Подписка ИИ Нутрициолог*\n\n"
                    f"Бесплатные лимиты: {remaining_photos} распознаваний КБЖУ по фото / {remaining_questions} вопросов ИИ нутрициологу\n"
                    f"Стоимость: {config.SUBSCRIPTION_PRICE} ₽ на {config.SUBSCRIPTION_DAYS} дней\n\n"
                    f"После оплаты вы получите:\n"
                    f"✅ Безлимитный анализ фото\n"
                    f"✅ Безлимитные вопросы\n\n"
                    f"Нажмите кнопку ниже для перехода к оплате:",
                    parse_mode="Markdown",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(
                                text=first_btn_text, 
                                url=payment_info["confirmation_url"]
                            )],
                            [types.InlineKeyboardButton(
                                text="✅ Я оплатил", 
                                callback_data=f"check_payment_{payment_info['id']}"
                            )],
                            [types.InlineKeyboardButton(
                                text="❌ Отменить", 
                                callback_data=f"cancel_payment_{payment_info['id']}"
                            )]
                        ]
                    )
                )
            else:
                await callback.message.edit_text(
                    "😔 Не удалось создать платеж. Попробуйте позже или обратитесь в поддержку."
                )
            
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в обработчике подписки: {str(e)}")
            await callback.answer("😔 Произошла ошибка.")

    @staticmethod
    async def handle_check_payment(callback: types.CallbackQuery, db: AsyncSession):
        """Проверка статуса платежа"""
        try:
            payment_id = callback.data.split("_")[2]
            
            # Проверяем статус платежа
            status = await payment_service.check_payment_status(payment_id)
            
            if status == "succeeded":
                # Активируем подписку
                subscription = await subscription_repository.activate_subscription(db, payment_id)
                if subscription:
                    # Сбрасываем счетчики
                    await usage_repository.reset_usage(db, subscription.user_id)
                    
                    end_date = subscription.end_date.strftime("%d.%m.%Y")
                    await callback.message.edit_text(
                        f"✅ *Подписка активирована!*\n\n"
                        f"Срок действия: до {end_date}\n"
                        f"Теперь вы можете пользоваться всеми функциями без ограничений!\n\n"
                        f"Спасибо за поддержку проекта! 🙏",
                        parse_mode="Markdown"
                    )
            elif status == "pending" or status == "waiting_for_capture":
                await callback.answer("⏳ Платеж еще обрабатывается. Попробуйте проверить через минуту.")
            else:
                await callback.answer("❌ Платеж не прошел. Попробуйте оплатить заново.")
                
        except Exception as e:
            logger.error(f"Ошибка при проверке платежа: {str(e)}")
            await callback.answer("😔 Произошла ошибка при проверке платежа.")

    @staticmethod
    async def handle_cancel_payment(callback: types.CallbackQuery, db: AsyncSession):
        """Отмена оплаты и подписки"""
        try:
            payment_id = callback.data.split("_")[2]

            # Находим подписку по payment_id и отменяем
            from sqlalchemy import select
            from models.database import UserSubscription

            result = await db.execute(select(UserSubscription).where(UserSubscription.payment_id == payment_id))
            subscription = result.scalar_one_or_none()

            if subscription and subscription.status == 'pending':
                subscription.status = 'canceled'
                await db.commit()
                await callback.message.edit_text("❌ Оплата отменена. Подписка не активирована.")
            else:
                await callback.message.edit_text("⚠️ Не удалось отменить оплату или подписка уже обработана.")

            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка при отмене оплаты: {str(e)}")
            await callback.answer("😔 Произошла ошибка при отмене оплаты.")

    @staticmethod
    async def handle_menu_feedback(callback: types.CallbackQuery, state: FSMContext, db: AsyncSession):
        """Запрашивает текст обратной связи у пользователя"""
        try:
            await callback.message.answer("💬 Пожалуйста, напишите ваше сообщение. Мы ценим вашу обратную связь!")
            # Устанавливаем состояние ожидания текстового сообщения обратной связи
            await state.set_state(UserStates.awaiting_feedback_message)
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в обработчике menu_feedback: {str(e)}")
            await callback.answer("😔 Произошла ошибка. Попробуйте позже.")

    @staticmethod
    async def handle_toggle_auto_renewal(callback: types.CallbackQuery, db: AsyncSession):
        """Переключить автопродление подписки"""
        try:
            user = await user_repository.get_by_telegram_id(db, callback.from_user.id)
            if not user:
                await callback.answer("⚠️ Пользователь не найден")
                return
            
            # Получаем активную подписку
            active_sub = await subscription_repository.get_active_subscription(db, user.id)
            if not active_sub:
                await callback.answer("⚠️ У вас нет активной подписки")
                return
            
            # Переключаем автопродление
            new_status = not active_sub.is_auto_renewal
            updated_sub = await subscription_repository.toggle_auto_renewal(db, user.id, new_status)
            
            if updated_sub:
                status_text = "включено" if new_status else "выключено"
                await callback.message.edit_text(
                    f"✅ Автопродление {status_text}!\n\n"
                    f"Ваша подписка действует до {updated_sub.end_date.strftime('%d.%m.%Y')}\n\n"
                    f"Вы можете изменить настройки в любое время через /subscription",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [types.InlineKeyboardButton(
                                text="🔙 Вернуться",
                                callback_data="back_to_subscription"
                            )]
                        ]
                    )
                )
                await callback.answer(f"Автопродление {status_text}")
            else:
                await callback.answer("😔 Не удалось изменить настройки")
                
        except Exception as e:
            logger.error(f"Ошибка при переключении автопродления: {str(e)}")
            await callback.answer("😔 Произошла ошибка")

    @staticmethod
    async def handle_cancel_subscription(callback: types.CallbackQuery, db: AsyncSession):
        """Отменить подписку"""
        try:
            # Сначала спрашиваем подтверждение
            await callback.message.edit_text(
                "❓ Вы уверены, что хотите отменить подписку?\n\n"
                "Вы сможете пользоваться всеми функциями до конца оплаченного периода.",
                reply_markup=types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(
                            text="✅ Да, отменить",
                            callback_data="confirm_cancel_subscription"
                        )],
                        [types.InlineKeyboardButton(
                            text="❌ Нет, оставить",
                            callback_data="back_to_subscription"
                        )]
                    ]
                )
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка при отмене подписки: {str(e)}")
            await callback.answer("😔 Произошла ошибка")

    @staticmethod
    async def handle_confirm_cancel_subscription(callback: types.CallbackQuery, db: AsyncSession):
        """Подтвердить отмену подписки"""
        try:
            user = await user_repository.get_by_telegram_id(db, callback.from_user.id)
            if not user:
                await callback.answer("⚠️ Пользователь не найден")
                return
            
            # Получаем активную подписку
            active_sub = await subscription_repository.get_active_subscription(db, user.id)
            if not active_sub:
                await callback.answer("⚠️ У вас нет активной подписки")
                return
            
            # Меняем статус подписки на canceled, чтобы не считалась активной
            active_sub.status = 'canceled'
            await db.commit()
 
            await callback.message.edit_text(
                f"✅ Подписка отменена\n\n"
                f"Вы можете пользоваться всеми функциями до {active_sub.end_date.strftime('%d.%m.%Y')}\n\n"
                f"Спасибо, что были с нами! 🙏\n\n"
                f"Вы всегда можете возобновить подписку через /subscription"
            )
            await callback.answer("Подписка отменена")
            
        except Exception as e:
            logger.error(f"Ошибка при подтверждении отмены подписки: {str(e)}")
            await callback.answer("😔 Произошла ошибка")

    @staticmethod
    async def handle_back_to_subscription(callback: types.CallbackQuery):
        """Вернуться к меню подписки"""
        try:
            # Просто вызываем команду /subscription
            await callback.message.answer("/subscription")
            await callback.message.delete()
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка при возврате к подписке: {str(e)}")
            await callback.answer("😔 Произошла ошибка")

    @staticmethod
    async def handle_cancel_renewal(callback: types.CallbackQuery, db: AsyncSession):
        """Отменить продление подписки"""
        try:
            payment_id = callback.data.split("_")[2]
            
            # Отменяем платеж
            from models.database import UserSubscription
            result = await db.execute(
                select(UserSubscription).where(UserSubscription.payment_id == payment_id)
            )
            subscription = result.scalar_one_or_none()
            
            if subscription and subscription.status == 'pending':
                subscription.status = 'canceled'
                await db.commit()
                
                # Отключаем автопродление у родительской подписки
                if subscription.parent_payment_id:
                    parent_result = await db.execute(
                        select(UserSubscription).where(
                            UserSubscription.payment_id == subscription.parent_payment_id
                        )
                    )
                    parent_sub = parent_result.scalar_one_or_none()
                    if parent_sub:
                        parent_sub.is_auto_renewal = False
                        await db.commit()
                
                await callback.message.edit_text(
                    "✅ Автопродление отменено\n\n"
                    "Вы можете продлить подписку вручную через /subscription"
                )
            else:
                await callback.message.edit_text("⚠️ Не удалось отменить продление")
            
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка при отмене продления: {str(e)}")
            await callback.answer("😔 Произошла ошибка")

    @staticmethod
    async def handle_edit_meal(callback: types.CallbackQuery, state: FSMContext, db: AsyncSession):
        """Обработчик кнопки редактирования блюда"""
        try:
            meal_log_id = int(callback.data.split("_")[2])
            meal_log = await meal_log_repository.get_by_id(db, meal_log_id)

            if not meal_log:
                await callback.answer("⚠️ Запись о приеме пищи не найдена.")
                return

            # Просим уточнить блюдо/ингредиенты
            from handlers.command_handlers import UserStates
            await callback.message.edit_text(
                "✏️ Уточните, что за блюдо либо ингредиент.\n"
                "Например: 'Гречневая кашка 200 г + куриное бедро 150 г'"
            )

            # сохраняем meal_id в FSM context
            await state.set_state(UserStates.awaiting_meal_edit_description)
            await state.update_data(edit_meal_id=meal_log_id)
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в обработчике редактирования блюда: {str(e)}")
            await callback.answer("😔 Произошла ошибка при редактировании блюда.")

# Регистрация обработчиков callback-запросов
def register_callback_handlers(dp):
    """Регистрация обработчиков callback-запросов"""
    # Регистрация обработчиков callback-запросов для aiogram 3.x
    dp.callback_query.register(
        CallbackHandlers.handle_feedback,
        lambda c: c.data.startswith("feedback_")
    )

    dp.callback_query.register(
        CallbackHandlers.handle_meal_type,
        lambda c: c.data.startswith("meal_type_")
    )

    dp.callback_query.register(
        CallbackHandlers.handle_goal_type,
        lambda c: c.data.startswith("goal_")
    )

    dp.callback_query.register(
        CallbackHandlers.handle_prefs_change,
        lambda c: c.data.startswith("change_prefs") or c.data.startswith("keep_prefs")
    )

    dp.callback_query.register(
        CallbackHandlers.handle_goals_change,
        lambda c: c.data.startswith("change_goals") or c.data.startswith("keep_goals")
    )

    dp.callback_query.register(
        CallbackHandlers.handle_report_period,
        lambda c: c.data.startswith("report_")
    )

    dp.callback_query.register(
        CallbackHandlers.handle_calories_change,
        lambda c: c.data.startswith("change_calories") or c.data.startswith("keep_calories")
    )

    dp.callback_query.register(
        CallbackHandlers.handle_subscribe,
        lambda c: c.data == "subscribe"
    )

    dp.callback_query.register(
        CallbackHandlers.handle_check_payment,
        lambda c: c.data.startswith("check_payment_")
    )

    dp.callback_query.register(
        CallbackHandlers.handle_cancel_payment,
        lambda c: c.data.startswith("cancel_payment_")
    )

    dp.callback_query.register(
        CallbackHandlers.handle_menu_feedback,
        lambda c: c.data == "menu_feedback"
    )

    dp.callback_query.register(
        CallbackHandlers.handle_cancel_subscription,
        lambda c: c.data == "cancel_subscription"
    )

    dp.callback_query.register(
        CallbackHandlers.handle_confirm_cancel_subscription,
        lambda c: c.data == "confirm_cancel_subscription"
    )

    dp.callback_query.register(
        CallbackHandlers.handle_back_to_subscription,
        lambda c: c.data == "back_to_subscription"
    )

    dp.callback_query.register(
        CallbackHandlers.handle_cancel_renewal,
        lambda c: c.data.startswith("cancel_renewal_")
    )

    # Новый обработчик для редактирования блюда
    dp.callback_query.register(
        CallbackHandlers.handle_edit_meal,
        lambda c: c.data.startswith("edit_meal_")
    )
