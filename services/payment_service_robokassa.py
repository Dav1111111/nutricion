import logging
import hashlib
from typing import Dict, Optional
from urllib.parse import urlencode
from config.config import config

logger = logging.getLogger(__name__)


class RobokassaPaymentService:
    """Сервис для работы с платежами через Робокассу"""
    
    # URL для оплаты
    PAYMENT_URL = "https://auth.robokassa.ru/Merchant/Index.aspx"
    
    def __init__(self):
        """Инициализация сервиса"""
        self.merchant_login = config.ROBOKASSA_MERCHANT_LOGIN
        self.password1 = config.ROBOKASSA_PASSWORD1
        self.password2 = config.ROBOKASSA_PASSWORD2
        self.test_mode = config.ROBOKASSA_TEST_MODE
        
        if self.merchant_login and self.password1:
            logger.info(f"Робокасса сконфигурирована для магазина: {self.merchant_login}")
            if self.test_mode:
                logger.info("Робокасса работает в ТЕСТОВОМ режиме")
        else:
            logger.warning("Робокасса не настроена - отсутствуют ROBOKASSA_MERCHANT_LOGIN или ROBOKASSA_PASSWORD1")
    
    def _generate_signature(self, *args) -> str:
        """Генерация MD5 подписи"""
        signature_string = ":".join(str(arg) for arg in args)
        return hashlib.md5(signature_string.encode()).hexdigest()
    
    async def create_payment(
        self, 
        amount: float,
        description: str,
        return_url: str,
        metadata: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Создать платеж и получить URL для оплаты"""
        try:
            if not self.merchant_login or not self.password1:
                logger.error("Робокасса не настроена")
                return None
            
            # Используем user_id как InvId (номер заказа)
            user_id = metadata.get("user_id", 0) if metadata else 0
            telegram_id = metadata.get("telegram_id", 0) if metadata else 0
            
            # Генерируем уникальный номер заказа
            import time
            inv_id = int(time.time() * 1000) % 2147483647  # Ограничение Робокассы
            
            # Сумма в рублях (целое число или с копейками)
            out_sum = f"{amount:.2f}"
            
            # Формируем подпись: MerchantLogin:OutSum:InvId:Password1
            signature = self._generate_signature(
                self.merchant_login,
                out_sum,
                inv_id,
                self.password1
            )
            
            # Дополнительные параметры (Shp_) - передаём user_id и telegram_id
            shp_params = {
                "Shp_telegram_id": telegram_id,
                "Shp_user_id": user_id
            }
            
            # Подпись с доп. параметрами (в алфавитном порядке)
            # MerchantLogin:OutSum:InvId:Password1:Shp_telegram_id=X:Shp_user_id=Y
            shp_string = ":".join(f"{k}={v}" for k, v in sorted(shp_params.items()))
            signature = self._generate_signature(
                self.merchant_login,
                out_sum,
                inv_id,
                self.password1,
                *[f"{k}={v}" for k, v in sorted(shp_params.items())]
            )
            
            # Формируем параметры URL
            params = {
                "MerchantLogin": self.merchant_login,
                "OutSum": out_sum,
                "InvId": inv_id,
                "Description": description[:100],  # Ограничение 100 символов
                "SignatureValue": signature,
                **shp_params
            }
            
            # Добавляем тестовый режим если включён
            if self.test_mode:
                params["IsTest"] = 1
            
            # Формируем URL для оплаты
            payment_url = f"{self.PAYMENT_URL}?{urlencode(params)}"
            
            logger.info(f"Создана ссылка на оплату Робокасса: InvId={inv_id}, сумма={amount} руб.")
            
            return {
                "id": str(inv_id),
                "status": "pending",
                "confirmation_url": payment_url,
                "amount": amount
            }
            
        except Exception as e:
            logger.error(f"Ошибка при создании платежа Робокасса: {str(e)}")
            return None
    
    def verify_result_signature(
        self,
        out_sum: str,
        inv_id: str,
        signature: str,
        shp_params: Dict[str, str] = None
    ) -> bool:
        """Проверить подпись от Робокассы (Result URL)"""
        try:
            # Формируем подпись: OutSum:InvId:Password2:Shp_...
            if shp_params:
                shp_string_parts = [f"{k}={v}" for k, v in sorted(shp_params.items())]
                expected_signature = self._generate_signature(
                    out_sum,
                    inv_id,
                    self.password2,
                    *shp_string_parts
                )
            else:
                expected_signature = self._generate_signature(
                    out_sum,
                    inv_id,
                    self.password2
                )
            
            is_valid = signature.lower() == expected_signature.lower()
            
            if is_valid:
                logger.info(f"Подпись Робокассы верна для InvId={inv_id}")
            else:
                logger.warning(f"Неверная подпись Робокассы для InvId={inv_id}")
                logger.debug(f"Ожидалось: {expected_signature}, получено: {signature}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Ошибка при проверке подписи: {str(e)}")
            return False
    
    async def check_payment_status(self, payment_id: str) -> Optional[str]:
        """
        Проверить статус платежа.
        Примечание: Робокасса не предоставляет API для проверки статуса.
        Статус определяется только через Result URL callback.
        """
        logger.warning("Робокасса не поддерживает проверку статуса платежа через API")
        return None


# Создание экземпляра сервиса
payment_service = RobokassaPaymentService()
