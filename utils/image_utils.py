import os
import logging
from typing import Optional
from datetime import datetime
from PIL import Image
from io import BytesIO
import aiofiles

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ImageUtils:
    """Утилиты для работы с изображениями"""

    @staticmethod
    async def save_image(image_data: bytes, user_id: int, prefix: str = "meal") -> Optional[str]:
        """
        Сохранение изображения на диск

        Args:
            image_data: Данные изображения в байтах
            user_id: ID пользователя
            prefix: Префикс для имени файла

        Returns:
            Путь к сохраненному изображению или None в случае ошибки
        """
        try:
            # Создание директории, если не существует
            image_dir = os.path.join("images", str(user_id))
            os.makedirs(image_dir, exist_ok=True)

            # Генерация имени файла
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{prefix}_{timestamp}.jpg"
            image_path = os.path.join(image_dir, filename)

            # Сохранение изображения
            async with aiofiles.open(image_path, "wb") as f:
                await f.write(image_data)

            logger.info(f"Изображение сохранено: {image_path}")
            return image_path

        except Exception as e:
            logger.error(f"Ошибка при сохранении изображения: {str(e)}")
            return None

    @staticmethod
    def optimize_image(image_data: bytes, max_size: int = 1024, quality: int = 85) -> bytes:
        """
        Оптимизация изображения (уменьшение размера)

        Args:
            image_data: Данные изображения в байтах
            max_size: Максимальный размер (ширина или высота) в пикселях
            quality: Качество JPEG (1-100)

        Returns:
            Оптимизированные данные изображения в байтах
        """
        try:
            # Открытие изображения из байтов
            img = Image.open(BytesIO(image_data))

            # Изменение размера, если нужно
            width, height = img.size
            if width > max_size or height > max_size:
                if width > height:
                    new_width = max_size
                    new_height = int(height * (max_size / width))
                else:
                    new_height = max_size
                    new_width = int(width * (max_size / height))

                img = img.resize((new_width, new_height), Image.LANCZOS)
                logger.info(f"Изображение изменено с {width}x{height} на {new_width}x{new_height}")

            # Конвертация в JPEG и оптимизация
            output = BytesIO()
            img.convert("RGB").save(output, format="JPEG", quality=quality, optimize=True)
            optimized_data = output.getvalue()

            logger.info(f"Изображение оптимизировано: {len(image_data)/1024:.1f} КБ -> {len(optimized_data)/1024:.1f} КБ")
            return optimized_data

        except Exception as e:
            logger.error(f"Ошибка при оптимизации изображения: {str(e)}")
            return image_data  # Возвращаем оригинальные данные в случае ошибки

# Экземпляр для использования в других модулях
image_utils = ImageUtils()
