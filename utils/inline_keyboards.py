from aiogram import types


def main_inline_menu() -> types.InlineKeyboardMarkup:
    """Главное меню в виде inline-кнопок."""

    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="📸 Анализ фото", callback_data="menu_photo"),
                types.InlineKeyboardButton(text="🎯 Задать цель", callback_data="menu_set_goal")
            ],
            [
                types.InlineKeyboardButton(text="📊 Калории за день", callback_data="menu_day_calories"),
                types.InlineKeyboardButton(text="📋 Что я ел сегодня", callback_data="menu_today_meals")
            ],
            [
                types.InlineKeyboardButton(text="♻️ Сбросить данные", callback_data="menu_reset_today"),
                types.InlineKeyboardButton(text="💳 Подписка", callback_data="subscribe")
            ],
            [
                types.InlineKeyboardButton(text="💬 Обратная связь", callback_data="menu_feedback")
            ]
        ]
    ) 