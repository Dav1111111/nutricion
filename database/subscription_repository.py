import logging
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from models.database import UserSubscription, UserUsage
from config.config import config

logger = logging.getLogger(__name__)


class SubscriptionRepository:
    """Репозиторий для работы с подписками"""
    
    async def create_subscription(
        self, 
        db: AsyncSession, 
        user_id: int, 
        payment_id: str,
        amount: float
    ) -> UserSubscription:
        """Создать новую подписку"""
        subscription = UserSubscription(
            user_id=user_id,
            payment_id=payment_id,
            amount=amount,
            status='pending'
        )
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)
        return subscription
    
    async def activate_subscription(
        self, 
        db: AsyncSession, 
        payment_id: str
    ) -> Optional[UserSubscription]:
        """Активировать подписку после успешной оплаты"""
        result = await db.execute(
            select(UserSubscription).where(UserSubscription.payment_id == payment_id)
        )
        subscription = result.scalar_one_or_none()
        
        if subscription:
            subscription.status = 'succeeded'
            subscription.start_date = datetime.utcnow()
            subscription.end_date = datetime.utcnow() + timedelta(days=config.SUBSCRIPTION_DAYS)
            subscription.next_payment_date = subscription.end_date  # Устанавливаем дату следующего платежа
            await db.commit()
            await db.refresh(subscription)
            
        return subscription
    
    async def get_active_subscription(
        self, 
        db: AsyncSession, 
        user_id: int
    ) -> Optional[UserSubscription]:
        """Получить активную подписку пользователя"""
        result = await db.execute(
            select(UserSubscription).where(
                and_(
                    UserSubscription.user_id == user_id,
                    UserSubscription.status == 'succeeded',
                    UserSubscription.end_date > datetime.utcnow()
                )
            ).order_by(UserSubscription.end_date.desc())
        )
        return result.scalar_one_or_none()
    
    async def cancel_subscription(
        self, 
        db: AsyncSession, 
        subscription_id: int
    ) -> bool:
        """Отменить подписку"""
        result = await db.execute(
            select(UserSubscription).where(UserSubscription.id == subscription_id)
        )
        subscription = result.scalar_one_or_none()
        
        if subscription:
            subscription.status = 'canceled'
            subscription.is_auto_renewal = False  # Отключаем автопродление
            await db.commit()
            return True
        return False
    
    async def toggle_auto_renewal(
        self,
        db: AsyncSession,
        user_id: int,
        enable: bool
    ) -> Optional[UserSubscription]:
        """Включить/выключить автопродление для активной подписки"""
        subscription = await self.get_active_subscription(db, user_id)
        if subscription:
            subscription.is_auto_renewal = enable
            await db.commit()
            await db.refresh(subscription)
        return subscription
    
    async def get_expiring_subscriptions(
        self,
        db: AsyncSession,
        days_before: int = 1
    ) -> List[UserSubscription]:
        """Получить подписки, которые скоро истекают"""
        check_date = datetime.utcnow() + timedelta(days=days_before)
        result = await db.execute(
            select(UserSubscription).where(
                and_(
                    UserSubscription.status == 'succeeded',
                    UserSubscription.is_auto_renewal == True,
                    UserSubscription.end_date <= check_date,
                    UserSubscription.end_date > datetime.utcnow()
                )
            )
        )
        return result.scalars().all()
    
    async def create_renewal_subscription(
        self,
        db: AsyncSession,
        old_subscription: UserSubscription,
        payment_id: str
    ) -> UserSubscription:
        """Создать новую подписку для продления"""
        new_subscription = UserSubscription(
            user_id=old_subscription.user_id,
            payment_id=payment_id,
            amount=old_subscription.amount,
            currency=old_subscription.currency,
            status='pending',
            parent_payment_id=old_subscription.payment_id,
            is_auto_renewal=old_subscription.is_auto_renewal
        )
        db.add(new_subscription)
        await db.commit()
        await db.refresh(new_subscription)
        return new_subscription
    
    async def update_renewal_attempt(
        self,
        db: AsyncSession,
        subscription_id: int
    ) -> None:
        """Обновить информацию о попытке продления"""
        result = await db.execute(
            select(UserSubscription).where(UserSubscription.id == subscription_id)
        )
        subscription = result.scalar_one_or_none()
        if subscription:
            subscription.renewal_attempts += 1
            subscription.last_renewal_attempt = datetime.utcnow()
            await db.commit()

    async def get_last_subscription(
        self,
        db: AsyncSession,
        user_id: int
    ) -> Optional[UserSubscription]:
        """Получить последнюю подписку пользователя (любого статуса)"""
        result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == user_id
            ).order_by(UserSubscription.created_at.desc())
        )
        return result.scalars().first()


class UsageRepository:
    """Репозиторий для отслеживания использования"""
    
    async def get_or_create_usage(
        self, 
        db: AsyncSession, 
        user_id: int
    ) -> UserUsage:
        """Получить или создать запись использования"""
        result = await db.execute(
            select(UserUsage).where(UserUsage.user_id == user_id)
        )
        usage = result.scalar_one_or_none()
        
        if not usage:
            usage = UserUsage(user_id=user_id)
            db.add(usage)
            await db.commit()
            await db.refresh(usage)
            
        return usage
    
    async def increment_photos(
        self, 
        db: AsyncSession, 
        user_id: int
    ) -> UserUsage:
        """Увеличить счетчик использованных фото"""
        usage = await self.get_or_create_usage(db, user_id)
        usage.photos_used += 1
        await db.commit()
        await db.refresh(usage)
        return usage
    
    async def increment_questions(
        self, 
        db: AsyncSession, 
        user_id: int
    ) -> UserUsage:
        """Увеличить счетчик заданных вопросов"""
        usage = await self.get_or_create_usage(db, user_id)
        usage.questions_used += 1
        await db.commit()
        await db.refresh(usage)
        return usage
    
    async def reset_usage(
        self, 
        db: AsyncSession, 
        user_id: int
    ) -> UserUsage:
        """Сбросить счетчики использования"""
        usage = await self.get_or_create_usage(db, user_id)
        usage.photos_used = 0
        usage.questions_used = 0
        usage.last_reset = datetime.utcnow()
        await db.commit()
        await db.refresh(usage)
        return usage
    
    async def can_use_photo(
        self, 
        db: AsyncSession, 
        user_id: int
    ) -> bool:
        """Проверить, может ли пользователь анализировать фото"""
        # Проверяем активную подписку
        subscription_repo = SubscriptionRepository()
        active_sub = await subscription_repo.get_active_subscription(db, user_id)
        if active_sub:
            return True
            
        # Проверяем лимит бесплатного использования
        usage = await self.get_or_create_usage(db, user_id)
        return usage.photos_used < config.FREE_PHOTO_LIMIT
    
    async def can_ask_question(
        self, 
        db: AsyncSession, 
        user_id: int
    ) -> bool:
        """Проверить, может ли пользователь задать вопрос"""
        # Проверяем активную подписку
        subscription_repo = SubscriptionRepository()
        active_sub = await subscription_repo.get_active_subscription(db, user_id)
        if active_sub:
            return True
            
        # Проверяем лимит бесплатного использования
        usage = await self.get_or_create_usage(db, user_id)
        return usage.questions_used < config.FREE_QUESTION_LIMIT


# Создание экземпляров репозиториев
subscription_repository = SubscriptionRepository()
usage_repository = UsageRepository() 