# Статус лабораторной работы №4

## Что уже готово
- Основа проекта из предыдущей лабораторной (`backend`, `frontend`, docker)
- Endpoint `POST /api/payments/retry-demo` для retry-сценария
- Подключён `IdempotencyMiddleware` с полной реализацией
- Миграция `backend/migrations/002_idempotency_keys.sql` реализована
- Тесты LAB 04 реализованы

## Реализовано студентом

### Backend
- [x] Реализована таблица `idempotency_keys` в `002_idempotency_keys.sql`
- [x] Реализована логика middleware в `idempotency_middleware.py`
- [x] Middleware подключен в `main.py`

### Тесты/демо
- [x] Реализован `test_retry_without_idempotency.py`
- [x] Реализован `test_retry_with_idempotency_key.py`
- [x] Реализован `test_compare_idempotency_vs_for_update.py`

### Отчёт
- [x] Заполнены все разделы в `REPORT.md`
- [x] Доказано, что повтор с тем же ключом возвращает кэш
- [x] Проведено сравнение подходов: idempotency key vs FOR UPDATE

## Минимальные требования к сдаче
1. Таблица `idempotency_keys` создана и используется.
2. Повтор с тем же `Idempotency-Key` не вызывает повторного списания.
3. Второй ответ возвращается из кэша.
4. Проведено сравнение с решением ЛР2 (`FOR UPDATE`).
5. Отчёт заполнен и содержит технические выводы.
