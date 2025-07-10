"""
Утилита для ручной проверки и продления подписок
"""
import asyncio
import logging
from datetime import datetime, timedelta

from database.connection import db_connection
from database.subscription_repository import subscription_repository
from services.subscription_renewal_service import subscription_renewal_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def check_expiring_subscriptions():
    """Проверить истекающие подписки"""
    async with db_connection.async_session() as db:
        # Подписки, истекающие в течение 3 дней
        expiring_subs = await subscription_repository.get_expiring_subscriptions(db, days_before=3)
        
        print(f"\n📅 Найдено {len(expiring_subs)} подписок, истекающих в ближайшие 3 дня:\n")
        
        for sub in expiring_subs:
            days_left = (sub.end_date - datetime.utcnow()).days
            auto_renewal = "✅" if sub.is_auto_renewal else "❌"
            
            print(f"User ID: {sub.user_id}")
            print(f"  - Истекает: {sub.end_date.strftime('%d.%m.%Y')} (через {days_left} дней)")
            print(f"  - Автопродление: {auto_renewal}")
            print(f"  - Попытки продления: {sub.renewal_attempts}")
            print(f"  - Последняя попытка: {sub.last_renewal_attempt or 'Нет'}")
            print()


async def force_renewal_check():
    """Принудительно запустить проверку и продление"""
    print("\n🔄 Запуск проверки и продления подписок...\n")
    await subscription_renewal_service.check_and_renew_subscriptions()
    print("\n✅ Проверка завершена")


async def list_all_active_subscriptions():
    """Показать все активные подписки"""
    async with db_connection.async_session() as db:
        from sqlalchemy import select, and_
        from models.database import UserSubscription
        
        result = await db.execute(
            select(UserSubscription).where(
                and_(
                    UserSubscription.status == 'succeeded',
                    UserSubscription.end_date > datetime.utcnow()
                )
            ).order_by(UserSubscription.end_date)
        )
        
        subscriptions = result.scalars().all()
        
        print(f"\n💳 Всего активных подписок: {len(subscriptions)}\n")
        
        for sub in subscriptions:
            days_left = (sub.end_date - datetime.utcnow()).days
            auto_renewal = "✅" if sub.is_auto_renewal else "❌"
            
            print(f"User ID: {sub.user_id}")
            print(f"  - Активна до: {sub.end_date.strftime('%d.%m.%Y')} ({days_left} дней)")
            print(f"  - Автопродление: {auto_renewal}")
            print(f"  - Сумма: {sub.amount} {sub.currency}")
            print()


async def main():
    """Главное меню"""
    await db_connection.init_db()
    
    while True:
        print("\n" + "="*50)
        print("УПРАВЛЕНИЕ ПОДПИСКАМИ")
        print("="*50)
        print("1. Показать истекающие подписки")
        print("2. Запустить проверку и продление")
        print("3. Показать все активные подписки")
        print("0. Выход")
        
        choice = input("\nВыберите действие: ")
        
        if choice == "1":
            await check_expiring_subscriptions()
        elif choice == "2":
            await force_renewal_check()
        elif choice == "3":
            await list_all_active_subscriptions()
        elif choice == "0":
            break
        else:
            print("❌ Неверный выбор")
        
        input("\nНажмите Enter для продолжения...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nВыход...") 