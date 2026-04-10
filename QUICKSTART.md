# Быстрый старт — LAB 04 (Idempotency Key)

## 0) Пререквизиты
Перед ЛР4 должны быть готовы:
- логика оплаты из ЛР2 (`pay_order_unsafe`, `pay_order_safe`);
- рабочая схема БД из предыдущих лабораторных.

## 1) Запуск проекта
```bash
cd lab_04
docker compose down -v
docker compose up -d --build
```

## 2) Миграция idempotency_keys
Файл:
- `backend/migrations/002_idempotency_keys.sql`

Применение:
```bash
docker compose exec -T db psql -U postgres -d marketplace -f /docker-entrypoint-initdb.d/002_idempotency_keys.sql
```

## 3) Middleware
Файл:
- `backend/app/middleware/idempotency_middleware.py`

Middleware уже подключен в `backend/app/main.py`.

## 4) Подготовить заказ для ручной проверки (опционально)
```bash
docker compose exec -T db psql -U postgres -d marketplace -f /sql/01_prepare_demo_order.sql
```

## 5) Запустить тесты
```bash
docker compose exec -T backend pytest app/tests/test_retry_without_idempotency.py -v -s
docker compose exec -T backend pytest app/tests/test_retry_with_idempotency_key.py -v -s
docker compose exec -T backend pytest app/tests/test_compare_idempotency_vs_for_update.py -v -s
```

## 6) Заполнить отчёт
Отчёт `REPORT.md` уже заполнен по результатам сценариев и сравнений.
