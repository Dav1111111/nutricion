import logging
import os
import uuid
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional
from config.config import config

logger = logging.getLogger(__name__)

# Thread pool для синхронных вызовов Yookassa (если без микросервиса)
_executor = ThreadPoolExecutor(max_workers=3)

# URL платёжного микросервиса
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "")


class PaymentService:
    """Сервис для работы с платежами (через микросервис или напрямую)"""
    
    def __init__(self):
        """Инициализация сервиса"""
        self.use_microservice = bool(PAYMENT_SERVICE_URL)
        
        if self.use_microservice:
            logger.info(f"Используем платёжный микросервис: {PAYMENT_SERVICE_URL}")
        else:
            # Прямое подключение к Yookassa
            try:
                from yookassa import Configuration
                if config.YOOKASSA_SHOP_ID and config.YOOKASSA_SECRET_KEY:
                    Configuration.account_id = config.YOOKASSA_SHOP_ID
                    Configuration.secret_key = config.YOOKASSA_SECRET_KEY
                    logger.info("ЮKassa сконфигурирована напрямую")
                else:
                    logger.warning("ЮKassa не настроена - отсутствуют YOOKASSA_SHOP_ID или YOOKASSA_SECRET_KEY")
            except ImportError:
                logger.warning("yookassa не установлена, используйте микросервис")
    
    async def create_payment(
        self, 
        amount: float,
        description: str,
        return_url: str,
        metadata: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Создать платеж (через микросервис или напрямую)"""
        
        # Через микросервис
        if self.use_microservice:
            return await self._create_payment_via_api(amount, description, return_url, metadata)
        
        # Напрямую через Yookassa
        return await self._create_payment_direct(amount, description, return_url, metadata)
    
    async def _create_payment_via_api(
        self,
        amount: float,
        description: str,
        return_url: str,
        metadata: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Создать платеж через микросервис"""
        try:
            user_id = metadata.get("user_id", 0) if metadata else 0
            telegram_id = metadata.get("telegram_id", 0) if metadata else 0
            
            async with aiohttp.ClientSession() as session:
                payload = {
                    "amount": int(amount),
                    "description": description,
                    "return_url": return_url,
                    "user_id": user_id,
                    "telegram_id": telegram_id
                }
                
                async with session.post(
                    f"{PAYMENT_SERVICE_URL}/create-payment",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"Платёж создан через API: {data.get('id')}")
                        return {
                            "id": data.get("id"),
                            "status": data.get("status"),
                            "confirmation_url": data.get("confirmation_url"),
                            "amount": amount
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка создания платежа через API: {response.status} - {error_text}")
                        return None
                        
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения с платёжным сервисом: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при создании платежа через API: {str(e)}")
            return None
    
    async def _create_payment_direct(
        self,
        amount: float,
        description: str,
        return_url: str,
        metadata: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Создать платеж напрямую через Yookassa"""
        try:
            from yookassa import Payment
            
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
        """Проверить статус платежа"""
        
        # Через микросервис
        if self.use_microservice:
            return await self._check_payment_via_api(payment_id)
        
        # Напрямую
        return await self._check_payment_direct(payment_id)
    
    async def _check_payment_via_api(self, payment_id: str) -> Optional[str]:
        """Проверить статус через микросервис"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{PAYMENT_SERVICE_URL}/check-payment/{payment_id}",
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        status = data.get("status")
                        logger.info(f"Статус платежа {payment_id}: {status}")
                        return status
                    else:
                        logger.error(f"Ошибка проверки платежа через API: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Ошибка при проверке платежа через API: {str(e)}")
            return None
    
    async def _check_payment_direct(self, payment_id: str) -> Optional[str]:
        """Проверить статус напрямую через Yookassa"""
        try:
            from yookassa import Payment
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