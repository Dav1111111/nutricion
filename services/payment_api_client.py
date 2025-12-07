"""
Клиент для обращения к платёжному микросервису
Используется вместо прямых вызовов Yookassa
"""

import os
import logging
import aiohttp
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# URL платёжного сервиса (из переменной окружения)
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8000")


class PaymentAPIClient:
    """Клиент для работы с платёжным микросервисом"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or PAYMENT_SERVICE_URL
        logger.info(f"PaymentAPIClient инициализирован: {self.base_url}")
    
    async def create_payment(
        self,
        amount: int,
        description: str,
        return_url: str,
        user_id: int,
        telegram_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Создание платежа через микросервис
        
        Returns:
            Dict с id, confirmation_url, amount или None при ошибке
        """
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "amount": amount,
                    "description": description,
                    "return_url": return_url,
                    "user_id": user_id,
                    "telegram_id": telegram_id
                }
                
                async with session.post(
                    f"{self.base_url}/create-payment",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"Платёж создан через API: {data.get('id')}")
                        return data
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка создания платежа: {response.status} - {error_text}")
                        return None
                        
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения с платёжным сервисом: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка: {str(e)}")
            return None
    
    async def check_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        """
        Проверка статуса платежа
        
        Returns:
            Dict с id, status, paid или None при ошибке
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/check-payment/{payment_id}",
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"Статус платежа {payment_id}: {data.get('status')}")
                        return data
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка проверки платежа: {response.status} - {error_text}")
                        return None
                        
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения с платёжным сервисом: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка: {str(e)}")
            return None
    
    async def health_check(self) -> bool:
        """Проверка доступности платёжного сервиса"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    return response.status == 200
        except Exception:
            return False


# Глобальный экземпляр клиента
payment_api_client = PaymentAPIClient()
