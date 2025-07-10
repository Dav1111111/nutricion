import logging
from typing import List, Optional, Any, Dict, Type, TypeVar, Generic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete
from sqlalchemy.sql import func

from models.database import User, Message, MealLog, Ingredient, NutritionalGoal, UserPreference, Feedback, FoodDatabase

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Тип для дженерика
T = TypeVar('T')

class BaseRepository(Generic[T]):
    """Базовый репозиторий для работы с сущностями"""

    def __init__(self, model: Type[T]):
        self.model = model

    async def create(self, db: AsyncSession, **kwargs) -> T:
        """Создать новую запись"""
        db_item = self.model(**kwargs)
        db.add(db_item)
        await db.commit()
        await db.refresh(db_item)
        return db_item

    async def get_by_id(self, db: AsyncSession, id: int) -> Optional[T]:
        """Получить запись по ID"""
        result = await db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def get_all(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> List[T]:
        """Получить все записи с пагинацией"""
        result = await db.execute(select(self.model).offset(skip).limit(limit))
        return result.scalars().all()

    async def update(self, db: AsyncSession, id: int, **kwargs) -> Optional[T]:
        """Обновить запись по ID"""
        await db.execute(
            update(self.model)
            .where(self.model.id == id)
            .values(**kwargs)
        )
        await db.commit()
        return await self.get_by_id(db, id)

    async def delete(self, db: AsyncSession, id: int) -> bool:
        """Удалить запись по ID"""
        result = await db.execute(
            delete(self.model)
            .where(self.model.id == id)
        )
        await db.commit()
        return result.rowcount > 0

    async def count(self, db: AsyncSession) -> int:
        """Подсчитать количество записей"""
        result = await db.execute(select(func.count()).select_from(self.model))
        return result.scalar_one()


class UserRepository(BaseRepository[User]):
    """Репозиторий для работы с пользователями"""

    def __init__(self):
        super().__init__(User)

    async def get_by_telegram_id(self, db: AsyncSession, telegram_id: int) -> Optional[User]:
        """Получить пользователя по Telegram ID"""
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_or_create_user(self, db: AsyncSession, telegram_id: int, **user_data) -> User:
        """Получить или создать пользователя"""
        user = await self.get_by_telegram_id(db, telegram_id)

        if user is None:
            try:
                user = await self.create(db, telegram_id=telegram_id, **user_data)
            except Exception as e:
                # Возможно, другой процесс уже создал пользователя – пытаемся получить снова
                await db.rollback()
                user = await self.get_by_telegram_id(db, telegram_id)

        return user


class MessageRepository(BaseRepository[Message]):
    """Репозиторий для работы с сообщениями"""

    def __init__(self):
        super().__init__(Message)

    async def get_user_messages(self, db: AsyncSession, user_id: int, limit: int = 10) -> List[Message]:
        """Получить последние сообщения пользователя"""
        result = await db.execute(
            select(Message)
            .where(Message.user_id == user_id)
            .order_by(Message.timestamp.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_conversation_history(self, db: AsyncSession, user_id: int, limit: int = 10) -> List[Dict[str, str]]:
        """Получить историю разговора в формате для API OpenAI"""
        messages = await self.get_user_messages(db, user_id, limit)
        return [{"role": msg.role, "content": msg.content} for msg in reversed(messages)]

    async def clear_user_history(self, db: AsyncSession, user_id: int) -> int:
        """Очистить историю сообщений пользователя"""
        result = await db.execute(
            delete(Message)
            .where(Message.user_id == user_id)
        )
        await db.commit()
        return result.rowcount


class MealLogRepository(BaseRepository[MealLog]):
    """Репозиторий для работы с приемами пищи"""

    def __init__(self):
        super().__init__(MealLog)

    async def get_user_meals(self, db: AsyncSession, user_id: int, limit: int = 10) -> List[MealLog]:
        """Получить последние приемы пищи пользователя"""
        result = await db.execute(
            select(MealLog)
            .where(MealLog.user_id == user_id)
            .order_by(MealLog.date.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_meals_by_date(self, db: AsyncSession, user_id: int, date_from, date_to) -> List[MealLog]:
        """Получить приемы пищи за определенный период"""
        result = await db.execute(
            select(MealLog)
            .where(MealLog.user_id == user_id)
            .where(MealLog.date >= date_from)
            .where(MealLog.date <= date_to)
            .order_by(MealLog.date.desc())
        )
        return result.scalars().all()


class IngredientRepository(BaseRepository[Ingredient]):
    """Репозиторий для работы с ингредиентами"""

    def __init__(self):
        super().__init__(Ingredient)

    async def get_by_meal_id(self, db: AsyncSession, meal_log_id: int) -> List[Ingredient]:
        """Получить ингредиенты определенного приема пищи"""
        result = await db.execute(
            select(Ingredient)
            .where(Ingredient.meal_log_id == meal_log_id)
        )
        return result.scalars().all()

    async def delete_by_meal_log(self, db: AsyncSession, meal_log_id: int) -> int:
        """Удалить все ингредиенты, связанные с приёмом пищи"""
        result = await db.execute(
            delete(Ingredient)
            .where(Ingredient.meal_log_id == meal_log_id)
        )
        await db.commit()
        return result.rowcount


class NutritionalGoalRepository(BaseRepository[NutritionalGoal]):
    """Репозиторий для работы с целями по питанию"""

    def __init__(self):
        super().__init__(NutritionalGoal)

    async def get_active_goal(self, db: AsyncSession, user_id: int) -> Optional[NutritionalGoal]:
        """Получить активную цель пользователя"""
        result = await db.execute(
            select(NutritionalGoal)
            .where(NutritionalGoal.user_id == user_id)
            .where(NutritionalGoal.is_active == True)
            .order_by(NutritionalGoal.start_date.desc())
        )
        return result.scalar_one_or_none()


class UserPreferenceRepository(BaseRepository[UserPreference]):
    """Репозиторий для работы с предпочтениями пользователя"""

    def __init__(self):
        super().__init__(UserPreference)

    async def get_by_user_id(self, db: AsyncSession, user_id: int) -> Optional[UserPreference]:
        """Получить предпочтения пользователя"""
        result = await db.execute(
            select(UserPreference)
            .where(UserPreference.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, db: AsyncSession, user_id: int) -> UserPreference:
        """Получить или создать предпочтения пользователя"""
        preference = await self.get_by_user_id(db, user_id)

        if preference is None:
            preference = await self.create(db, user_id=user_id)

        return preference


class FeedbackRepository(BaseRepository[Feedback]):
    """Репозиторий для работы с обратной связью"""

    def __init__(self):
        super().__init__(Feedback)

    async def get_by_message_id(self, db: AsyncSession, message_id: int) -> Optional[Feedback]:
        """Получить обратную связь по ID сообщения"""
        result = await db.execute(
            select(Feedback)
            .where(Feedback.message_id == message_id)
        )
        return result.scalar_one_or_none()


class FoodDatabaseRepository(BaseRepository[FoodDatabase]):
    """Репозиторий для работы с базой данных продуктов"""

    def __init__(self):
        super().__init__(FoodDatabase)

    async def search_by_name(self, db: AsyncSession, name: str, limit: int = 10) -> List[FoodDatabase]:
        """Поиск продуктов по названию"""
        result = await db.execute(
            select(FoodDatabase)
            .where(FoodDatabase.name.ilike(f"%{name}%"))
            .limit(limit)
        )
        return result.scalars().all()

    async def get_by_category(self, db: AsyncSession, category: str) -> List[FoodDatabase]:
        """Получить продукты по категории"""
        result = await db.execute(
            select(FoodDatabase)
            .where(FoodDatabase.category == category)
        )
        return result.scalars().all()


# Экспорт репозиториев для использования в других модулях
user_repository = UserRepository()
message_repository = MessageRepository()
meal_log_repository = MealLogRepository()
ingredient_repository = IngredientRepository()
nutritional_goal_repository = NutritionalGoalRepository()
user_preference_repository = UserPreferenceRepository()
feedback_repository = FeedbackRepository()
food_database_repository = FoodDatabaseRepository()
