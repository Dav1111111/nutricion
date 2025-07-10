"""
Сервис для автоматического продления подписок
"""
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import db_connection
from database.subscription_repository import subscription_repository
from services.payment_service import payment_service
from config.config import config

logger = logging.getLogger(__name__)


class SubscriptionRenewalService:
    """Сервис для управления автопродлением подписок"""
    
    def __init__(self):
        self.is_running = False
        self.check_interval = 3600  # Проверка каждый час
        self.bot = None  # будет установлен позднее через set_bot
    
    def set_bot(self, bot_instance):
        """Установить экземпляр бота, чтобы избежать циклического импорта"""
        self.bot = bot_instance
    
    async def start(self):
        """Запустить сервис автопродления"""
        self.is_running = True
        logger.info("Сервис автопродления подписок запущен")
        
        while self.is_running:
            try:
                await self.check_and_renew_subscriptions()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Ошибка в сервисе автопродления: {e}")
                await asyncio.sleep(60)  # Подождать минуту при ошибке
    
    async def stop(self):
        """Остановить сервис"""
        self.is_running = False
        logger.info("Сервис автопродления подписок остановлен")
    
    async def check_and_renew_subscriptions(self):
        """Проверить и продлить истекающие подписки"""
        async with db_connection.async_session() as db:
            # Получаем подписки, которые истекают в течение суток
            expiring_subs = await subscription_repository.get_expiring_subscriptions(db, days_before=1)
            
            logger.info(f"Найдено {len(expiring_subs)} подписок для продления")
            
            for subscription in expiring_subs:
                try:
                    await self.process_renewal(db, subscription)
                except Exception as e:
                    logger.error(f"Ошибка при продлении подписки {subscription.id}: {e}")
                    await subscription_repository.update_renewal_attempt(db, subscription.id)
    
    async def process_renewal(self, db: AsyncSession, subscription: 'UserSubscription'):
        """Обработать продление одной подписки"""
        # Проверяем количество попыток
        if subscription.renewal_attempts >= 3:
            logger.warning(f"Превышено количество попыток продления для подписки {subscription.id}")
            await self.notify_user_renewal_failed(subscription)
            return
        
        # Проверяем, не было ли попытки в последние 6 часов
        if subscription.last_renewal_attempt:
            time_since_last = datetime.utcnow() - subscription.last_renewal_attempt
            if time_since_last < timedelta(hours=6):
                logger.info(f"Слишком рано для повторной попытки продления подписки {subscription.id}")
                return
        
        # Создаем рекуррентный платеж
        if not self.bot:
            logger.error("Bot instance not set in SubscriptionRenewalService")
            return

        return_url = f"https://t.me/{(await self.bot.get_me()).username}"
        payment_info = await payment_service.create_recurrent_payment(
            amount=subscription.amount,
            description=f"Продление подписки на ИИ Нутрициолог",
            return_url=return_url,
            parent_payment_id=subscription.payment_id,
            metadata={
                "user_id": subscription.user_id,
                "telegram_id": subscription.user.telegram_id,
                "is_renewal": True
            }
        )
        
        if payment_info:
            # Создаем новую запись подписки
            new_subscription = await subscription_repository.create_renewal_subscription(
                db, subscription, payment_info["id"]
            )
            
            # Автоматически подтверждаем платеж (для рекуррентных платежей)
            if payment_info.get("status") == "succeeded":
                await subscription_repository.activate_subscription(db, payment_info["id"])
                await self.notify_user_renewal_success(subscription)
            else:
                # Отправляем уведомление о необходимости подтверждения
                await self.notify_user_renewal_pending(subscription, payment_info)
        else:
            # Обновляем счетчик попыток
            await subscription_repository.update_renewal_attempt(db, subscription.id)
            logger.error(f"Не удалось создать платеж для продления подписки {subscription.id}")
    
    async def notify_user_renewal_success(self, subscription: 'UserSubscription'):
        """Уведомить пользователя об успешном продлении"""
        try:
            new_end_date = (subscription.end_date + timedelta(days=config.SUBSCRIPTION_DAYS)).strftime("%d.%m.%Y")
            await self.bot.send_message(
                subscription.user.telegram_id,
                f"✅ Ваша подписка автоматически продлена до {new_end_date}!\n\n"
                f"Спасибо, что остаётесь с нами! 🙏\n\n"
                f"Управлять автопродлением можно в /subscription"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {subscription.user.telegram_id}: {e}")
    
    async def notify_user_renewal_pending(self, subscription: 'UserSubscription', payment_info: dict):
        """Уведомить пользователя о необходимости подтверждения платежа"""
        try:
            from aiogram import types
            
            keyboard = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(
                        text="💳 Подтвердить оплату",
                        url=payment_info["confirmation_url"]
                    )],
                    [types.InlineKeyboardButton(
                        text="❌ Отменить продление",
                        callback_data=f"cancel_renewal_{payment_info['id']}"
                    )]
                ]
            )
            
            await self.bot.send_message(
                subscription.user.telegram_id,
                f"📅 Ваша подписка истекает {subscription.end_date.strftime('%d.%m.%Y')}\n\n"
                f"Для продления необходимо подтвердить платеж.\n"
                f"Стоимость: {subscription.amount} ₽",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {subscription.user.telegram_id}: {e}")
    
    async def notify_user_renewal_failed(self, subscription: 'UserSubscription'):
        """Уведомить пользователя о неудачном продлении"""
        try:
            await self.bot.send_message(
                subscription.user.telegram_id,
                f"❌ Не удалось автоматически продлить вашу подписку.\n\n"
                f"Подписка истекает {subscription.end_date.strftime('%d.%m.%Y')}\n\n"
                f"Пожалуйста, продлите подписку вручную через /subscription"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {subscription.user.telegram_id}: {e}")


# Создаем экземпляр сервиса
subscription_renewal_service = SubscriptionRenewalService() 