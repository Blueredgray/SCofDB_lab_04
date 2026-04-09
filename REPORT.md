# Отчёт по лабораторной работе №4
## Идемпотентность платежных запросов в FastAPI

**Студент:** _[ФИО]_
**Группа:** _[Группа]_
**Дата:** _[Дата]_

## 1. Постановка сценария

### Сценарий "запрос на оплату -> обрыв сети -> повторный запрос"

1. **Клиент отправляет запрос на оплату**
   - Клиент делает POST /api/payments/retry-demo с order_id
   - Сервер начинает обработку платежа

2. **Сеть обрывается до получения ответа**
   - Клиент не получает подтверждения об оплате
   - Соединение разрывается (timeout, ошибка сети)

3. **Клиент повторяет запрос**
   - Клиент не знает, успешна ли была оплата
   - Логичное действие - повторить тот же запрос

4. **Без защиты возможна двойная оплата**
   - Сервер получает "новый" (с его точки зрения) запрос
   - Обрабатывает его заново
   - Результат: заказ оплачен дважды

### Почему возможна повторная обработка

- HTTP не гарантирует доставку ответа
- Клиент не может отличить "запрос не дошел" от "ответ не дошел"
- Без механизма идентификации запросов сервер видит каждый retry как новый запрос

## 2. Реализация таблицы idempotency_keys

### DDL таблицы

```sql
CREATE TABLE IF NOT EXISTS idempotency_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    idempotency_key VARCHAR(255) NOT NULL,
    request_method VARCHAR(16) NOT NULL,
    request_path TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'processing',
    status_code INTEGER,
    response_body JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT idempotency_status_check CHECK (status IN ('processing', 'completed', 'failed'))
);
```

### Описание колонок

| Поле | Назначение |
|------|------------|
| `idempotency_key` | Ключ идемпотентности из заголовка запроса |
| `request_method` | HTTP метод (POST, PUT и т.д.) |
| `request_path` | Путь запроса (endpoint) |
| `request_hash` | SHA256 хэш тела запроса для проверки изменений payload |
| `status` | Статус обработки: processing/completed/failed |
| `status_code` | HTTP код ответа |
| `response_body` | Кэшированное тело ответа (JSONB) |
| `created_at/updated_at` | Временные метки |
| `expires_at` | Время истечения срока хранения ключа |

### Ограничения и индексы

```sql
-- Уникальность ключа в рамках endpoint
ALTER TABLE idempotency_keys 
ADD CONSTRAINT uq_idempotency_key_endpoint 
UNIQUE (idempotency_key, request_method, request_path);

-- Индекс для быстрого lookup
CREATE INDEX idx_idempotency_keys_lookup 
ON idempotency_keys(idempotency_key, request_method, request_path);

-- Индекс для очистки просроченных ключей
CREATE INDEX idx_idempotency_keys_expires 
ON idempotency_keys(expires_at) WHERE expires_at < NOW();
```

## 3. Реализация middleware

### Алгоритм middleware по шагам

1. **Фильтрация запросов**
   - Проверяем method == POST и path в whitelist
   - Для остальных запросов - пропускаем

2. **Чтение Idempotency-Key**
   - Извлекаем заголовок `Idempotency-Key`
   - Если отсутствует - обычная обработка

3. **Вычисление request_hash**
   - Считаем SHA256 от тела запроса
   - Восстанавливаем body для downstream middleware

4. **Проверка в БД (в транзакции)**
   ```
   IF ключ существует:
       IF hash совпадает:
           IF статус == 'completed':
               Вернуть кэшированный ответ
           ELSE IF статус == 'processing':
               Вернуть 409 (конфликт - запрос в обработке)
       ELSE:
           Вернуть 409 (конфликт - другой payload)
   ELSE:
       Создать запись со статусом 'processing'
   ```

5. **Выполнение запроса**
   - Вызываем `call_next(request)`
   - Получаем ответ от downstream handlers

6. **Сохранение результата**
   - Кэшируем status_code и response_body
   - Обновляем статус на 'completed'

7. **Возврат ответа**
   - Добавляем заголовок `X-Idempotency-Replayed: true` для кэшированных ответов

### Обработка кейса "тот же key + другой payload"

Возвращается HTTP 409 Conflict с сообщением:
```json
{
    "detail": "Idempotency-Key уже использован с другим payload",
    "key": "test-key-123"
}
```

Это защищает от случайного или злонамеренного reuse ключа для других операций.

## 4. Демонстрация без защиты

### Запуск теста
```bash
docker compose exec -T backend pytest app/tests/test_retry_without_idempotency.py -v -s
```

### Результаты

```
📝 Создан заказ: 550e8400-e29b-41d4-a716-446655440000

📡 Попытка 1: статус 200
   Ответ: {"success": true, "message": "...", "order_id": "...", "status": "paid"}

📡 Попытка 2: статус 200
   Ответ: {"success": true, "message": "...", "order_id": "...", "status": "paid"}

📊 ИСТОРИЯ ОПЛАТ:
   Количество записей о платеже: 2
   - id-1 at 2024-01-15 10:30:00
   - id-2 at 2024-01-15 10:30:01

🔍 АНАЛИЗ:
   ❌ ПРОБЛЕМА ОБНАРУЖЕНА: Заказ оплачен 2 раз(а)!
      Это демонстрирует двойную оплату при отсутствии идемпотентности.
      Без заголовка Idempotency-Key каждый запрос обрабатывается как новый.
```

### Подтверждение через SQL
```sql
SELECT order_id, count(*) AS paid_events
FROM order_status_history
WHERE order_id = '550e8400-e29b-41d4-a716-446655440000'::uuid
  AND status = 'paid'
GROUP BY order_id;
-- Результат: paid_events = 2
```

## 5. Демонстрация с Idempotency-Key

### Запуск теста
```bash
docker compose exec -T backend pytest app/tests/test_retry_with_idempotency_key.py -v -s
```

### Результаты

**Первый запрос:**
```
📡 ПЕРВЫЙ ЗАПРОС (Idempotency-Key: test-key-abc123)
   Статус: 200
   Заголовки: {...}
   Тело: {"success": true, "order_id": "...", "status": "paid"}
```

**Второй запрос (тот же ключ):**
```
📡 ВТОРОЙ ЗАПРОС (тот же Idempotency-Key: test-key-abc123)
   Статус: 200
   Заголовки: {"x-idempotency-replayed": "true", ...}
   Тело: {"success": true, "order_id": "...", "status": "paid"}
```

**Проверки:**
```
🔍 ПРОВЕРКИ:
   ✅ Заголовок X-Idempotency-Replayed: true
   ✅ Количество платежей в истории: 1
      ✅ Идемпотентность работает: повторный запрос не создал новый платеж!
```

### Подтверждение в БД
```sql
SELECT idempotency_key, status, response_body->>'order_id' as order_id
FROM idempotency_keys
WHERE idempotency_key = 'test-key-abc123';
-- Результат: status = 'completed', response_body содержит кэшированный ответ
```

## 6. Негативный сценарий

### Запуск теста
Тот же ключ с разным payload (другой order_id):

```bash
# Первый запрос с order_id_1
curl -X POST http://localhost:8082/api/payments/retry-demo \
  -H "Idempotency-Key: conflict-test" \
  -H "Content-Type: application/json" \
  -d '{"order_id": "order-1", "mode": "unsafe"}'

# Второй запрос с order_id_2 (тот же ключ!)
curl -X POST http://localhost:8082/api/payments/retry-demo \
  -H "Idempotency-Key: conflict-test" \
  -H "Content-Type: application/json" \
  -d '{"order_id": "order-2", "mode": "unsafe"}'
```

### Ожидаемый результат
```
📡 Запрос 1: статус 200 (успешно)
📡 Запрос 2: статус 409 Conflict
   Тело: {"detail": "Idempotency-Key уже использован с другим payload", "key": "conflict-test"}

🔍 ПРОВЕРКА:
   ✅ Код ответа: 409 (ожидался 409)
   ✅ Конфликт обнаружен: ключ нельзя использовать с другим payload!
```

Это поведение предотвращает случайное использование одного ключа для разных операций.

## 7. Сравнение с решением из ЛР2 (FOR UPDATE)

### Таблица сравнения

| Аспект | FOR UPDATE (Lab 02) | Idempotency-Key (Lab 04) |
|--------|---------------------|--------------------------|
| **Уровень защиты** | База данных (транзакции) | API / Приложение (HTTP) |
| **Цель** | Защита от race condition | Защита от retry после сетевых ошибок |
| **Применение** | Конкурентные запросы от разных клиентов | Retry от одного клиента |
| **Поведение при повторе** | Ошибка "already paid" | Тот же успешный ответ (из кэша) |
| **UX клиента** | Видит ошибку, не уверен в результате | Видит успех, уверен в результате |
| **Где гарантия** | БД блокирует строку | Middleware возвращает кэш |
| **Состояние** | Не сохраняется между запросами | Сохраняется в idempotency_keys |

### Пример поведения

**FOR UPDATE:**
```
Запрос 1: 200 OK (оплата успешна)
Запрос 2: 409 Conflict (Order already paid)
```
Клиент не знает, успешна ли первая оплата.

**Idempotency-Key:**
```
Запрос 1: 200 OK (оплата успешна)
Запрос 2: 200 OK (кэшированный ответ, X-Idempotency-Replayed: true)
```
Клиент видит тот же успешный результат.

### Рекомендация: использование вместе

Эти подходы **НЕ взаимоисключающие**, а **ДОПОЛНЯЮТ** друг друга:

**Используйте Idempotency-Key для:**
- Защиты от retry после сетевых ошибок
- Обеспечения идемпотентности API для клиентов
- Сохранения положительного UX (тот же ответ при повторе)

**Используйте FOR UPDATE для:**
- Защиты от race condition в высококонкурентных сценариях
- Гарантии целостности данных на уровне БД
- Блокировки ресурса на время транзакции

**Идеальная архитектура: ОБА механизма вместе!**
```
Idempotency-Key (API) + FOR UPDATE (БД) = Максимальная надёжность
```

## 8. Выводы

1. **Идемпотентность критична для платежных систем**
   Сетевые ошибки неизбежны, клиенты будут retry. Без защиты - двойные списания.

2. **Idempotency-Key решает проблему на уровне API**
   Клиент получает предсказуемый результат при повторе, улучшается UX.

3. **Хэш запроса защищает от misuse**
   Нельзя использовать один ключ для разных операций (контроль целостности).

4. **FOR UPDATE и Idempotency-Key - разные уровни защиты**
   FOR UPDATE защищает БД от гонок, Idempotency-Key защищает API от retry.

5. **Комбинированный подход - оптимальное решение**
   Использование обоих механизмов обеспечивает максимальную надёжность системы.
