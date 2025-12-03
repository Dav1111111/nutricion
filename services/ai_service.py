import os
import base64
import json
import logging
import re
from typing import List, Dict, Optional, Union, Any
from dotenv import load_dotenv
from config.config import config
 

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI (опционально)
try:
    from openai import AsyncOpenAI
except ImportError:  # библиотека может быть не установлена, пока в requirements добавили openai
    AsyncOpenAI = None

class AIService:
    """Сервис для работы с OpenAI API"""

    def __init__(self):
        # Разрешён только OpenAI
        self.provider = "openai"

        if self.provider == "openai":
            if AsyncOpenAI is None:
                raise ImportError("Библиотека openai не установлена. Установите openai>=1.14.0 и повторите.")

            self.api_key = config.OPENAI_API_KEY
            if not self.api_key:
                logger.error("OPENAI_API_KEY не найден в переменных окружения")
                raise ValueError("OPENAI_API_KEY не найден в переменных окружения")

            # Увеличенный таймаут для нестабильного соединения
            import httpx
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                timeout=httpx.Timeout(120.0, connect=30.0)  # 120 сек общий, 30 сек на подключение
            )
            self.model_name = config.GPT_MODEL

            logger.info(f"Используем OpenAI модель: {self.model_name}")

        else:
            # Эта ветка больше не должна вызываться
            raise ValueError("Anthropic больше не поддерживается. Установите AI_PROVIDER=openai")

        # Системные промпты (одни и те же для любого провайдера)
        self.food_system_prompt = config.SYSTEM_PROMPT_FOOD
        self.nutrition_system_prompt = config.SYSTEM_PROMPT_NUTRITION

        # Максимальное количество сообщений в истории
        self.max_history_length = config.MAX_HISTORY_LENGTH

        # Имя параметра ограничения токенов зависит от модели (gpt-5* → max_completion_tokens)
        self._use_max_completion_tokens = isinstance(self.model_name, str) and self.model_name.startswith("gpt-5")

    def _token_limit_param(self, tokens: int) -> Dict[str, int]:
        """Возвращает корректный параметр лимита токенов для текущей модели."""
        if self._use_max_completion_tokens:
            return {"max_completion_tokens": tokens}
        return {"max_tokens": tokens}

    def _supports_temperature(self) -> bool:
        """Возвращает True, если текущая модель поддерживает явную установку temperature.

        Примечание: семейство gpt-5* (например, "gpt-5-mini") принимает только значение по умолчанию (1)
        и отклоняет любое заданное значение temperature.
        """
        return not (isinstance(self.model_name, str) and self.model_name.startswith("gpt-5"))

    @property
    def supports_temperature(self) -> bool:
        """Публичное свойство для использования вне класса (например, в обработчиках)."""
        return self._supports_temperature()

    def _temperature_param(self, value: Optional[float]) -> Dict[str, float]:
        """Возвращает словарь с параметром temperature, если модель это поддерживает.

        Иначе возвращает пустой словарь, чтобы не передавать неподдерживаемый параметр.
        """
        if not self._supports_temperature() or value is None:
            return {}
        return {"temperature": value}

    # --- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ -------------------------------------------------
    @staticmethod
    def _sanitize_response(text: str) -> str:
        """Удаляет нежелательные символы/паттерны из ответа модели."""
        if not text:
            return text
        # Удаляем markdown-заголовки вида ###
        return text.replace("###", "").strip()

    async def analyze_food_image(self, image_data, message: str, history: List[Dict] = None) -> str:
        """
        Анализ фотографии еды с помощью OpenAI Vision

        Args:
            image_data: Данные изображения (bytes или строка с путем к файлу)
            message: Текстовое сообщение от пользователя
            history: История сообщений (опционально)

        Returns:
            Текст анализа
        """
        try:
            # Проверяем, что получили - путь к файлу или байты изображения
            if isinstance(image_data, str):
                # Если получили путь к файлу, читаем изображение
                logger.info(f"Получен путь к изображению: {image_data}")
                try:
                    with open(image_data, 'rb') as f:
                        image_bytes = f.read()
                except Exception as e:
                    logger.error(f"Ошибка при чтении файла изображения: {str(e)}")
                    raise ValueError(f"Не удалось прочитать файл изображения по пути {image_data}: {str(e)}")
            else:
                # Если получили байты, используем их напрямую
                image_bytes = image_data
                
            # Проверяем, что image_bytes действительно байты
            if not isinstance(image_bytes, bytes):
                logger.error(f"Неверный тип данных изображения: {type(image_bytes)}")
                raise TypeError("Данные изображения должны быть в формате bytes")
            
            # Кодирование изображения в base64
            encoded_image = base64.b64encode(image_bytes).decode('utf-8')
            
            # Подготовка сообщения
            if not message or message.strip() == "":
                modified_message = "Проанализируй это блюдо детально и предоставь полную информацию о БЖУ и пищевой ценности."
            else:
                modified_message = message

            # Создаем системное сообщение
            system_message = self.food_system_prompt
            
            # Логирование для диагностики
            logger.info(f"Используемая модель: {self.model_name}")
            logger.info(f"Системное сообщение: {system_message[:100]}...")
            logger.info(f"Сообщение пользователя (модифицированное): {modified_message}")
            
            # Формируем запрос к API
            if self.provider == "openai":
                # Добавляем краткую историю (последние 2-3 обмена), если есть
                short_history: List[Dict] = []
                if history:
                    for msg in history[-3:]:
                        role = msg.get("role")
                        content = msg.get("content")
                        if role and content:
                            short_history.append({"role": role, "content": content})

                if self._use_max_completion_tokens:
                    # Ветка для gpt-5*: используем Responses API с input_image
                    input_blocks: List[Dict[str, Any]] = []
                    # История: user → input_text, assistant → output_text
                    for h in short_history:
                        role_val = h.get("role", "user")
                        content_val = h.get("content", "")
                        if not content_val:
                            continue
                        if role_val == "assistant":
                            input_blocks.append(
                                {
                                    "role": "assistant",
                                    "content": [
                                        {"type": "output_text", "text": content_val}
                                    ],
                                }
                            )
                        else:
                            input_blocks.append(
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "input_text", "text": content_val}
                                    ],
                                }
                            )
                    # Текущий запрос с изображением
                    input_blocks.append(
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": modified_message},
                                {
                                    "type": "input_image",
                                    "image_url": f"data:image/jpeg;base64,{encoded_image}",
                                },
                            ],
                        }
                    )

                    # Выполняем запрос через Responses API
                    # Для Responses используем max_output_tokens
                    responses_params: Dict[str, Any] = {
                        "model": self.model_name,
                        "input": input_blocks,
                        "max_output_tokens": 2000,
                        "instructions": system_message,
                    }
                    response = await self.client.responses.create(**responses_params)

                    # Извлекаем текст ответа
                    response_text: Optional[str] = None
                    try:
                        response_text = getattr(response, "output_text", None)
                    except Exception:
                        response_text = None

                    if not response_text:
                        # Пытаемся разобрать структуру output -> content -> text
                        try:
                            output = getattr(response, "output", None) or response.get("output")  # type: ignore
                            if output:
                                for item in output:
                                    content_list = getattr(item, "content", None) or item.get("content", [])  # type: ignore
                                    for c in content_list:
                                        text_candidate = (
                                            getattr(c, "text", None)
                                            if hasattr(c, "text")
                                            else c.get("text")  # type: ignore
                                        )
                                        if text_candidate:
                                            response_text = text_candidate
                                            break
                                    if response_text:
                                        break
                        except Exception:
                            response_text = None

                    if not response_text:
                        response_text = ""

                else:
                    # Ветка для 4o-семейства: используем Chat Completions Vision
                    messages = [
                        {"role": "system", "content": system_message},
                        *short_history,
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{encoded_image}",
                                        "detail": "low",
                                    },
                                },
                                {"type": "text", "text": modified_message},
                            ],
                        },
                    ]

                    response = await self.client.chat.completions.create(
                        model=self.model_name,
                        messages=messages,
                        **self._temperature_param(0.1),
                        **self._token_limit_param(2000),
                    )

                    response_text = response.choices[0].message.content
                    # Сохраняем токены при наличии истории сообщений
                    try:
                        usage_total = getattr(response, "usage", None)
                        if usage_total and history is not None:
                            logger.info(f"Vision usage: {usage_total}")
                    except Exception:
                        pass

            # Логирование для диагностики
            logger.info(f"Первые 100 символов ответа: {response_text[:100]}...")

            # Финальная очистка
            response_text = self._sanitize_response(response_text)

            # Защита от пустого ответа для Telegram
            if not response_text or not str(response_text).strip():
                response_text = "😔 Не удалось проанализировать изображение. Пожалуйста, попробуйте другое фото." 

            return response_text

        except Exception as e:
            logger.error(f"Ошибка при анализе изображения: {str(e)}")
            raise

    async def answer_nutrition_question(self, question: str, history: List[Dict] = None) -> str:
        """
        Ответ на вопрос о питании

        Args:
            question: Вопрос пользователя
            history: История сообщений (опционально)

        Returns:
            Ответ на вопрос
        """
        try:
            # Формируем сообщения для запроса
            messages = []
            
            # Добавляем историю сообщений, если она есть (с ограничением длины)
            MAX_MSG_LENGTH = 1000  # Максимальная длина одного сообщения в истории
            # Паттерны ошибок, которые не должны попадать в контекст
            ERROR_PATTERNS = ["Не удалось получить ответ", "Произошла ошибка", "😔"]
            
            if history:
                for msg in history[-self.max_history_length:]:
                    role = msg.get("role")
                    content = msg.get("content")
                    if role and content:
                        # Пропускаем сообщения с ошибками
                        if any(err in content for err in ERROR_PATTERNS):
                            continue
                        # Обрезаем слишком длинные сообщения
                        if len(content) > MAX_MSG_LENGTH:
                            content = content[:MAX_MSG_LENGTH] + "..."
                        messages.append({"role": role, "content": content})
            
            modified_question = question
            
            if self.provider == "openai":
                # Добавляем системный промпт в начало для OpenAI
                messages.insert(0, {"role": "system", "content": self.nutrition_system_prompt})
                messages.append({"role": "user", "content": modified_question})

                logger.info(f"Используем OpenAI модель: {self.model_name}")
                response = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": m.get("role"), "content": m.get("content")} for m in messages],
                    **self._temperature_param(0.1),
                    **self._token_limit_param(2000),
                )

                response_text = response.choices[0].message.content
                
                # Полное логирование для дебага
                logger.info(f"OpenAI response finish_reason: {response.choices[0].finish_reason}")
                logger.info(f"OpenAI response content type: {type(response_text)}")
                logger.info(f"OpenAI response content length: {len(response_text) if response_text else 0}")
                
                # Проверка на None или пустой ответ
                if response_text is None:
                    logger.warning("OpenAI вернул None вместо ответа")
                    response_text = ""

            # Логирование для диагностики
            if response_text:
                logger.info(f"Первые 100 символов ответа на вопрос: {response_text[:100]}...")
            else:
                logger.warning("Получен пустой ответ от AI")

            # Финальная очистка
            response_text = self._sanitize_response(response_text)

            # Защита от пустого ответа для Telegram
            if not response_text or not str(response_text).strip():
                response_text = "😔 Не удалось получить ответ. Пожалуйста, попробуйте снова." 

            return response_text

        except Exception as e:
            logger.error(f"Ошибка при ответе на вопрос: {str(e)}")
            raise

    async def extract_nutrition_data(self, analysis_text: str) -> Dict[str, Any]:
        """
        Извлекает данные о питательной ценности из анализа текста
        
        Args:
            analysis_text: Текст анализа от модели AI
            
        Returns:
            Словарь с данными о питательной ценности
        """
        if not analysis_text:
            return {}
            
        try:
            # Логируем начало извлечения данных
            logging.info(f"Начинаем извлечение питательных данных из текста анализа")
            
            # Системный промпт, который объясняет роль модели
            system_prompt = """
            Ты эксперт по извлечению данных. 
            Тебя попросят извлечь числовые значения, связанные с питательной ценностью пищи.
            Предоставь ответ только в формате JSON, без дополнительного текста.
            Все значения должны быть числами, где возможно. Используй null для отсутствующих данных.
            
            Ты должен ВСЕГДА возвращать содержательный и точный ответ в запрошенном формате JSON.
            """
            
            # Пользовательский промпт для извлечения данных
            user_prompt = f"""
            Извлеки числовые значения питательной ценности из следующего анализа пищи:
            
            ---
            {analysis_text}
            ---
            
            Извлеки следующие поля:
            - название_блюда (строка)
            - калории (число)
            - белки (число, граммы)
            - жиры (число, граммы)
            - углеводы (число, граммы)
            - клетчатка (число, граммы, если есть)
            - сахар (число, граммы, если есть)
            - основные_ингредиенты (массив строк)
            
            Пример ответа:
            {{
                "название_блюда": "Салат 'Цезарь'",
                "калории": 450,
                "белки": 25,
                "жиры": 30,
                "углеводы": 20,
                "клетчатка": 5,
                "сахар": 3,
                "основные_ингредиенты": ["куриная грудка", "салат романо", "сыр пармезан", "гренки", "соус цезарь"]
            }}
            """
            
            # Выполнение запроса к API
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                **self._temperature_param(0),
                response_format={"type": "json_object"},
                **self._token_limit_param(1024),
            )
            
            response_text = response.choices[0].message.content
            
            # Логирование сырого ответа для диагностики
            logging.info(f"Сырой ответ для извлечения данных: {response_text}")
            
            # Попытка разобрать JSON
            try:
                # Извлекаем только JSON-объект, если вокруг него есть лишний текст
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if not json_match:
                    logging.warning("JSON-объект не найден в ответе")
                    return {}
                
                json_str = json_match.group(0)
                extracted_data = json.loads(json_str)
                
                # Приводим числовые значения к float, если они существуют, и обрабатываем None
                for key in ["калории", "белки", "жиры", "углеводы", "клетчатка", "сахар"]:
                    if key in extracted_data and extracted_data[key] is not None:
                        try:
                            extracted_data[key] = float(extracted_data[key])
                        except (ValueError, TypeError):
                            logging.warning(f"Не удалось преобразовать значение '{extracted_data[key]}' для ключа '{key}' в float")
                            extracted_data[key] = None
                
                # Проверка, что основные_ингредиенты - это список
                if "основные_ингредиенты" in extracted_data and not isinstance(extracted_data.get("основные_ингредиенты"), list):
                    extracted_data["основные_ингредиенты"] = []
                    
                logging.info(f"Успешно извлечены и обработаны данные: {extracted_data}")
                return extracted_data
                
            except json.JSONDecodeError as e:
                logging.error(f"Ошибка декодирования JSON: {e}")
                return {}
                
        except Exception as e:
            logging.error(f"Непредвиденная ошибка при извлечении данных: {e}")
            return {}

    async def generate_meal_plan(self, user_preferences: Dict, nutrition_goals: Dict) -> str:
        """
        Генерация персонального плана питания на 3 дня
        """
        try:
            # Формирование промпта
            system_prompt = """
            Ты высококвалифицированный диетолог-нутрициолог. Твоя задача — составить персонализированный, сбалансированный и разнообразный план питания на 3 дня, основываясь на целях и предпочтениях пользователя.

            План должен быть:
            1.  **Детализированным:** Укажи конкретные блюда на завтрак, обед, ужин и 1-2 перекуса. Для каждого блюда приведи примерный вес порции в граммах и КБЖУ.
            2.  **Сбалансированным:** Суточное КБЖУ должно максимально соответствовать целям пользователя.
            3.  **Практичным:** Предлагай простые в приготовлении блюда из доступных продуктов.
            4.  **Разнообразным:** Не повторяй одни и те же блюда слишком часто.
            5.  **Адаптированным:** Строго учитывай все предпочтения пользователя (тип диеты, аллергии, нелюбимые продукты).

            В конце плана дай 3-4 общих совета по питанию, исходя из целей пользователя.

            Ответ должен быть структурирован с использованием Markdown для максимальной читаемости. Используй заголовки, списки и выделение жирным шрифтом.
            """

            user_prompt = f"""
            Пожалуйста, составь для меня план питания на 3 дня.

            **Мои цели:**
            - Тип цели: {nutrition_goals.get('goal_type', 'не указан')}
            - Целевые калории: {nutrition_goals.get('target_calories', 'не указано')} ккал/день
            - Белки: {nutrition_goals.get('target_proteins', 'не указано')} г/день
            - Жиры: {nutrition_goals.get('target_fats', 'не указано')} г/день
            - Углеводы: {nutrition_goals.get('target_carbs', 'не указано')} г/день

            **Мои предпочтения:**
            - Тип диеты: {user_preferences.get('diet_type', 'обычная')}
            - Аллергии: {user_preferences.get('allergies', 'нет')}
            - Нелюбимые продукты: {user_preferences.get('disliked_foods', 'нет')}
            - Предпочитаемая кухня: {user_preferences.get('preferred_cuisine', 'любая')}

            Оформи ответ в виде подробного плана на каждый день.
            """

            # Выполнение запроса к API
            response = await self.client.chat.completions.create(
                model=config.GPT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                **self._temperature_param(0.3),
                **self._token_limit_param(3500),
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Ошибка при генерации плана питания: {str(e)}")
            return "😔 Произошла ошибка при генерации плана питания. Пожалуйста, попробуйте позже."

    async def generate_nutrition_report(self, meals_data: List[Dict], goals_data: Dict, start_date: str, end_date: str) -> str:
        """
        Анализ прогресса питания и генерация отчета
        """
        try:
            # Формирование промпта
            system_prompt = """
            Ты опытный нутрициолог, анализирующий данные о питании пользователя. Твоя задача — на основе предоставленных логов приемов пищи и целей пользователя составить подробный и полезный отчет.

            Структура отчета:
            1.  **Общий итог:** Сравни среднее фактическое потребление КБЖУ с целевыми показателями. Укажи, достигнуты ли цели.
            2.  **Анализ по нутриентам:**
                *   **Белки:** Оцени, достаточно ли белков. Похвали, если да. Если нет, предложи конкретные продукты для увеличения их потребления.
                *   **Жиры:** Оцени качество и количество жиров. Предостереги от избытка насыщенных жиров, если это видно. Посоветуй источники полезных жиров.
                *   **Углеводы:** Оцени количество. Посоветуй отдавать предпочтение сложным углеводам.
            3.  **Ключевые выводы и рекомендации:** Сделай 2-3 главных вывода из анализа. Дай практические, легко выполнимые советы. Например, "Увеличьте порцию овощей на обед" или "Добавьте горсть орехов в качестве перекуса".
            4.  **Мотивационное заключение:** Подбодри пользователя и похвали за ведение дневника питания.

            Используй позитивный и поддерживающий тон. Форматируй отчет с помощью Markdown.
            """

            user_prompt = f"""
            Проанализируй мой рацион за период с {start_date} по {end_date}.

            **Мои цели по питанию:**
            {json.dumps(goals_data, indent=2, ensure_ascii=False) if goals_data else "Цели не установлены."}

            **Мои приемы пищи за этот период:**
            {json.dumps(meals_data, indent=2, ensure_ascii=False)}

            Предоставь, пожалуйста, подробный отчет по моему питанию.
            """

            # Выполнение запроса к API
            response = await self.client.chat.completions.create(
                model=config.GPT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                **self._temperature_param(0.2),
                **self._token_limit_param(2500),
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Ошибка при генерации отчета о питании: {str(e)}")
            return "😔 Произошла ошибка при генерации отчета. Пожалуйста, попробуйте позже."

    async def format_nutrition_summary(self, nutrition_data: Dict[str, Any]) -> str:
        """
        Форматирует данные о питании в красивую и читаемую сводку.

        Args:
            nutrition_data: Словарь с данными о питательной ценности.

        Returns:
            Строка со сводкой в формате Markdown.
        """
        try:
            name = nutrition_data.get('название_блюда', 'Неизвестное блюдо')
            calories = nutrition_data.get('калории')
            proteins = nutrition_data.get('белки')
            fats = nutrition_data.get('жиры')
            carbs = nutrition_data.get('углеводы')
            
            summary = f"**📊 Сводка по блюду: \"{name}\"**\n"
            
            if calories:
                summary += f"🔥 Калории: **{calories:.0f} ккал**\n"
            
            bju_parts = []
            if proteins is not None:
                bju_parts.append(f"Белки: {proteins:.1f} г")
            if fats is not None:
                bju_parts.append(f"Жиры: {fats:.1f} г")
            if carbs is not None:
                bju_parts.append(f"Углеводы: {carbs:.1f} г")

            if bju_parts:
                summary += f"⚖️ БЖУ: " + " | ".join(bju_parts) + "\n"

            # Возвращаем пустую строку, если нет данных для отображения, кроме названия
            if not bju_parts and not calories:
                return ""
                
            return summary.strip()
            
        except Exception as e:
            logger.error(f"Ошибка при форматировании сводки о питании: {e}")
            return ""

    async def analyze_nutrition_progress(self, meals_data: List[Dict], goals_data: Dict) -> str:
        """
        Анализирует прогресс питания на основе логов и целей
        """
        try:
            # Преобразуем данные в удобный для промпта формат
            meals_str = json.dumps(meals_data, indent=2, ensure_ascii=False)
            goals_str = json.dumps(goals_data, indent=2, ensure_ascii=False)

            system_prompt = """
            Ты опытный нутрициолог. Твоя задача — проанализировать данные о приемах пищи пользователя и его цели, а затем предоставить краткий, но емкий отчет.

            Отчет должен включать:
            1.  **Сравнение с целью:** Сравни средние суточные показатели КБЖУ с целями пользователя.
            2.  **Ключевые наблюдения:** Выдели 1-2 самых важных момента (например, "Белка достаточно, но не хватает полезных жиров" или "Калорийность в норме, но многовато сахара").
            3.  **Одна главная рекомендация:** Дай один самый важный и легко выполнимый совет на будущее.

            Будь позитивным и поддерживающим. Используй Markdown для форматирования.
            """

            user_prompt = f"""
            Вот данные о моем питании и моих целях. Проанализируй их и дай отчет.

            **Мои цели:**
            {goals_str}

            **Мои приемы пищи:**
            {meals_str}
            """

            response = await self.client.chat.completions.create(
                model=config.GPT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                **self._temperature_param(0.2),
                **self._token_limit_param(1500),
            )
            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Ошибка при анализе прогресса питания: {str(e)}")
            return "😔 Произошла ошибка при анализе вашего прогресса. Пожалуйста, попробуйте позже."
            
async def debug_api_calls():
    """Отладочная функция для проверки вызовов API"""
    ai = AIService()
    
    # 1. Тест ответа на вопрос
    try:
        logger.info("--- ТЕСТ 1: Ответ на вопрос о питании ---")
        question = "Что такое гликемический индекс и почему он важен?"
        history = [
            {"role": "user", "content": "Привет! Расскажи про диеты."},
            {"role": "assistant", "content": "Как нутрициолог, я могу сказать, что: Существует множество диет, каждая со своими принципами. Какая вас интересует?"}
        ]
        answer = await ai.answer_nutrition_question(question, history)
        logger.info(f"Ответ на вопрос: {answer}\n")
    except Exception as e:
        logger.error(f"Ошибка в тесте 1: {e}\n")

    # 2. Тест извлечения данных
    try:
        logger.info("--- ТЕСТ 2: Извлечение структурированных данных ---")
        analysis_text = """
        Как нутрициолог, я проанализировал(а) это блюдо и могу сказать следующее:
        Это похоже на большую порцию пасты Карбонара. 
        Примерное количество калорий: 850 ккал. 
        Белки: 40 г, жиры: 50 г, углеводы: 60 г. 
        Основные ингредиенты: спагетти, гуанчале, яичный желток, сыр пекорино.
        """
        extracted_data = await ai.extract_nutrition_data(analysis_text)
        logger.info(f"Извлеченные данные: {extracted_data}\n")
    except Exception as e:
        logger.error(f"Ошибка в тесте 2: {e}\n")

    # 3. Тест анализа изображения (требует наличия файла)
    try:
        logger.info("--- ТЕСТ 3: Анализ изображения ---")
        image_path = "debug_image.jpg"  # Создайте этот файл для теста
        if os.path.exists(image_path):
            with open(image_path, "rb") as f:
                image_data = f.read()
            image_analysis = await ai.analyze_food_image(image_data, "Что это за блюдо?", [])
            logger.info(f"Анализ изображения: {image_analysis}\n")
        else:
            logger.warning(f"Файл {image_path} не найден. Пропуск теста 3.\n")
    except Exception as e:
        logger.error(f"Ошибка в тесте 3: {e}\n")

    return "Отладочные тесты завершены. Проверьте логи сервера для результатов."

# --- Глобальный экземпляр сервиса ---
# Другие модули (например, обработчики команд) импортируют именно этот экземпляр.
ai_service = AIService()
