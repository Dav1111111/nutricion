"""
Сервис для работы с Graspil Analytics API
Отправляет целевые события (конверсии) для аналитики
"""

import logging
import aiohttp
from datetime import datetime
from typing import Optional

from config.config import config

logger = logging.getLogger(__name__)


class GraspilService:
    """Сервис для отправки событий в Graspil Analytics"""
    
    API_URL = "https://api.graspil.com/v1/send-target"
    
    def __init__(self):
        self.api_key = config.GRASPIL_API_KEY
        self.enabled = bool(self.api_key)
        if not self.enabled:
            logger.warning("GRASPIL_API_KEY не установлен. Graspil аналитика отключена.")
    
    async def _send_event(
        self,
        target_id: int,
        user_id: int,
        value: Optional[float] = None,
        unit: Optional[str] = None
    ) -> bool:
        """
        Отправляет событие в Graspil API
        
        Args:
            target_id: ID цели из Graspil
            user_id: Telegram ID пользователя
            value: Сумма (для платежей)
            unit: Валюта (RUB, USD и т.д.)
        
        Returns:
            True если успешно, False если ошибка
        """
        if not self.enabled:
            return False
        
        payload = {
            "target_id": target_id,
            "user_id": user_id,
            "date": datetime.now().astimezone().isoformat()
        }
        
        if value is not None and unit:
            payload["value"] = value
            payload["unit"] = unit
        
        headers = {
            "Api-Key": self.api_key,
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.API_URL,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    result = await response.json()
                    
                    if result.get("ok"):
                        logger.info(f"Graspil: событие отправлено (target_id={target_id}, user_id={user_id})")
                        return True
                    else:
                        logger.error(f"Graspil: ошибка отправки события: {result}")
                        return False
                        
        except Exception as e:
            logger.error(f"Graspil: исключение при отправке события: {e}")
            return False
    
    async def send_purchase_event(self, user_id: int, amount: float, currency: str = "RUB") -> bool:
        """Отправляет событие успешной покупки подписки (target_id: 10669)"""
        return await self._send_event(
            target_id=config.GRASPIL_TARGET_PURCHASE,
            user_id=user_id,
            value=amount,
            unit=currency
        )
    
    async def send_registration_event(self, user_id: int) -> bool:
        """Отправляет событие прохождения анкеты (target_id: 10675)"""
        return await self._send_event(
            target_id=config.GRASPIL_TARGET_REGISTRATION,
            user_id=user_id
        )
    
    async def send_first_photo_event(self, user_id: int) -> bool:
        """Отправляет событие первого фото еды (target_id: 10676)"""
        return await self._send_event(
            target_id=config.GRASPIL_TARGET_FIRST_PHOTO,
            user_id=user_id
        )
    
    async def send_view_tariffs_event(self, user_id: int) -> bool:
        """Отправляет событие просмотра тарифов (target_id: 10677)"""
        return await self._send_event(
            target_id=config.GRASPIL_TARGET_VIEW_TARIFFS,
            user_id=user_id
        )
    
    async def send_click_pay_event(self, user_id: int) -> bool:
        """Отправляет событие нажатия кнопки Оплатить (target_id: 10678)"""
        return await self._send_event(
            target_id=config.GRASPIL_TARGET_CLICK_PAY,
            user_id=user_id
        )


# Глобальный экземпляр сервиса
graspil_service = GraspilService()
