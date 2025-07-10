from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    registration_date = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    is_premium = Column(Boolean, default=False)
    language_code = Column(String, default='ru')

    # Отношения
    messages = relationship("Message", back_populates="user")
    meal_logs = relationship("MealLog", back_populates="user")
    nutritional_goals = relationship("NutritionalGoal", back_populates="user")
    preferences = relationship("UserPreference", back_populates="user", uselist=False)
    subscriptions = relationship("UserSubscription", back_populates="user")
    usage = relationship("UserUsage", back_populates="user", uselist=False)

class Message(Base):
    __tablename__ = 'messages'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    role = Column(String, nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    message_type = Column(String, default='text')  # text, image, voice
    image_path = Column(String, nullable=True)  # путь к изображению, если есть
    timestamp = Column(DateTime, default=datetime.utcnow)
    tokens_used = Column(Integer, nullable=True)  # количество использованных токенов

    # Отношения
    user = relationship("User", back_populates="messages")
    feedback = relationship("Feedback", back_populates="message")

class MealLog(Base):
    __tablename__ = 'meal_logs'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    meal_type = Column(String)  # завтрак, обед, ужин, перекус
    meal_name = Column(String)
    description = Column(Text, nullable=True)
    image_path = Column(String, nullable=True)
    date = Column(DateTime, default=datetime.utcnow)

    # Питательные вещества
    calories = Column(Float, nullable=True)
    proteins = Column(Float, nullable=True)
    fats = Column(Float, nullable=True)
    carbs = Column(Float, nullable=True)
    fiber = Column(Float, nullable=True)
    sugar = Column(Float, nullable=True)

    # Отношения
    user = relationship("User", back_populates="meal_logs")
    ingredients = relationship("Ingredient", back_populates="meal_log")

class Ingredient(Base):
    __tablename__ = 'ingredients'

    id = Column(Integer, primary_key=True)
    meal_log_id = Column(Integer, ForeignKey('meal_logs.id'))
    name = Column(String, nullable=False)
    weight = Column(Float, nullable=True)
    calories = Column(Float, nullable=True)
    proteins = Column(Float, nullable=True)
    fats = Column(Float, nullable=True)
    carbs = Column(Float, nullable=True)

    # Отношения
    meal_log = relationship("MealLog", back_populates="ingredients")

class NutritionalGoal(Base):
    __tablename__ = 'nutritional_goals'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    goal_type = Column(String)  # снижение веса, набор массы, поддержание
    target_calories = Column(Float, nullable=True)
    target_proteins = Column(Float, nullable=True)
    target_fats = Column(Float, nullable=True)
    target_carbs = Column(Float, nullable=True)
    start_date = Column(DateTime, default=datetime.utcnow)
    end_date = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

    # Отношения
    user = relationship("User", back_populates="nutritional_goals")

class UserPreference(Base):
    """Модель для хранения предпочтений пользователя"""
    __tablename__ = 'user_preferences'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    diet_type = Column(String(100))  # Тип диеты (вегетарианская, веганская и т.д.)
    allergies = Column(Text)  # Аллергии
    disliked_foods = Column(Text)  # Нелюбимые продукты
    preferred_cuisine = Column(String(100))  # Предпочитаемая кухня
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связи
    user = relationship("User", back_populates="preferences")

class Feedback(Base):
    __tablename__ = 'feedback'

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey('messages.id'))
    rating = Column(Integer)  # 1-5
    comment = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Отношения
    message = relationship("Message", back_populates="feedback")

class FoodDatabase(Base):
    __tablename__ = 'food_database'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=True)
    calories_per_100g = Column(Float, nullable=True)
    proteins_per_100g = Column(Float, nullable=True)
    fats_per_100g = Column(Float, nullable=True)
    carbs_per_100g = Column(Float, nullable=True)
    fiber_per_100g = Column(Float, nullable=True)
    sugar_per_100g = Column(Float, nullable=True)

class UserSubscription(Base):
    """Модель для хранения подписок пользователей"""
    __tablename__ = 'user_subscriptions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    payment_id = Column(String(255), unique=True)  # ID платежа в ЮKassa
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default='RUB')
    status = Column(String(50), default='pending')  # pending, succeeded, canceled, expired
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Поля для автопродления
    is_auto_renewal = Column(Boolean, default=True)  # Включено ли автопродление
    parent_payment_id = Column(String(255), nullable=True)  # ID родительского платежа для рекуррентных
    next_payment_date = Column(DateTime, nullable=True)  # Дата следующего платежа
    renewal_attempts = Column(Integer, default=0)  # Количество попыток продления
    last_renewal_attempt = Column(DateTime, nullable=True)  # Последняя попытка продления
    
    # Связи
    user = relationship("User", back_populates="subscriptions")

class UserUsage(Base):
    """Модель для отслеживания использования бота"""
    __tablename__ = 'user_usage'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, unique=True)
    photos_used = Column(Integer, default=0)
    questions_used = Column(Integer, default=0)
    last_reset = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    user = relationship("User", back_populates="usage", uselist=False)
