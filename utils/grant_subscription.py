"""
Утилита для ручной выдачи подписки пользователю по Telegram ID.

Пример запуска:
  python3 -m utils.grant_subscription --telegram-id 483246512 --days 30

Делает следующее:
  - Создаёт пользователя при отсутствии
  - Если подписка активна — продлевает на указанное количество дней
  - Если подписки нет — создаёт и активирует на указанный срок
  - Отключает автопродление для вручную выданной подписки
  - Сбрасывает счётчики использования (бесплатные лимиты)
  - Помечает пользователя как is_premium=True
"""

import argparse
import asyncio
from datetime import datetime, timedelta
import logging

from database.connection import db_connection
from database.repository import user_repository
from database.subscription_repository import subscription_repository, usage_repository
from models.database import UserSubscription
from config.config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def grant_subscription(telegram_id: int, days: int) -> None:
    async with db_connection.async_session() as db:
        # Инициализация схемы (на случай запуска отдельно)
        await db_connection.init_db()

        # Получаем/создаём пользователя
        user = await user_repository.get_or_create_user(db, telegram_id=telegram_id)

        # Проверяем текущую активную подписку
        active = await subscription_repository.get_active_subscription(db, user.id)

        if active:
            # Продлеваем существующую активную подписку
            base_date = active.end_date if active.end_date and active.end_date > datetime.utcnow() else datetime.utcnow()
            active.end_date = base_date + timedelta(days=days)
            # Для вручную выданной подписки выключаем автопродление
            active.is_auto_renewal = False
            await db.commit()
            await db.refresh(active)
            logger.info(
                f"Подписка пользователя {telegram_id} продлена до {active.end_date.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        else:
            # Создаём платеж и активируем подписку
            payment_id = f"manual_{telegram_id}_{int(datetime.utcnow().timestamp())}"
            amount = float(config.SUBSCRIPTION_PRICE)
            sub = await subscription_repository.create_subscription(
                db, user_id=user.id, payment_id=payment_id, amount=amount
            )

            # Активируем (установит start/end по config.SUBSCRIPTION_DAYS)
            sub = await subscription_repository.activate_subscription(db, payment_id)
            if sub is None:
                raise RuntimeError("Не удалось активировать подписку")

            # Переопределим срок, если days отличается от SUBSCRIPTION_DAYS
            if days != config.SUBSCRIPTION_DAYS:
                sub.start_date = datetime.utcnow()
                sub.end_date = sub.start_date + timedelta(days=days)

            # Выключаем автопродление для ручной подписки
            sub.is_auto_renewal = False
            await db.commit()
            await db.refresh(sub)

            logger.info(
                f"Подписка пользователю {telegram_id} выдана до {sub.end_date.strftime('%Y-%m-%d %H:%M:%S')}"
            )

        # Сброс счётчиков использования
        await usage_repository.reset_usage(db, user.id)

        # Помечаем как премиум-пользователя
        user.is_premium = True
        await db.commit()

        logger.info("Счётчики использования сброшены. Пользователь помечен как premium")


async def main():
    parser = argparse.ArgumentParser(description="Ручная выдача подписки пользователю по Telegram ID")
    parser.add_argument("--telegram-id", type=int, required=True, help="Telegram ID пользователя")
    parser.add_argument("--days", type=int, default=config.SUBSCRIPTION_DAYS, help="Количество дней подписки")
    args = parser.parse_args()

    await grant_subscription(args.telegram_id, args.days)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nОперация отменена пользователем")


