import logging
from aiogram import types, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from database.repository import user_repository, nutritional_goal_repository
from services.graspil_service import graspil_service

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RegistrationStates(StatesGroup):
    awaiting_goal = State()
    awaiting_gender = State()
    awaiting_age = State()
    awaiting_height = State()
    awaiting_weight = State()
    awaiting_activity = State()

class RegistrationHandlers:
    """Обработчики процесса регистрации (анкетирования)"""

    @staticmethod
    async def start_registration(message: types.Message, state: FSMContext):
        """Начало регистрации - запрос цели"""
        # Сообщение с приветствием уже отправлено в start_command
        # Здесь мы просто отправляем клавиатуру выбора цели
        
        await message.answer(
            "Выберите цель:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📉 Похудеть", callback_data="reg_goal_lose")],
                    [InlineKeyboardButton(text="⚖️ Поддерживать вес", callback_data="reg_goal_maintain")],
                    [InlineKeyboardButton(text="💪 Набрать массу", callback_data="reg_goal_gain")]
                ]
            )
        )
        await state.set_state(RegistrationStates.awaiting_goal)

    @staticmethod
    async def process_goal(callback: types.CallbackQuery, state: FSMContext):
        goal_map = {
            "reg_goal_lose": "снижение веса",
            "reg_goal_maintain": "поддержание веса",
            "reg_goal_gain": "набор массы"
        }
        goal = goal_map.get(callback.data)
        if not goal:
            await callback.answer("Пожалуйста, выберите вариант из меню")
            return

        await state.update_data(goal=goal)
        
        await callback.message.edit_text(f"Цель: {goal}")
        await callback.message.answer(
            "Укажите ваш пол:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="👨 Мужской", callback_data="reg_gender_male")],
                    [InlineKeyboardButton(text="👩 Женский", callback_data="reg_gender_female")]
                ]
            )
        )
        await state.set_state(RegistrationStates.awaiting_gender)
        await callback.answer()

    @staticmethod
    async def process_gender(callback: types.CallbackQuery, state: FSMContext):
        gender_map = {
            "reg_gender_male": "male",
            "reg_gender_female": "female"
        }
        gender = gender_map.get(callback.data)
        if not gender:
            await callback.answer("Пожалуйста, выберите вариант из меню")
            return

        await state.update_data(gender=gender)
        
        gender_text = "Мужской" if gender == "male" else "Женский"
        await callback.message.edit_text(f"Пол: {gender_text}")
        
        await callback.message.answer("Сколько вам лет? (введите число)")
        await state.set_state(RegistrationStates.awaiting_age)
        await callback.answer()

    @staticmethod
    async def process_age(message: types.Message, state: FSMContext):
        if not message.text.isdigit():
            await message.answer("Пожалуйста, введите возраст числом.")
            return
        
        age = int(message.text)
        if age < 10 or age > 100:
            await message.answer("Пожалуйста, укажите реальный возраст (10-100 лет).")
            return
            
        await state.update_data(age=age)
        await message.answer("Какой у вас рост (в см)?")
        await state.set_state(RegistrationStates.awaiting_height)

    @staticmethod
    async def process_height(message: types.Message, state: FSMContext):
        if not message.text.isdigit():
            await message.answer("Пожалуйста, введите рост числом (в см).")
            return
            
        height = float(message.text)
        if height < 50 or height > 250:
            await message.answer("Пожалуйста, укажите реальный рост (50-250 см).")
            return

        await state.update_data(height=height)
        await message.answer("Какой у вас вес (в кг)?")
        await state.set_state(RegistrationStates.awaiting_weight)

    @staticmethod
    async def process_weight(message: types.Message, state: FSMContext):
        try:
            weight = float(message.text.replace(',', '.'))
        except ValueError:
            await message.answer("Пожалуйста, введите вес числом.")
            return
            
        if weight < 20 or weight > 300:
            await message.answer("Пожалуйста, укажите реальный вес (20-300 кг).")
            return

        await state.update_data(weight=weight)
        
        await message.answer(
            "Какой у вас уровень активности?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💤 Сидячий", callback_data="reg_activity_sedentary")],
                    [InlineKeyboardButton(text="🚶 Небольшая", callback_data="reg_activity_light")],
                    [InlineKeyboardButton(text="🏃 Средняя", callback_data="reg_activity_moderate")],
                    [InlineKeyboardButton(text="🏋️ Высокая", callback_data="reg_activity_active")],
                    [InlineKeyboardButton(text="🔥 Экстремальная", callback_data="reg_activity_extra")]
                ]
            )
        )
        await state.set_state(RegistrationStates.awaiting_activity)

    @staticmethod
    async def process_activity(callback: types.CallbackQuery, state: FSMContext, db: AsyncSession):
        activity_map = {
            "reg_activity_sedentary": "sedentary",
            "reg_activity_light": "light",
            "reg_activity_moderate": "moderate",
            "reg_activity_active": "active",
            "reg_activity_extra": "extra"
        }
        activity_level = activity_map.get(callback.data)
        if not activity_level:
            await callback.answer("Пожалуйста, выберите вариант из меню")
            return

        await state.update_data(activity_level=activity_level)
        
        # Get all data
        data = await state.get_data()
        
        # Calculate calories
        maintain_calories = RegistrationHandlers.calculate_calories(
            data['gender'], data['weight'], data['height'], data['age'], activity_level
        )
        
        target_calories = RegistrationHandlers.calculate_target(
            maintain_calories, data['goal']
        )
        
        # Calculate macros (simple distribution)
        # Protein: 30%, Fat: 30%, Carbs: 40% (example)
        target_proteins = (target_calories * 0.3) / 4
        target_fats = (target_calories * 0.3) / 9
        target_carbs = (target_calories * 0.4) / 4
        
        # Save to User model
        user = await user_repository.get_by_telegram_id(db, callback.from_user.id)
        if user:
            user.age = data['age']
            user.gender = data['gender']
            user.weight = data['weight']
            user.height = data['height']
            user.activity_level = activity_level
            user.goal = data['goal']
            user.maintain_calories = maintain_calories
        
        # Create NutritionalGoal (deactivate old ones)
        current_goal = await nutritional_goal_repository.get_active_goal(db, user.id)
        if current_goal:
            await nutritional_goal_repository.update(db, current_goal.id, is_active=False)

        await nutritional_goal_repository.create(
            db,
            user_id=user.id,
            goal_type=data['goal'],
            target_calories=target_calories,
            target_proteins=target_proteins,
            target_fats=target_fats,
            target_carbs=target_carbs,
            is_active=True
        )
        
        await db.commit()
        
        # Отправляем событие в Graspil: прошёл анкету
        await graspil_service.send_registration_event(callback.from_user.id)
        
        # Final message
        activity_names = {
            "sedentary": "Сидячий",
            "light": "Небольшая активность",
            "moderate": "Средняя активность",
            "active": "Высокая активность",
            "extra": "Экстремальная активность"
        }
        
        await callback.message.edit_text(f"Уровень активности: {activity_names.get(activity_level, activity_level)}")
        await callback.message.answer(
            f"✅ Анкета заполнена!\n\n"
            f"📊 Ваши показатели:\n"
            f"• BMR (Базовый обмен): {int(maintain_calories / RegistrationHandlers.get_activity_multiplier(activity_level))} ккал\n"
            f"• Норма поддержки: {int(maintain_calories)} ккал\n\n"
            f"🎯 Ваша цель: {data['goal']}\n"
            f"🔥 Рекомендуемая норма: **{int(target_calories)} ккал**\n"
            f"• Белки: {int(target_proteins)} г\n"
            f"• Жиры: {int(target_fats)} г\n"
            f"• Углеводы: {int(target_carbs)} г\n\n"
            f"Теперь вы можете отправлять фото еды, и я буду учитывать эти нормы!"
        )
        await state.clear()
        await callback.answer()

    @staticmethod
    def get_activity_multiplier(level):
        multipliers = {
            "sedentary": 1.2,
            "light": 1.375,
            "moderate": 1.55,
            "active": 1.725,
            "extra": 1.9
        }
        return multipliers.get(level, 1.2)

    @staticmethod
    def calculate_calories(gender, weight, height, age, activity_level):
        # Mifflin-St Jeor Equation
        bmr = (10 * weight) + (6.25 * height) - (5 * age)
        if gender == "male":
            bmr += 5
        else:
            bmr -= 161
            
        multiplier = RegistrationHandlers.get_activity_multiplier(activity_level)
        return bmr * multiplier

    @staticmethod
    def calculate_target(maintain_calories, goal):
        if goal == "снижение веса":
            return maintain_calories * 0.85  # -15%
        elif goal == "набор массы":
            return maintain_calories * 1.15  # +15%
        else:
            return maintain_calories

def register_registration_handlers(dp: Router):
    dp.callback_query.register(RegistrationHandlers.process_goal, RegistrationStates.awaiting_goal)
    dp.callback_query.register(RegistrationHandlers.process_gender, RegistrationStates.awaiting_gender)
    dp.message.register(RegistrationHandlers.process_age, RegistrationStates.awaiting_age)
    dp.message.register(RegistrationHandlers.process_height, RegistrationStates.awaiting_height)
    dp.message.register(RegistrationHandlers.process_weight, RegistrationStates.awaiting_weight)
    dp.callback_query.register(RegistrationHandlers.process_activity, RegistrationStates.awaiting_activity)
