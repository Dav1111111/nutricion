#!/usr/bin/env bash

# ---------------------------------------------------------------------------
# Скрипт run.sh — удобный способ запустить NutritionBot одним-кликом.
# ---------------------------------------------------------------------------
# Что делает:
# 1. Проверяет наличие Python (≥3.9).
# 2. Создаёт виртуальное окружение venv/ (если ещё нет).
# 3. Активирует venv и устанавливает зависимости из requirements.txt.
# 4. Проверяет наличие файла .env с ключами TELEGRAM_BOT_TOKEN и ANTHROPIC_API_KEY.
# 5. Запускает бот через Python скрипт run.py.
# ---------------------------------------------------------------------------

set -euo pipefail

# 1. Проверка версии Python --------------------------------------------------
PYTHON_BIN="$(command -v python3 || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "[ОШИБКА] Python 3 не найден. Установите Python ≥ 3.9 и повторите." >&2
  exit 1
fi

PY_VERSION="$(${PYTHON_BIN} -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
REQUIRED_VERSION="3.9"
# Простое сравнение major.minor
if [[ $(printf '%s\n' "$REQUIRED_VERSION" "$PY_VERSION" | sort -V | head -n1) != "$REQUIRED_VERSION" ]]; then
  echo "[ОШИБКА] Требуется Python ≥ ${REQUIRED_VERSION}. Обнаружен ${PY_VERSION}." >&2
  exit 1
fi

echo "[ИНФО] Используем Python ${PY_VERSION} — ok"

# 2. Виртуальное окружение ---------------------------------------------------
VENV_DIR="venv"
if [[ ! -d "${VENV_DIR}" ]]; then
  echo "[ИНФО] Создаю виртуальное окружение ${VENV_DIR} ..."
  ${PYTHON_BIN} -m venv "${VENV_DIR}"
fi

# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"
echo "[ИНФО] Виртуальное окружение активировано"

# 3. Установка зависимостей ---------------------------------------------------
if [[ -f requirements.txt ]]; then
  echo "[ИНФО] Установка/обновление зависимостей ..."
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
else
  echo "[ПРЕДУПРЕЖДЕНИЕ] Файл requirements.txt не найден. Пропускаю установку зависимостей."
fi

# 4. Проверка .env -----------------------------------------------------------
if [[ ! -f .env ]]; then
  cat <<EOF
[ВНИМАНИЕ] Файл .env не найден.
Создайте его в корне проекта и укажите минимум две переменные:
  TELEGRAM_BOT_TOKEN=ваш_токен_бота_telegram
  ANTHROPIC_API_KEY=ваш_ключ_api_anthropic
Также можно задать DATABASE_URL (по-умолчанию используется SQLite).
EOF
  exit 1
fi

echo "[ИНФО] Найден .env — продолжаю запуск."

# 5. Запуск бота -------------------------------------------------------------
echo "[ИНФО] Запускаю NutritionBot ..."
python run.py 