"""
Webhook сервер для обработки уведомлений от Робокассы.
Запускается отдельно от бота на порту 8080.
"""
import asyncio
import logging
from aiohttp import web
from datetime import datetime, timedelta
from sqlalchemy import select

from config.config import config
from database.connection import db_connection
from database.repository import user_repository
from database.subscription_repository import subscription_repository
from services.payment_service import payment_service
from models.database import UserSubscription

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def handle_robokassa_result(request: web.Request) -> web.Response:
    """
    Обработчик Result URL от Робокассы.
    Робокасса отправляет POST с параметрами:
    - OutSum: сумма
    - InvId: номер заказа
    - SignatureValue: подпись
    - Shp_user_id: ID пользователя
    - Shp_telegram_id: Telegram ID
    """
    try:
        # Получаем параметры
        if request.method == "POST":
            data = await request.post()
        else:
            data = request.query
        
        out_sum = data.get("OutSum", "")
        inv_id = data.get("InvId", "")
        signature = data.get("SignatureValue", "")
        
        # Дополнительные параметры
        shp_params = {}
        for key in data.keys():
            if key.startswith("Shp_"):
                shp_params[key] = data[key]
        
        user_id = int(shp_params.get("Shp_user_id", 0))
        telegram_id = int(shp_params.get("Shp_telegram_id", 0))
        
        logger.info(f"Получен Result от Робокассы: InvId={inv_id}, OutSum={out_sum}, user_id={user_id}")
        
        # Проверяем подпись
        is_valid = payment_service.verify_result_signature(
            out_sum=out_sum,
            inv_id=inv_id,
            signature=signature,
            shp_params=shp_params
        )
        
        if not is_valid:
            logger.error(f"Неверная подпись для InvId={inv_id}")
            return web.Response(text="bad sign", status=400)
        
        # Активируем подписку
        async with db_connection.async_session() as db:
            # Находим пользователя
            user = await user_repository.get_by_id(db, user_id)
            if not user:
                user = await user_repository.get_by_telegram_id(db, telegram_id)
            
            if not user:
                logger.error(f"Пользователь не найден: user_id={user_id}, telegram_id={telegram_id}")
                return web.Response(text="user not found", status=400)

            # Делаем обработку идемпотентной:
            # 1) если запись уже есть (бот создал pending) — просто активируем
            # 2) если записи нет — создаём pending и активируем
            subscription = await subscription_repository.activate_subscription(db, payment_id=inv_id)
            if not subscription:
                # Проверяем, есть ли запись с таким payment_id (на всякий случай)
                existing = await db.execute(
                    select(UserSubscription).where(UserSubscription.payment_id == inv_id)
                )
                existing_sub = existing.scalar_one_or_none()

                if not existing_sub:
                    await subscription_repository.create_subscription(
                        db,
                        user_id=user.id,
                        payment_id=inv_id,
                        amount=float(out_sum),
                    )

                subscription = await subscription_repository.activate_subscription(db, payment_id=inv_id)
            if not subscription:
                logger.error(f"Не удалось активировать подписку для InvId={inv_id}, user_id={user.id}")
                return web.Response(text="subscription not activated", status=500)

            logger.info(
                "Подписка активирована для user_id=%s, до %s",
                user.id,
                subscription.end_date,
            )
        
        # Робокасса ожидает ответ "OK" + InvId
        return web.Response(text=f"OK{inv_id}")
        
    except Exception as e:
        logger.error(f"Ошибка обработки Result URL: {str(e)}")
        return web.Response(text="error", status=500)


async def handle_robokassa_success(request: web.Request) -> web.Response:
    """Обработчик Success URL - редирект после успешной оплаты"""
    return web.Response(
        text="<html><body><h1>Оплата прошла успешно!</h1><p>Вернитесь в Telegram бот.</p></body></html>",
        content_type="text/html"
    )


async def handle_robokassa_fail(request: web.Request) -> web.Response:
    """Обработчик Fail URL - редирект после неудачной оплаты"""
    return web.Response(
        text="<html><body><h1>Оплата отменена</h1><p>Вернитесь в Telegram бот и попробуйте снова.</p></body></html>",
        content_type="text/html"
    )


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint"""
    return web.json_response({"status": "ok", "service": "robokassa-webhook"})


def create_app() -> web.Application:
    """Создание веб-приложения"""
    app = web.Application()
    
    app.router.add_post("/result", handle_robokassa_result)
    app.router.add_get("/result", handle_robokassa_result)  # Робокасса может слать GET
    app.router.add_get("/success", handle_robokassa_success)
    app.router.add_get("/fail", handle_robokassa_fail)
    app.router.add_get("/health", handle_health)
    
    return app


if __name__ == "__main__":
    app = create_app()
    port = 8080
    logger.info(f"Запуск webhook сервера на порту {port}")
    web.run_app(app, host="0.0.0.0", port=port)
