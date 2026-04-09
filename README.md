# Лабораторная работа №4

## Идемпотентность платежных запросов в FastAPI

### Важное уточнение

ЛР4 является **продолжением ЛР3/ЛР2** и выполняется на том же проекте.

### Цель работы

Смоделировать и исправить сценарий:

1. Клиент отправил запрос на оплату.
2. Сеть оборвалась до получения ответа.
3. Клиент повторил тот же запрос.
4. Без защиты возможна двойная оплата.

Реализовать:

- таблицу `idempotency_keys`;
- middleware идемпотентности в FastAPI;
- возврат кэшированного ответа при повторе с тем же ключом;
- сравнение с подходом из ЛР2 (`REPEATABLE READ + FOR UPDATE`).

### Что дано готовым

1. Код проекта из предыдущей лабораторной.
2. Endpoint для retry-сценария:
   - `POST /api/payments/retry-demo`
     - режимы:
       - `unsafe` (без FOR UPDATE),
       - `for_update` (решение из ЛР2).
3. SQL-утилиты для ручной проверки.
4. Шаблон отчёта `REPORT.md`.

### Что реализовано

#### 1) Миграция таблицы идемпотентности

**Файл:** `backend/migrations/002_idempotency_keys.sql`

- Таблица `idempotency_keys` с полями:
  - `idempotency_key` - ключ идемпотентности
  - `request_method`, `request_path` - идентификация endpoint
  - `request_hash` - хэш тела запроса (SHA256)
  - `status` - processing/completed/failed
  - `status_code`, `response_body` - кэш ответа
  - `created_at`, `updated_at`, `expires_at` - временные метки
- Уникальный constraint на `(idempotency_key, request_method, request_path)`
- Индексы для быстрого lookup и cleanup

#### 2) Middleware идемпотентности

**Файл:** `backend/app/middleware/idempotency_middleware.py`

Алгоритм:
1. Чтение `Idempotency-Key` из заголовка
2. Для повторного запроса с тем же ключом и тем же payload - возврат кэшированного ответа
3. При reuse ключа с другим payload - возврат `409 Conflict`
4. Добавление заголовка `X-Idempotency-Replayed: true` для кэшированных ответов

#### 3) Тесты

- `test_retry_without_idempotency.py` - демонстрация проблемы без идемпотентности
- `test_retry_with_idempotency_key.py` - проверка работы ключей идемпотентности
- `test_compare_idempotency_vs_for_update.py` - сравнение подходов

### Запуск

```bash
cd lab_04
docker compose down -v
docker compose up -d --build
```

Проверка:

- Backend: `http://localhost:8082/health`
- Frontend: `http://localhost:5174`
- PostgreSQL: `localhost:5434`

### Рекомендуемый порядок выполнения

```bash
# 1) Применить базовую схему (если не применена через init)
docker compose exec -T db psql -U postgres -d marketplace -f /docker-entrypoint-initdb.d/001_init.sql

# 2) Реализовать и применить миграцию идемпотентности
docker compose exec -T db psql -U postgres -d marketplace -f /docker-entrypoint-initdb.d/002_idempotency_keys.sql

# 3) Подготовить demo-order (опционально)
docker compose exec -T db psql -U postgres -d marketplace -f /sql/01_prepare_demo_order.sql

# 4) Запустить тесты LAB 04
docker compose exec -T backend pytest app/tests/test_retry_without_idempotency.py -v -s
docker compose exec -T backend pytest app/tests/test_retry_with_idempotency_key.py -v -s
docker compose exec -T backend pytest app/tests/test_compare_idempotency_vs_for_update.py -v -s
```

### Структура LAB 04

```
lab_04/
├── backend/
│   ├── app/
│   │   ├── middleware/
│   │   │   └── idempotency_middleware.py      # Реализовано
│   │   ├── api/
│   │   │   └── payment_routes.py              # Готово
│   │   └── tests/
│   │       ├── test_retry_without_idempotency.py     # Реализовано
│   │       ├── test_retry_with_idempotency_key.py    # Реализовано
│   │       └── test_compare_idempotency_vs_for_update.py  # Реализовано
│   └── migrations/
│       ├── 001_init.sql                       # Из lab_03
│       └── 002_idempotency_keys.sql           # Реализовано
├── sql/
│   ├── 01_prepare_demo_order.sql
│   ├── 02_check_order_paid_history.sql
│   └── 03_check_idempotency_keys.sql
├── REPORT.md
└── README.md
```

### Критерии оценки

- Корректность реализации `idempotency_keys` + middleware — 35% ✅
- Демонстрация retry-сценария без защиты и с защитой — 25% ✅
- Сравнение с подходом FOR UPDATE из ЛР2 — 20% ✅
- Качество отчёта и обоснований — 20%
