import logging
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional
from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotification
from config.config import config

logger = logging.getLogger(__name__)

# Thread pool для синхронных вызовов Yookassa
_executor = ThreadPoolExecutor(max_workers=3)


class PaymentService:
    """Сервис для работы с ЮKassa"""
    
    def __init__(self):
        """Инициализация сервиса"""
        if config.YOOKASSA_SHOP_ID and config.YOOKASSA_SECRET_KEY:
            Configuration.account_id = config.YOOKASSA_SHOP_ID
            Configuration.secret_key = config.YOOKASSA_SECRET_KEY
            logger.info("ЮKassa сконфигурирована успешно")
        else:
            logger.warning("ЮKassa не настроена - отсутствуют YOOKASSA_SHOP_ID или YOOKASSA_SECRET_KEY")
    
    async def create_payment(
        self, 
        amount: float,
        description: str,
        return_url: str,
        metadata: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Создать платеж в ЮKassa"""
        try:
            idempotency_key = str(uuid.uuid4())
            
            payment_data = {
                "amount": {
                    "value": f"{amount:.2f}",
                    "currency": "RUB"
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": return_url
                },
                "capture": True,
                "description": description
            }
            
            if metadata:
                payment_data["metadata"] = metadata
            
            # Выполняем синхронный вызов в отдельном потоке с таймаутом
            loop = asyncio.get_event_loop()
            try:
                payment = await asyncio.wait_for(
                    loop.run_in_executor(
                        _executor,
                        lambda: Payment.create(payment_data, idempotency_key)
                    ),
                    timeout=20.0  # 20 секунд максимум
                )
            except asyncio.TimeoutError:
                logger.error("Таймаут при создании платежа в Yookassa")
                return None
            
            logger.info(f"Создан платеж {payment.id} на сумму {amount} руб.")
            
            return {
                "id": payment.id,
                "status": payment.status,
                "confirmation_url": payment.confirmation.confirmation_url,
                "amount": amount
            }
            
        except Exception as e:
            logger.error(f"Ошибка при создании платежа: {str(e)}")
            return None
    
    async def create_recurrent_payment(
        self,
        amount: float,
        description: str,
        return_url: str,
        parent_payment_id: str,
        metadata: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Создать рекуррентный платеж на основе предыдущего"""
        try:
            # Сначала получаем информацию о родительском платеже
            parent_payment = Payment.find_one(parent_payment_id)
            
            if not parent_payment or not parent_payment.payment_method:
                logger.error(f"Не удалось найти сохраненный метод оплаты для платежа {parent_payment_id}")
                return None
            
            idempotency_key = str(uuid.uuid4())
            
            payment_data = {
                "amount": {
                    "value": f"{amount:.2f}",
                    "currency": "RUB"
                },
                "capture": True,
                "payment_method_id": parent_payment.payment_method.id,
                "description": description,
                "save_payment_method": True  # Сохраняем метод для будущих платежей
            }
            
            if metadata:
                payment_data["metadata"] = metadata
            
            payment = Payment.create(payment_data, idempotency_key)
            
            logger.info(f"Создан рекуррентный платеж {payment.id} на сумму {amount} руб.")
            
            return {
                "id": payment.id,
                "status": payment.status,
                "confirmation_url": payment.confirmation.confirmation_url if payment.confirmation else None,
                "amount": amount
            }
            
        except Exception as e:
            logger.error(f"Ошибка при создании рекуррентного платежа: {str(e)}")
            # Если не удалось создать рекуррентный платеж, пробуем создать обычный
            return await self.create_payment(amount, description, return_url, metadata)
    
    async def check_payment_status(self, payment_id: str) -> Optional[str]:
        """Проверить статус платежа и логировать детали отмены, если есть"""
        try:
            payment = Payment.find_one(payment_id)

            # Если платеж отменён — логируем детали
            if payment.status == "canceled" and getattr(payment, "cancellation_details", None):
                details = payment.cancellation_details
                # В ЮKassa это объект, у него есть поля reason и party
                reason = getattr(details, "reason", None)
                party = getattr(details, "party", None)
                logger.warning(
                    "Платёж %s отменён. Код: %s, Сторона: %s",
                    payment_id,
                    reason,
                    party,
                )

            return payment.status
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса платежа {payment_id}: {str(e)}")
            return None
    
    def process_webhook(self, request_body: bytes) -> Optional[Dict]:
        """Обработать вебхук от ЮKassa"""
        try:
            notification = WebhookNotification(request_body)
            payment = notification.object
            
            return {
                "payment_id": payment.id,
                "status": payment.status,
                "metadata": payment.metadata
            }
        except Exception as e:
            logger.error(f"Ошибка при обработке вебхука: {str(e)}")
            return None


# Создание экземпляра сервиса
payment_service = PaymentService() 